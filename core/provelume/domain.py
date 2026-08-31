from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

EMAIL_EVIDENCE_SCHEMA_VERSION = 1


def email_message_evidence_id(
    source_id: str,
    original_sha256: str,
    size_bytes: int,
) -> str:
    identity = f"{source_id}\0{original_sha256}\0{size_bytes}".encode()
    return f"emsg_{hashlib.sha256(identity).hexdigest()}"


def email_attachment_evidence_id(
    source_id: str,
    parent_message_id: str,
    part_identity_sha256: str,
    original_sha256: str,
    size_bytes: int,
) -> str:
    identity = (
        f"{source_id}\0{parent_message_id}\0{part_identity_sha256}\0"
        f"{original_sha256}\0{size_bytes}"
    ).encode()
    return f"eatt_{hashlib.sha256(identity).hexdigest()}"


def email_message_observation_id(
    source_id: str,
    adapter_id: str,
    adapter_version: str,
    container_identity_sha256: str,
    container_snapshot_sha256: str,
    locator_sha256: str,
    original_sha256: str,
    size_bytes: int,
    settings_sha256: str,
) -> str:
    identity = "\0".join(
        (
            source_id,
            adapter_id,
            adapter_version,
            container_identity_sha256,
            container_snapshot_sha256,
            locator_sha256,
            original_sha256,
            str(size_bytes),
            settings_sha256,
        )
    ).encode()
    return f"eobs_{hashlib.sha256(identity).hexdigest()}"


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
    authorization: dict[str, Any]
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
    schema_version: int = 1
    acquisition_kind: str = "filesystem"
    connector_instance_id: str | None = None
    requested_url: str | None = None
    final_url: str | None = None
    retrieved_at: str | None = None
    media_type: str | None = None
    original_id: str | None = None
    http_status: int | None = None
    content_encoding: str | None = None
    response_size_bytes: int | None = None
    authorized_origins: tuple[str, ...] | None = None
    replay_of_acquisition_id: str | None = None
    exact_duplicate: bool | None = None
    derived_status: str | None = None
    derived_artifact_id: str | None = None


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


@dataclass(frozen=True, slots=True)
class EmailMessageEvidence:
    """PII-free canonical identity and integrity evidence for one email message."""

    schema_version: int
    id: str
    source_id: str
    document_id: str
    version_id: str
    original_id: str
    original_sha256: str
    size_bytes: int
    adapter_id: str
    adapter_version: str
    parser_id: str
    parser_version: str
    contract_version: str
    settings_sha256: str
    first_acquired_at: str


@dataclass(frozen=True, slots=True)
class EmailMessageObservation:
    """PII-free evidence for one bounded local-container observation."""

    schema_version: int
    id: str
    source_id: str
    message_id: str
    acquisition_id: str
    container_identity_sha256: str
    container_snapshot_sha256: str
    locator_sha256: str
    filesystem_identity_sha256: str
    filesystem_mtime_ns: int
    observed_at: str
    acquired_at: str
    adapter_id: str
    adapter_version: str
    settings_sha256: str


@dataclass(frozen=True, slots=True)
class EmailAttachmentEvidence:
    """PII-free canonical occurrence evidence for decoded attachment bytes."""

    schema_version: int
    id: str
    source_id: str
    parent_message_id: str
    parent_document_id: str
    parent_version_id: str
    part_identity_sha256: str
    original_id: str
    original_sha256: str
    size_bytes: int
    accepted_at: str


def as_record(value: Any) -> dict[str, Any]:
    return asdict(value)
