from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .domain import DerivedArtifact, ProvenanceEdge
from .transcript_contract import ParsedTranscript, TranscriptContractError, TranscriptLimits

TRANSCRIPT_BUNDLE_SCHEMA_VERSION = 1
TRANSCRIPT_BUNDLE_KIND = "transcript_bundle"
TRANSCRIPT_BUNDLE_GENERATOR = "provelume.local_transcript"
TRANSCRIPT_BUNDLE_GENERATOR_VERSION = "1"


def json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{uuid5(NAMESPACE_URL, value).hex}"


def transcript_id(source_id: str, locator_sha256: str) -> str:
    return _stable_id("trn", f"transcript:{source_id}:{locator_sha256}")


def revision_id(selected_transcript_id: str, original_sha256: str) -> str:
    return _stable_id("trev", f"transcript-revision:{selected_transcript_id}:{original_sha256}")


def cue_id(
    selected_revision_id: str,
    ordinal: int,
    start_ms: int,
    end_ms: int,
    text_sha256: str,
) -> str:
    key = f"transcript-cue:{selected_revision_id}:{ordinal}:{start_ms}:{end_ms}:{text_sha256}"
    return _stable_id("tcue", key)


def derivation_key_values(
    *,
    original_sha256: str,
    profile: str,
    parser_id: str,
    parser_version: str,
    parser_protocol_version: int,
    settings_sha256: str,
) -> str:
    payload = {
        "schema_version": TRANSCRIPT_BUNDLE_SCHEMA_VERSION,
        "original_sha256": original_sha256,
        "profile": profile,
        "parser_id": parser_id,
        "parser_version": parser_version,
        "parser_protocol_version": parser_protocol_version,
        "settings_sha256": settings_sha256,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def derivation_key(parsed: ParsedTranscript, settings_sha256: str) -> str:
    return derivation_key_values(
        original_sha256=parsed.original_sha256,
        profile=parsed.profile,
        parser_id=parsed.parser_id,
        parser_version=parsed.parser_version,
        parser_protocol_version=parsed.parser_protocol_version,
        settings_sha256=settings_sha256,
    )


def _edge(
    from_kind: str,
    from_id: str,
    relation: str,
    to_kind: str,
    to_id: str,
    *,
    created_at: str,
) -> ProvenanceEdge:
    identity = f"{from_kind}:{from_id}:{relation}:{to_kind}:{to_id}"
    return ProvenanceEdge(
        id=_stable_id("edge", identity),
        from_kind=from_kind,
        from_id=from_id,
        relation=relation,
        to_kind=to_kind,
        to_id=to_id,
        created_at=created_at,
    )


@dataclass(frozen=True, slots=True)
class TranscriptDerivedPlan:
    derivation_key: str
    transcript_id: str
    revision_id: str
    root_relative: str
    manifest_relative: str
    cues_relative: str
    text_relative: str
    manifest: dict[str, Any]
    manifest_bytes: bytes
    cues_bytes: bytes
    text_bytes: bytes
    bundle_artifact: DerivedArtifact
    text_artifact: DerivedArtifact
    derived_edges: tuple[ProvenanceEdge, ...]


def build_transcript_bundle(
    *,
    parsed: ParsedTranscript,
    limits: TranscriptLimits,
    settings_sha256: str,
    job_id: str,
    source_id: str,
    connector_instance_id: str,
    locator_sha256: str,
    filesystem_identity_sha256: str,
    filesystem_mtime_ns: int,
    acquisition_id: str,
    document_id: str,
    version_id: str,
    original_id: str,
    acquired_at: str,
) -> TranscriptDerivedPlan:
    """Build inert derived bytes in memory; nothing is promoted by this function."""

    selected_transcript_id = transcript_id(source_id, locator_sha256)
    selected_revision_id = revision_id(selected_transcript_id, parsed.original_sha256)
    selected_derivation = derivation_key(parsed, settings_sha256)
    root = f"state/derived/transcripts/{selected_revision_id}/{selected_derivation}"
    manifest_relative = f"{root}/manifest.json"
    cues_relative = f"{root}/cues.json"
    text_relative = f"{root}/transcript.txt"

    cue_rows: list[dict[str, Any]] = []
    for cue in parsed.cues:
        text_sha256 = hashlib.sha256(cue.text.encode("utf-8")).hexdigest()
        cue_rows.append(
            {
                "schema_version": TRANSCRIPT_BUNDLE_SCHEMA_VERSION,
                "id": cue_id(
                    selected_revision_id,
                    cue.ordinal,
                    cue.start_ms,
                    cue.end_ms,
                    text_sha256,
                ),
                "revision_id": selected_revision_id,
                "ordinal": cue.ordinal,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "identifier": cue.identifier,
                "speaker_label": cue.speaker_label,
                "settings": cue.settings,
                "text": cue.text,
                "text_sha256": text_sha256,
                "warning_codes": list(cue.warning_codes),
                "identity_authoritative": False,
                "speaker_identity_verified": False,
                "media_existence_attested": False,
                "active_content": "inert-text",
            }
        )
    cues_payload = {
        "schema_version": TRANSCRIPT_BUNDLE_SCHEMA_VERSION,
        "kind": "transcript_cues",
        "transcript_id": selected_transcript_id,
        "revision_id": selected_revision_id,
        "source_id": source_id,
        "cues": cue_rows,
        "source_scoped": True,
        "cross_source_merge": False,
        "derived": True,
        "complete": True,
        "active_content_executed": False,
        "remote_resources_fetched": False,
    }
    cues_encoded = json_bytes(cues_payload)
    text_encoded = "\n\n".join(cue.text for cue in parsed.cues).encode("utf-8")
    cues_sha256 = hashlib.sha256(cues_encoded).hexdigest()
    text_sha256 = hashlib.sha256(text_encoded).hexdigest()
    total_derived = len(cues_encoded) + len(text_encoded)
    if total_derived > limits.max_derived_bytes_per_file:
        raise TranscriptContractError(
            "transcript_output_limit_exceeded",
            "transcript derived-output limit was exceeded",
        )

    bundle_artifact_id = _stable_id(
        "derived", f"{version_id}:{TRANSCRIPT_BUNDLE_KIND}:{selected_derivation}"
    )
    text_artifact_id = _stable_id(
        "derived", f"{version_id}:transcript_text:{selected_derivation}:{text_sha256}"
    )
    manifest = {
        "schema_version": TRANSCRIPT_BUNDLE_SCHEMA_VERSION,
        "kind": TRANSCRIPT_BUNDLE_KIND,
        "status": "complete",
        "complete": True,
        "job_id": job_id,
        "source_id": source_id,
        "connector_instance_id": connector_instance_id,
        "transcript_id": selected_transcript_id,
        "revision_id": selected_revision_id,
        "acquisition_id": acquisition_id,
        "document_id": document_id,
        "version_id": version_id,
        "original_id": original_id,
        "original_sha256": parsed.original_sha256,
        "original_size_bytes": parsed.original_size_bytes,
        "locator_sha256": locator_sha256,
        "filesystem_identity_sha256": filesystem_identity_sha256,
        "filesystem_mtime_ns": filesystem_mtime_ns,
        "profile": parsed.profile,
        "format": parsed.format,
        "encoding": parsed.encoding,
        "bom": parsed.bom,
        "source_line_endings": parsed.source_line_endings,
        "parser": {
            "id": parsed.parser_id,
            "version": parsed.parser_version,
            "protocol_version": parsed.parser_protocol_version,
            "settings_sha256": settings_sha256,
        },
        "counts": {
            "cues": len(parsed.cues),
            "text_characters": parsed.text_character_count,
            "warnings": len(parsed.warning_codes),
        },
        "warning_codes": list(parsed.warning_codes),
        "representations": {
            "cues": {
                "storage_ref": cues_relative,
                "sha256": cues_sha256,
                "size_bytes": len(cues_encoded),
            },
            "text": {
                "storage_ref": text_relative,
                "sha256": text_sha256,
                "size_bytes": len(text_encoded),
            },
        },
        "acquired_at": acquired_at,
        "original_authoritative": True,
        "derived": True,
        "removable": True,
        "rebuildable_from_original": True,
        "filename_authoritative": False,
        "path_authoritative": False,
        "cue_identity_provider_neutral": True,
        "speaker_identity_verified": False,
        "media_existence_attested": False,
        "active_content_executed": False,
        "remote_resources_fetched": False,
        "network_used": False,
        "runtime_downloads": False,
        "remote_fallback": False,
    }
    manifest_encoded = json_bytes(manifest)
    if total_derived + len(manifest_encoded) > limits.max_derived_bytes_per_file:
        raise TranscriptContractError(
            "transcript_output_limit_exceeded",
            "transcript derived-output limit was exceeded",
        )
    bundle_artifact = DerivedArtifact(
        id=bundle_artifact_id,
        version_id=version_id,
        kind=TRANSCRIPT_BUNDLE_KIND,
        generator=TRANSCRIPT_BUNDLE_GENERATOR,
        generator_version=TRANSCRIPT_BUNDLE_GENERATOR_VERSION,
        storage_ref=manifest_relative,
        checksum=hashlib.sha256(manifest_encoded).hexdigest(),
        created_at=acquired_at,
    )
    text_artifact = DerivedArtifact(
        id=text_artifact_id,
        version_id=version_id,
        kind="transcript_text",
        generator=TRANSCRIPT_BUNDLE_GENERATOR,
        generator_version=TRANSCRIPT_BUNDLE_GENERATOR_VERSION,
        storage_ref=text_relative,
        checksum=text_sha256,
        created_at=acquired_at,
    )
    edges = (
        _edge(
            "original",
            original_id,
            "derived_to",
            "derived_artifact",
            bundle_artifact_id,
            created_at=acquired_at,
        ),
        _edge(
            "version",
            version_id,
            "represented_by",
            "derived_artifact",
            bundle_artifact_id,
            created_at=acquired_at,
        ),
        _edge(
            "version",
            version_id,
            "transcribed_to",
            "derived_artifact",
            text_artifact_id,
            created_at=acquired_at,
        ),
    )
    return TranscriptDerivedPlan(
        derivation_key=selected_derivation,
        transcript_id=selected_transcript_id,
        revision_id=selected_revision_id,
        root_relative=root,
        manifest_relative=manifest_relative,
        cues_relative=cues_relative,
        text_relative=text_relative,
        manifest=manifest,
        manifest_bytes=manifest_encoded,
        cues_bytes=cues_encoded,
        text_bytes=text_encoded,
        bundle_artifact=bundle_artifact,
        text_artifact=text_artifact,
        derived_edges=edges,
    )


__all__ = [
    "TRANSCRIPT_BUNDLE_GENERATOR",
    "TRANSCRIPT_BUNDLE_GENERATOR_VERSION",
    "TRANSCRIPT_BUNDLE_KIND",
    "TRANSCRIPT_BUNDLE_SCHEMA_VERSION",
    "TranscriptDerivedPlan",
    "build_transcript_bundle",
    "cue_id",
    "derivation_key",
    "derivation_key_values",
    "revision_id",
    "transcript_id",
]
