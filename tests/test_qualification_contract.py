from __future__ import annotations

import json
import tomllib
from pathlib import Path

from provelume.qualification_contract import (
    FINDING_TYPES,
    QUALIFICATION_SOURCE_PROFILES,
    WORKFLOW_STATES,
    QualificationLimits,
    qualification_matrix,
)

ROOT = Path(__file__).resolve().parents[1]


def test_matrix_is_closed_versioned_and_keeps_real_google_unqualified() -> None:
    matrix = qualification_matrix()
    assert matrix["schema_version"] == 1
    assert matrix["matrix_version"] == "2026-09-01.1"
    assert tuple(item["id"] for item in matrix["profiles"]) == QUALIFICATION_SOURCE_PROFILES
    assert matrix["unqualified_combinations"]
    google = {
        item["id"]: item
        for item in matrix["profiles"]
        if item["id"] in {"gmail-synthetic-v1", "drive-synthetic-v1"}
    }
    assert set(google) == {"gmail-synthetic-v1", "drive-synthetic-v1"}
    assert all(
        item["authenticated_real_qualification"] == "unqualified" for item in google.values()
    )
    assert "synthetic" in matrix["claim_boundary"]


def test_contract_registries_cover_required_findings_and_human_states() -> None:
    assert {
        "possible-exact-byte-duplicate",
        "possible-revision-relation",
        "observed-metadata-inconsistent",
        "checksum-provenance-incompatible",
        "timestamp-inconsistent",
        "language-format-discordant",
        "possible-same-event-document-content",
        "possible-participant-homonym",
        "representation-missing",
        "representation-obsolete",
        "representation-not-reconstructible",
        "representation-recipe-inconsistent",
        "qualification-required",
    } == set(FINDING_TYPES)
    assert {
        "open",
        "acknowledged",
        "accepted",
        "rejected",
        "deferred",
        "superseded",
        "withdrawn",
        "reverted",
    } == set(WORKFLOW_STATES)
    limits = QualificationLimits()
    assert limits.max_sources == 16
    assert limits.max_candidate_relations == 50_000
    assert limits.max_output_bytes == 32 * 1024 * 1024


def test_schemas_packaging_and_distribution_are_closed_and_release_aligned() -> None:
    for name in ("qualification_finding.schema.json", "qualification_decision.schema.json"):
        schema = json.loads((ROOT / "core" / "provelume" / name).read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
    manifest = json.loads(
        (ROOT / "packaging" / "qualification" / "cross-source-qualification.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["slice"] == "0.9/S06"
    assert manifest["release_identity"] == "0.9.0"
    assert manifest["permanent_smoke"]["real_provider_qualification"] is False
    assert manifest["distribution"]["new_python_dependencies"] == []
    assert manifest["integrity"]["automatic_merge"] is False
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.9.0"
    bom = json.loads(
        (ROOT / "packaging" / "qualification" / "qualified-local-components.cdx.json").read_text(
            encoding="utf-8"
        )
    )
    assert bom["components"] == []
    assert bom["metadata"]["component"]["version"] == "0.9.0"
