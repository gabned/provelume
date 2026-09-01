from __future__ import annotations

from pathlib import Path

from provelume.transcript_i18n import TRANSCRIPT_TRANSLATIONS

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_transcript_architecture_en_it_cover_the_same_contract_boundaries() -> None:
    english = _read("docs/architecture/transcript-profiles.md")
    italian = _read("docs/architecture/transcript-profiles.it.md")
    required = (
        "srt-v1",
        "webvtt-v1",
        "provelume.bounded-transcript",
        "ConnectorInstance",
        "Source",
        "Original",
        "DocumentVersion",
        "Acquisition",
        "transcript_recipe.schema.json",
        "transcript_bundle.schema.json",
        "transcript_cues.schema.json",
        "transcript_input_changed",
        "speaker_label_ambiguous",
        "no-network",
        "Ubuntu 24.04",
        "Windows Server 2025",
        "CPython 3.12",
        "0.8.0",
        "0.9.0",
        "44851",
    )
    for token in required:
        assert token in english
        assert token in italian
    assert "plain-text profile" in english
    assert "profilo plain-text" in italian
    assert "real provider qualification" in english
    assert "qualificazione provider reale" in italian


def test_adr_release_plan_roadmap_changelog_and_api_keep_slice_boundary() -> None:
    adr = _read("docs/adr/0018-versioned-transcript-profiles.md")
    release = _read("docs/releases/0.9.0.md")
    roadmap = _read("docs/roadmap.md")
    changelog = _read("CHANGELOG.md")
    api = _read("docs/api.md")
    assert "Owner issue: [#151]" in adr
    assert "Owner PR: [#152]" in adr
    assert "Public identity: `0.8.0`" in adr
    assert "DELIVERED_SLICES: 0.9/S01,0.9/S02,0.9/S03,0.9/S04,0.9/S05,0.9/S06" in release
    assert "DELIVERED_SLICE_OWNER_PRS: #138,#141,#147,#150,#152,#154" in release
    assert "CURRENT_SLICE: NONE" in release
    assert "NEXT_SLICE: NONE" in release
    assert "CURRENT_SLICE_STATE: NONE" in release
    assert "does not publish `0.9.0`" in roadmap
    assert "S05 itself made no publication or identity change" in changelog
    assert "upload transcript bytes" in api
    assert "include_content=true" in api


def test_browser_translation_catalogues_have_exact_en_it_key_parity() -> None:
    assert set(TRANSCRIPT_TRANSLATIONS["en"]) == set(TRANSCRIPT_TRANSLATIONS["it"])
    assert all(TRANSCRIPT_TRANSLATIONS["en"].values())
    assert all(TRANSCRIPT_TRANSLATIONS["it"].values())
