from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import pytest

from provelume import cli


def _subparsers(parser):
    return next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )


def _shape(parser):
    fields = (
        "prog", "usage", "description", "epilog", "prefix_chars", "fromfile_prefix_chars",
        "add_help", "allow_abbrev", "exit_on_error", "conflict_handler", "argument_default",
    )
    actions = []
    for action in parser._actions:
        values = tuple(getattr(action, field) for field in (
            "option_strings", "dest", "nargs", "const", "default", "type", "required",
            "help", "metavar",
        ))
        choices = (
            [(name, _shape(child)) for name, child in action.choices.items()]
            if isinstance(action, argparse._SubParsersAction) else action.choices
        )
        actions.append((type(action), values, choices))
    return (
        tuple(getattr(parser, field) for field in fields), parser._defaults, actions,
        [(group.title, group.description, [parser._actions.index(a) for a in group._group_actions])
         for group in parser._action_groups],
        [(group.required, [parser._actions.index(a) for a in group._group_actions])
         for group in parser._mutually_exclusive_groups],
    )


def _registration_count(parser):
    return sum(
        len(action.choices) + sum(_registration_count(child) for child in action.choices.values())
        for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )


def _required_arguments(parser):
    values = []
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            name, child = next(iter(action.choices.items()))
            values += [name, *_required_arguments(child)]
            continue
        if action.option_strings and not action.required:
            continue
        if action.option_strings:
            values.append(action.option_strings[0])
        if action.nargs == 0:
            continue
        sample = str(next(iter(action.choices))) if action.choices is not None else "1"
        if getattr(action.type, "__name__", "") == "_loopback_host":
            sample = "127.0.0.1"
        values.extend([sample] * (action.nargs if isinstance(action.nargs, int) else 1))
    return values


def _outcome(parse, arguments):
    output, error = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        try:
            result = ("parsed", vars(parse(arguments)))
        except SystemExit as exc:
            result = ("exit", exc.code)
    return result, output.getvalue(), error.getvalue()


def test_every_registered_command_retains_grammar_and_parse_behavior():
    full = cli.build_parser()
    complete = _subparsers(full)
    # Enumerate actual registrations, including both publication subcommands.
    assert _registration_count(full) == 248
    for name, reference in complete.choices.items():
        selected = cli._build_parser(name)
        choices = _subparsers(selected)
        assert list(choices.choices) == list(complete.choices)
        assert choices.choices is choices._name_parser_map
        assert _shape(choices.choices[name]) == _shape(reference), name
        assert selected.format_help() == full.format_help(), name
        assert choices.choices[name].format_help() == reference.format_help(), name
        arguments = [name, *_required_arguments(reference)]
        expected = _outcome(full.parse_args, arguments)
        assert expected[0][0] == "parsed", (name, expected)
        assert _outcome(selected.parse_args, arguments) == expected, name
        for invalid in ([name], [*arguments, "--selection-unknown-option"]):
            actual = _outcome(selected.parse_args, invalid)
            assert actual == _outcome(full.parse_args, invalid), name


def test_top_level_help_unknown_and_global_options_use_full_fallback(monkeypatch):
    full = cli.build_parser()
    original = cli.build_parser
    calls = []

    def build_full():
        calls.append(True)
        return original()

    monkeypatch.setattr(cli, "build_parser", build_full)
    for arguments in (
        [], ["-h"], ["--help"], ["--version"], ["--unknown"], ["not-a-command"],
        ["health", "1", "--help"], ["publication", "-h"], ["--", "health", "1"],
    ):
        calls.clear()
        assert _outcome(cli._parse_args, arguments) == _outcome(full.parse_args, arguments)
        assert calls == [True]


def test_selected_aliases_nested_grammar_and_mutual_exclusion(monkeypatch):
    register = cli.add_qualification_commands

    def with_alias(subparsers):
        register(subparsers)
        parser = subparsers.add_parser("selection-alias", aliases=["sa"], help="Alias example")
        parser.add_argument("--item", action="append", default=[])

    monkeypatch.setattr(cli, "add_qualification_commands", with_alias)
    full = cli.build_parser()
    for arguments in (
        ["sa", "--item", "one"], ["selection-alias", "--item", "two"],
        ["publication", "show"],
        ["publication", "import", "--receipt", "1", "--manifest", "2", "--payload", "3"],
        ["connector-instance-update", "1", "2", "--account-identity", "one",
         "--clear-account-identity"],
        ["serve", "1", "--host", "0.0.0.0"],
        ["qualification-jobs", "1", "--lim", "2"],
        ["qualification-jobs", "--", "--literal-instance"],
    ):
        assert _outcome(cli._parse_args, arguments) == _outcome(full.parse_args, arguments)
    selected = cli._build_parser("sa")
    choices = _subparsers(selected).choices
    assert choices["sa"] is choices["selection-alias"]
    assert selected.format_help() == full.format_help()


def test_public_and_selected_parsers_never_share_mutable_defaults(monkeypatch):
    register = cli.add_qualification_commands

    def with_alias(subparsers):
        register(subparsers)
        parser = subparsers.add_parser("selection-items")
        parser.add_argument("--item", action="append", default=[])

    monkeypatch.setattr(cli, "add_qualification_commands", with_alias)
    first, second = cli.build_parser(), cli.build_parser()
    assert first is not second
    assert all(_subparsers(first).choices[name] is not _subparsers(second).choices[name]
               for name in _subparsers(first).choices)
    first.parse_args(["selection-items"]).item.append("changed")
    assert second.parse_args(["selection-items"]).item == []
    selected_first = cli._parse_args(["selection-items"])
    selected_first.item.append("changed")
    assert cli._parse_args(["selection-items"]).item == []
    assert cli._parse_args(["selection-items", "--item", "new"]).item == ["new"]
    video = _subparsers(second).choices["video-queue"]
    arguments = ["video-queue", *_required_arguments(video)]
    cli._parse_args(arguments).frame_ms.append(1000)
    assert cli._parse_args(arguments).frame_ms == []


def test_none_reads_sys_argv_and_explicit_sequence_is_unchanged(monkeypatch):
    values = ["qualification-jobs", "1", "--limit", "2"]
    original = values.copy()
    monkeypatch.setattr(cli.sys, "argv", ["provelume", *values])
    expected = vars(cli.build_parser().parse_args(values))
    assert vars(cli._parse_args(None)) == expected
    assert vars(cli._parse_args(values)) == expected and values == original
    assert vars(cli._parse_args(tuple(values))) == expected
    with pytest.raises(SystemExit) as exc:
        cli._parse_args([])
    assert exc.value.code == 2


def test_parse_failure_precedes_any_command_handler(monkeypatch):
    def forbidden(_args):
        raise AssertionError("A command handler ran before argument validation")

    monkeypatch.setattr(cli, "handle_publication_command", forbidden)
    with pytest.raises(SystemExit) as exc:
        cli.main(["qualification-jobs", "1", "--limit", "0"])
    assert exc.value.code == 2
