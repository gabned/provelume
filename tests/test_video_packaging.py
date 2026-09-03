from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_video_manifest_pins_one_external_unbundled_pair() -> None:
    manifest = _json(ROOT / "packaging" / "video" / "ffmpeg-9.0.1.json")
    selected = manifest["selected_pair"]
    distribution = manifest["distribution"]
    assert isinstance(selected, dict) and isinstance(distribution, dict)
    assert manifest["slice"] == "0.10/S05"
    assert selected["version"] == "9.0.1"
    assert selected["source_sha256"] == SOURCE_SHA256
    assert selected["source_size_bytes"] == 12_036_420
    assert selected["bundled_by_provelume"] is False
    assert selected["path_discovery"] is False
    assert selected["runtime_downloads"] is False
    assert distribution["windows_installer"] is False
    assert manifest["rejected_components"] == ["PyAV", "PySceneDetect"]
    matrix = {item["container"]: item for item in manifest["codec_matrix"]}
    assert matrix["WEBM"] == {
        "container": "WEBM",
        "video": ["vp9"],
        "audio": ["opus"],
        "subtitle": ["webvtt"],
    }

    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["dependencies"]
    assert all("av" not in dependency.casefold() for dependency in dependencies)
    assert all("scene" not in dependency.casefold() for dependency in dependencies)


def test_video_schema_bom_workflow_docs_and_notices_agree() -> None:
    schema = _json(ROOT / "core" / "provelume" / "video_profile.schema.json")
    bom = _json(ROOT / "packaging" / "video" / "qualified-local-components.cdx.json")
    workflow = (ROOT / ".github" / "workflows" / "video-smoke.yml").read_text(
        encoding="utf-8"
    )
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    english = (ROOT / "docs" / "video.md").read_text(encoding="utf-8")
    italian = (ROOT / "docs" / "video.it.md").read_text(encoding="utf-8")

    assert schema["properties"]["profile_id"] == {"const": "perceptio-video-v1"}
    assert bom["bomFormat"] == "CycloneDX"
    assert [component["name"] for component in bom["components"]] == [
        "FFmpeg and ffprobe CLI pair"
    ]
    assert SOURCE_SHA256 in workflow
    assert "ffmpeg-9.0.1.tar.xz" in workflow
    assert "--disable-x86asm" in workflow
    assert "Provision fixture generator only" in workflow
    assert "not bundled by Provelume" in notices
    for document in (english, italian):
        assert "PROVELUME_FFMPEG_SHA256" in document
        assert SOURCE_SHA256 in document
        assert "PySceneDetect" in document
