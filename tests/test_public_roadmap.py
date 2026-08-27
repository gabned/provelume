from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_PATH = ROOT / "docs" / "roadmap.md"
RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.4.0.md"

EXPECTED_CONTRACT = {
    "RELEASE_PLAN_SCHEMA": "1",
    "PLANNED_VERSION": "0.4.0",
    "MILESTONE_TITLE": "0.4.0",
    "CURRENT_PACKAGE_VERSION": "0.4.0",
    "PACKAGE_VERSION_UPDATE": "APPLIED",
    "EXECUTION_ISSUE": "57",
    "PRODUCT_THEME": "WINDOWS_PRODUCT_SHELL_PREVIEW",
    "RELEASE_STATUS": "PUBLISHED_PREVIEW",
    "WINDOWS_SIGNING": "NOT_INCLUDED",
    "UPDATE_APPLY_MODE": "USER_CONFIRMED_INSTALLER",
}

FORECAST_VERSIONS = tuple(f"0.{minor}.0" for minor in range(5, 23)) + ("1.0.0",)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contract_fields(plan: str) -> dict[str, str]:
    blocks = re.findall(r"^```text\n(.*?)\n```$", plan, re.MULTILINE | re.DOTALL)
    if len(blocks) != 1:
        raise AssertionError("release plan must contain exactly one text contract block")

    fields: dict[str, str] = {}
    for line in blocks[0].splitlines():
        if not line:
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]+): ([A-Z0-9_.]+)", line)
        if match is None:
            raise AssertionError(f"invalid release-plan field: {line!r}")
        key, value = match.groups()
        if key not in EXPECTED_CONTRACT:
            raise AssertionError(f"unknown release-plan field: {key}")
        if key in fields:
            raise AssertionError(f"duplicate release-plan field: {key}")
        fields[key] = value
    return fields


def test_release_plan_contract_is_complete_and_closed() -> None:
    assert _contract_fields(_read(RELEASE_PLAN_PATH)) == EXPECTED_CONTRACT


@pytest.mark.parametrize(
    "extra_field",
    (
        "RELEASE_STATUS: planned",
        "UNKNOWN-FIELD: VALUE",
        "UNKNOWN_FIELD: VALUE",
    ),
)
def test_release_plan_contract_rejects_unsupported_lines(extra_field: str) -> None:
    plan = _read(RELEASE_PLAN_PATH)
    contract_end = plan.index("\n```", plan.index("```text"))
    malformed = f"{plan[:contract_end]}\n{extra_field}{plan[contract_end:]}"

    with pytest.raises(AssertionError):
        _contract_fields(malformed)


def test_release_preparation_aligns_package_identity() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        package_version = tomllib.load(handle)["project"]["version"]

    assert package_version == EXPECTED_CONTRACT["CURRENT_PACKAGE_VERSION"]
    assert package_version == EXPECTED_CONTRACT["PLANNED_VERSION"]


def test_roadmap_records_release_and_closed_scope() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Published preview | `0.4.0` |"
    ) == 1
    assert "#57" in roadmap
    assert "#5 — optional local OCR" in roadmap
    assert "#24 — immutable OCI builder" in roadmap
    assert "not part of `0.4.0`" in roadmap


def test_release_forecast_is_complete_ordered_and_not_changelog_history() -> None:
    roadmap = _read(ROADMAP_PATH)
    changelog = _read(ROOT / "CHANGELOG.md")
    heading_positions: list[int] = []

    for version in FORECAST_VERSIONS:
        assert roadmap.count(f"| `{version}` |") == 1
        heading = f"### {version} — "
        assert roadmap.count(heading) == 1
        heading_positions.append(roadmap.index(heading))
        assert f"## {version} -" not in changelog

    assert heading_positions == sorted(heading_positions)
    assert "| Published preview | `0.4.0` |" in roadmap
    assert "| Next forecast | `0.5.0` |" in roadmap
    assert "| Active implementation |" not in roadmap
    assert "#57" in roadmap
    assert "issue just in time" in roadmap
    assert "Forecast entries describe intended sequencing" in roadmap


def test_productivity_connector_forecast_is_explicit_and_guarded() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.12.0` | Productivity connectors and guarded sync preview |"
    ) == 1
    for required_contract in (
        "Every connector type is multi-instance by contract",
        "No adapter may rely on",
        "Google connector preview",
        "Google Calendar",
        "Asana supports multiple OAuth identities",
        "organizations/workspaces, teams and projects",
        "Tududi supports multiple server",
        "per-instance read/write policy",
        "guarded task write-back preview",
        "explicit diff, human confirmation",
        "Local-only mode performs no connector access",
    ):
        assert required_contract in roadmap

    assert "Every later unreleased\nforecast moves forward atomically by one" in roadmap
    assert "`0.22.0` release candidate" in roadmap
    assert "stable `1.0.0` remain unchanged" in roadmap


def test_mobile_capture_is_bounded_and_review_first() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.10.0` | Mobile Capture Inbox and review queue |"
    ) == 1
    for required_contract in (
        "short-lived QR pairing",
        "iOS Shortcut exposed in the Share Sheet",
        "Android share-target",
        "watched Google Drive drop",
        "optional Telegram bot adapter",
        "content traverses Telegram",
        "outside the LAN requires",
        "WhatsApp Cloud API integration",
        "dedicated Business number/API flow",
        "creates no automatic Claim, Decision, Task or CalendarEvent",
    ):
        assert required_contract in roadmap


def test_readme_links_canonical_planning_surfaces() -> None:
    readme = _read(ROOT / "README.md")

    assert "[public roadmap](docs/roadmap.md)" in readme
    assert "[0.4.0 release plan](docs/releases/0.4.0.md)" in readme
    assert "latest published preview is `v0.4.0`" in readme
    assert "[Windows preview guide](docs/windows-preview.md)" in readme


def test_previous_0_3_release_plan_remains_published() -> None:
    plan = _read(ROOT / "docs" / "releases" / "0.3.0.md")
    block = re.findall(r"^```text\n(.*?)\n```$", plan, re.MULTILINE | re.DOTALL)
    assert len(block) == 1
    fields = dict(line.split(": ", 1) for line in block[0].splitlines())
    assert fields["PLANNED_VERSION"] == "0.3.0"
    assert fields["CURRENT_PACKAGE_VERSION"] == "0.3.0"
    assert fields["RELEASE_STATUS"] == "PUBLISHED_PREVIEW"
