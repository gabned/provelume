from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .domain import DerivedArtifact, ProvenanceEdge
from .email_contract import ParsedEmail, qualified_runtime_target

EMAIL_BUNDLE_SCHEMA_VERSION = 1
EMAIL_BUNDLE_KIND = "email_message_bundle"
EMAIL_BUNDLE_GENERATOR = "provelume.local_email"
EMAIL_BUNDLE_GENERATOR_VERSION = "1"
EMAIL_DERIVED_WARNING_CODES = (
    "declared_message_id_collision",
    "thread_reference_missing",
    "thread_reference_ambiguous",
    "thread_reference_cross_source",
    "thread_reference_cycle",
)


def json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def stable_edge(
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
        id=f"edge_{uuid5(NAMESPACE_URL, identity).hex}",
        from_kind=from_kind,
        from_id=from_id,
        relation=relation,
        to_kind=to_kind,
        to_id=to_id,
        created_at=created_at,
    )


def attachment_part_identity(part_id: str, part_path: str) -> str:
    payload = f"email-part-v1\0{part_id}\0{part_path}".encode()
    return hashlib.sha256(payload).hexdigest()


def email_derivation_key(parsed: ParsedEmail, settings_sha256: str) -> str:
    payload = {
        "schema_version": EMAIL_BUNDLE_SCHEMA_VERSION,
        "message_sha256": parsed.message_sha256,
        "parser_id": parsed.parser_id,
        "parser_version": parsed.parser_version,
        "parser_protocol_version": parsed.parser_protocol_version,
        "settings_sha256": settings_sha256,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def bundle_artifact_id(version_id: str, derivation_key: str) -> str:
    key = f"{version_id}:{EMAIL_BUNDLE_KIND}:{derivation_key}"
    return f"derived_{uuid5(NAMESPACE_URL, key).hex}"


def text_artifact_id(version_id: str, body_sha256: str) -> str:
    key = (
        f"{version_id}:extracted_text:{EMAIL_BUNDLE_GENERATOR}:"
        f"{EMAIL_BUNDLE_SCHEMA_VERSION}:{body_sha256}"
    )
    return f"derived_{uuid5(NAMESPACE_URL, key).hex}"


def _warning_record(value: Any) -> dict[str, Any]:
    return {
        "code": value.code,
        "part_id": value.part_id,
        "header_name": value.header_name,
        "occurrence": value.occurrence,
    }


def _header_record(value: Any) -> dict[str, Any]:
    return {
        "name": value.name,
        "occurrence": value.occurrence,
        "raw_value": value.raw_value,
        "raw_sha256": value.raw_sha256,
        "decoded_value": value.decoded_value,
        "state": value.state,
        "warning_codes": list(value.warning_codes),
    }


def _address_group_record(value: Any) -> dict[str, Any]:
    return {
        "header_name": value.header_name,
        "occurrence": value.occurrence,
        "display_name": value.display_name,
        "addresses": [
            {
                "display_name": address.display_name,
                "username": address.username,
                "domain": address.domain,
            }
            for address in value.addresses
        ],
    }


def _part_record(value: Any) -> dict[str, Any]:
    return {
        "part_id": value.part_id,
        "part_path": value.part_path,
        "parent_part_id": value.parent_part_id,
        "media_type": value.media_type,
        "disposition": value.disposition,
        "transfer_encoding": value.transfer_encoding,
        "content_id": value.content_id,
        "filename": value.filename,
        "filename_is_untrusted": value.filename is not None,
        "is_multipart": value.is_multipart,
        "child_part_ids": list(value.child_part_ids),
        "decoded_status": value.decoded_status,
        "decoded_sha256": value.decoded_sha256,
        "decoded_size_bytes": value.decoded_size_bytes,
        "warning_codes": list(value.warning_codes),
    }


def _body_record(parsed: ParsedEmail, storage_ref: str | None) -> dict[str, Any]:
    body = parsed.body
    return {
        "status": body.status,
        "selection_rule": body.selection_rule,
        "part_id": body.part_id,
        "media_type": body.media_type,
        "charset": body.charset,
        "sha256": body.sha256,
        "character_count": body.character_count,
        "storage_ref": storage_ref,
        "authoritative": False,
        "derived": True,
    }


@dataclass(frozen=True, slots=True)
class EmailDerivedPlan:
    derivation_key: str
    bundle_relative: str
    manifest_relative: str
    manifest: dict[str, Any]
    manifest_bytes: bytes
    bundle_artifact: DerivedArtifact
    body_relative: str | None
    body_bytes: bytes | None
    text_artifact: DerivedArtifact | None
    derived_edges: tuple[ProvenanceEdge, ...]


def build_email_bundle(
    *,
    parsed: ParsedEmail,
    job_id: str,
    source_id: str,
    message_id: str,
    observation_id: str,
    acquisition_id: str,
    document_id: str,
    version_id: str,
    original_id: str,
    observed_at: str,
    acquired_at: str,
    container_identity_sha256: str,
    snapshot_sha256: str,
    locator_sha256: str,
    filesystem_identity_sha256: str,
    filesystem_mtime_ns: int,
    adapter: Mapping[str, Any],
    settings_sha256: str,
    attachments: Sequence[Mapping[str, Any]],
    identity_warnings: Sequence[str] = (),
    thread_observation: Mapping[str, Any] | None = None,
) -> EmailDerivedPlan:
    """Build a complete inert representation without writing any Instance state."""

    derivation = email_derivation_key(parsed, settings_sha256)
    relative_root = f"state/derived/email-messages/{message_id}/{derivation}"
    manifest_relative = f"{relative_root}/manifest.json"
    artifact_id = bundle_artifact_id(version_id, derivation)
    body_bytes = (
        parsed.body.text.encode("utf-8")
        if parsed.body.status == "available" and parsed.body.text is not None
        else None
    )
    if body_bytes is not None:
        digest = hashlib.sha256(body_bytes).hexdigest()
        if digest != parsed.body.sha256:
            raise ValueError("email body digest does not match the parser result")
        selected_text_id = text_artifact_id(version_id, digest)
        body_relative = f"state/derived/text/{selected_text_id}.txt"
        text_artifact = DerivedArtifact(
            id=selected_text_id,
            version_id=version_id,
            kind="extracted_text",
            generator=EMAIL_BUNDLE_GENERATOR,
            generator_version=EMAIL_BUNDLE_GENERATOR_VERSION,
            storage_ref=body_relative,
            checksum=digest,
            created_at=acquired_at,
        )
    else:
        body_relative = None
        text_artifact = None

    attachment_rows = [dict(item) for item in attachments]
    manifest = {
        "schema_version": EMAIL_BUNDLE_SCHEMA_VERSION,
        "kind": EMAIL_BUNDLE_KIND,
        "status": "complete",
        "job": {"id": job_id, "state": "message-complete"},
        "derivation_key": derivation,
        "message": {
            "id": message_id,
            "observation_id": observation_id,
            "source_id": source_id,
            "acquisition_id": acquisition_id,
            "document_id": document_id,
            "version_id": version_id,
            "original_id": original_id,
            "original_sha256": parsed.message_sha256,
            "original_size_bytes": parsed.message_size_bytes,
            "container_identity_sha256": container_identity_sha256,
            "container_snapshot_sha256": snapshot_sha256,
            "locator_sha256": locator_sha256,
            "filesystem_identity_sha256": filesystem_identity_sha256,
            "filesystem_mtime_ns": filesystem_mtime_ns,
        },
        "timestamps": {
            "declared": {
                "parsed": list(parsed.declared_dates),
                "observations": [
                    {
                        "occurrence": header.occurrence,
                        "raw": header.raw_value,
                        "decoded": header.decoded_value,
                        "state": header.state,
                    }
                    for header in parsed.headers
                    if header.name.casefold() == "date"
                ],
            },
            "filesystem_observed_at": observed_at,
            "acquired_at": acquired_at,
        },
        "envelope": {
            "headers": [_header_record(item) for item in parsed.headers],
            "address_groups": [
                _address_group_record(item) for item in parsed.address_groups
            ],
        },
        "declared_identity": {
            "message_ids": list(parsed.declared_message_ids),
            "references": list(parsed.references),
            "in_reply_to": list(parsed.in_reply_to),
            "authoritative": False,
        },
        "body": _body_record(parsed, body_relative),
        "mime_tree": [_part_record(item) for item in parsed.parts],
        "attachments": attachment_rows,
        "thread_observation": dict(
            thread_observation
            or {
                "parent_message_id": None,
                "reason": "no-qualified-reference",
                "warning_codes": [],
                "authoritative": False,
                "source_scoped": True,
            }
        ),
        "parser": {
            "id": parsed.parser_id,
            "version": parsed.parser_version,
            "protocol_version": parsed.parser_protocol_version,
            "settings_sha256": settings_sha256,
            "limits": parsed.limits.as_record(),
            "total_decoded_bytes": parsed.total_decoded_bytes,
        },
        "adapter": dict(adapter),
        "platform": qualified_runtime_target(),
        "warnings": [_warning_record(item) for item in parsed.warnings],
        "identity_warnings": [
            {"code": code}
            for code in dict.fromkeys(identity_warnings)
            if code in EMAIL_DERIVED_WARNING_CODES
        ],
        "original_authoritative": True,
        "derived": True,
        "removable": True,
        "rebuildable_from_original": True,
        "active_content_executed": False,
        "remote_fetch": False,
        "network_used": False,
        "runtime_downloads": False,
        "remote_fallback": False,
        "complete": True,
    }
    encoded = json_bytes(manifest)
    bundle_artifact = DerivedArtifact(
        id=artifact_id,
        version_id=version_id,
        kind=EMAIL_BUNDLE_KIND,
        generator=EMAIL_BUNDLE_GENERATOR,
        generator_version=EMAIL_BUNDLE_GENERATOR_VERSION,
        storage_ref=manifest_relative,
        checksum=hashlib.sha256(encoded).hexdigest(),
        created_at=acquired_at,
    )
    edges = [
        stable_edge(
            "email_message",
            message_id,
            "represented_by",
            "derived_artifact",
            bundle_artifact.id,
            created_at=acquired_at,
        )
    ]
    if text_artifact is not None:
        edges.append(
            stable_edge(
                "version",
                version_id,
                "extracted_to",
                "derived_artifact",
                text_artifact.id,
                created_at=acquired_at,
            )
        )
    return EmailDerivedPlan(
        derivation_key=derivation,
        bundle_relative=relative_root,
        manifest_relative=manifest_relative,
        manifest=manifest,
        manifest_bytes=encoded,
        bundle_artifact=bundle_artifact,
        body_relative=body_relative,
        body_bytes=body_bytes,
        text_artifact=text_artifact,
        derived_edges=tuple(edges),
    )


def _declared_id(value: Mapping[str, Any]) -> str | None:
    identity = value.get("declared_identity")
    if not isinstance(identity, Mapping):
        return None
    raw = identity.get("message_ids")
    if not isinstance(raw, list):
        return None
    selected = [item for item in raw if isinstance(item, str)]
    unique = list(dict.fromkeys(selected))
    return unique[0] if len(selected) == 1 and len(unique) == 1 else None


def _references(value: Mapping[str, Any]) -> list[str]:
    identity = value.get("declared_identity")
    if not isinstance(identity, Mapping):
        return []
    reply = identity.get("in_reply_to")
    if isinstance(reply, list):
        selected = list(dict.fromkeys(item for item in reply if isinstance(item, str)))
        if len(selected) == 1:
            return selected
        if len(selected) > 1:
            return []
    references = identity.get("references")
    if not isinstance(references, list):
        return []
    return list(reversed(list(dict.fromkeys(item for item in references if isinstance(item, str)))))


def observed_threads(
    manifests: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build conservative, Source-scoped observed groups from removable manifests."""

    selected: dict[str, Mapping[str, Any]] = {}
    source_for: dict[str, str] = {}
    declared_global: dict[str, list[str]] = defaultdict(list)
    declared_source: dict[tuple[str, str], list[str]] = defaultdict(list)
    for value in manifests:
        message = value.get("message")
        if not isinstance(message, Mapping):
            continue
        message_id = message.get("id")
        source_id = message.get("source_id")
        if not isinstance(message_id, str) or not isinstance(source_id, str):
            continue
        selected[message_id] = value
        source_for[message_id] = source_id
        declared = _declared_id(value)
        if declared is not None:
            declared_global[declared].append(message_id)
            declared_source[(source_id, declared)].append(message_id)

    parents: dict[str, str] = {}
    observations: dict[str, dict[str, Any]] = {}
    for message_id, value in sorted(selected.items()):
        source_id = source_for[message_id]
        declared = _declared_id(value)
        identity_warnings: list[str] = []
        if declared is not None and len(declared_source[(source_id, declared)]) > 1:
            identity_warnings.append("declared_message_id_collision")
        parent: str | None = None
        reason = "no-qualified-reference"
        for reference in _references(value):
            local = declared_source.get((source_id, reference), [])
            if len(local) == 1:
                parent = local[0]
                reason = "unique-same-source-reference"
                break
            if len(local) > 1:
                identity_warnings.append("thread_reference_ambiguous")
                reason = "ambiguous-same-source-reference"
                break
            if declared_global.get(reference):
                identity_warnings.append("thread_reference_cross_source")
                reason = "cross-source-reference-rejected"
                break
            identity_warnings.append("thread_reference_missing")
            reason = "reference-not-observed"
        if parent == message_id:
            parent = None
            reason = "cycle-rejected"
            identity_warnings.append("thread_reference_cycle")
        if parent is not None:
            parents[message_id] = parent
        observations[message_id] = {
            "parent_message_id": parent,
            "reason": reason,
            "warning_codes": list(dict.fromkeys(identity_warnings)),
            "authoritative": False,
            "source_scoped": True,
        }

    cycle_nodes: set[str] = set()
    for start in sorted(parents):
        order: list[str] = []
        positions: dict[str, int] = {}
        current = start
        while current in parents:
            if current in positions:
                cycle_nodes.update(order[positions[current] :])
                break
            positions[current] = len(order)
            order.append(current)
            current = parents[current]
    for message_id in cycle_nodes:
        parents.pop(message_id, None)
        observation = observations[message_id]
        observation["parent_message_id"] = None
        observation["reason"] = "cycle-rejected"
        observation["warning_codes"] = list(
            dict.fromkeys([*observation["warning_codes"], "thread_reference_cycle"])
        )

    def root(message_id: str) -> str:
        current = message_id
        seen: set[str] = set()
        while current in parents and current not in seen:
            seen.add(current)
            current = parents[current]
        return current

    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for message_id in selected:
        grouped[(source_for[message_id], root(message_id))].append(message_id)
    threads: list[dict[str, Any]] = []
    for (source_id, root_id), message_ids in sorted(grouped.items()):
        thread_digest = hashlib.sha256(
            f"{source_id}\0{root_id}".encode()
        ).hexdigest()
        threads.append(
            {
                "schema_version": EMAIL_BUNDLE_SCHEMA_VERSION,
                "id": f"ethr_{thread_digest}",
                "source_id": source_id,
                "root_message_id": root_id,
                "message_ids": sorted(message_ids),
                "message_count": len(message_ids),
                "authoritative": False,
                "source_scoped": True,
                "cross_source_merge": False,
            }
        )
    return threads, observations


__all__ = [
    "EMAIL_BUNDLE_GENERATOR",
    "EMAIL_BUNDLE_GENERATOR_VERSION",
    "EMAIL_BUNDLE_KIND",
    "EMAIL_BUNDLE_SCHEMA_VERSION",
    "EMAIL_DERIVED_WARNING_CODES",
    "EmailDerivedPlan",
    "attachment_part_identity",
    "build_email_bundle",
    "bundle_artifact_id",
    "email_derivation_key",
    "json_bytes",
    "observed_threads",
    "stable_edge",
    "text_artifact_id",
]
