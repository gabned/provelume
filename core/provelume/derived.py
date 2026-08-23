from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from .domain import DerivedArtifact, ProvenanceEdge
from .extractors import ExtractionResult
from .storage import InstanceStore, utc_now

EXTRACTED_TEXT_SCHEMA = 1


def provenance_edge(
    from_kind: str,
    from_id: str,
    relation: str,
    to_kind: str,
    to_id: str,
) -> ProvenanceEdge:
    value = f"{from_kind}:{from_id}:{relation}:{to_kind}:{to_id}"
    return ProvenanceEdge(
        id=f"edge_{uuid5(NAMESPACE_URL, value).hex}",
        from_kind=from_kind,
        from_id=from_id,
        relation=relation,
        to_kind=to_kind,
        to_id=to_id,
        created_at=utc_now(),
    )


def materialize_extracted_text(
    store: InstanceStore,
    version_id: str,
    extraction: ExtractionResult,
) -> DerivedArtifact:
    artifact_key = (
        f"{version_id}:extracted_text:{extraction.generator}:{EXTRACTED_TEXT_SCHEMA}"
    )
    artifact_id = f"derived_{uuid5(NAMESPACE_URL, artifact_key).hex}"
    relative, checksum = store.write_derived_text(artifact_id, extraction.text)
    artifact = DerivedArtifact(
        id=artifact_id,
        version_id=version_id,
        kind="extracted_text",
        generator=extraction.generator,
        generator_version=extraction.generator_version,
        storage_ref=relative,
        checksum=checksum,
        created_at=utc_now(),
    )
    store.write_derived_artifact(artifact)
    store.write_derived_provenance(
        provenance_edge(
            "version",
            version_id,
            "extracted_to",
            "derived_artifact",
            artifact.id,
        )
    )
    return artifact
