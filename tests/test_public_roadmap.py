from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_PATH = ROOT / "docs" / "roadmap.md"
RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.4.1.md"

EXPECTED_CONTRACT = {
    "RELEASE_PLAN_SCHEMA": "1",
    "PLANNED_VERSION": "0.4.1",
    "MILESTONE_TITLE": "0.4.1",
    "CURRENT_PACKAGE_VERSION": "0.4.1",
    "PACKAGE_VERSION_UPDATE": "APPLIED",
    "EXECUTION_ISSUE": "62",
    "PRODUCT_THEME": "WINDOWS_PRODUCT_SHELL_HARDENING",
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

    assert roadmap.count("| Published preview | `0.4.0` |") == 1
    assert roadmap.count("| Published preview | `0.4.1` |") == 1
    assert "#57" in roadmap
    assert "#62" in roadmap
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
    assert "| Published preview | `0.4.1` |" in roadmap
    assert "| Next forecast | `0.5.0` |" in roadmap
    assert "| Active implementation |" not in roadmap
    assert "#57" in roadmap
    assert "#62" in roadmap
    assert "issue just in time" in roadmap
    assert "Forecast entries describe intended sequencing" in roadmap


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
        "`0.5/S01` persistent run ledger and retry",
        "`0.6/S01` schema migration, backup and recovery",
        "`0.10/S01` Action Center state model and local queues",
    ):
        assert required_contract in roadmap

    assert "## Development slices and installable checkpoints" in policy
    assert "one canonical parent issue and at most one open owner slice pull request" in policy
    assert "never versions, tags or published changelog headings" in policy
    assert "letter-suffixed package versions, are not used" in policy


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
    assert "stable `1.0.0` now depends on `0.22.0`" in roadmap
    assert "connector-related scope expansions in `0.7.0`–`0.11.0`, are explicit above" in roadmap


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


def test_local_inbox_pdf_bundle_and_duplicate_contract_is_explicit() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Next forecast | `0.5.0` | Durable ingestion, local Inbox and document bundles |"
    ) == 1
    for required_contract in (
        "filesystem Drop Inbox",
        "move-after-commit only after exact-byte preservation and hash verification",
        "normalized Markdown, page map",
        "optional separately hashed viewing/mobile optimization",
        "every drop or Source observation\nretains its own Acquisition",
        "Probable duplicates are not silently merged",
        "no input is moved before a committed hash-verified acquisition",
    ):
        assert required_contract in roadmap


def test_hierarchical_filesystem_library_contract_is_explicit() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.6.0` | Portable Instance and hierarchical Markdown library |"
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


def test_ai_uses_bounded_document_context_and_reviewable_proposals() -> None:
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "bounded agent document-context contract",
        "normalized Markdown, page map and minimum required assets",
        "source pages or\nthe Original only when permitted and needed",
        "classification proposals delivered through the same Action Center",
        "immutable separation\nbetween extracted Markdown and AI-authored output",
    ):
        assert required_contract in roadmap


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


def test_readme_links_canonical_planning_surfaces() -> None:
    readme = _read(ROOT / "README.md")

    assert "[public roadmap](docs/roadmap.md)" in readme
    assert "[0.4.1 release plan](docs/releases/0.4.1.md)" in readme
    assert "latest published preview is `v0.4.1`" in readme
    assert "[Windows preview guide](docs/windows-preview.md)" in readme


@pytest.mark.parametrize("version", ("0.3.0", "0.4.0"))
def test_previous_release_plans_remain_published(version: str) -> None:
    plan = _read(ROOT / "docs" / "releases" / f"{version}.md")
    block = re.findall(r"^```text\n(.*?)\n```$", plan, re.MULTILINE | re.DOTALL)
    assert len(block) == 1
    fields = dict(line.split(": ", 1) for line in block[0].splitlines())
    assert fields["PLANNED_VERSION"] == version
    assert fields["CURRENT_PACKAGE_VERSION"] == version
    assert fields["RELEASE_STATUS"] == "PUBLISHED_PREVIEW"
