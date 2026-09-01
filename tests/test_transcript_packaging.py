from __future__ import annotations

import json
import tomllib
from pathlib import Path

from provelume.transcript_contract import TRANSCRIPT_PARSER_ID

ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_transcript_baseline_adds_no_dependency_model_provider_or_runtime_download() -> None:
    manifest = _json(
        ROOT / "packaging" / "transcript" / "local-transcript-profiles.json"
    )
    distribution = manifest["distribution"]
    assert isinstance(distribution, dict)
    assert distribution["new_python_dependencies"] == []
    assert distribution["new_native_components"] == []
    assert distribution["new_models"] == []
    assert distribution["new_provider_payloads"] == []
    assert distribution["silent_runtime_download"] is False
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert all("transcript" not in item.casefold() for item in dependencies)
    assert all("webvtt" not in item.casefold() for item in dependencies)
    assert all("srt" not in item.casefold() for item in dependencies)


def test_profile_matrix_is_closed_versioned_synthetic_and_release_aligned() -> None:
    manifest = _json(
        ROOT / "packaging" / "transcript" / "local-transcript-profiles.json"
    )
    assert manifest["slice"] == "0.9/S05"
    assert manifest["release_identity"] == "0.9.0"
    assert manifest["development_line"] == "0.9.0-Lectio"
    baseline = manifest["baseline"]
    assert isinstance(baseline, dict)
    assert baseline["default_enabled"] is False
    assert baseline["network_required"] is False
    assert baseline["source_mutation"] is False
    assert baseline["exact_byte_original"] is True
    profiles = baseline["profile_matrix"]
    assert isinstance(profiles, list)
    assert {item["profile"] for item in profiles} == {"srt-v1", "webvtt-v1"}
    boundary = baseline["qualification_boundary"]
    assert boundary == {
        "deterministic_profile_conformance": "requires-positive-exact-head-workflow",
        "platform_smoke": "requires-positive-exact-head-workflow",
        "real_provider_qualification": False,
        "cloud_import_qualification": False,
        "audio_or_video_qualification": False,
    }
    assert "plain text" in baseline["unqualified"]
    assert baseline["parser"]["id"] == TRANSCRIPT_PARSER_ID
    for name in (
        "transcript_contract.schema.json",
        "transcript_revision.schema.json",
        "transcript_recipe.schema.json",
        "transcript_bundle.schema.json",
        "transcript_cues.schema.json",
    ):
        schema = _json(ROOT / "core" / "provelume" / name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False


def test_component_manifest_records_only_runtime_stdlib_and_notices() -> None:
    bom = _json(
        ROOT / "packaging" / "transcript" / "qualified-local-components.cdx.json"
    )
    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.6"
    assert [item["name"] for item in bom["components"]] == [
        "CPython standard library"
    ]
    assert bom["components"][0]["licenses"] == [{"license": {"id": "PSF-2.0"}}]
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "first-party parser in 0.9/S05" in notices
    assert "baseline is included in the later `0.9.0` release boundary" in notices


def test_workflow_is_permanent_exact_checkout_and_has_no_release_or_download_step() -> None:
    workflow = (ROOT / ".github" / "workflows" / "transcript-smoke.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803" in workflow
    assert "ubuntu-24.04" in workflow
    assert "windows-2025" in workflow
    assert "PROVELUME_TRANSCRIPT_CONFORMANCE_SMOKE" in workflow
    assert "persist-credentials: false" in workflow
    assert "gh release" not in workflow.casefold()
    assert "git tag" not in workflow.casefold()
    assert "upload-release-asset" not in workflow.casefold()
