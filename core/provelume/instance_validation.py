from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .connector_model import canonical_connector_errors
from .domain import (
    EMAIL_EVIDENCE_SCHEMA_VERSION,
    email_attachment_evidence_id,
    email_message_evidence_id,
    email_message_observation_id,
)
from .hierarchy_model import (
    canonical_hierarchy_errors,
    classification_provenance_errors,
)
from .instance_schema import (
    CURRENT_INSTANCE_SCHEMA_VERSION,
    DERIVED_STATE_POLICY,
    LEGACY_INSTANCE_SCHEMA_VERSION,
    manifest_validation_errors,
)
from .ocr_contract import OcrContractError, ocr_settings_from_config
from .paths import UnsafePathError, safe_instance_path
from .retention_model import canonical_disposition_errors
from .storage import CANONICAL_KINDS, REQUIRED_CANONICAL_KINDS, InstanceStore
from .web_transport import WebTransportError, canonical_web_origin, canonical_web_url

VALIDATION_REPORT_SCHEMA_VERSION = 1
_INSTANCE_ID = re.compile(r"inst_[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_ACQUISITION_ID = re.compile(r"acq_[0-9a-f]{32}\Z")
_DOCUMENT_ID = re.compile(r"doc_[0-9a-f]{32}\Z")
_VERSION_ID = re.compile(r"ver_[0-9a-f]{32}\Z")
_ORIGINAL_ID = re.compile(r"sha256_[0-9a-f]{64}\Z")
_DERIVED_ID = re.compile(r"derived_[0-9a-f]{32}\Z")
_EMAIL_MESSAGE_ID = re.compile(r"emsg_[0-9a-f]{64}\Z")
_EMAIL_OBSERVATION_ID = re.compile(r"eobs_[0-9a-f]{64}\Z")
_EMAIL_ATTACHMENT_ID = re.compile(r"eatt_[0-9a-f]{64}\Z")
_EMAIL_PART_ID = re.compile(r"epart_[0-9a-f]{64}\Z")
_TECHNICAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z")

_DERIVED_ARTIFACT_FIELDS = {
    "id",
    "version_id",
    "kind",
    "generator",
    "generator_version",
    "storage_ref",
    "checksum",
    "created_at",
}
_EMAIL_BUNDLE_FIELDS = {
    "schema_version",
    "kind",
    "status",
    "job",
    "derivation_key",
    "message",
    "timestamps",
    "envelope",
    "declared_identity",
    "body",
    "mime_tree",
    "attachments",
    "thread_observation",
    "provider_observation",
    "parser",
    "adapter",
    "platform",
    "warnings",
    "identity_warnings",
    "original_authoritative",
    "derived",
    "removable",
    "rebuildable_from_original",
    "active_content_executed",
    "remote_fetch",
    "network_used",
    "runtime_downloads",
    "remote_fallback",
    "complete",
}
_EMAIL_BUNDLE_FIELDS_LEGACY = _EMAIL_BUNDLE_FIELDS - {"provider_observation"}

_EMAIL_MESSAGE_FIELDS = {
    "schema_version",
    "id",
    "source_id",
    "document_id",
    "version_id",
    "original_id",
    "original_sha256",
    "size_bytes",
    "adapter_id",
    "adapter_version",
    "parser_id",
    "parser_version",
    "contract_version",
    "settings_sha256",
    "first_acquired_at",
}
_EMAIL_OBSERVATION_FIELDS = {
    "schema_version",
    "id",
    "source_id",
    "message_id",
    "acquisition_id",
    "container_identity_sha256",
    "container_snapshot_sha256",
    "locator_sha256",
    "filesystem_identity_sha256",
    "filesystem_mtime_ns",
    "observed_at",
    "acquired_at",
    "adapter_id",
    "adapter_version",
    "settings_sha256",
}
_EMAIL_ATTACHMENT_FIELDS = {
    "schema_version",
    "id",
    "source_id",
    "parent_message_id",
    "parent_document_id",
    "parent_version_id",
    "part_identity_sha256",
    "original_id",
    "original_sha256",
    "size_bytes",
    "accepted_at",
}


def _finding(code: str, message: str, *, path: str | None = None) -> dict[str, str]:
    value = {"code": code, "message": message}
    if path is not None:
        value["path"] = path
    return value


def _load_config(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "provelume.yml must contain a mapping"
    return value, None


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "expected a JSON object"
    return value, None


def _valid_instant(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        selected = datetime.fromisoformat(value)
    except ValueError:
        return False
    return selected.tzinfo is not None and selected.utcoffset() is not None


def _valid_technical_value(value: Any) -> bool:
    return isinstance(value, str) and _TECHNICAL_ID.fullmatch(value) is not None


def _derived_json_records(
    directory: Path,
    *,
    errors: list[dict[str, str]] | None = None,
    path_prefix: str | None = None,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.json")):
        value, problem = _load_json(path)
        if problem is None and value is not None:
            records[path.stem] = value
        elif errors is not None and path_prefix is not None:
            errors.append(
                _finding(
                    "derived_state_record_invalid",
                    "Derived state metadata is not a valid JSON object",
                    path=f"{path_prefix}/{path.name}",
                )
            )
    return records


def _email_bundle_body_problem(
    store: InstanceStore,
    value: Any,
    version_id: str,
    artifacts: Mapping[str, Mapping[str, Any]],
    derived_edges: set[tuple[str, str, str, str, str]],
) -> str | None:
    expected = {
        "status",
        "selection_rule",
        "part_id",
        "media_type",
        "charset",
        "sha256",
        "character_count",
        "storage_ref",
        "authoritative",
        "derived",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("status") not in {"available", "unavailable"}
        or not isinstance(value.get("selection_rule"), str)
        or type(value.get("character_count")) is not int
        or int(value.get("character_count", -1)) < 0
        or value.get("authoritative") is not False
        or value.get("derived") is not True
    ):
        return "email bundle body evidence is invalid"
    if value["status"] == "unavailable":
        if (
            value.get("part_id") is not None
            or value.get("media_type") is not None
            or value.get("charset") is not None
            or value.get("sha256") is not None
            or value.get("storage_ref") is not None
            or value.get("character_count") != 0
        ):
            return "unavailable email body has unexpected derived content"
        return None
    storage_ref = value.get("storage_ref")
    digest = value.get("sha256")
    part_id = value.get("part_id")
    if (
        not isinstance(storage_ref, str)
        or _SHA256.fullmatch(str(digest)) is None
        or _EMAIL_PART_ID.fullmatch(str(part_id)) is None
        or value.get("media_type") != "text/plain"
        or not isinstance(value.get("charset"), str)
    ):
        return "available email body identity is invalid"
    matches = [
        artifact
        for artifact in artifacts.values()
        if artifact.get("version_id") == version_id
        and artifact.get("kind") == "extracted_text"
        and artifact.get("generator") == "provelume.local_email"
        and artifact.get("storage_ref") == storage_ref
    ]
    if len(matches) != 1:
        return "email body artifact binding is missing or ambiguous"
    artifact = matches[0]
    artifact_id = str(artifact.get("id"))
    if (
        set(artifact) != _DERIVED_ARTIFACT_FIELDS
        or _DERIVED_ID.fullmatch(artifact_id) is None
        or artifact.get("generator_version") != "1"
        or artifact.get("checksum") != digest
        or not _valid_instant(artifact.get("created_at"))
        or (
            "version",
            version_id,
            "extracted_to",
            "derived_artifact",
            artifact_id,
        )
        not in derived_edges
    ):
        return "email body artifact metadata or provenance is invalid"
    try:
        path = safe_instance_path(store.paths.root, storage_ref)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            return "email body artifact is unavailable or oversized"
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeError, UnsafePathError):
        return "email body artifact is unavailable or invalid"
    if hashlib.sha256(payload).hexdigest() != digest or len(text) != value.get("character_count"):
        return "email body artifact checksum or character count does not match"
    return None


def _email_bundle_attachment_problem(
    value: Any,
    message_id: str,
    attachments: Mapping[str, Mapping[str, Any]],
) -> str | None:
    if not isinstance(value, list) or len(value) > 1000:
        return "email bundle attachment list is invalid"
    expected = {
        "id",
        "part_id",
        "part_path",
        "part_identity_sha256",
        "original_id",
        "sha256",
        "size_bytes",
        "media_type",
        "disposition",
        "content_id",
        "filename",
        "filename_is_untrusted",
        "original_authoritative",
        "ocr",
    }
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, Mapping) or set(row) != expected:
            return "email bundle attachment fields are invalid"
        attachment_id = str(row.get("id"))
        evidence = attachments.get(attachment_id)
        size = row.get("size_bytes")
        ocr = row.get("ocr")
        if (
            attachment_id in seen
            or _EMAIL_ATTACHMENT_ID.fullmatch(attachment_id) is None
            or evidence is None
            or evidence.get("parent_message_id") != message_id
            or row.get("original_id") != evidence.get("original_id")
            or row.get("sha256") != evidence.get("original_sha256")
            or row.get("size_bytes") != evidence.get("size_bytes")
            or row.get("part_identity_sha256") != evidence.get("part_identity_sha256")
            or _EMAIL_PART_ID.fullmatch(str(row.get("part_id"))) is None
            or _SHA256.fullmatch(str(row.get("part_identity_sha256"))) is None
            or _SHA256.fullmatch(str(row.get("sha256"))) is None
            or type(size) is not int
            or int(size) < 0
            or not isinstance(row.get("part_path"), str)
            or not isinstance(row.get("media_type"), str)
            or row.get("filename_is_untrusted") is not (row.get("filename") is not None)
            or row.get("original_authoritative") is not True
            or not isinstance(ocr, Mapping)
            or set(ocr)
            != {
                "eligible",
                "media_type_supported",
                "signature_matches",
                "configured_mode",
                "execution_requested",
                "execution_started",
            }
            or any(
                type(ocr.get(field)) is not bool
                for field in (
                    "eligible",
                    "media_type_supported",
                    "signature_matches",
                    "execution_requested",
                    "execution_started",
                )
            )
            or ocr.get("eligible")
            is not (ocr.get("media_type_supported") and ocr.get("signature_matches"))
            or ocr.get("execution_requested") is not False
            or ocr.get("execution_started") is not False
        ):
            return "email bundle attachment evidence is invalid"
        seen.add(attachment_id)
    return None


def _email_bundle_problem(
    store: InstanceStore,
    artifact_id: str,
    artifact: Mapping[str, Any],
    message_id: str,
    message: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
    attachments: Mapping[str, Mapping[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    derived_edges: set[tuple[str, str, str, str, str]],
) -> str | None:
    version_id = str(message.get("version_id"))
    storage_ref = artifact.get("storage_ref")
    checksum = artifact.get("checksum")
    if (
        set(artifact) != _DERIVED_ARTIFACT_FIELDS
        or artifact.get("id") != artifact_id
        or _DERIVED_ID.fullmatch(artifact_id) is None
        or artifact.get("version_id") != version_id
        or artifact.get("kind") != "email_message_bundle"
        or artifact.get("generator") != "provelume.local_email"
        or artifact.get("generator_version") != "1"
        or not isinstance(storage_ref, str)
        or _SHA256.fullmatch(str(checksum)) is None
        or not _valid_instant(artifact.get("created_at"))
        or (
            "email_message",
            message_id,
            "represented_by",
            "derived_artifact",
            artifact_id,
        )
        not in derived_edges
    ):
        return "email bundle artifact metadata is invalid"
    try:
        manifest_path = safe_instance_path(store.paths.root, storage_ref)
        relative = manifest_path.relative_to(store.paths.root).as_posix()
        manifest_bytes = manifest_path.read_bytes()
    except (OSError, UnsafePathError, ValueError):
        return "email bundle manifest is unavailable or unsafe"
    if manifest_path.is_symlink() or hashlib.sha256(manifest_bytes).hexdigest() != checksum:
        return "email bundle manifest checksum does not match"
    try:
        manifest_value = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "email bundle manifest is not valid UTF-8 JSON"
    if not isinstance(manifest_value, Mapping) or set(manifest_value) not in {
        frozenset(_EMAIL_BUNDLE_FIELDS),
        frozenset(_EMAIL_BUNDLE_FIELDS_LEGACY),
    }:
        return "email bundle manifest fields are invalid"
    manifest = manifest_value
    derivation = manifest.get("derivation_key")
    expected_ref = f"state/derived/email-messages/{message_id}/{derivation}/manifest.json"
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "email_message_bundle"
        or manifest.get("status") != "complete"
        or manifest.get("complete") is not True
        or _SHA256.fullmatch(str(derivation)) is None
        or relative != expected_ref
        or storage_ref != expected_ref
        or manifest.get("original_authoritative") is not True
        or manifest.get("derived") is not True
        or manifest.get("removable") is not True
        or manifest.get("rebuildable_from_original") is not True
        or manifest.get("active_content_executed") is not False
        or type(manifest.get("remote_fetch")) is not bool
        or type(manifest.get("network_used")) is not bool
        or manifest.get("runtime_downloads") is not False
        or manifest.get("remote_fallback") is not False
    ):
        return "email bundle completion or safety flags are invalid"
    message_record = manifest.get("message")
    job_record = manifest.get("job")
    if (
        not isinstance(job_record, Mapping)
        or set(job_record) != {"id", "state"}
        or re.fullmatch(r"job_[0-9a-f]{32}", str(job_record.get("id"))) is None
        or job_record.get("state") != "message-complete"
    ):
        return "email bundle job binding is invalid"
    if not isinstance(message_record, Mapping):
        return "email bundle message binding is missing"
    observation_id = str(message_record.get("observation_id", ""))
    observation = observations.get(observation_id)
    if (
        observation is None
        or message_record.get("id") != message_id
        or message_record.get("source_id") != message.get("source_id")
        or message_record.get("acquisition_id") != observation.get("acquisition_id")
        or message_record.get("document_id") != message.get("document_id")
        or message_record.get("version_id") != version_id
        or message_record.get("original_id") != message.get("original_id")
        or message_record.get("original_sha256") != message.get("original_sha256")
        or message_record.get("original_size_bytes") != message.get("size_bytes")
        or message_record.get("container_identity_sha256")
        != observation.get("container_identity_sha256")
        or message_record.get("container_snapshot_sha256")
        != observation.get("container_snapshot_sha256")
        or message_record.get("locator_sha256") != observation.get("locator_sha256")
        or message_record.get("filesystem_identity_sha256")
        != observation.get("filesystem_identity_sha256")
        or message_record.get("filesystem_mtime_ns") != observation.get("filesystem_mtime_ns")
    ):
        return "email bundle message or observation binding is invalid"
    timestamps = manifest.get("timestamps")
    if (
        not isinstance(timestamps, Mapping)
        or timestamps.get("filesystem_observed_at") != observation.get("observed_at")
        or timestamps.get("acquired_at") != observation.get("acquired_at")
    ):
        return "email bundle timestamps do not match its observation"
    parser = manifest.get("parser")
    if (
        not isinstance(parser, Mapping)
        or not _valid_technical_value(parser.get("id"))
        or not _valid_technical_value(parser.get("version"))
        or type(parser.get("protocol_version")) is not int
        or int(parser.get("protocol_version", 0)) < 1
        or _SHA256.fullmatch(str(parser.get("settings_sha256"))) is None
        or not isinstance(parser.get("limits"), Mapping)
    ):
        return "email bundle parser evidence is invalid"
    adapter = manifest.get("adapter")
    adapter_id = observation.get("adapter_id")
    expected_network = "explicit_only" if adapter_id == "provelume.google" else "none"
    if (
        not isinstance(adapter, Mapping)
        or adapter.get("adapter_id") != adapter_id
        or adapter.get("adapter_version") != observation.get("adapter_version")
        or adapter.get("network_access") != expected_network
        or manifest.get("remote_fetch") != (adapter_id == "provelume.google")
        or manifest.get("network_used") != (adapter_id == "provelume.google")
    ):
        return "email bundle adapter evidence is invalid"
    provider_observation = manifest.get("provider_observation")
    if adapter_id == "provelume.google":
        if not isinstance(provider_observation, Mapping):
            return "Google email provider observation is missing"
        allowed = {
            "provider_item_ref_sha256",
            "provider_revision_ref_sha256",
            "provider_thread_ref_sha256",
            "provider_label_ref_sha256",
            "provider_observed_at",
            "authoritative",
            "source_scoped",
        }
        if (
            set(provider_observation) != allowed
            or _SHA256.fullmatch(str(provider_observation.get("provider_item_ref_sha256"))) is None
            or _SHA256.fullmatch(str(provider_observation.get("provider_revision_ref_sha256")))
            is None
            or (
                provider_observation.get("provider_thread_ref_sha256") is not None
                and _SHA256.fullmatch(str(provider_observation.get("provider_thread_ref_sha256")))
                is None
            )
            or not isinstance(provider_observation.get("provider_label_ref_sha256"), list)
            or any(
                _SHA256.fullmatch(str(value)) is None
                for value in provider_observation.get("provider_label_ref_sha256", [])
            )
            or provider_observation.get("authoritative") is not False
            or provider_observation.get("source_scoped") is not True
        ):
            return "Google email provider observation is invalid"
    elif provider_observation is not None:
        return "local email bundle cannot retain provider observation"
    body_problem = _email_bundle_body_problem(
        store,
        manifest.get("body"),
        version_id,
        artifacts,
        derived_edges,
    )
    if body_problem is not None:
        return body_problem
    attachment_problem = _email_bundle_attachment_problem(
        manifest.get("attachments"),
        message_id,
        attachments,
    )
    if attachment_problem is not None:
        return attachment_problem
    thread = manifest.get("thread_observation")
    if (
        not isinstance(thread, Mapping)
        or thread.get("authoritative") is not False
        or thread.get("source_scoped") is not True
    ):
        return "email bundle thread observation is invalid"
    try:
        if manifest_path.read_bytes() != manifest_bytes:
            return "email bundle manifest changed during validation"
    except OSError:
        return "email bundle manifest changed during validation"
    return None


def _validate_email_evidence(
    store: InstanceStore,
    records: Mapping[str, Mapping[str, Mapping[str, Any]]],
    errors: list[dict[str, str]],
) -> None:
    sources = records["sources"]
    acquisitions = records["acquisitions"]
    documents = records["documents"]
    versions = records["versions"]
    originals = records["originals"]
    valid_messages: dict[str, Mapping[str, Any]] = {}
    observed_edges = {
        (
            str(edge.get("from_kind")),
            str(edge.get("from_id")),
            str(edge.get("relation")),
            str(edge.get("to_kind")),
            str(edge.get("to_id")),
        )
        for edge in records["provenance"].values()
    }

    for record_id, message in records["email-messages"].items():
        path = f"knowledge/email-messages/{record_id}.json"
        size = message.get("size_bytes")
        digest = message.get("original_sha256")
        source_id = message.get("source_id")
        document_id = message.get("document_id")
        version_id = message.get("version_id")
        original_id = message.get("original_id")
        structurally_valid = (
            set(message) == _EMAIL_MESSAGE_FIELDS
            and message.get("schema_version") == EMAIL_EVIDENCE_SCHEMA_VERSION
            and _EMAIL_MESSAGE_ID.fullmatch(record_id) is not None
            and _SOURCE_ID.fullmatch(str(source_id)) is not None
            and _DOCUMENT_ID.fullmatch(str(document_id)) is not None
            and _VERSION_ID.fullmatch(str(version_id)) is not None
            and _ORIGINAL_ID.fullmatch(str(original_id)) is not None
            and _SHA256.fullmatch(str(digest)) is not None
            and type(size) is int
            and size >= 0
            and _valid_technical_value(message.get("adapter_id"))
            and _valid_technical_value(message.get("adapter_version"))
            and _valid_technical_value(message.get("parser_id"))
            and _valid_technical_value(message.get("parser_version"))
            and _valid_technical_value(message.get("contract_version"))
            and _SHA256.fullmatch(str(message.get("settings_sha256"))) is not None
            and _valid_instant(message.get("first_acquired_at"))
        )
        if not structurally_valid:
            errors.append(
                _finding(
                    "email_message_record_invalid",
                    "Email message evidence has invalid or unsupported fields",
                    path=path,
                )
            )
            continue
        if original_id != f"sha256_{digest}" or record_id != email_message_evidence_id(
            str(source_id), str(digest), int(size)
        ):
            errors.append(
                _finding(
                    "email_message_identity_invalid",
                    "Email message evidence identity does not match its bound bytes",
                    path=path,
                )
            )
            continue

        source = sources.get(str(source_id))
        document = documents.get(str(document_id))
        version = versions.get(str(version_id))
        original = originals.get(str(original_id))
        google_message = message.get("adapter_id") == "provelume.google"
        expected_source_kind = "connector" if google_message else "email"
        expected_title = (
            f"Google Gmail message {record_id}"
            if google_message
            else f"Local email message {record_id}"
        )
        if (
            source is None
            or source.get("kind") != expected_source_kind
            or document is None
            or document.get("source_id") != source_id
            or document.get("locator") != f"email-message:{record_id}"
            or document.get("title") != expected_title
            or document.get("media_type") != "message/rfc822"
            or document.get("current_version_id") != version_id
            or version is None
            or version.get("document_id") != document_id
            or version.get("original_id") != original_id
            or version.get("content_hash") != digest
            or version.get("size_bytes") != size
            or version.get("media_type") != "message/rfc822"
            or version.get("sequence") != 1
            or version.get("acquired_at") != message.get("first_acquired_at")
            or original is None
            or original.get("sha256") != digest
            or original.get("size_bytes") != size
        ):
            errors.append(
                _finding(
                    "email_message_reference_invalid",
                    "Email message evidence has an invalid canonical reference",
                    path=path,
                )
            )
            continue
        valid_messages[record_id] = message

    valid_observations: dict[str, Mapping[str, Any]] = {}
    acquisition_observations: dict[str, int] = {}
    for record_id, observation in records["email-observations"].items():
        path = f"knowledge/email-observations/{record_id}.json"
        source_id = observation.get("source_id")
        message_id = observation.get("message_id")
        acquisition_id = observation.get("acquisition_id")
        mtime = observation.get("filesystem_mtime_ns")
        structurally_valid = (
            set(observation) == _EMAIL_OBSERVATION_FIELDS
            and observation.get("schema_version") == EMAIL_EVIDENCE_SCHEMA_VERSION
            and _EMAIL_OBSERVATION_ID.fullmatch(record_id) is not None
            and _SOURCE_ID.fullmatch(str(source_id)) is not None
            and _EMAIL_MESSAGE_ID.fullmatch(str(message_id)) is not None
            and _ACQUISITION_ID.fullmatch(str(acquisition_id)) is not None
            and all(
                _SHA256.fullmatch(str(observation.get(field))) is not None
                for field in (
                    "container_identity_sha256",
                    "container_snapshot_sha256",
                    "locator_sha256",
                    "filesystem_identity_sha256",
                    "settings_sha256",
                )
            )
            and type(mtime) is int
            and mtime >= 0
            and _valid_instant(observation.get("observed_at"))
            and _valid_instant(observation.get("acquired_at"))
            and _valid_technical_value(observation.get("adapter_id"))
            and _valid_technical_value(observation.get("adapter_version"))
        )
        if not structurally_valid:
            errors.append(
                _finding(
                    "email_observation_record_invalid",
                    "Email observation evidence has invalid or unsupported fields",
                    path=path,
                )
            )
            continue
        message = valid_messages.get(str(message_id))
        if message is None or record_id != email_message_observation_id(
            str(source_id),
            str(observation.get("adapter_id")),
            str(observation.get("adapter_version")),
            str(observation.get("container_identity_sha256")),
            str(observation.get("container_snapshot_sha256")),
            str(observation.get("locator_sha256")),
            str(message.get("original_sha256")),
            int(message.get("size_bytes", -1)),
            str(observation.get("settings_sha256")),
        ):
            errors.append(
                _finding(
                    "email_observation_identity_invalid",
                    "Email observation identity does not match its bounded evidence",
                    path=path,
                )
            )
            continue
        acquisition = acquisitions.get(str(acquisition_id))
        original_id = message.get("original_id")
        expected_acquisition_kind = (
            "google_gmail_readonly"
            if observation.get("adapter_id") == "provelume.google"
            else "local_email"
        )
        valid_acquisition = (
            source_id == message.get("source_id")
            and acquisition is not None
            and acquisition.get("source_id") == source_id
            and acquisition.get("document_id") == message.get("document_id")
            and acquisition.get("version_id") == message.get("version_id")
            and acquisition.get("content_hash") == message.get("original_sha256")
            and acquisition.get("original_id") == original_id
            and acquisition.get("locator")
            == f"email-locator:sha256:{observation.get('locator_sha256')}"
            and acquisition.get("observed_at") == observation.get("observed_at")
            and acquisition.get("acquisition_kind") == expected_acquisition_kind
            and acquisition.get("outcome") in {"created", "unchanged"}
            and acquisition.get("media_type") == "message/rfc822"
            and acquisition.get("response_size_bytes") == message.get("size_bytes")
            and acquisition.get("error") is None
            and acquisition.get("connector_instance_id") is None
            and acquisition.get("requested_url") is None
            and acquisition.get("final_url") is None
            and acquisition.get("retrieved_at") is None
            and acquisition.get("http_status") is None
            and acquisition.get("content_encoding") is None
            and acquisition.get("authorized_origins") is None
            and acquisition.get("replay_of_acquisition_id") is None
            and acquisition.get("derived_status") is None
            and acquisition.get("derived_artifact_id") is None
            and type(acquisition.get("exact_duplicate")) is bool
            and acquisition.get("exact_duplicate") is (acquisition.get("outcome") == "unchanged")
        )
        required_edges = {
            ("source", str(source_id), "observed", "acquisition", str(acquisition_id)),
            (
                "acquisition",
                str(acquisition_id),
                "captured",
                "original",
                str(original_id),
            ),
            (
                "acquisition",
                str(acquisition_id),
                "matched",
                "version",
                str(message.get("version_id")),
            ),
            (
                "original",
                str(original_id),
                "materialized_as",
                "version",
                str(message.get("version_id")),
            ),
            (
                "version",
                str(message.get("version_id")),
                "version_of",
                "document",
                str(message.get("document_id")),
            ),
            (
                "acquisition",
                str(acquisition_id),
                "observed_as",
                "email_message",
                str(message_id),
            ),
        }
        if not valid_acquisition:
            errors.append(
                _finding(
                    "email_observation_reference_invalid",
                    "Email observation has an invalid local Acquisition binding",
                    path=path,
                )
            )
            continue
        if not required_edges.issubset(observed_edges):
            errors.append(
                _finding(
                    "email_observation_provenance_incomplete",
                    "Email observation Acquisition provenance is incomplete",
                    path=path,
                )
            )
            continue
        valid_observations[record_id] = observation
        acquisition_key = str(acquisition_id)
        acquisition_observations[acquisition_key] = (
            acquisition_observations.get(acquisition_key, 0) + 1
        )

    for acquisition_id, acquisition in acquisitions.items():
        if acquisition.get("acquisition_kind") != "local_email":
            continue
        count = acquisition_observations.get(acquisition_id, 0)
        if count != 1:
            errors.append(
                _finding(
                    "email_acquisition_observation_invalid",
                    "Local email Acquisition must bind exactly one valid observation",
                    path=f"knowledge/acquisitions/{acquisition_id}.json",
                )
            )

    observed_message_ids = {str(item.get("message_id")) for item in valid_observations.values()}
    for message_id in valid_messages:
        if message_id not in observed_message_ids:
            errors.append(
                _finding(
                    "email_message_observation_missing",
                    "Email message evidence has no valid container observation",
                    path=f"knowledge/email-messages/{message_id}.json",
                )
            )

    valid_attachments: dict[str, Mapping[str, Any]] = {}
    for record_id, attachment in records["email-attachments"].items():
        path = f"knowledge/email-attachments/{record_id}.json"
        source_id = attachment.get("source_id")
        parent_message_id = attachment.get("parent_message_id")
        parent_document_id = attachment.get("parent_document_id")
        parent_version_id = attachment.get("parent_version_id")
        part_identity = attachment.get("part_identity_sha256")
        original_id = attachment.get("original_id")
        digest = attachment.get("original_sha256")
        size = attachment.get("size_bytes")
        structurally_valid = (
            set(attachment) == _EMAIL_ATTACHMENT_FIELDS
            and attachment.get("schema_version") == EMAIL_EVIDENCE_SCHEMA_VERSION
            and _EMAIL_ATTACHMENT_ID.fullmatch(record_id) is not None
            and _SOURCE_ID.fullmatch(str(source_id)) is not None
            and _EMAIL_MESSAGE_ID.fullmatch(str(parent_message_id)) is not None
            and _DOCUMENT_ID.fullmatch(str(parent_document_id)) is not None
            and _VERSION_ID.fullmatch(str(parent_version_id)) is not None
            and _SHA256.fullmatch(str(part_identity)) is not None
            and _ORIGINAL_ID.fullmatch(str(original_id)) is not None
            and _SHA256.fullmatch(str(digest)) is not None
            and type(size) is int
            and size >= 0
            and _valid_instant(attachment.get("accepted_at"))
        )
        if not structurally_valid:
            errors.append(
                _finding(
                    "email_attachment_record_invalid",
                    "Email attachment evidence has invalid or unsupported fields",
                    path=path,
                )
            )
            continue
        if original_id != f"sha256_{digest}" or record_id != email_attachment_evidence_id(
            str(source_id),
            str(parent_message_id),
            str(part_identity),
            str(digest),
            int(size),
        ):
            errors.append(
                _finding(
                    "email_attachment_identity_invalid",
                    "Email attachment evidence identity does not match its occurrence",
                    path=path,
                )
            )
            continue
        parent = valid_messages.get(str(parent_message_id))
        original = originals.get(str(original_id))
        if (
            parent is None
            or parent.get("source_id") != source_id
            or parent.get("document_id") != parent_document_id
            or parent.get("version_id") != parent_version_id
            or original is None
            or original.get("sha256") != digest
            or original.get("size_bytes") != size
        ):
            errors.append(
                _finding(
                    "email_attachment_reference_invalid",
                    "Email attachment evidence has an invalid parent or Original reference",
                    path=path,
                )
            )
            continue
        required_edges = {
            (
                "email_message",
                str(parent_message_id),
                "contained",
                "email_attachment",
                record_id,
            ),
            (
                "email_attachment",
                record_id,
                "materialized_as",
                "original",
                str(original_id),
            ),
        }
        if not required_edges.issubset(observed_edges):
            errors.append(
                _finding(
                    "email_attachment_provenance_incomplete",
                    "Email attachment provenance is incomplete",
                    path=path,
                )
            )
            continue
        valid_attachments[record_id] = attachment

    artifacts = _derived_json_records(
        store.paths.derived_artifacts,
        errors=errors,
        path_prefix="state/derived/artifacts",
    )
    derived_provenance = _derived_json_records(
        store.paths.derived_provenance,
        errors=errors,
        path_prefix="state/derived/provenance",
    )
    derived_edges = {
        (
            str(edge.get("from_kind")),
            str(edge.get("from_id")),
            str(edge.get("relation")),
            str(edge.get("to_kind")),
            str(edge.get("to_id")),
        )
        for edge in derived_provenance.values()
    }
    bundles_by_version: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for artifact_id, artifact in artifacts.items():
        if artifact.get("kind") != "email_message_bundle":
            continue
        bundles_by_version.setdefault(str(artifact.get("version_id")), []).append(
            (artifact_id, artifact)
        )
    for message_id, message in valid_messages.items():
        version_id = str(message.get("version_id"))
        bundles = bundles_by_version.pop(version_id, [])
        if len(bundles) > 1:
            errors.append(
                _finding(
                    "email_bundle_ambiguous",
                    "Email message has more than one active derived bundle",
                    path=f"knowledge/email-messages/{message_id}.json",
                )
            )
            continue
        if not bundles:
            continue
        artifact_id, artifact = bundles[0]
        problem = _email_bundle_problem(
            store,
            artifact_id,
            artifact,
            message_id,
            message,
            valid_observations,
            valid_attachments,
            artifacts,
            derived_edges,
        )
        if problem is not None:
            errors.append(
                _finding(
                    "email_bundle_invalid",
                    problem,
                    path=f"state/derived/artifacts/{artifact_id}.json",
                )
            )
    for bundles in bundles_by_version.values():
        for artifact_id, _artifact in bundles:
            errors.append(
                _finding(
                    "email_bundle_orphaned",
                    "Email bundle does not bind a valid email message Version",
                    path=f"state/derived/artifacts/{artifact_id}.json",
                )
            )


def _canonical_records(
    store: InstanceStore,
    errors: list[dict[str, str]],
) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {}
    for kind in CANONICAL_KINDS:
        directory = store.paths.canonical_dir(kind)
        selected: dict[str, dict[str, Any]] = {}
        records[kind] = selected
        if not directory.is_dir() and (directory.exists() or directory.is_symlink()):
            errors.append(
                _finding(
                    "canonical_directory_invalid",
                    f"canonical path is not a directory: knowledge/{kind}",
                    path=f"knowledge/{kind}",
                )
            )
            continue
        if not directory.is_dir() and kind in REQUIRED_CANONICAL_KINDS:
            errors.append(
                _finding(
                    "canonical_directory_missing",
                    f"canonical directory is missing: knowledge/{kind}",
                    path=f"knowledge/{kind}",
                )
            )
            continue
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            relative = path.relative_to(store.paths.root).as_posix()
            value, problem = _load_json(path)
            if problem is not None or value is None:
                errors.append(
                    _finding(
                        "canonical_record_invalid",
                        f"canonical record cannot be read: {problem}",
                        path=relative,
                    )
                )
                continue
            record_id = value.get("id")
            if not isinstance(record_id, str) or not record_id:
                errors.append(
                    _finding(
                        "canonical_id_invalid",
                        "canonical record has no valid ID",
                        path=relative,
                    )
                )
                continue
            if path.stem != record_id:
                errors.append(
                    _finding(
                        "canonical_filename_mismatch",
                        "canonical filename does not match its record ID",
                        path=relative,
                    )
                )
            if record_id in selected:
                errors.append(
                    _finding(
                        "canonical_id_duplicate",
                        "canonical record ID is duplicated",
                        path=relative,
                    )
                )
                continue
            selected[record_id] = value
    return records


def _validate_google_evidence(
    store: InstanceStore,
    records: Mapping[str, Mapping[str, Mapping[str, Any]]],
    errors: list[dict[str, str]],
) -> None:
    sha_fields = {
        "provider_item_ref_sha256",
        "provider_revision_ref_sha256",
        "provider_thread_ref_sha256",
        "provider_file_ref_sha256",
        "checksum_sha256",
    }
    gmail_fields = {
        "schema_version",
        "id",
        "source_id",
        "message_id",
        "provider_item_ref_sha256",
        "provider_revision_ref_sha256",
        "provider_thread_ref_sha256",
        "provider_label_ref_sha256",
        "provider_observed_at",
        "authoritative",
        "source_scoped",
        "accepted_at",
    }
    for record_id, value in records["google-gmail-observations"].items():
        path = f"knowledge/google-gmail-observations/{record_id}.json"
        valid_sha = all(
            value.get(field) is None or _SHA256.fullmatch(str(value.get(field))) is not None
            for field in sha_fields & set(value)
        )
        labels = value.get("provider_label_ref_sha256")
        valid = (
            set(value) == gmail_fields
            and record_id.startswith("google_gmail_observation_")
            and value.get("schema_version") == 1
            and value.get("source_id") in records["sources"]
            and value.get("message_id") in records["email-messages"]
            and valid_sha
            and isinstance(labels, list)
            and labels == sorted(set(labels))
            and all(_SHA256.fullmatch(str(item)) is not None for item in labels)
            and value.get("authoritative") is False
            and value.get("source_scoped") is True
            and _valid_instant(value.get("accepted_at"))
            and (
                value.get("provider_observed_at") is None
                or _valid_instant(value.get("provider_observed_at"))
            )
        )
        if not valid:
            errors.append(
                _finding(
                    "google_gmail_observation_invalid",
                    "Google Gmail observation is not bounded and source-scoped",
                    path=path,
                )
            )

    file_fields = {
        "schema_version",
        "id",
        "source_id",
        "document_id",
        "provider_file_ref_sha256",
        "current_revision_id",
        "provider_neutral_identity",
        "updated_at",
    }
    revision_fields = {
        "schema_version",
        "id",
        "source_id",
        "document_id",
        "version_id",
        "original_id",
        "acquisition_id",
        "provider_file_ref_sha256",
        "provider_revision_ref_sha256",
        "sequence",
        "source_format",
        "export_format",
        "google_native",
        "media_type",
        "checksum_sha256",
        "size_bytes",
        "provider_observed_at",
        "accepted_at",
        "exact_byte_original",
        "provider_write",
    }
    for record_id, value in records["google-drive-files"].items():
        path = f"knowledge/google-drive-files/{record_id}.json"
        valid = (
            set(value) == file_fields
            and record_id.startswith("google_drive_file_")
            and value.get("schema_version") == 1
            and value.get("source_id") in records["sources"]
            and value.get("document_id") in records["documents"]
            and value.get("current_revision_id") in records["google-drive-revisions"]
            and _SHA256.fullmatch(str(value.get("provider_file_ref_sha256"))) is not None
            and value.get("provider_neutral_identity") is True
            and _valid_instant(value.get("updated_at"))
        )
        if not valid:
            errors.append(
                _finding(
                    "google_drive_file_invalid",
                    "Google Drive file identity is not provider-neutral",
                    path=path,
                )
            )
    for record_id, value in records["google-drive-revisions"].items():
        path = f"knowledge/google-drive-revisions/{record_id}.json"
        original = records["originals"].get(str(value.get("original_id")))
        source_format = value.get("source_format")
        export_format = value.get("export_format")
        google_native = value.get("google_native")
        native_format_valid = isinstance(source_format, str) and (
            (google_native is False and export_format is None)
            or (
                google_native is True
                and source_format.startswith("application/vnd.google-apps.")
                and isinstance(export_format, str)
                and export_format == value.get("media_type")
            )
        )
        valid = (
            set(value) == revision_fields
            and record_id.startswith("google_drive_revision_")
            and value.get("schema_version") == 1
            and value.get("source_id") in records["sources"]
            and value.get("document_id") in records["documents"]
            and value.get("version_id") in records["versions"]
            and value.get("acquisition_id") in records["acquisitions"]
            and original is not None
            and original.get("sha256") == value.get("checksum_sha256")
            and original.get("size_bytes") == value.get("size_bytes")
            and all(
                _SHA256.fullmatch(str(value.get(field))) is not None
                for field in (
                    "provider_file_ref_sha256",
                    "provider_revision_ref_sha256",
                    "checksum_sha256",
                )
            )
            and type(value.get("sequence")) is int
            and int(value.get("sequence", 0)) >= 1
            and type(value.get("size_bytes")) is int
            and int(value.get("size_bytes", -1)) >= 0
            and native_format_valid
            and value.get("exact_byte_original") is True
            and value.get("provider_write") is False
            and _valid_instant(value.get("accepted_at"))
            and (
                value.get("provider_observed_at") is None
                or _valid_instant(value.get("provider_observed_at"))
            )
        )
        if not valid:
            errors.append(
                _finding(
                    "google_drive_revision_invalid",
                    "Google Drive revision evidence or Original binding is invalid",
                    path=path,
                )
            )

    forbidden_keys = {
        "access_token",
        "authorization_header",
        "client_secret",
        "credential_value",
        "refresh_token",
        "token",
    }

    def secret_key_present(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(
                str(key).casefold() in forbidden_keys or secret_key_present(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(secret_key_present(item) for item in value)
        return False

    state_root = store.paths.state / "google-adapters"
    if state_root.is_dir():
        for path in sorted(state_root.rglob("*.json")):
            value, problem = _load_json(path)
            relative = path.relative_to(store.paths.root).as_posix()
            if problem is not None or value is None or secret_key_present(value):
                errors.append(
                    _finding(
                        "google_secret_material_invalid",
                        "Google state contains unreadable or forbidden secret material",
                        path=relative,
                    )
                )


def _validate_references(
    store: InstanceStore,
    records: Mapping[str, Mapping[str, Mapping[str, Any]]],
    errors: list[dict[str, str]],
) -> None:
    sources = records["sources"]
    documents = records["documents"]
    versions = records["versions"]
    originals = records["originals"]

    for record_id, document in documents.items():
        path = f"knowledge/documents/{record_id}.json"
        if document.get("source_id") not in sources:
            errors.append(
                _finding(
                    "document_source_missing",
                    "Document references a missing Source",
                    path=path,
                )
            )
        current = document.get("current_version_id")
        version = versions.get(str(current))
        if version is None or version.get("document_id") != record_id:
            errors.append(
                _finding(
                    "document_current_version_missing",
                    "Document current Version is missing or belongs to another Document",
                    path=path,
                )
            )

    for record_id, version in versions.items():
        path = f"knowledge/versions/{record_id}.json"
        if version.get("document_id") not in documents:
            errors.append(
                _finding(
                    "version_document_missing",
                    "Version references a missing Document",
                    path=path,
                )
            )
        original = originals.get(str(version.get("original_id")))
        if original is None:
            errors.append(
                _finding(
                    "version_original_missing",
                    "Version references a missing Original",
                    path=path,
                )
            )
        elif version.get("content_hash") != original.get("sha256") or version.get(
            "size_bytes"
        ) != original.get("size_bytes"):
            errors.append(
                _finding(
                    "version_original_integrity_mismatch",
                    "Version hash or size does not match its retained Original",
                    path=path,
                )
            )

    for record_id, acquisition in records["acquisitions"].items():
        path = f"knowledge/acquisitions/{record_id}.json"
        for key, selected, code in (
            ("source_id", sources, "acquisition_source_missing"),
            ("document_id", documents, "acquisition_document_missing"),
            ("version_id", versions, "acquisition_version_missing"),
        ):
            value = acquisition.get(key)
            if not isinstance(value, str) or value not in selected:
                errors.append(
                    _finding(
                        code,
                        f"Acquisition references a missing {key.removesuffix('_id')}",
                        path=path,
                    )
                )

        if acquisition.get("acquisition_kind") != "manual_web":
            continue
        source = sources.get(str(acquisition.get("source_id")))
        connector = records["connector-instances"].get(
            str(acquisition.get("connector_instance_id"))
        )
        version = versions.get(str(acquisition.get("version_id")))
        original = originals.get(str(acquisition.get("original_id")))
        requested_url = acquisition.get("requested_url")
        final_url = acquisition.get("final_url")
        valid_urls = True
        for selected in (requested_url, final_url):
            try:
                if not isinstance(selected, str) or canonical_web_url(selected) != selected:
                    valid_urls = False
            except WebTransportError:
                valid_urls = False
        authorized_origins = acquisition.get("authorized_origins")
        valid_authorized_origins = (
            isinstance(authorized_origins, list)
            and bool(authorized_origins)
            and all(isinstance(origin, str) for origin in authorized_origins)
            and authorized_origins == sorted(set(authorized_origins))
        )
        if valid_authorized_origins:
            try:
                valid_authorized_origins = all(
                    isinstance(origin, str) and canonical_web_origin(origin) == origin
                    for origin in authorized_origins
                ) and all(
                    canonical_web_origin(selected) in authorized_origins
                    for selected in (requested_url, final_url)
                )
            except WebTransportError:
                valid_authorized_origins = False
        source_url_matches = False
        if source is not None:
            try:
                source_url_matches = canonical_web_url(source.get("external_id")) == requested_url
            except WebTransportError:
                source_url_matches = False
        replay_id = acquisition.get("replay_of_acquisition_id")
        replay = records["acquisitions"].get(replay_id) if isinstance(replay_id, str) else None
        replay_valid = replay_id is None or (
            replay is not None
            and replay_id != record_id
            and replay.get("acquisition_kind") == "manual_web"
            and replay.get("source_id") == acquisition.get("source_id")
            and replay.get("requested_url") == requested_url
        )
        derived_status = acquisition.get("derived_status")
        derived_artifact_id = acquisition.get("derived_artifact_id")
        if (
            acquisition.get("schema_version") != 1
            or source is None
            or source.get("kind") != "connector"
            or connector is None
            or source.get("connector_instance_id") != acquisition.get("connector_instance_id")
            or acquisition.get("locator") != requested_url
            or acquisition.get("observed_at") != acquisition.get("retrieved_at")
            or acquisition.get("http_status") != 200
            or not isinstance(acquisition.get("media_type"), str)
            or type(acquisition.get("response_size_bytes")) is not int
            or int(acquisition.get("response_size_bytes", -1)) < 0
            or acquisition.get("outcome")
            not in {"created", "unchanged", "version_created", "version_reused"}
            or acquisition.get("derived_status") not in {"created", "reused", "unavailable"}
            or type(acquisition.get("exact_duplicate")) is not bool
            or not replay_valid
            or (derived_status == "unavailable" and derived_artifact_id is not None)
            or (
                derived_status in {"created", "reused"} and not isinstance(derived_artifact_id, str)
            )
            or not source_url_matches
            or not valid_authorized_origins
            or not valid_urls
        ):
            errors.append(
                _finding(
                    "manual_web_acquisition_invalid",
                    "Manual web Acquisition metadata or authority binding is invalid",
                    path=path,
                )
            )
        if (
            version is None
            or original is None
            or acquisition.get("content_hash") != version.get("content_hash")
            or acquisition.get("content_hash") != original.get("sha256")
            or acquisition.get("original_id") != version.get("original_id")
            or acquisition.get("response_size_bytes") != original.get("size_bytes")
        ):
            errors.append(
                _finding(
                    "manual_web_original_binding_invalid",
                    "Manual web Acquisition does not match its Version and Original",
                    path=path,
                )
            )
        required_edges = {
            (
                "source",
                str(acquisition.get("source_id")),
                "observed",
                "acquisition",
                record_id,
            ),
            (
                "connector_instance",
                str(acquisition.get("connector_instance_id")),
                "acquired_via",
                "acquisition",
                record_id,
            ),
            (
                "acquisition",
                record_id,
                "captured",
                "original",
                str(acquisition.get("original_id")),
            ),
            (
                "acquisition",
                record_id,
                "matched",
                "version",
                str(acquisition.get("version_id")),
            ),
            (
                "original",
                str(acquisition.get("original_id")),
                "materialized_as",
                "version",
                str(acquisition.get("version_id")),
            ),
            (
                "version",
                str(acquisition.get("version_id")),
                "version_of",
                "document",
                str(acquisition.get("document_id")),
            ),
        }
        observed_edges = {
            (
                str(edge.get("from_kind")),
                str(edge.get("from_id")),
                str(edge.get("relation")),
                str(edge.get("to_kind")),
                str(edge.get("to_id")),
            )
            for edge in records["provenance"].values()
        }
        if not required_edges.issubset(observed_edges):
            errors.append(
                _finding(
                    "manual_web_provenance_incomplete",
                    "Manual web Acquisition provenance is incomplete",
                    path=path,
                )
            )

    _validate_email_evidence(store, records, errors)
    _validate_google_evidence(store, records, errors)
    for code, message, path in canonical_connector_errors(
        records["connector-definitions"],
        records["connector-instances"],
        sources,
    ):
        errors.append(_finding(code, message, path=path))
    for code, message, path in canonical_hierarchy_errors(
        records["hierarchy"],
        records["classifications"],
        documents,
    ):
        errors.append(_finding(code, message, path=path))
    for code, message, path in classification_provenance_errors(
        records["classifications"],
        records["provenance"],
    ):
        errors.append(_finding(code, message, path=path))
    for code, message, path in canonical_disposition_errors(
        records["dispositions"],
        documents,
    ):
        errors.append(_finding(code, message, path=path))


def _validate_originals(
    store: InstanceStore,
    originals: Mapping[str, Mapping[str, Any]],
    errors: list[dict[str, str]],
    fingerprint_rows: list[str],
) -> int:
    valid_files = 0
    for record_id, original in originals.items():
        record_path = f"knowledge/originals/{record_id}.json"
        digest = original.get("sha256")
        size = original.get("size_bytes")
        reference = original.get("storage_ref")
        if (
            not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or record_id != f"sha256_{digest}"
            or type(size) is not int
            or size < 0
            or not isinstance(reference, str)
        ):
            errors.append(
                _finding(
                    "original_record_invalid",
                    "Original identity, hash, size or storage reference is invalid",
                    path=record_path,
                )
            )
            continue
        try:
            target = safe_instance_path(store.paths.root, reference)
        except UnsafePathError as exc:
            errors.append(
                _finding(
                    "original_path_unsafe",
                    str(exc),
                    path=record_path,
                )
            )
            continue
        if not target.is_file() or target.is_symlink():
            errors.append(
                _finding(
                    "original_file_missing",
                    "Original bytes are missing or are not a regular file",
                    path=reference,
                )
            )
            continue
        actual_digest = hashlib.sha256()
        actual_size = 0
        try:
            with target.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    actual_digest.update(chunk)
                    actual_size += len(chunk)
        except OSError as exc:
            errors.append(
                _finding(
                    "original_file_unreadable",
                    str(exc),
                    path=reference,
                )
            )
            continue
        actual = actual_digest.hexdigest()
        if actual != digest or actual_size != size:
            errors.append(
                _finding(
                    "original_integrity_mismatch",
                    "Original bytes do not match their canonical hash and size",
                    path=reference,
                )
            )
            continue
        valid_files += 1
        fingerprint_rows.append(f"{reference}:{actual}:{actual_size}")
    return valid_files


def inspect_instance(root: Path | str, *, deep: bool = True) -> dict[str, Any]:
    """Validate one Instance without migrating, repairing or rebuilding it."""

    store = InstanceStore(root)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    config, config_problem = _load_config(store.paths.config)
    if config_problem is not None or config is None:
        errors.append(
            _finding(
                "configuration_invalid",
                f"provelume.yml cannot be read: {config_problem}",
                path="provelume.yml",
            )
        )
        return {
            "schema_version": VALIDATION_REPORT_SCHEMA_VERSION,
            "status": "invalid",
            "instance_id": None,
            "instance_schema_version": None,
            "current_instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
            "migration_required": False,
            "deep": deep,
            "derived_state": dict(DERIVED_STATE_POLICY),
            "content_fingerprint": None,
            "counts": {"canonical_records": 0, "original_files": 0},
            "errors": errors,
            "warnings": warnings,
        }

    schema = config.get("schema_version")
    instance = config.get("instance")
    instance_id = instance.get("id") if isinstance(instance, Mapping) else None
    if type(schema) is not int:
        errors.append(
            _finding(
                "instance_schema_invalid",
                "Instance schema version must be an integer",
                path="provelume.yml",
            )
        )
    elif schema > CURRENT_INSTANCE_SCHEMA_VERSION:
        errors.append(
            _finding(
                "unsupported_future_schema",
                "Instance was created by a newer unsupported Provelume Core",
                path="provelume.yml",
            )
        )
    elif schema not in {
        LEGACY_INSTANCE_SCHEMA_VERSION,
        CURRENT_INSTANCE_SCHEMA_VERSION,
    }:
        errors.append(
            _finding(
                "unsupported_legacy_schema",
                "Instance schema has no supported forward migration path",
                path="provelume.yml",
            )
        )

    if (
        not isinstance(instance, Mapping)
        or not isinstance(instance_id, str)
        or _INSTANCE_ID.fullmatch(instance_id) is None
        or not isinstance(instance.get("name"), str)
        or not str(instance["name"]).strip()
        or not isinstance(instance.get("created_at"), str)
        or not str(instance["created_at"]).strip()
    ):
        errors.append(
            _finding(
                "instance_identity_invalid",
                "Instance ID, name or creation time is invalid",
                path="provelume.yml",
            )
        )

    try:
        ocr_settings_from_config(config)
    except OcrContractError as exc:
        errors.append(
            _finding(
                "ocr_configuration_invalid",
                str(exc),
                path="provelume.yml",
            )
        )

    migration_required = schema == LEGACY_INSTANCE_SCHEMA_VERSION
    if migration_required:
        warnings.append(
            _finding(
                "migration_required",
                "Instance schema 1 requires the supported forward migration to schema 2",
                path="provelume.yml",
            )
        )
    elif schema == CURRENT_INSTANCE_SCHEMA_VERSION:
        manifest, manifest_problem = _load_json(store.paths.manifest)
        if manifest_problem is not None or manifest is None:
            errors.append(
                _finding(
                    "instance_manifest_invalid",
                    f"Instance manifest cannot be read: {manifest_problem}",
                    path="instance-manifest.json",
                )
            )
        else:
            for problem in manifest_validation_errors(manifest, config=config):
                errors.append(
                    _finding(
                        "instance_manifest_invalid",
                        problem,
                        path="instance-manifest.json",
                    )
                )

    records = {kind: {} for kind in CANONICAL_KINDS}
    fingerprint_rows = []
    original_files = 0
    if deep and schema in {
        LEGACY_INSTANCE_SCHEMA_VERSION,
        CURRENT_INSTANCE_SCHEMA_VERSION,
    }:
        for path in sorted(store.paths.root.rglob("*")):
            if path.is_symlink():
                errors.append(
                    _finding(
                        "instance_symlink_unsupported",
                        "Instance-internal symbolic links are not supported",
                        path=path.relative_to(store.paths.root).as_posix(),
                    )
                )
        records = _canonical_records(store, errors)
        _validate_references(store, records, errors)
        from .folder_sources import folder_source_state_findings
        from .maintenance import maintenance_state_findings
        from .qualification import qualification_state_findings
        from .resource_statistics import resource_statistics_state_findings
        from .scheduler import scheduler_state_findings
        from .source_reconciliation import source_reconciliation_state_findings
        from .transcript_jobs import transcript_state_findings

        errors.extend(folder_source_state_findings(store))
        errors.extend(maintenance_state_findings(store))
        errors.extend(qualification_state_findings(store, records))
        errors.extend(scheduler_state_findings(store))
        errors.extend(source_reconciliation_state_findings(store))
        errors.extend(resource_statistics_state_findings(store))
        errors.extend(transcript_state_findings(store, records))
        original_files = _validate_originals(
            store,
            records["originals"],
            errors,
            fingerprint_rows,
        )
        for kind in CANONICAL_KINDS:
            for record_id, value in sorted(records[kind].items()):
                encoded = json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                fingerprint_rows.append(
                    f"knowledge/{kind}/{record_id}.json:{hashlib.sha256(encoded).hexdigest()}"
                )

    fingerprint = None
    if deep and not errors:
        fingerprint = hashlib.sha256(
            "\n".join(sorted(fingerprint_rows)).encode("utf-8")
        ).hexdigest()
    return {
        "schema_version": VALIDATION_REPORT_SCHEMA_VERSION,
        "status": "valid" if not errors else "invalid",
        "instance_id": instance_id if isinstance(instance_id, str) else None,
        "instance_schema_version": schema if type(schema) is int else None,
        "current_instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
        "migration_required": migration_required,
        "deep": deep,
        "derived_state": dict(DERIVED_STATE_POLICY),
        "content_fingerprint": fingerprint,
        "counts": {
            "canonical_records": sum(len(values) for values in records.values()),
            "original_files": original_files,
        },
        "errors": errors,
        "warnings": warnings,
    }
