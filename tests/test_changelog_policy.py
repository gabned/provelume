from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs" / "changelog-policy.md"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"

EXPECTED_CONTRACT = {
    "UNPLANNED_RELEASE_INSERTION_POLICY": "SHIFT_FORWARD",
    "SHIFT_SCOPE": "ALL_LATER_UNRELEASED_PLANNED_RELEASES",
    "PUBLISHED_HISTORY": "IMMUTABLE",
    "CURRENT_VERSION_UPDATE": "RELEASE_PREPARATION_ONLY",
    "FOLLOWUP_RELEASES": "MOVE_WITH_PARENT",
    "ATOMIC_PLANNING_SURFACES": "REQUIRED",
    "PRESERVE_RELATIVE_ORDER": "TRUE",
    "PRESERVE_SCOPE_AND_ISSUE_IDENTITY": "TRUE",
    "CONFLICT_STATE": "ROADMAP_VERSION_SHIFT_CONFLICT",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contract_fields(policy: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in re.findall(r"^([A-Z][A-Z0-9_]+): ([A-Z0-9_]+)$", policy, re.MULTILINE):
        if key in fields:
            raise AssertionError(f"duplicate contract field: {key}")
        fields[key] = value
    return fields


def test_forward_shift_contract_is_complete_and_closed() -> None:
    policy = _read(POLICY_PATH)

    assert _contract_fields(policy) == EXPECTED_CONTRACT
    assert policy.count("ROADMAP_VERSION_SHIFT_CONFLICT") >= 2
    assert "Every later unreleased planned release moves forward" in policy
    assert "Never renumber an existing tag" in policy
    assert "current package version" in policy


def test_changelog_links_policy_and_keeps_unreleased_first() -> None:
    changelog = _read(CHANGELOG_PATH)

    assert "[`docs/changelog-policy.md`](docs/changelog-policy.md)" in changelog
    unreleased_at = changelog.index("## Unreleased")
    first_release = re.search(r"^## \d+\.\d+\.\d+ - \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)
    assert first_release is not None
    assert unreleased_at < first_release.start()
    assert "atomic forward-shift contract for unplanned release insertions" in changelog


def test_released_headings_are_unique_semantic_versions() -> None:
    changelog = _read(CHANGELOG_PATH)
    versions = re.findall(r"^## (\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)

    assert versions
    assert len(versions) == len(set(versions))
