from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .connector_model import canonical_connector_errors
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
from .paths import UnsafePathError, safe_instance_path
from .retention_model import canonical_disposition_errors
from .storage import CANONICAL_KINDS, REQUIRED_CANONICAL_KINDS, InstanceStore
from .web_transport import WebTransportError, canonical_web_url

VALIDATION_REPORT_SCHEMA_VERSION = 1
_INSTANCE_ID = re.compile(r"inst_[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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


def _canonical_records(
    store: InstanceStore,
    errors: list[dict[str, str]],
) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {}
    for kind in CANONICAL_KINDS:
        directory = store.paths.canonical_dir(kind)
        selected: dict[str, dict[str, Any]] = {}
        records[kind] = selected
        if not directory.is_dir() and (
            directory.exists() or directory.is_symlink()
        ):
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


def _validate_references(
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
        elif (
            version.get("content_hash") != original.get("sha256")
            or version.get("size_bytes") != original.get("size_bytes")
        ):
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
        source_url_matches = False
        if source is not None:
            try:
                source_url_matches = (
                    canonical_web_url(source.get("external_id")) == requested_url
                )
            except WebTransportError:
                source_url_matches = False
        replay_id = acquisition.get("replay_of_acquisition_id")
        replay = (
            records["acquisitions"].get(replay_id)
            if isinstance(replay_id, str)
            else None
        )
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
            or source.get("connector_instance_id") != acquisition.get(
                "connector_instance_id"
            )
            or acquisition.get("locator") != requested_url
            or acquisition.get("observed_at") != acquisition.get("retrieved_at")
            or acquisition.get("http_status") != 200
            or not isinstance(acquisition.get("media_type"), str)
            or type(acquisition.get("response_size_bytes")) is not int
            or int(acquisition.get("response_size_bytes", -1)) < 0
            or acquisition.get("outcome")
            not in {"created", "unchanged", "version_created", "version_reused"}
            or acquisition.get("derived_status")
            not in {"created", "reused", "unavailable"}
            or type(acquisition.get("exact_duplicate")) is not bool
            or not replay_valid
            or (derived_status == "unavailable" and derived_artifact_id is not None)
            or (
                derived_status in {"created", "reused"}
                and not isinstance(derived_artifact_id, str)
            )
            or not source_url_matches
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
        _validate_references(records, errors)
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
                    f"knowledge/{kind}/{record_id}.json:"
                    f"{hashlib.sha256(encoded).hexdigest()}"
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
