from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from .scheduler_model import SchedulerError, instant_text, utc_instant, validate_progress

MAINTENANCE_SCHEMA_VERSION = 1
REINDEX_MODES = ("full", "incremental")
REINDEX_STATUSES = ("building", "validating", "activating", "completed")

MAINTENANCE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "search.reindex.full",
        "label": "Full FTS reindex",
        "description": "Build and atomically activate a complete rebuildable FTS generation.",
        "scheduler_job_kind": "search.reindex",
        "scope_kind": "instance",
        "authority": "derived_write",
        "mutation": "rebuildable_generation",
        "available": True,
        "unavailable_reason": None,
        "schedulable": True,
        "dry_run": True,
        "recovery": "resumable",
    },
    {
        "id": "search.reindex.incremental",
        "label": "Incremental FTS reindex",
        "description": "Reindex exact changed Version evidence in an isolated generation.",
        "scheduler_job_kind": "search.reindex.incremental",
        "scope_kind": "instance",
        "authority": "derived_write",
        "mutation": "rebuildable_generation",
        "available": True,
        "unavailable_reason": None,
        "schedulable": True,
        "dry_run": True,
        "recovery": "resumable",
    },
    {
        "id": "maintenance.library_rebuild",
        "label": "Markdown-library rebuild",
        "description": "Rebuild the disposable Markdown library projection.",
        "scheduler_job_kind": "maintenance.library_rebuild",
        "scope_kind": "instance",
        "authority": "derived_write",
        "mutation": "rebuildable_generation",
        "available": True,
        "unavailable_reason": None,
        "schedulable": True,
        "dry_run": False,
        "recovery": "restart_only",
    },
    {
        "id": "maintenance.source_reconcile",
        "label": "Source reconciliation",
        "description": "Compare one Source cursor and lifecycle state with durable evidence.",
        "scheduler_job_kind": None,
        "scope_kind": "source",
        "authority": "read_only",
        "mutation": "none",
        "available": False,
        "unavailable_reason": "planned_s04",
        "schedulable": False,
        "dry_run": False,
        "recovery": "not_available",
    },
    {
        "id": "maintenance.validate",
        "label": "Instance validation",
        "description": "Run deep, read-only validation over exact Instance state.",
        "scheduler_job_kind": "maintenance.validate",
        "scope_kind": "instance",
        "authority": "read_only",
        "mutation": "none",
        "available": True,
        "unavailable_reason": None,
        "schedulable": True,
        "dry_run": False,
        "recovery": "restart_only",
    },
    {
        "id": "maintenance.original_assurance",
        "label": "Original assurance",
        "description": "Verify retained Original bytes and canonical references without repair.",
        "scheduler_job_kind": "maintenance.original_assurance",
        "scope_kind": "instance",
        "authority": "read_only",
        "mutation": "none",
        "available": True,
        "unavailable_reason": None,
        "schedulable": True,
        "dry_run": False,
        "recovery": "restart_only",
    },
    {
        "id": "maintenance.duplicate_scan",
        "label": "Duplicate scan",
        "description": "Refresh review-only exact and probable duplicate evidence.",
        "scheduler_job_kind": "maintenance.duplicate_scan",
        "scope_kind": "instance",
        "authority": "derived_write",
        "mutation": "review_evidence",
        "available": True,
        "unavailable_reason": None,
        "schedulable": True,
        "dry_run": False,
        "recovery": "restart_only",
    },
    {
        "id": "maintenance.backup_create",
        "label": "Verified backup creation",
        "description": "Create a verified backup at one explicit operator-selected target.",
        "scheduler_job_kind": None,
        "scope_kind": "instance",
        "authority": "explicit_destination",
        "mutation": "backup_archive",
        "available": False,
        "unavailable_reason": "explicit_target_required",
        "schedulable": False,
        "dry_run": False,
        "recovery": "not_available",
    },
    {
        "id": "maintenance.backup_verify",
        "label": "Backup verification",
        "description": "Verify one explicit backup target without changing the Instance.",
        "scheduler_job_kind": None,
        "scope_kind": "instance",
        "authority": "explicit_destination",
        "mutation": "none",
        "available": False,
        "unavailable_reason": "explicit_target_required",
        "schedulable": False,
        "dry_run": False,
        "recovery": "not_available",
    },
)

MAINTENANCE_ACTION_IDS = tuple(item["id"] for item in MAINTENANCE_CATALOG)
AVAILABLE_MAINTENANCE_JOB_KINDS = tuple(
    str(item["scheduler_job_kind"])
    for item in MAINTENANCE_CATALOG
    if item["available"] and item["scheduler_job_kind"] is not None
)

_JOB_ID = re.compile(r"job_([0-9a-f]{32})\Z")
_RUN_ID = re.compile(r"reindex_([0-9a-f]{32})\Z")
_GENERATION_ID = re.compile(r"generation_[0-9a-f]{32}\Z")
_CANONICAL_ID = re.compile(r"[A-Za-z0-9_.:-]{1,240}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class MaintenanceError(ValueError):
    pass


class MaintenanceNotFoundError(MaintenanceError):
    pass


class MaintenanceUnavailableError(MaintenanceError):
    pass


class MaintenanceInsufficientSpaceError(MaintenanceError):
    pass


class MaintenanceStateError(MaintenanceError):
    pass


def maintenance_action(action_id: str) -> dict[str, Any]:
    for item in MAINTENANCE_CATALOG:
        if item["id"] == action_id:
            return dict(item)
    raise MaintenanceNotFoundError("maintenance action not found")


def action_for_job_kind(job_kind: str) -> dict[str, Any]:
    for item in MAINTENANCE_CATALOG:
        if item["scheduler_job_kind"] == job_kind:
            return dict(item)
    raise MaintenanceNotFoundError("maintenance job kind is not catalogued")


def reindex_mode_for_job_kind(job_kind: str) -> str:
    if job_kind == "search.reindex":
        return "full"
    if job_kind == "search.reindex.incremental":
        return "incremental"
    raise MaintenanceError("job kind is not a reindex action")


def reindex_run_identifier(value: str) -> bool:
    return isinstance(value, str) and _RUN_ID.fullmatch(value) is not None


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def plan_digest(plan: Mapping[str, Any]) -> str:
    return _hash_json(dict(plan))


def _integer(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = 2**63 - 1,
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise MaintenanceStateError(f"invalid {label}")
    return value


def _relative_candidate(value: Any, suffix: str) -> str:
    if not isinstance(value, str):
        raise MaintenanceStateError("reindex candidate reference is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.parts[:2] != ("indexes", "reindex-candidates")
        or not value.endswith(suffix)
    ):
        raise MaintenanceStateError("reindex candidate reference is unsafe")
    return value


def validate_reindex_plan(value: Any) -> dict[str, Any]:
    expected = {
        "requested_mode",
        "strategy",
        "canonical_fingerprint",
        "knowledge_fingerprint",
        "documents",
        "baseline_documents",
        "selected_document_ids",
        "estimated_items",
        "estimated_bytes",
        "temporary_bytes_required",
        "free_bytes_observed",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise MaintenanceStateError("reindex plan fields are incomplete or unsupported")
    requested_mode = value.get("requested_mode")
    strategy = value.get("strategy")
    if requested_mode not in REINDEX_MODES or strategy not in REINDEX_MODES:
        raise MaintenanceStateError("reindex plan mode is invalid")
    if requested_mode == "full" and strategy != "full":
        raise MaintenanceStateError("full reindex cannot use an incremental strategy")
    canonical_fingerprint = value.get("canonical_fingerprint")
    knowledge_fingerprint = value.get("knowledge_fingerprint")
    if (
        not isinstance(canonical_fingerprint, str)
        or _SHA256.fullmatch(canonical_fingerprint) is None
        or not isinstance(knowledge_fingerprint, str)
        or _SHA256.fullmatch(knowledge_fingerprint) is None
    ):
        raise MaintenanceStateError("reindex plan fingerprint is invalid")
    def document_map(candidate: Any, label: str) -> dict[str, str]:
        if not isinstance(candidate, Mapping) or any(
            not isinstance(key, str)
            or _CANONICAL_ID.fullmatch(key) is None
            or not isinstance(item, str)
            or _CANONICAL_ID.fullmatch(item) is None
            for key, item in candidate.items()
        ):
            raise MaintenanceStateError(f"reindex {label} identity is invalid")
        return {str(key): str(item) for key, item in sorted(candidate.items())}

    normalised_documents = document_map(value.get("documents"), "plan document")
    baseline_documents = document_map(
        value.get("baseline_documents"),
        "baseline document",
    )
    selected = value.get("selected_document_ids")
    if (
        not isinstance(selected, list)
        or selected != sorted(set(selected))
        or any(
            not isinstance(item, str) or _CANONICAL_ID.fullmatch(item) is None
            for item in selected
        )
    ):
        raise MaintenanceStateError("reindex selected document IDs are invalid")
    expected_selected = (
        sorted(normalised_documents)
        if strategy == "full"
        else sorted(
            document_id
            for document_id in set(baseline_documents) | set(normalised_documents)
            if baseline_documents.get(document_id)
            != normalised_documents.get(document_id)
        )
    )
    if strategy == "full" and baseline_documents:
        raise MaintenanceStateError("full reindex cannot retain baseline documents")
    if selected != expected_selected:
        raise MaintenanceStateError("reindex selection does not match its strategy")
    estimated_items = _integer(value.get("estimated_items"), "estimated item count")
    if estimated_items != len(selected):
        raise MaintenanceStateError("reindex estimate does not match its selected items")
    return {
        "requested_mode": requested_mode,
        "strategy": strategy,
        "canonical_fingerprint": canonical_fingerprint,
        "knowledge_fingerprint": knowledge_fingerprint,
        "documents": normalised_documents,
        "baseline_documents": baseline_documents,
        "selected_document_ids": list(selected),
        "estimated_items": estimated_items,
        "estimated_bytes": _integer(value.get("estimated_bytes"), "estimated bytes"),
        "temporary_bytes_required": _integer(
            value.get("temporary_bytes_required"), "temporary bytes"
        ),
        "free_bytes_observed": _integer(value.get("free_bytes_observed"), "free bytes"),
    }


def validate_reindex_run(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "id",
        "job_id",
        "status",
        "plan_revision",
        "generation_id",
        "plan_digest",
        "plan",
        "candidate",
        "cursor",
        "indexed",
        "skipped",
        "errors",
        "base_progress",
        "created_at",
        "updated_at",
        "completed_at",
        "network_used",
        "canonical_mutation",
        "automatic_deletion",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise MaintenanceStateError("reindex run fields are incomplete or unsupported")
    run_id = value.get("id")
    job_id = value.get("job_id")
    run_match = _RUN_ID.fullmatch(str(run_id))
    job_match = _JOB_ID.fullmatch(str(job_id))
    if (
        value.get("schema_version") != MAINTENANCE_SCHEMA_VERSION
        or run_match is None
        or job_match is None
        or run_match.group(1) != job_match.group(1)
        or value.get("status") not in REINDEX_STATUSES
    ):
        raise MaintenanceStateError("reindex run identity is invalid")
    plan = validate_reindex_plan(value.get("plan"))
    digest = value.get("plan_digest")
    if not isinstance(digest, str) or digest != plan_digest(plan):
        raise MaintenanceStateError("reindex plan digest is invalid")
    revision = _integer(
        value.get("plan_revision"),
        "plan revision",
        minimum=1,
        maximum=2**31 - 1,
    )
    generation_id = value.get("generation_id")
    expected_generation = "generation_" + hashlib.sha256(
        f"{job_id}:{revision}:{digest}".encode()
    ).hexdigest()[:32]
    if (
        not isinstance(generation_id, str)
        or _GENERATION_ID.fullmatch(generation_id) is None
        or generation_id != expected_generation
    ):
        raise MaintenanceStateError("reindex generation identity is invalid")
    candidate = value.get("candidate")
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "database_ref",
        "metadata_ref",
    }:
        raise MaintenanceStateError("reindex candidate fields are invalid")
    prefix = f"{run_id}-r{revision}-{generation_id.removeprefix('generation_')}"
    database_ref = _relative_candidate(candidate.get("database_ref"), ".sqlite3")
    metadata_ref = _relative_candidate(candidate.get("metadata_ref"), ".json")
    if (
        database_ref != f"indexes/reindex-candidates/{prefix}.sqlite3"
        or metadata_ref != f"indexes/reindex-candidates/{prefix}.json"
    ):
        raise MaintenanceStateError("reindex candidate identity is invalid")
    cursor = _integer(value.get("cursor"), "reindex cursor", maximum=2**31 - 1)
    indexed = _integer(value.get("indexed"), "indexed count", maximum=2**31 - 1)
    skipped = _integer(value.get("skipped"), "skipped count", maximum=2**31 - 1)
    errors = _integer(value.get("errors"), "error count", maximum=2**31 - 1)
    if cursor != indexed + skipped or cursor > len(plan["selected_document_ids"]):
        raise MaintenanceStateError("reindex cursor and progress disagree")
    status = str(value.get("status"))
    completed_at = value.get("completed_at")
    if completed_at is not None:
        completed_at = instant_text(completed_at)
    if status == "completed":
        if cursor != len(plan["selected_document_ids"]) or completed_at is None:
            raise MaintenanceStateError("completed reindex evidence is incomplete")
    elif completed_at is not None:
        raise MaintenanceStateError("unfinished reindex cannot have a completion time")
    if value.get("network_used") is not False:
        raise MaintenanceStateError("reindex cannot report network use")
    if value.get("canonical_mutation") is not False:
        raise MaintenanceStateError("reindex cannot report canonical mutation")
    if value.get("automatic_deletion") is not False:
        raise MaintenanceStateError("reindex cannot authorize automatic deletion")
    created_at = instant_text(value.get("created_at"))
    updated_at = instant_text(value.get("updated_at"))
    if utc_instant(updated_at) < utc_instant(created_at):
        raise MaintenanceStateError("reindex run update precedes creation")
    if completed_at is not None and utc_instant(completed_at) < utc_instant(updated_at):
        raise MaintenanceStateError("reindex completion precedes its last update")
    try:
        base_progress = validate_progress(value.get("base_progress"))
    except SchedulerError as exc:
        raise MaintenanceStateError("reindex base progress is invalid") from exc
    return {
        "schema_version": MAINTENANCE_SCHEMA_VERSION,
        "id": run_id,
        "job_id": job_id,
        "status": status,
        "plan_revision": revision,
        "generation_id": generation_id,
        "plan_digest": digest,
        "plan": plan,
        "candidate": {
            "database_ref": database_ref,
            "metadata_ref": metadata_ref,
        },
        "cursor": cursor,
        "indexed": indexed,
        "skipped": skipped,
        "errors": errors,
        "base_progress": base_progress,
        "created_at": created_at,
        "updated_at": updated_at,
        "completed_at": completed_at,
        "network_used": False,
        "canonical_mutation": False,
        "automatic_deletion": False,
    }


__all__ = [
    "AVAILABLE_MAINTENANCE_JOB_KINDS",
    "MAINTENANCE_ACTION_IDS",
    "MAINTENANCE_CATALOG",
    "MAINTENANCE_SCHEMA_VERSION",
    "MaintenanceError",
    "MaintenanceInsufficientSpaceError",
    "MaintenanceNotFoundError",
    "MaintenanceStateError",
    "MaintenanceUnavailableError",
    "action_for_job_kind",
    "maintenance_action",
    "plan_digest",
    "reindex_mode_for_job_kind",
    "reindex_run_identifier",
    "validate_reindex_plan",
    "validate_reindex_run",
]
