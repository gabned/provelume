"""Offline structural/behavior checks; never evidence of linguistic or device review."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from jinja2 import Environment

from provelume.capture_http import capture_script_bytes
from provelume.catalog_registry import (
    LANGUAGE_CHOICES,
    SUPPORTED_LANGUAGES,
    _unique,
    cardinal,
    format_date,
    format_number,
    message,
    raw_catalog,
    registry,
    render_message,
    resolve_language,
    sort_key,
    validate_catalogs,
    validate_registry,
)
from provelume.shell_settings import LauncherSettings, ShellSettingsManager


def test_system_fallback_and_explicit_choice_survive_restart(tmp_path):
    assert {"en", "it", "de", "es", "fr", "pt", "ro"} == SUPPORTED_LANGUAGES
    assert SUPPORTED_LANGUAGES | {"system"} == LANGUAGE_CHOICES
    for host in ("de_DE.UTF-8", "DE-de", "de-CH"):
        assert resolve_language("system", host) == "de"
    assert resolve_language("system", "ja-JP") == "en"
    assert resolve_language("ro", "it-IT") == "ro"
    path = tmp_path / "synthetic-shell.json"
    defaults = LauncherSettings(instance_path=str(tmp_path / "synthetic-instance"))
    manager = ShellSettingsManager(path, defaults)
    manager.save(defaults)
    assert ShellSettingsManager(path, defaults).load().settings.language == "system"
    for language in sorted(LANGUAGE_CHOICES):
        current = manager.load().settings
        manager.set_preferences(expected_revision=current.revision, language=language)
        assert ShellSettingsManager(path, defaults).load().settings.language == language


def test_catalog_completeness_and_review_remain_separate():
    result = validate_catalogs()
    assert result["catalogs"]["en"]["complete"]
    assert result["catalogs"]["it"]["complete"]
    assert all(row["complete"] for row in result["catalogs"].values())
    assert result["automatic_contract"] == "PASS"
    # Draft pack gaps are visible, never counted as translated English or human approval.
    assert result["linguistic_review"] == "UNVERIFIED"
    if any(row["missing"] for row in result["catalogs"].values()):
        assert result["automatic_contract"] == "FAIL"
    assert validate_catalogs(require_complete=False)["automatic_contract"] == "PASS"


def test_registry_rejects_catalog_path_escape_duplicate_language_and_missing_context():
    for mutation in ("path", "duplicate", "context", "export", "glossary"):
        candidate = deepcopy(registry())
        if mutation == "path":
            candidate["languages"][0]["id"] = "../../synthetic"
        elif mutation == "duplicate":
            candidate["languages"].append(candidate["languages"][0])
        elif mutation == "context":
            candidate["messages"][next(iter(candidate["messages"]))]["context"] = ""
        elif mutation == "export":
            candidate["exports"][next(iter(candidate["exports"]))]["keys"].append("absent")
        else:
            candidate["glossary"] = {}
        with pytest.raises(ValueError):
            validate_registry(candidate)


def test_duplicate_keys_and_executable_message_shapes_fail_closed():
    with pytest.raises(ValueError, match="Duplicate"):
        _unique([("key", "first"), ("key", "second")])
    for value in ({"type": "exec", "variable": "count", "cases": {"other": "x"}},
                  {"type": "plural", "variable": "count", "cases": {"one": "one"}},
                  "{value.__class__}", "{value!r}", "{value:>10}"):
        with pytest.raises(ValueError):
            render_message("en", value, count=1, value="synthetic")


def test_parameters_remain_text_and_escape_at_rendering_boundary():
    rendered = render_message("it", "Item: {name}", name='<script>synthetic</script>')
    output = Environment(autoescape=True).from_string("{{ text }}").render(text=rendered)
    assert "<script>" not in output
    assert "&lt;script&gt;" in output
    with pytest.raises(ValueError, match="Missing"):
        render_message("en", "{name}")


def test_cardinal_and_select_contract_includes_romanian_and_portuguese_region():
    assert [cardinal("ro", count) for count in (0, 1, 2, 19, 20, 101)] == [
        "few", "one", "few", "few", "other", "few"]
    assert cardinal("fr", 0) == "one"
    assert cardinal("pt", 0) == "other"  # registry declares pt-PT, not pt-BR
    assert cardinal("fr", 1000000) == "many"
    with pytest.raises(ValueError):
        cardinal("ro", True)
    with pytest.raises(ValueError):
        cardinal("ro", 2**53)
    value = {"type": "plural", "variable": "count",
             "cases": {"one": "one {count}", "few": "few {count}", "other": "other {count}"}}
    assert render_message("ro", value, count=2) == "few 2"
    assert render_message("en", value, count=2) == "other 2"
    selected = {"type": "select", "variable": "state",
                "cases": {"ready": "Ready", "other": "Unavailable"}}
    assert render_message("en", selected, state="unknown") == "Unavailable"


def test_offline_numbers_dates_and_sort_do_not_mutate_canonical_values():
    assert format_number("1234.5", "de", decimals=2) == "1.234,50"
    assert format_number("1234.5", "fr", decimals=1) == "1\u202f234,5"
    date = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
    assert format_date(date, "ro") == "01.10.2026 12:30 +0000"
    assert date.isoformat() == "2026-10-01T12:30:00+00:00"
    with pytest.raises(ValueError):
        format_date(date.replace(tzinfo=None), "en")
    assert sort_key("e\u0301") == sort_key("é")
    for value in ("Infinity", "NaN"):
        with pytest.raises(ValueError):
            format_number(value, "en")


def test_capture_uses_same_offline_catalog_and_contains_no_payload_placeholder():
    source = capture_script_bytes().decode()
    assert "__CAPTURE_WORDS__" not in source
    assert message("it", "capture.retrievalConsent") in raw_catalog("it").values()
    assert len(capture_script_bytes()) < 256 * 1024
    assert all(row["linguistic_review"] == "UNVERIFIED" for row in registry()["languages"])
