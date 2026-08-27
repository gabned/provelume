from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_PATH = ROOT / "docs" / "roadmap.md"
RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.3.0.md"

EXPECTED_CONTRACT = {
    "RELEASE_PLAN_SCHEMA": "1",
    "PLANNED_VERSION": "0.3.0",
    "MILESTONE_TITLE": "0.3.0",
    "CURRENT_PACKAGE_VERSION": "0.2.0",
    "PACKAGE_VERSION_UPDATE": "RELEASE_PREPARATION_ONLY",
    "EXECUTION_ISSUE": "52",
    "SOURCE_SCOPE_ISSUE": "20",
    "PRODUCT_THEME": "ANCHORED_LOCAL_INSTALLATION_TRUST",
    "RELEASE_STATUS": "PLANNED",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contract_fields(plan: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in re.findall(
        r"^([A-Z][A-Z0-9_]+): ([A-Z0-9_.]+)$", plan, re.MULTILINE
    ):
        if key in fields:
            raise AssertionError(f"duplicate release-plan field: {key}")
        fields[key] = value
    return fields


def test_release_plan_contract_is_complete_and_closed() -> None:
    assert _contract_fields(_read(RELEASE_PLAN_PATH)) == EXPECTED_CONTRACT


def test_planning_does_not_change_package_identity() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        package_version = tomllib.load(handle)["project"]["version"]

    assert package_version == EXPECTED_CONTRACT["CURRENT_PACKAGE_VERSION"]
    assert package_version != EXPECTED_CONTRACT["PLANNED_VERSION"]


def test_roadmap_has_one_next_release_and_closed_scope() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count("| Next planned | `0.3.0` |") == 1
    assert "#52" in roadmap
    assert "#20" in roadmap
    assert "#5 — optional local OCR" in roadmap
    assert "#24 — immutable OCI builder" in roadmap
    assert "not part of `0.3.0`" in roadmap


def test_readme_links_canonical_planning_surfaces() -> None:
    readme = _read(ROOT / "README.md")

    assert "[public roadmap](docs/roadmap.md)" in readme
    assert "[0.3.0 release plan](docs/releases/0.3.0.md)" in readme
    assert "Planning does not change the current package identity" in readme
