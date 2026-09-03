from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_SHA256 = "818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7"
SOURCE_COMMIT = "306c88f4d1286aec1bf96e544632897886af5501"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_audio_manifest_pins_one_external_unbundled_path() -> None:
    manifest = _json(ROOT / "packaging" / "audio" / "whisper-cpp-1.9.2.json")
    engine = manifest["selected_engine"]
    model = manifest["selected_model"]
    distribution = manifest["distribution"]
    assert isinstance(engine, dict) and isinstance(model, dict) and isinstance(distribution, dict)
    assert manifest["slice"] == "0.10/S04"
    assert engine["version"] == "1.9.2"
    assert engine["source_commit"] == SOURCE_COMMIT
    assert engine["bundled_by_provelume"] is False
    assert model["sha256"] == MODEL_SHA256
    assert model["size_bytes"] == 32_152_673
    assert model["bundled_by_provelume"] is False
    assert distribution["silent_install"] is False
    assert distribution["automatic_update"] is False

    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "dependencies"
    ]
    assert all("whisper" not in dependency.casefold() for dependency in dependencies)


def test_audio_schema_bom_workflow_docs_and_notices_agree() -> None:
    schema = _json(ROOT / "core" / "provelume" / "audio_profile.schema.json")
    bom = _json(ROOT / "packaging" / "audio" / "qualified-local-components.cdx.json")
    workflow = (ROOT / ".github" / "workflows" / "audio-smoke.yml").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    english = (ROOT / "docs" / "audio.md").read_text(encoding="utf-8")
    italian = (ROOT / "docs" / "audio.it.md").read_text(encoding="utf-8")

    assert schema["properties"]["profile_id"] == {"const": "perceptio-audio-v1"}
    assert bom["bomFormat"] == "CycloneDX"
    assert {component["name"] for component in bom["components"]} == {
        "whisper.cpp CLI",
        "Whisper tiny multilingual q5_1 GGML",
    }
    assert SOURCE_COMMIT in workflow
    assert MODEL_SHA256 in workflow
    assert "resolve/d148abaa5548d0deea3cf8075f0fd3376e483c8f/" in workflow
    assert "not bundled by Provelume" in notices
    for document in (english, italian):
        assert "PROVELUME_WHISPER_CPP_SHA256" in document
        assert MODEL_SHA256 in document
