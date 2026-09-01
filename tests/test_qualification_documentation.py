from __future__ import annotations

from pathlib import Path

from provelume.i18n import catalog

ROOT = Path(__file__).resolve().parents[1]


def test_english_italian_architecture_contracts_have_semantic_parity() -> None:
    english = (ROOT / "docs" / "architecture" / "cross-source-qualification.md").read_text(
        encoding="utf-8"
    )
    italian = (ROOT / "docs" / "architecture" / "cross-source-qualification.it.md").read_text(
        encoding="utf-8"
    )
    required = {
        "2026-09-01.1",
        "qualification_finding.schema.json",
        "qualification_decision.schema.json",
        "possible-exact-byte-duplicate",
        "possible-participant-homonym",
        "representation-recipe-inconsistent",
        "qualification-required",
        "acknowledge",
        "declare-distinct",
        "correct-observation",
        "supersede",
        "withdraw",
        "revert",
        "qualification_reference_stale",
        "/api/v1/qualification",
        "0.8.0",
        "44851",
    }
    for token in required - {"44851"}:
        assert token in english
        assert token in italian
    assert "authenticated" in english.casefold()
    assert "autentic" in italian.casefold()
    assert "automatic merge" in english.casefold() or "automatico" in english.casefold()
    assert "merge" in italian.casefold()


def test_adr_api_release_roadmap_and_changelog_bind_s06_without_publication() -> None:
    adr = (ROOT / "docs" / "adr" / "0019-cross-source-qualification-and-corrections.md").read_text(
        encoding="utf-8"
    )
    api = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    release = (ROOT / "docs" / "releases" / "0.9.0.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Owner issue: [#153]" in adr
    assert "Public identity: `0.8.0`" in adr
    assert "OWNER PR: PENDING" not in adr
    for endpoint in (
        "/qualification/matrix",
        "/qualification/limits",
        "/qualification/jobs",
        "/qualification/findings",
        "/qualification/decisions",
    ):
        assert endpoint in api
    assert "There are no qualification `POST`, `PATCH`, `DELETE`" in api
    assert "DELIVERED_SLICES: 0.9/S01,0.9/S02,0.9/S03,0.9/S04,0.9/S05,0.9/S06" in release
    assert "DELIVERED_SLICE_ISSUES: #5,#140,#143,#149,#151,#153" in release
    assert "DELIVERED_SLICE_OWNER_PRS: #138,#141,#147,#150,#152,#154" in release
    assert "CURRENT_SLICE: NONE" in release
    assert "CURRENT_PACKAGE_VERSION: 0.8.0" in release
    assert "NEXT_SLICE: 0.9/S07" in release
    assert "product/0.9-s06-cross-source-qualification" in release
    assert "product/0.9-s06-cross-source-qualification" in roadmap
    assert "`0.9/S07` remains forecast-only" in roadmap
    assert "implemented `0.9/S06`" in changelog
    assert "no `0.9.0` publication" in changelog


def test_browser_translation_catalogs_cover_every_qualification_key() -> None:
    english = {key for key in catalog("en") if key.startswith("qualification.")}
    italian = {key for key in catalog("it") if key.startswith("qualification.")}
    assert english == italian
    assert len(english) >= 30
    assert "nav.qualification" in catalog("en")
    assert "nav.qualification" in catalog("it")


def test_permanent_workflow_is_exact_checkout_synthetic_and_nonpublishing() -> None:
    workflow = (ROOT / ".github" / "workflows" / "qualification-smoke.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803" in workflow
    assert "persist-credentials: false" in workflow
    assert "ubuntu-24.04" in workflow
    assert "windows-2025" in workflow
    assert 'PROVELUME_QUALIFICATION_CONFORMANCE_SMOKE: "1"' in workflow
    assert "tests/test_qualification_real_smoke.py" in workflow
    assert "gh release" not in workflow.casefold()
    assert "git tag" not in workflow.casefold()
    assert "upload-release-asset" not in workflow.casefold()
