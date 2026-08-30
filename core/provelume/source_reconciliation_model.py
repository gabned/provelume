from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .scheduler_model import instant_text, utc_instant, validate_progress

SOURCE_RECONCILIATION_SCHEMA_VERSION = 1
MAX_RECONCILIATION_FILES = 100_000
MAX_RECONCILIATION_PLAN_ITEMS = 200_000

RECONCILIATION_CLASSIFICATIONS = (
    "current",
    "changed",
    "renamed",
    "untracked",
    "missing",
)
RECONCILIATION_SNAPSHOT_STATES = (
    "available",
    "paused",
    "missing",
    "error",
    "superseded",
)
RECONCILIATION_RUN_STATUSES = ("scanning", "completed", "failed", "superseded")
SOURCE_OPERATIONAL_STATES = (
    "active",
    "paused",
    "missing",
    "error",
    "superseded",
    "reauthorization_required",
)
SOURCE_OPERATIONAL_CODES = (
    "never_reconciled",
    "current",
    "resync_required",
    "source_paused",
    "source_missing",
    "source_unreadable",
    "source_limit",
    "source_unsafe",
    "source_io",
    "source_changed",
    "authorization_required",
)

_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_JOB_ID = re.compile(r"job_([0-9a-f]{32})\Z")
_RUN_ID = re.compile(r"reconcile_([0-9a-f]{32})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class SourceReconciliationError(ValueError):
    pass


class SourceReconciliationStateError(SourceReconciliationError):
    pass


class SourceReconciliationSupersededError(SourceReconciliationError):
    pass


class SourceReconciliationIOError(SourceReconciliationError):
    pass


class SourceReconciliationAuthorizationError(SourceReconciliationError):
    pass


class SourceReconciliationLimitError(SourceReconciliationError):
    pass


def _integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise SourceReconciliationStateError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SourceReconciliationStateError(f"{label} is invalid")
    return value


def _instant(value: Any, label: str) -> str:
    try:
        return instant_text(value)
    except ValueError as exc:
        raise SourceReconciliationStateError(f"{label} is invalid") from exc


def _optional_instant(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _instant(value, label)


def hash_payload(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reconciliation_run_identifier(value: Any) -> bool:
    return isinstance(value, str) and _RUN_ID.fullmatch(value) is not None


def empty_reconciliation_counts() -> dict[str, int]:
    return {classification: 0 for classification in RECONCILIATION_CLASSIFICATIONS}


def normalise_reconciliation_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(
        RECONCILIATION_CLASSIFICATIONS
    ):
        raise SourceReconciliationStateError(
            "Source reconciliation counts are incomplete or unsupported"
        )
    return {
        classification: _integer(
            value.get(classification),
            classification,
            minimum=0,
            maximum=2**63 - 1,
        )
        for classification in RECONCILIATION_CLASSIFICATIONS
    }


def _normalise_item(value: Any) -> dict[str, Any]:
    expected = {"identity", "content_hash", "size_bytes", "classification"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SourceReconciliationStateError(
            "Source reconciliation item fields are incomplete or unsupported"
        )
    classification = value.get("classification")
    if classification not in RECONCILIATION_CLASSIFICATIONS:
        raise SourceReconciliationStateError(
            "Source reconciliation item classification is invalid"
        )
    return {
        "identity": _digest(value.get("identity"), "item identity"),
        "content_hash": _digest(value.get("content_hash"), "item content hash"),
        "size_bytes": _integer(
            value.get("size_bytes"),
            "item size",
            minimum=0,
            maximum=2**63 - 1,
        ),
        "classification": str(classification),
    }


def validate_reconciliation_plan(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "source_id",
        "configuration_fingerprint",
        "canonical_fingerprint",
        "snapshot_fingerprint",
        "snapshot_state",
        "items",
        "estimated_items",
        "estimated_bytes",
        "lifecycle_state",
        "lifecycle_code",
        "resync_required",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SourceReconciliationStateError(
            "Source reconciliation plan fields are incomplete or unsupported"
        )
    source_id = value.get("source_id")
    snapshot_state = value.get("snapshot_state")
    lifecycle_state = value.get("lifecycle_state")
    lifecycle_code = value.get("lifecycle_code")
    if (
        value.get("schema_version") != SOURCE_RECONCILIATION_SCHEMA_VERSION
        or not isinstance(source_id, str)
        or _SOURCE_ID.fullmatch(source_id) is None
        or snapshot_state not in RECONCILIATION_SNAPSHOT_STATES
        or lifecycle_state not in SOURCE_OPERATIONAL_STATES
        or lifecycle_code not in SOURCE_OPERATIONAL_CODES
        or type(value.get("resync_required")) is not bool
    ):
        raise SourceReconciliationStateError(
            "Source reconciliation plan identity is invalid"
        )
    raw_items = value.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > MAX_RECONCILIATION_PLAN_ITEMS:
        raise SourceReconciliationStateError(
            "Source reconciliation plan item bound is invalid"
        )
    items = [_normalise_item(item) for item in raw_items]
    identities = [str(item["identity"]) for item in items]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise SourceReconciliationStateError(
            "Source reconciliation plan item identities are not unique and sorted"
        )
    estimated_items = _integer(
        value.get("estimated_items"),
        "estimated items",
        minimum=0,
        maximum=MAX_RECONCILIATION_PLAN_ITEMS,
    )
    estimated_bytes = _integer(
        value.get("estimated_bytes"),
        "estimated bytes",
        minimum=0,
        maximum=2**63 - 1,
    )
    if estimated_items != len(items):
        raise SourceReconciliationStateError(
            "Source reconciliation plan item count is inconsistent"
        )
    state_contract = {
        "available": ({"active"}, {"current", "resync_required"}),
        "paused": ({"paused"}, {"source_paused"}),
        "missing": ({"missing"}, {"source_missing"}),
        "error": (
            {"error", "reauthorization_required"},
            {
                "source_unreadable",
                "source_limit",
                "source_unsafe",
                "source_io",
                "authorization_required",
            },
        ),
        "superseded": ({"superseded"}, {"source_changed"}),
    }
    allowed_states, allowed_codes = state_contract[str(snapshot_state)]
    if lifecycle_state not in allowed_states or lifecycle_code not in allowed_codes:
        raise SourceReconciliationStateError(
            "Source reconciliation snapshot and lifecycle state disagree"
        )
    expected_resync = lifecycle_code not in {"current", "source_paused"}
    if bool(value["resync_required"]) != expected_resync:
        raise SourceReconciliationStateError(
            "Source reconciliation resync state is inconsistent"
        )
    if snapshot_state != "available" and items:
        raise SourceReconciliationStateError(
            "Unavailable Source reconciliation plans cannot contain items"
        )
    if snapshot_state == "available":
        has_delta = any(item["classification"] != "current" for item in items)
        if has_delta != bool(value["resync_required"]):
            raise SourceReconciliationStateError(
                "Source reconciliation classifications disagree with resync state"
            )
    return {
        "schema_version": SOURCE_RECONCILIATION_SCHEMA_VERSION,
        "source_id": source_id,
        "configuration_fingerprint": _digest(
            value.get("configuration_fingerprint"),
            "configuration fingerprint",
        ),
        "canonical_fingerprint": _digest(
            value.get("canonical_fingerprint"),
            "canonical fingerprint",
        ),
        "snapshot_fingerprint": _digest(
            value.get("snapshot_fingerprint"),
            "snapshot fingerprint",
        ),
        "snapshot_state": str(snapshot_state),
        "items": items,
        "estimated_items": estimated_items,
        "estimated_bytes": estimated_bytes,
        "lifecycle_state": str(lifecycle_state),
        "lifecycle_code": str(lifecycle_code),
        "resync_required": bool(value["resync_required"]),
    }


def validate_reconciliation_run(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "id",
        "job_id",
        "source_id",
        "status",
        "plan_revision",
        "plan",
        "plan_digest",
        "cursor",
        "counts",
        "base_progress",
        "superseded_revisions",
        "created_at",
        "updated_at",
        "completed_at",
        "network_used",
        "canonical_mutation",
        "automatic_deletion",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SourceReconciliationStateError(
            "Source reconciliation run fields are incomplete or unsupported"
        )
    run_id = value.get("id")
    job_id = value.get("job_id")
    source_id = value.get("source_id")
    status = value.get("status")
    if (
        value.get("schema_version") != SOURCE_RECONCILIATION_SCHEMA_VERSION
        or not isinstance(run_id, str)
        or _RUN_ID.fullmatch(run_id) is None
        or not isinstance(job_id, str)
        or _JOB_ID.fullmatch(job_id) is None
        or run_id != f"reconcile_{job_id.removeprefix('job_')}"
        or not isinstance(source_id, str)
        or _SOURCE_ID.fullmatch(source_id) is None
        or status not in RECONCILIATION_RUN_STATUSES
        or type(value.get("network_used")) is not bool
        or value.get("canonical_mutation") is not False
        or value.get("automatic_deletion") is not False
    ):
        raise SourceReconciliationStateError(
            "Source reconciliation run identity is invalid"
        )
    plan = validate_reconciliation_plan(value.get("plan"))
    if plan["source_id"] != source_id or hash_payload(plan) != value.get("plan_digest"):
        raise SourceReconciliationStateError(
            "Source reconciliation run plan binding is invalid"
        )
    cursor = _integer(
        value.get("cursor"),
        "Source reconciliation cursor",
        minimum=0,
        maximum=len(plan["items"]),
    )
    counts = normalise_reconciliation_counts(value.get("counts"))
    expected_counts = empty_reconciliation_counts()
    for item in plan["items"][:cursor]:
        expected_counts[str(item["classification"])] += 1
    if counts != expected_counts:
        raise SourceReconciliationStateError(
            "Source reconciliation cursor and counts disagree"
        )
    created_at = _instant(value.get("created_at"), "creation time")
    updated_at = _instant(value.get("updated_at"), "update time")
    completed_at = _optional_instant(value.get("completed_at"), "completion time")
    if utc_instant(updated_at) < utc_instant(created_at) or (
        completed_at is not None and utc_instant(completed_at) < utc_instant(updated_at)
    ):
        raise SourceReconciliationStateError(
            "Source reconciliation run clocks are not monotonic"
        )
    if status == "scanning" and completed_at is not None:
        raise SourceReconciliationStateError(
            "Scanning Source reconciliation cannot be completed"
        )
    if status != "scanning" and completed_at is None:
        raise SourceReconciliationStateError(
            "Terminal Source reconciliation requires a completion time"
        )
    if status == "completed" and cursor != len(plan["items"]):
        raise SourceReconciliationStateError(
            "Completed Source reconciliation did not consume its plan"
        )
    if status == "completed" and plan["snapshot_state"] not in {
        "available",
        "paused",
        "missing",
    }:
        raise SourceReconciliationStateError(
            "Completed Source reconciliation has an invalid snapshot state"
        )
    if status == "failed" and plan["snapshot_state"] != "error":
        raise SourceReconciliationStateError(
            "Failed Source reconciliation lacks closed error evidence"
        )
    return {
        "schema_version": SOURCE_RECONCILIATION_SCHEMA_VERSION,
        "id": run_id,
        "job_id": job_id,
        "source_id": source_id,
        "status": str(status),
        "plan_revision": _integer(
            value.get("plan_revision"),
            "plan revision",
            minimum=1,
            maximum=2**31 - 1,
        ),
        "plan": plan,
        "plan_digest": str(value["plan_digest"]),
        "cursor": cursor,
        "counts": counts,
        "base_progress": validate_progress(value.get("base_progress")),
        "superseded_revisions": _integer(
            value.get("superseded_revisions"),
            "superseded revisions",
            minimum=0,
            maximum=2**31 - 1,
        ),
        "created_at": created_at,
        "updated_at": updated_at,
        "completed_at": completed_at,
        "network_used": bool(value["network_used"]),
        "canonical_mutation": False,
        "automatic_deletion": False,
    }


def validate_source_cursor(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "source_id",
        "revision",
        "state",
        "code",
        "configuration_fingerprint",
        "snapshot_fingerprint",
        "last_attempt_at",
        "last_success_at",
        "last_job_id",
        "last_run_id",
        "last_run_revision",
        "counts",
        "resync_required",
        "network_used",
        "canonical_mutation",
        "automatic_deletion",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SourceReconciliationStateError(
            "Source reconciliation cursor fields are incomplete or unsupported"
        )
    source_id = value.get("source_id")
    state = value.get("state")
    code = value.get("code")
    if (
        value.get("schema_version") != SOURCE_RECONCILIATION_SCHEMA_VERSION
        or not isinstance(source_id, str)
        or _SOURCE_ID.fullmatch(source_id) is None
        or state not in SOURCE_OPERATIONAL_STATES
        or code not in SOURCE_OPERATIONAL_CODES
        or type(value.get("resync_required")) is not bool
        or type(value.get("network_used")) is not bool
        or value.get("canonical_mutation") is not False
        or value.get("automatic_deletion") is not False
    ):
        raise SourceReconciliationStateError(
            "Source reconciliation cursor identity is invalid"
        )
    revision = _integer(
        value.get("revision"),
        "cursor revision",
        minimum=0,
        maximum=2**31 - 1,
    )
    state_codes = {
        "active": {"never_reconciled", "current", "resync_required"},
        "paused": {"source_paused"},
        "missing": {"source_missing"},
        "error": {"source_unreadable", "source_limit", "source_unsafe", "source_io"},
        "superseded": {"source_changed"},
        "reauthorization_required": {"authorization_required"},
    }
    if code not in state_codes[str(state)]:
        raise SourceReconciliationStateError(
            "Source reconciliation cursor state and code disagree"
        )
    expected_resync = code not in {"never_reconciled", "current", "source_paused"}
    if bool(value["resync_required"]) != expected_resync:
        raise SourceReconciliationStateError(
            "Source reconciliation cursor resync evidence is inconsistent"
        )
    last_job_id = value.get("last_job_id")
    last_run_id = value.get("last_run_id")
    last_run_revision = value.get("last_run_revision")
    if last_job_id is not None and (
        not isinstance(last_job_id, str) or _JOB_ID.fullmatch(last_job_id) is None
    ):
        raise SourceReconciliationStateError("Source reconciliation cursor job ID is invalid")
    if last_run_id is not None and not reconciliation_run_identifier(last_run_id):
        raise SourceReconciliationStateError("Source reconciliation cursor run ID is invalid")
    if (last_job_id is None) != (last_run_id is None):
        raise SourceReconciliationStateError(
            "Source reconciliation cursor run binding is incomplete"
        )
    if isinstance(last_job_id, str) and last_run_id != (
        f"reconcile_{last_job_id.removeprefix('job_')}"
    ):
        raise SourceReconciliationStateError(
            "Source reconciliation cursor run binding is inconsistent"
        )
    if last_run_id is None:
        if last_run_revision is not None:
            raise SourceReconciliationStateError(
                "Initial Source reconciliation cursor has a run revision"
            )
    else:
        last_run_revision = _integer(
            last_run_revision,
            "last run revision",
            minimum=1,
            maximum=2**31 - 1,
        )
    last_attempt = _optional_instant(value.get("last_attempt_at"), "last attempt")
    last_success = _optional_instant(value.get("last_success_at"), "last success")
    if (
        last_attempt is not None
        and last_success is not None
        and utc_instant(last_success) > utc_instant(last_attempt)
    ):
        raise SourceReconciliationStateError(
            "Source reconciliation success follows its last attempt"
        )
    if revision == 0:
        if (
            code != "never_reconciled"
            or last_attempt is not None
            or last_success is not None
            or last_job_id is not None
            or last_run_revision is not None
            or value.get("snapshot_fingerprint") is not None
        ):
            raise SourceReconciliationStateError(
                "Initial Source reconciliation cursor is inconsistent"
            )
    elif last_attempt is None or last_job_id is None:
        raise SourceReconciliationStateError(
            "Durable Source reconciliation cursor lacks attempt evidence"
        )
    snapshot = value.get("snapshot_fingerprint")
    if snapshot is not None:
        snapshot = _digest(snapshot, "cursor snapshot fingerprint")
    return {
        "schema_version": SOURCE_RECONCILIATION_SCHEMA_VERSION,
        "source_id": source_id,
        "revision": revision,
        "state": str(state),
        "code": str(code),
        "configuration_fingerprint": _digest(
            value.get("configuration_fingerprint"),
            "cursor configuration fingerprint",
        ),
        "snapshot_fingerprint": snapshot,
        "last_attempt_at": last_attempt,
        "last_success_at": last_success,
        "last_job_id": last_job_id,
        "last_run_id": last_run_id,
        "last_run_revision": last_run_revision,
        "counts": normalise_reconciliation_counts(value.get("counts")),
        "resync_required": bool(value["resync_required"]),
        "network_used": bool(value["network_used"]),
        "canonical_mutation": False,
        "automatic_deletion": False,
    }


__all__ = [
    "MAX_RECONCILIATION_FILES",
    "MAX_RECONCILIATION_PLAN_ITEMS",
    "RECONCILIATION_CLASSIFICATIONS",
    "RECONCILIATION_RUN_STATUSES",
    "SOURCE_OPERATIONAL_CODES",
    "SOURCE_OPERATIONAL_STATES",
    "SOURCE_RECONCILIATION_SCHEMA_VERSION",
    "SourceReconciliationAuthorizationError",
    "SourceReconciliationError",
    "SourceReconciliationIOError",
    "SourceReconciliationLimitError",
    "SourceReconciliationStateError",
    "SourceReconciliationSupersededError",
    "empty_reconciliation_counts",
    "hash_payload",
    "normalise_reconciliation_counts",
    "reconciliation_run_identifier",
    "validate_reconciliation_plan",
    "validate_reconciliation_run",
    "validate_source_cursor",
]
