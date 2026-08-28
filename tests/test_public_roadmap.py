from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_PATH = ROOT / "docs" / "roadmap.md"
RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.5.0.md"

EXPECTED_CONTRACT = {
    "RELEASE_PLAN_SCHEMA": "1",
    "PLANNED_VERSION": "0.5.0",
    "MILESTONE_TITLE": "0.5.0",
    "CURRENT_PACKAGE_VERSION": "0.5.0",
    "PACKAGE_VERSION_UPDATE": "APPLIED",
    "EXECUTION_ISSUE": "72",
    "PRODUCT_THEME": "DURABLE_INGESTION_INBOX_BUNDLES_ASSURANCE",
    "RELEASE_STATUS": "PUBLISHED_PREVIEW",
    "WINDOWS_SIGNING": "NOT_INCLUDED",
    "UPDATE_APPLY_MODE": "USER_CONFIRMED_INSTALLER",
}

FORECAST_VERSIONS = tuple(f"0.{minor}.0" for minor in range(6, 23)) + ("1.0.0",)


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


def test_release_plan_contract_is_complete_and_published() -> None:
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
    init_source = _read(ROOT / "core" / "provelume" / "__init__.py")

    assert package_version == EXPECTED_CONTRACT["CURRENT_PACKAGE_VERSION"]
    assert package_version == EXPECTED_CONTRACT["PLANNED_VERSION"]
    assert f'__version__ = "{package_version}"' in init_source


def test_roadmap_records_published_history_and_next_forecast() -> None:
    roadmap = _read(ROADMAP_PATH)

    for version in ("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.4.1", "0.5.0"):
        assert roadmap.count(f"| Published preview | `{version}` |") == 1
    assert "| Next forecast | `0.6.0` |" in roadmap
    assert roadmap.count("| Active implementation |") == 0
    assert "#66 and #72 (completed)" in roadmap
    assert "The package and embedded identity are `0.5.0`" in roadmap
    assert "`0.6.0` forecast is not active" in roadmap


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
    assert "## 0.5.0 - 2026-08-28" in changelog
    assert "Forecast entries describe intended sequencing" in roadmap
    assert "issue just in time" in roadmap


def test_development_slices_do_not_create_ambiguous_package_versions() -> None:
    roadmap = _read(ROADMAP_PATH)
    policy = _read(ROOT / "docs" / "changelog-policy.md")

    for required_contract in (
        "one homogeneous slice per agent turn",
        "at most one owner slice open at a time",
        "`0.N/S01/F01`",
        "micro-adjustment may append `-a`",
        "These IDs create no tag",
        "package versions such\nas `0.5.0a1`, `0.5.0b1` or `0.5.0rc1`",
        "matching SemVer tags",
        "Collapsed forms such as `0.51` or `0.511`",
    ):
        assert required_contract in roadmap

    assert "## Development slices and installable checkpoints" in policy
    assert "one canonical parent issue and at most one open owner slice pull request" in policy
    assert "never versions, tags or published changelog headings" in policy
    assert "letter-suffixed package versions, are not used" in policy


def test_published_0_5_contract_is_explicit() -> None:
    roadmap = _read(ROADMAP_PATH)
    release_plan = _read(RELEASE_PLAN_PATH)

    for required_contract in (
        "persistent ingestion run/item records",
        "move-after-commit only after exact-byte",
        "navigable, path-redacted operation log",
        "normalized Markdown, page map and bounded assets",
        "Probable duplicates are not silently merged",
        "read-only Original assurance",
        "exclusive rebuild locking",
        "configurable Inbox display name, Drop folder and managed-copy folder",
        "external local\n  filesystem locations",
        "missing external mount is not\nsilently recreated",
    ):
        assert required_contract in roadmap

    for required_release_boundary in (
        "relative Instance-local paths or absolute folders elsewhere",
        "Canonical Originals, readable knowledge JSON, derived state, indexes",
        "managed-copy\nfolder is blocked",
        "no automatic merge or deletion",
        "loopback-only, CSRF-protected folder-settings form",
    ):
        assert required_release_boundary in release_plan


def test_update_policy_forecast_is_explicit_and_user_controlled() -> None:
    roadmap = _read(ROADMAP_PATH)

    for published_baseline in (
        "update checks disabled by default",
        "manual `Check now` action",
        "optional check at startup",
        "comparison of the embedded local\nversion",
        "leaves download and installation to the user",
    ):
        assert published_baseline in roadmap

    assert roadmap.count(
        "| Forecast | `0.20.0` | Signed Windows release and safe updater |"
    ) == 1
    for future_policy in (
        "**Disabled/offline:**",
        "**Manual check only:**",
        "**Notify only:**",
        "**Download and ask:**",
        "**Controlled automatic install:**",
        "version pinning, skip-this-version, defer-until",
        "metered-network and battery-aware controls",
        "security-update prominence",
        "update/rollback history",
        "one-click return to manual-only mode",
        "no Instance content is transmitted",
        "Disabled/offline\nperforms no update network access",
        "automatic install cannot run outside its opt-in policy",
    ):
        assert future_policy in roadmap


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

    assert "`0.22.0` release candidate" in roadmap
    assert "stable `1.0.0` now depends on `0.22.0`" in roadmap


def test_mobile_capture_is_bounded_and_review_first() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.10.0` | Unified Capture and Action Center |"
    ) == 1
    for required_contract in (
        "short-lived QR pairing",
        "minimal mobile retrieval view",
        "explicit authenticated original download",
        "iOS Shortcut exposed in the Share Sheet",
        "Android share-target",
        "watched Google Drive drop",
        "optional Telegram bot adapter",
        "content traverses Telegram",
        "outside the LAN requires",
        "WhatsApp Cloud API integration",
        "dedicated Business number/API flow",
        "capture creates no automatic Claim, Decision, Task or\nCalendarEvent",
    ):
        assert required_contract in roadmap


def test_hierarchical_filesystem_library_contract_is_explicit() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Next forecast | `0.6.0` | Portable Instance and hierarchical Markdown library |"
    ) == 1
    for required_contract in (
        "The filesystem is a supported navigation surface",
        "hierarchical Area/Subarea and Project paths",
        "one\nprimary library path",
        "stable and parent-linked",
        "library remains understandable with Provelume stopped",
        "Area/Subarea, Project and Collection\nclassification identities",
        "root\nand per-folder README indexes",
        "generated tag/person/Source/\ndate/type views without duplicate originals",
        "Area/Project rename or movement preserves stable references",
    ):
        assert required_contract in roadmap


def test_original_assurance_and_action_center_contract_is_explicit() -> None:
    roadmap = _read(ROADMAP_PATH)
    browser_architecture = _read(ROOT / "docs" / "architecture" / "knowledge-browser.md")
    state_architecture = _read(
        ROOT / "docs" / "architecture" / "canonical-derived-state.md"
    )

    for required_contract in (
        "routine ingestion, classification,\ndeduplication, refresh, source disappearance",
        "Exact duplicate bytes are stored once by content identity",
        "Archive,\nremove-from-library, recoverable trash and permanent purge",
        "it is never inferred from rejecting an Inbox item",
        "Needs attention` Action Center",
        "reason/confidence,\nimpact and reversibility",
        "destructive or identity-changing decisions always require a human action",
        "reusable non-destructive routing rule",
        "ignored queue items\ncause no destructive action",
    ):
        assert required_contract in roadmap

    assert "## Original assurance and retention" in state_architecture
    assert "A missing or deleted provider item" in state_architecture
    assert "## Filesystem library" in browser_architecture
    assert "## Inbox and Action Center" in browser_architecture
    assert "Generic `Delete` is not a valid knowledge action" in browser_architecture


def test_markdown_navigation_and_viewer_contract_is_explicit() -> None:
    roadmap = _read(ROADMAP_PATH)
    browser_architecture = _read(ROOT / "docs" / "architecture" / "knowledge-browser.md")
    state_architecture = _read(
        ROOT / "docs" / "architecture" / "canonical-derived-state.md"
    )

    assert roadmap.count(
        "| Forecast | `0.13.0` | Knowledge navigation, relations and deterministic discovery |"
    ) == 1
    for required_contract in (
        "Markdown is the first-class portable, human-facing format",
        "it is not the sole canonical storage model or a second database",
        "The published Knowledge Browser already provides",
        "It is also the\nbuilt-in Viewer",
        "safe rendered Markdown, raw/rendered/original modes",
        "A graph is an optional secondary overview",
        "deterministic Markdown library projection",
        "outgoing links and backlinks",
        "visible reason for each suggestion",
        "without AI or a vector store",
    ):
        assert required_contract in roadmap

    assert "# Knowledge Browser/Viewer architecture" in browser_architecture
    assert "The initial Viewer shows bounded extracted text" in browser_architecture
    assert "raw HTML, active content" in browser_architecture
    assert "## Human-facing Markdown" in state_architecture
    assert "derived projections" in state_architecture
    assert "never silently mutate an Original" in state_architecture


def test_readme_links_current_release_and_canonical_planning_surfaces() -> None:
    readme = _read(ROOT / "README.md")

    assert "[public roadmap](docs/roadmap.md)" in readme
    assert "[0.5.0 release plan](docs/releases/0.5.0.md)" in readme
    assert "latest published preview is `v0.5.0`" in readme
    assert "[Windows preview guide](docs/windows-preview.md)" in readme
    assert "configure-inbox" in readme
    assert "external Drop folder" in readme


@pytest.mark.parametrize("version", ("0.3.0", "0.4.0", "0.4.1"))
def test_previous_release_plans_remain_published(version: str) -> None:
    plan = _read(ROOT / "docs" / "releases" / f"{version}.md")
    block = re.findall(r"^```text\n(.*?)\n```$", plan, re.MULTILINE | re.DOTALL)
    assert len(block) == 1
    fields = dict(line.split(": ", 1) for line in block[0].splitlines())
    assert fields["PLANNED_VERSION"] == version
    assert fields["CURRENT_PACKAGE_VERSION"] == version
    assert fields["RELEASE_STATUS"] == "PUBLISHED_PREVIEW"
