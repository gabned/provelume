from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    kind: str
    name: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Acquisition:
    id: str
    source_id: str
    locator: str
    observed_at: str
    content_hash: str
    outcome: str
    document_id: str
    version_id: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Original:
    id: str
    sha256: str
    size_bytes: int
    storage_ref: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    source_id: str
    locator: str
    title: str
    media_type: str
    created_at: str
    current_version_id: str


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    id: str
    document_id: str
    sequence: int
    content_hash: str
    original_id: str
    media_type: str
    size_bytes: int
    acquired_at: str


@dataclass(frozen=True, slots=True)
class DerivedArtifact:
    id: str
    version_id: str
    kind: str
    generator: str
    generator_version: str
    storage_ref: str
    checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    id: str
    from_kind: str
    from_id: str
    relation: str
    to_kind: str
    to_id: str
    created_at: str


def as_record(value: Any) -> dict[str, Any]:
    return asdict(value)
