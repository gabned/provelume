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
class ConnectorDefinition:
    schema_version: int
    id: str
    adapter_key: str
    adapter_version: str
    display_name: str
    provider: str
    conformance_profile: str
    adapter_protocol_version: int
    capabilities: tuple[str, ...]
    authorization_modes: tuple[str, ...]
    source_kinds: tuple[str, ...]
    data_categories: tuple[str, ...]
    multi_instance: bool
    network_access: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ConnectorInstance:
    schema_version: int
    id: str
    definition_id: str
    name: str
    provider_identity: str
    account_identity: str | None
    endpoint: str | None
    network_mode: str
    allowed_origins: tuple[str, ...]
    authorization_mode: str
    scopes: tuple[str, ...]
    credential_reference: dict[str, str] | None
    enabled: bool
    lifecycle_state: str
    removed_at: str | None
    cursors: dict[str, Any]
    health: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ConnectorSource:
    schema_version: int
    id: str
    kind: str
    name: str
    created_at: str
    connector_instance_id: str
    source_kind: str
    external_id: str
    enabled: bool
    lifecycle_state: str
    updated_at: str
    removed_at: str | None


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


@dataclass(frozen=True, slots=True)
class HierarchyNode:
    schema_version: int
    id: str
    kind: str
    name: str
    slug: str
    parent_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class DocumentClassification:
    schema_version: int
    id: str
    document_id: str
    primary_node_id: str
    secondary_node_ids: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class DocumentDisposition:
    schema_version: int
    id: str
    document_id: str
    status: str
    library_visibility: str
    restore_status: str | None
    restore_library_visibility: str | None
    revision: int
    created_at: str
    updated_at: str
    last_operation_id: str


def as_record(value: Any) -> dict[str, Any]:
    return asdict(value)
