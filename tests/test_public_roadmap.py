from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_PATH = ROOT / "docs" / "roadmap.md"
RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.8.0.md"
VINCULUM_RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.7.0.md"
BASE_RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.5.0.md"
CAPABILITY_RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.6.0.md"
CORRECTION_RELEASE_PLAN_PATH = ROOT / "docs" / "releases" / "0.6.1.md"

EXPECTED_CONTRACT = {
    "RELEASE_PLAN_SCHEMA": "1",
    "PLANNED_VERSION": "0.8.0",
    "MILESTONE_TITLE": "0.8.0",
    "CURRENT_PACKAGE_VERSION": "0.8.0",
    "PACKAGE_VERSION_UPDATE": "APPLIED",
    "EXECUTION_ISSUE": "NONE",
    "PRODUCT_THEME": "DURABLE_SCHEDULER_FOLDER_SOURCES_MAINTENANCE",
    "RELEASE_STATUS": "PUBLISHED_PREVIEW",
    "WINDOWS_SIGNING": "NOT_INCLUDED",
    "UPDATE_APPLY_MODE": "USER_CONFIRMED_INSTALLER",
}

FORECAST_VERSIONS = (
    tuple(f"0.{minor}.0" for minor in range(9, 24))
    + tuple(f"1.{minor}.0" for minor in range(0, 5))
)
LATIN_RELEASE_NAMES = {
    "0.1.0": "Fundamentum",
    "0.2.0": "Fiducia",
    "0.3.0": "Ancora",
    "0.4.0": "Fenestra",
    "0.4.1": "Robur",
    "0.5.0": "Ingressus",
    "0.5.1": "Firmitas",
    "0.6.0": "Bibliotheca",
    "0.6.1": "Integritas",
    "0.7.0": "Vinculum",
    "0.8.0": "Vigilia",
    "0.9.0": "Lectio",
    "0.10.0": "Perceptio",
    "0.11.0": "Cura",
    "0.12.0": "Custodia",
    "0.13.0": "Iudicium",
    "0.14.0": "Entitas",
    "0.15.0": "Concordia",
    "0.16.0": "Itinerarium",
    "0.17.0": "Interfacies",
    "0.18.0": "Sensus",
    "0.19.0": "Domus",
    "0.20.0": "Excubitor",
    "0.21.0": "Renovatio",
    "0.22.0": "Societas",
    "0.23.0": "Probatio",
    "1.0.0": "Maturitas",
    "1.1.0": "Extensio",
    "1.2.0": "Mobilitas",
    "1.3.0": "Cooperatio",
    "1.4.0": "Conservatio",
}


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


def test_release_plan_contract_is_complete_for_published_preview() -> None:
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


def test_release_candidate_aligns_package_identity() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        package_version = tomllib.load(handle)["project"]["version"]
    init_source = _read(ROOT / "core" / "provelume" / "__init__.py")

    assert package_version == EXPECTED_CONTRACT["CURRENT_PACKAGE_VERSION"]
    assert package_version == EXPECTED_CONTRACT["PLANNED_VERSION"]
    assert f'__version__ = "{package_version}"' in init_source


def test_roadmap_records_published_history_and_active_lectio_development() -> None:
    roadmap = _read(ROADMAP_PATH)

    for version in (
        "0.1.0",
        "0.2.0",
        "0.3.0",
        "0.4.0",
        "0.4.1",
        "0.5.0",
        "0.5.1",
        "0.6.0",
        "0.6.1",
        "0.7.0",
        "0.8.0",
    ):
        assert roadmap.count(f"| Published preview | `{version}` |") == 1
    assert roadmap.count("| Active development | `0.9.0` |") == 1
    assert roadmap.count("| Active implementation |") == 0
    assert re.search(r"^\| Release preparation \| `", roadmap, re.MULTILINE) is None
    assert "| Next forecast | `0.9.0` |" not in roadmap
    assert "#137; S01 completed by #5/#138; S02 completed by #140/" in roadmap
    assert "#95 (completed)" in roadmap
    assert "#102 (completed)" in roadmap
    assert "#105 (completed)" in roadmap
    assert "Published package and embedded identity are aligned to `0.8.0`" in roadmap
    assert "Issues #122, #124, #126, #128 and\n#130 completed" in roadmap
    assert "`0.9/S03` is completed by owner" in roadmap
    assert "`0.9/S04` is completed by" in roadmap
    assert "S04 completed by #149/#150" in roadmap
    assert re.search(
        r"`0\.9/S05` transcript profiles is the current\s+merge-gated product candidate",
        roadmap,
    )
    assert "`0.9/S06` is forecast-only" in roadmap


def test_every_release_has_a_unique_latin_name_and_concise_outcome() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert len(LATIN_RELEASE_NAMES) == 31
    assert len(set(LATIN_RELEASE_NAMES.values())) == len(LATIN_RELEASE_NAMES)
    for version, name in LATIN_RELEASE_NAMES.items():
        assert re.fullmatch(r"[A-Za-z]+", name)
        assert roadmap.count(f"| `{name}` |") == 1
        summary = re.compile(
            rf"^- \*\*`{re.escape(version)}` — `{name}`\.\*\* .+\n(?:  .+\n)*  .+\.$",
            re.MULTILINE,
        )
        assert summary.search(roadmap), f"missing concise outcome for {version} — {name}"

    assert "names do not replace SemVer, package identity, tags" in roadmap


def test_public_website_updates_follow_release_evidence() -> None:
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "## Public website synchronization contract",
        "[`provelume.com`](https://provelume.com/)",
        "website build identity from the latest\npublished Core release",
        "`facts.json`,\n`llms.txt`",
        "immediate bounded website workstream",
        "published Core `0.8.0`",
        "website-only correction can begin now",
        "After every verified Core tag and asset publication",
        "`planned`, `preview`, `release candidate` and `available`",
        "| Now, published `0.8.0` |",
        "| Published `0.10.0` |",
        "| Published `0.11.0` |",
        "| Published `0.12.0` |",
        "| Published `0.13.0` |",
        "| Published `0.15.0` |",
        "| Published `0.17.0` |",
        "| Published `0.18.0` |",
        "| Published `0.19.0` |",
        "| Published `0.21.0` |",
        "| Published `0.23.0` |",
        "controlled public beta",
        "developer/client dissemination",
        "broad non-technical desktop-preview distribution",
        "broad release-candidate diffusion",
        "Begin general distribution",
        "EN/IT semantic parity",
        "Website/release/facts parity",
        "website outage\ncannot block installation",
    ):
        assert required_contract in roadmap


def test_release_forecast_is_complete_ordered_and_not_changelog_history() -> None:
    roadmap = _read(ROADMAP_PATH)
    changelog = _read(ROOT / "CHANGELOG.md")
    heading_positions: list[int] = []

    for version in FORECAST_VERSIONS:
        release_row = re.compile(
            rf"^\| (?:Active development|Forecast|Release candidate|Stable|"
            rf"Post-stable forecast) \| `{re.escape(version)}` \|",
            re.MULTILINE,
        )
        assert len(release_row.findall(roadmap)) == 1
        heading = f"### {version} — "
        assert roadmap.count(heading) == 1
        heading_positions.append(roadmap.index(heading))
        assert f"## {version} -" not in changelog

    assert heading_positions == sorted(heading_positions)
    assert "## 0.7.0 - 2026-08-29" in changelog
    assert "## 0.8.0 - 2026-08-30" in changelog
    assert "## 0.6.1 - 2026-08-29" in changelog
    assert "## 0.6.0 - 2026-08-28" in changelog
    assert "## 0.5.1 - 2026-08-28" in changelog
    assert "## 0.5.0 - 2026-08-28" in changelog
    assert "Forecast entries describe intended sequencing" in roadmap
    assert "issue just in time" in roadmap


def test_unreleased_forecast_changes_do_not_rewrite_published_changelog() -> None:
    changelog = _read(ROOT / "CHANGELOG.md")
    published_heading = changelog.index("## 0.7.0 - 2026-08-29")
    next_heading = changelog.index("## 0.6.1 - 2026-08-29")
    published_release = changelog[published_heading:next_heading]

    for forecast_entry in (
        "- expanded the unreleased public forecast with user-controlled "
        "refresh/reindex/maintenance",
        "- added optional mobile/PWA and macOS delivery profiles",
        "- added one-way local-folder and rsync/SSH mirror boundaries",
        "- defined a versioned, authorized and citable grounded-RAG retrieval boundary",
        "- added an evidence-gated `provelume.com` synchronization cadence",
    ):
        assert changelog.count(forecast_entry) == 1
        assert changelog.index(forecast_entry) < published_heading

    published_forecast_entry = (
        "- expanded the unreleased `0.8.0`–`0.20.0` public forecast with user-controlled "
        "watched-folder"
    )
    assert changelog.count(published_forecast_entry) == 1
    for release_time_contract in (
        published_forecast_entry,
        "local OCR, legacy archive import, optional Git mirrors, direct MCP client connections",
        "privacy-routed AI classification, qualified Synology operations",
        "assigned one unique one-word\n  Latin codename",
        "changing already published package, tag or version identity",
    ):
        assert release_time_contract in published_release


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
    release_plan = _read(BASE_RELEASE_PLAN_PATH)

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


def test_published_0_6_contract_is_explicit() -> None:
    release_plan = _read(CAPABILITY_RELEASE_PLAN_PATH)

    for required_contract in (
        "schema-2 Instance manifest",
        "stable parent-linked Area/Subarea, Project and Collection identities",
        "deterministic staged `library/` projection",
        "recoverable trash",
        "deterministic hash-manifested portable export",
        "schema-1 to schema-2 migration",
        "compares every indexed identity, filter field, title and content value",
        "real upgrade from the immutable public `0.5.1` installer",
        "Provelume-Setup-0.5.1-x64.exe",
        "Authenticode",
    ):
        assert required_contract in release_plan


def test_published_0_6_1_correction_is_explicit() -> None:
    release_plan = _read(CORRECTION_RELEASE_PLAN_PATH)
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "adds no new product capability",
        "linked through the selected Document's\n  Version and Acquisition identities",
        "derived search-index refresh and Inbox ingestion",
        "same cross-process Instance lifecycle lock as permanent purge",
        "Provelume-Setup-0.6.0-x64.exe",
        "18,343,369",
        "da338c65b8698d411561bbcb02e0711a1467628e3551c74b0989a7efe7ef6bc3",
        "does not activate or begin `0.7.0`",
    ):
        assert required_contract in release_plan

    assert roadmap.count(
        "| Published preview | `0.6.1` | Purge integrity and ingestion serialization correction |"
    ) == 1


def test_published_0_7_vinculum_is_explicit_and_bounded() -> None:
    release_plan = _read(VINCULUM_RELEASE_PLAN_PATH)
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "first Provelume preview that can acquire one explicitly requested web URL",
        "ConnectorDefinition`, `ConnectorInstance` and `Source` as separate stable identities",
        "mandatory PKCE S256",
        "One explicit local action acquires one canonical URL",
        "exact response representation as a content-addressed immutable Original",
        "0.7/S01 — Connector foundations",
        "0.7/S05 — Manual acquisition",
        "does not include automatic or scheduled refresh, watched folders",
        "OCR, email or Google Drive intake, AI classification",
        "real immutable public `0.6.1 → 0.7.0` in-place upgrade",
        "Provelume-Setup-0.6.1-x64.exe",
        "18,344,455",
        "98e7b693903bc160ac45c11a7c114fed88019c403a98efc07bef5b7e5039afc3",
        "public release exposes exactly 22 assets",
        "1e1731969552497c2d3fe79b1c26eccdaad712c0",
        "46d7df0f94f3e9431685741594489ffcc99e0edf3f4880644c87e280fdecd5cb",
    ):
        assert required_contract in release_plan

    for slice_id in ("0.7/S01", "0.7/S02", "0.7/S03", "0.7/S04", "0.7/S05"):
        assert slice_id in roadmap
    assert "The immutable [`v0.8.0`]" in roadmap


def test_published_0_8_vigilia_is_explicit_and_default_disabled() -> None:
    release_plan = _read(RELEASE_PLAN_PATH)
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "first Provelume preview with durable, explicitly configured scheduling",
        "No policy is created or enabled by upgrade",
        "0.8/S01 — Durable scheduler and journal",
        "0.8/S05 — Resource observations",
        "scheduler policies, jobs, receipts",
        "real immutable public `0.7.0 → 0.8.0` upgrade",
        "Provelume-Setup-0.7.0-x64.exe",
        "18,464,821",
        "46d7df0f94f3e9431685741594489ffcc99e0edf3f4880644c87e280fdecd5cb",
        "provelume-0.7.0-py3-none-any.whl",
        "1beba35635fca2bcafa5d4f1a93d035592751f18785339705e1dbb3df7bf2a41",
        "does not activate `0.9.0 Lectio`",
        "RELEASE_STATUS: PUBLISHED_PREVIEW",
        "33315580878",
        "d20e63079adf85829723cab86766266a8bc6cdcd",
        "22 uniquely named, nonempty assets",
    ):
        assert required_contract in release_plan

    assert "All are merged and published as the bounded `v0.8.0` preview" in roadmap
    assert "[`releases/0.8.0.md`](releases/0.8.0.md)" in roadmap


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
        "| Forecast | `0.21.0` | Signed desktop releases and safe updaters |"
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
        "Disabled/offline performs no update network access",
        "automatic install cannot run outside its opt-in\npolicy",
        "macOS Developer ID signing, notarization and",
        "tampered, revoked, unnotarized, incompatible",
    ):
        assert future_policy in roadmap


def test_watched_folder_ocr_and_automation_forecast_is_explicit() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Published preview | `0.8.0` | Scheduler, watched folders and "
        "recoverable maintenance |"
    ) == 1
    assert roadmap.count(
        "| Active development | `0.9.0` | OCR, email, Google file and transcript intake |"
    ) == 1
    for required_contract in (
        "**disabled/offline**",
        "**manual**",
        "**assisted with confirmation**",
        "**controlled automatic**",
        "UNC/SMB or mounted",
        "configurable quiescence window",
        "move-after-commit",
        "missing external folder or network mount",
        "optional local OCR increment tracked by #5",
        "disabled, automatic when",
        "forced and selected-page modes",
        "page-level text, coordinates",
        "OCR never replaces the Original",
        "remote OCR or\nvision provider",
    ):
        assert required_contract in roadmap


def test_multimedia_representations_and_component_catalogue_are_explicit() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.10.0` | Multimedia, universal content representations and "
        "component inventory |"
    ) == 1
    for required_contract in (
        "## Universal content representation and file-family contract",
        "**Preserve**, **Inspect**",
        "state/derived/bundles/<version_id>/<output_fingerprint>/",
        "`time-map.json`, `region-map.json`",
        "There is no automatic `.md` file beside every source file",
        "versioned\nannotations over one exact derived result",
        "PDF/PDF-A, DOCX, ODT, RTF, EPUB",
        "CSV, TSV, XLSX, ODS, JSONL, Parquet",
        "WAV, FLAC, MP3, M4A/AAC, OGG and Opus",
        "MP4, MOV, MKV, WebM and AVI",
        "P7M/P7S, ASiC-E",
        "## Component provenance, licensing and update visibility contract",
        "Components, models & licenses",
        "latest-known upstream version",
        "`not checked`",
        "Checking never runs `pip`",
        "https://cyclonedx.org/specification/overview/",
        "https://osv.dev/",
        "https://github.com/SYSTRAN/faster-whisper",
        "https://github.com/ggml-org/whisper.cpp",
        "https://pyav.org/docs/stable/",
        "https://www.scenedetect.com/docs/latest/",
        "https://exiftool.org/",
        "https://github.com/zxing-cpp/zxing-cpp",
        "local audio transcription and time anchors",
        "video streams, subtitles, scenes, keyframes and frame OCR",
    ):
        assert required_contract in roadmap


def test_release_quality_and_adoption_gates_are_mandatory_and_aligned() -> None:
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "## Personal use and dissemination contract",
        "Forecast means unavailable",
        "Current published `0.8.0`",
        "First recommended personal daily-use beta",
        "non-technical desktop-preview gate",
        "broad release-candidate qualification",
        "`1.0.0` is general distribution",
        "## Release quality, UX, documentation and security cadence",
        (
            "any pre-publication moment from `Before activation` through "
            "`Release preparation` is missing"
        ),
        "The `After publication` row is a follow-up obligation, not an entry prerequisite",
        "| Before activation |",
        "| Every bounded slice |",
        "| Final quality slice |",
        "| Release preparation |",
        "| After publication |",
        "EN/IT semantic parity",
        "migration/rollback and backup/restore drills",
        "security-response readiness",
        "At least one final bounded slice in every feature release",
    ):
        assert required_contract in roadmap


def test_perceptio_insertion_shifts_the_complete_unreleased_lane() -> None:
    roadmap = _read(ROADMAP_PATH)
    changelog = _read(ROOT / "CHANGELOG.md")
    readme = _read(ROOT / "README.md")

    assert "takes the former `0.10.0` slot" in roadmap
    assert "through the `0.23.0` release candidate" in roadmap
    assert "`0.9.x` stays reserved for corrections" in roadmap
    assert "not hidden in a `0.9.5` feature release" in roadmap
    assert "shifted every later unreleased\n  forecast atomically" in changelog
    assert "It does not use `0.9.5` for feature work" in readme
    assert "0.23.0 — Perceptio" not in roadmap


def test_post_stable_horizon_preserves_personal_and_provider_independence() -> None:
    roadmap = _read(ROADMAP_PATH)

    for version, outcome in (
        ("1.1.0", "Public Adapter SDK and Advanced Format Profiles"),
        ("1.2.0", "Native Mobile Companions and Encrypted Offline Collections"),
        ("1.3.0", "Collaboration, Review and Shared-workspace Workflows"),
        ("1.4.0", "Long-term Preservation, Signatures and Governed Retention"),
    ):
        assert f"### {version} — {outcome}" in roadmap

    for required_contract in (
        "complete Core path works with every extension\ndisabled",
        "no cloud relay is required",
        "personal mode incurs no account, network or collaboration dependency",
        "no technical\nresult is presented as legal advice",
    ):
        assert required_contract in roadmap


def test_scheduler_maintenance_and_local_statistics_are_user_controlled() -> None:
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "## Scheduling, maintenance and local observability contract",
        "fixed interval, local calendar schedule, event-assisted or conditional",
        "skip,\ncoalesce-to-one or one bounded catch-up",
        "lease,\nheartbeat, checkpoint",
        "Incremental or\nfull search reindex",
        "Operations & Maintenance view",
        "run now,\npause, resume, retry, cancel or safely restart",
        "canonical, derived, cache and external-replica",
        "disk-exhaustion forecasts",
        "content-free support bundle",
        "low space pauses new acquisitions",
        "Statistics & Capacity view",
    ):
        assert required_contract in roadmap


def test_legacy_import_git_mirror_and_mcp_connections_are_optional() -> None:
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "generic legacy filesystem/Markdown archive importer",
        "operator-authored mapping manifest",
        "dry-run, copy-only staging",
        "final\nreconciliation report",
        "provider-independent Git mirror capability",
        "GitHub, GitLab and Gitea",
        "disabled, manual publish or scheduled one-way publish",
        "secret and sensitive-data findings",
        "unknown visibility fails closed for private payloads",
        "Bidirectional multi-master Git synchronization remains excluded",
        "authenticated remote HTTPS MCP",
        "ChatGPT is qualified as one\noptional client",
        "Git mirror and MCP are independent choices",
        "no-GitHub modes remain complete product paths",
    ):
        assert required_contract in roadmap


def test_rsync_mirror_and_verified_backup_are_separate() -> None:
    roadmap = _read(ROADMAP_PATH)

    for required_contract in (
        "provider-independent filesystem mirror capability",
        "`rsync` over SSH reference profile",
        "Destination deletion is disabled by default",
        "never applies it\nto an Original store",
        "destination-side staging generation",
        "atomically activated",
        "instead of exposing a mixed or partial generation",
        "approval is bound to the exact source and destination manifests",
        "requires a fresh preview and confirmation",
        "transport and mirror mechanism, not evidence that a backup",
        "Bidirectional rsync",
        "creates an atomic bundle",
        "rereads and verifies the destination manifest",
        "never reads a live mutable Instance",
        "one documented Synology and one documented QNAP",
    ):
        assert required_contract in roadmap


def test_grounded_rag_is_versioned_authorized_and_citable() -> None:
    roadmap = _read(ROADMAP_PATH)
    changelog = _read(ROOT / "CHANGELOG.md")

    assert roadmap.count(
        "| Forecast | `0.18.0` | Semantic, hybrid and grounded RAG retrieval |"
    ) == 1
    for required_contract in (
        "## Grounded retrieval and RAG contract",
        "not another canonical\nstore",
        "Authorization and Source/Area/Project filters run before",
        "stable evidence reference",
        "Original hash, page/section/span",
        "Chunks, embeddings, vector indexes, reranking features and answer caches",
        "search knowledge, assemble context",
        "retrieval receipt",
        "`answer-with-sources`",
        "Retrieved document content remains untrusted input",
        "permission isolation",
        "direct API/MCP retrieval is the authoritative path",
    ):
        assert required_contract in roadmap

    rag_entry = "- defined a versioned, authorized and citable grounded-RAG retrieval boundary"
    assert changelog.count(rag_entry) == 1
    assert changelog.index(rag_entry) < changelog.index("## 0.7.0 - 2026-08-29")


def test_ai_classification_is_closed_reviewable_and_reconcilable() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.13.0` | AI classification, controlled autonomy, receipts, "
        "provider adapters and evaluation |"
    ) == 1
    for required_contract in (
        "disabled`, `proposal-only`, `confirm-each` and\n`controlled-automatic` policies",
        "How much can Provelume decide?",
        "Confidence alone never grants authority",
        "exact Document Version/Original hash",
        "closed schema",
        "every new, changed or broadened rule",
        "Destructive actions, permanent purge",
        "treated as untrusted data rather than\ninstructions",
        "receive no ambient tools or connector secrets",
        "indirect prompt-injection tests",
        "watched-folder acquisition, exact Original\npreservation, extraction/OCR",
        "higher processing level never\nauthorizes canonical classification",
    ):
        assert required_contract in roadmap


def test_nas_and_desktop_background_profiles_are_qualified() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.19.0` | Self-hosted, Synology and QNAP operations |"
    ) == 1
    assert roadmap.count(
        "| Forecast | `0.20.0` | Windows and macOS background agents and bootstrap "
        "completion |"
    ) == 1
    for required_contract in (
        "DSM Container Manager and Portainer-compatible Compose",
        "QTS and QuTS hero systems through Container Station Compose V2",
        "UID/GID and ACL diagnostics",
        "HBS 3, storage snapshots and external rsync jobs",
        "native QPKG",
        "optional encrypted portable\nbundle",
        "one documented Synology and one documented QNAP",
        "per-user background agent and tray surface",
        "macOS adds an application/menu-bar surface and per-user LaunchAgent",
        "Keychain\ncredential references",
        "Apple Silicon baseline",
        "Sleep/wake and disconnected-volume recovery",
        "while the main window is closed",
    ):
        assert required_contract in roadmap


def test_productivity_connector_forecast_is_explicit_and_guarded() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.15.0` | Productivity connectors and guarded sync preview |"
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
        "Local-only/no-GitHub/no-rsync mode performs no connector or mirror access",
    ):
        assert required_contract in roadmap

    assert "`0.23.0` release candidate" in roadmap
    assert "Stable `1.0.0` depends on `0.23.0`" in roadmap


def test_mobile_capture_is_bounded_and_review_first() -> None:
    roadmap = _read(ROADMAP_PATH)

    assert roadmap.count(
        "| Forecast | `0.11.0` | Unified Capture, Operations and Action Center |"
    ) == 1
    for required_contract in (
        "short-lived QR pairing",
        "installable responsive web/PWA surface",
        "offline capture outbox",
        "minimal mobile retrieval view",
        "explicit authenticated original download",
        "iOS Shortcut exposed in the Share Sheet",
        "iOS Share Sheet/Shortcut",
        "Android share-target",
        "optional native iOS and Android",
        "Native\napp-store distribution is a separately qualified delivery decision",
        "Every non-loopback browser connection",
        "requires authenticated HTTPS for installation",
        "plain-HTTP\nfallback disables those capabilities visibly",
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
        "| Published preview | `0.6.0` | Portable Instance and hierarchical Markdown "
        "library |"
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
        "| Forecast | `0.16.0` | Knowledge navigation, statistics, relations and "
        "deterministic discovery |"
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
    assert "[0.8.0 release plan](docs/releases/0.8.0.md)" in readme
    assert "[0.7.0 release plan](docs/releases/0.7.0.md)" in readme
    assert "[`v0.8.0`](https://github.com/gabned/provelume/releases/tag/v0.8.0)" in readme
    assert "is the latest published\nprerelease" in readme
    assert "[Windows preview guide](docs/windows-preview.md)" in readme
    assert "configure-inbox" in readme
    assert "external Drop folder" in readme


@pytest.mark.parametrize(
    "version",
    ("0.3.0", "0.4.0", "0.4.1", "0.5.0", "0.5.1", "0.6.0", "0.6.1", "0.7.0", "0.8.0"),
)
def test_release_plans_remain_published(version: str) -> None:
    plan = _read(ROOT / "docs" / "releases" / f"{version}.md")
    block = re.findall(r"^```text\n(.*?)\n```$", plan, re.MULTILINE | re.DOTALL)
    assert len(block) == 1
    fields = dict(line.split(": ", 1) for line in block[0].splitlines())
    assert fields["PLANNED_VERSION"] == version
    assert fields["CURRENT_PACKAGE_VERSION"] == version
    assert fields["RELEASE_STATUS"] == "PUBLISHED_PREVIEW"
