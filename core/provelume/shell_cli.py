from __future__ import annotations

import argparse
import json
from pathlib import Path

from .shell_settings import (
    DEFAULT_LOCAL_PORT,
    ShellSettingsError,
    ShellSettingsManager,
    default_settings,
    probe_port,
    settings_path,
)


def _manager(args: argparse.Namespace) -> ShellSettingsManager:
    selected = getattr(args, "settings_file", None) or settings_path()
    return ShellSettingsManager(selected, default_settings())


def _add_settings_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--settings-file",
        type=Path,
        help="explicit launcher settings path (defaults to the platform state directory)",
    )


def _add_revision(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--expected-revision",
        type=int,
        help="fail if the persisted configuration no longer has this revision",
    )


def add_shell_commands(subparsers: argparse._SubParsersAction) -> None:
    show = subparsers.add_parser(
        "shell-config",
        help="show the effective sanitized shell and endpoint configuration",
    )
    _add_settings_file(show)

    validate = subparsers.add_parser(
        "validate-endpoint",
        help="validate an explicit local port without changing configuration",
    )
    validate.add_argument("port")

    set_endpoint = subparsers.add_parser(
        "set-endpoint",
        help="atomically persist an explicit loopback port",
    )
    set_endpoint.add_argument("port")
    _add_settings_file(set_endpoint)
    _add_revision(set_endpoint)

    reset_endpoint = subparsers.add_parser(
        "reset-endpoint",
        help=f"restore the default loopback port {DEFAULT_LOCAL_PORT}",
    )
    _add_settings_file(reset_endpoint)
    _add_revision(reset_endpoint)

    restart_plan = subparsers.add_parser(
        "shell-restart-plan",
        help="show the bounded restart plan without restarting anything",
    )
    _add_settings_file(restart_plan)

    diagnostics = subparsers.add_parser(
        "shell-diagnostics",
        help="show sanitized shell diagnostics without network access",
    )
    _add_settings_file(diagnostics)

    recover = subparsers.add_parser(
        "recover-shell-settings",
        help="remove bounded abandoned atomic-write files under the shell lock",
    )
    _add_settings_file(recover)

    tray = subparsers.add_parser("set-tray", help="enable or disable tray-default behavior")
    tray.add_argument("value", choices=("enabled", "disabled"))
    _add_settings_file(tray)
    _add_revision(tray)

    theme = subparsers.add_parser("set-theme", help="set the Browser visual theme")
    theme.add_argument("value", choices=("system", "light", "dark"))
    _add_settings_file(theme)
    _add_revision(theme)

    login = subparsers.add_parser(
        "set-login-startup",
        help="separately enable or disable installed Windows login startup",
    )
    login.add_argument("value", choices=("enabled", "disabled"))
    login.add_argument(
        "--command",
        dest="startup_executable",
        help="explicit installed executable used for the Run entry",
    )
    _add_settings_file(login)
    _add_revision(login)

    for name, help_text in (
        ("export-shell-preferences", "export portable shell preferences"),
        ("backup-shell-preferences", "back up portable shell preferences"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("destination", type=Path)
        _add_settings_file(command)

    for name, help_text in (
        ("import-shell-preferences", "import portable shell preferences"),
        ("restore-shell-preferences", "restore portable shell preferences"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("source", type=Path)
        _add_settings_file(command)
        _add_revision(command)


def _print(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _success(settings) -> dict:
    result = settings.public_view()
    result["status"] = "saved"
    result["restart_plan"] = {
        "required": settings.restart_required,
        "automatic_restart": False,
        "rollback_available": settings.last_good_port != settings.endpoint_port,
    }
    return result


def handle_shell_command(args: argparse.Namespace) -> int | None:
    commands = {
        "shell-config",
        "validate-endpoint",
        "set-endpoint",
        "reset-endpoint",
        "shell-restart-plan",
        "shell-diagnostics",
        "recover-shell-settings",
        "set-tray",
        "set-theme",
        "set-login-startup",
        "export-shell-preferences",
        "backup-shell-preferences",
        "import-shell-preferences",
        "restore-shell-preferences",
    }
    if args.command not in commands:
        return None
    try:
        if args.command == "validate-endpoint":
            result = probe_port(args.port)
            _print(result)
            return 0 if result["available"] else 2

        manager = _manager(args)
        loaded = manager.load()
        if args.command == "shell-config":
            _print(loaded.settings.public_view(warning=loaded.warning))
            return 0
        if args.command == "shell-restart-plan":
            settings = loaded.settings
            _print(
                {
                    "schema_version": 1,
                    "required": settings.restart_required,
                    "automatic_restart": False,
                    "configured_port": settings.endpoint_port,
                    "previous_known_port": (
                        settings.last_good_port
                        if settings.last_good_port != settings.endpoint_port
                        else None
                    ),
                    "random_fallback": False,
                    "network_used": False,
                }
            )
            return 0
        if args.command == "shell-diagnostics":
            result = loaded.settings.public_view(warning=loaded.warning)
            result["status"] = "configuration_valid" if loaded.warning is None else "warning"
            result["privacy"] = {
                "contains_instance_path": False,
                "contains_secrets": False,
                "network_used": False,
            }
            result["signing"] = {
                "authenticode": "unsigned",
                "publisher_authentication": "not_established",
            }
            _print(result)
            return 0
        if args.command == "recover-shell-settings":
            _print(manager.recover_abandoned_writes())
            return 0
        if args.command == "set-endpoint":
            settings = manager.set_port(
                args.port,
                expected_revision=args.expected_revision,
            )
            _print(_success(settings))
            return 0
        if args.command == "reset-endpoint":
            settings = manager.reset_port(expected_revision=args.expected_revision)
            _print(_success(settings))
            return 0
        if args.command == "set-tray":
            settings = manager.set_preferences(
                tray_enabled=args.value == "enabled",
                expected_revision=args.expected_revision,
            )
            _print(_success(settings))
            return 0
        if args.command == "set-theme":
            settings = manager.set_preferences(
                theme=args.value,
                expected_revision=args.expected_revision,
            )
            _print(_success(settings))
            return 0
        if args.command == "set-login-startup":
            settings = manager.set_preferences(
                login_startup=args.value == "enabled",
                expected_revision=args.expected_revision,
                startup_command=args.startup_executable,
            )
            _print(_success(settings))
            return 0
        if args.command in {"export-shell-preferences", "backup-shell-preferences"}:
            _print(manager.export_preferences(args.destination))
            return 0
        if args.command in {"import-shell-preferences", "restore-shell-preferences"}:
            settings = manager.import_preferences(
                args.source,
                expected_revision=args.expected_revision,
            )
            _print(_success(settings))
            return 0
    except (OSError, ShellSettingsError, ValueError) as exc:
        message = "shell filesystem operation failed" if isinstance(exc, OSError) else str(exc)
        _print(
            {
                "schema_version": 1,
                "status": "error",
                "code": getattr(exc, "code", "shell_settings_error"),
                "message": message,
                "network_used": False,
            }
        )
        return 2
    raise RuntimeError(f"unsupported shell command: {args.command}")
