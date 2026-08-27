from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_PATH = ROOT / "docs" / "roadmap.md"
RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.3.0.md"

EXPECTED_CONTRACT = {
    "RELEASE_PLAN_SCHEMA": "1",
    "PLANNED_VERSION": "0.3.0",
    "MILESTONE_TITLE": "0.3.0",
    "CURRENT_PACKAGE_VERSION": "0.3.0",
    "PACKAGE_VERSION_UPDATE": "APPLIED",
    "EXECUTION_ISSUE": "52",
    "SOURCE_SCOPE_ISSUE": "20",
    "PRODUCT_THEME": "ANCHORED_LOCAL_INSTALLATION_TRUST",
    "RELEASE_STATUS": "PUBLISHED_PREVIEW",
}

FORECAST_VERSIONS = tuple(f"0.{minor}.0" for minor in range(4, 22)) + ("1.0.0",)


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
        "| Published preview | `0.3.0` |"
    ) == 1
    assert "#52" in roadmap
    assert "#20" in roadmap
    assert "#5 — optional local OCR" in roadmap
    assert "#24 — immutable OCI builder" in roadmap
    assert "not part of `0.3.0`" in roadmap


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
    assert "| Active implementation | `0.4.0` |" in roadmap
    assert "| Next forecast | `0.5.0` |" in roadmap
    assert "#57" in roadmap
    assert "issue just in time" in roadmap
    assert "Forecast entries describe intended sequencing" in roadmap


def test_readme_links_canonical_planning_surfaces() -> None:
    readme = _read(ROOT / "README.md")

    assert "[public roadmap](docs/roadmap.md)" in readme
    assert "[0.3.0 release plan](docs/releases/0.3.0.md)" in readme
    assert "latest published preview is `v0.3.0`" in readme
    assert "[release plan](docs/releases/0.4.0.md)" in readme


def test_active_0_4_release_plan_preserves_deferred_package_identity() -> None:
    plan = _read(ROOT / "docs" / "releases" / "0.4.0.md")
    expected = {
        "RELEASE_PLAN_SCHEMA": "1",
        "PLANNED_VERSION": "0.4.0",
        "MILESTONE_TITLE": "0.4.0",
        "CURRENT_PACKAGE_VERSION": "0.3.0",
        "PACKAGE_VERSION_UPDATE": "DEFERRED",
        "EXECUTION_ISSUE": "57",
        "PRODUCT_THEME": "WINDOWS_PRODUCT_SHELL_PREVIEW",
        "RELEASE_STATUS": "ACTIVE_IMPLEMENTATION",
        "WINDOWS_SIGNING": "NOT_INCLUDED",
        "UPDATE_APPLY_MODE": "USER_CONFIRMED_INSTALLER",
    }
    block = re.findall(r"^```text\n(.*?)\n```$", plan, re.MULTILINE | re.DOTALL)
    assert len(block) == 1
    fields = dict(line.split(": ", 1) for line in block[0].splitlines())
    assert fields == expected
