"""Durable cooperative commands; the existing scheduler remains the job authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .scheduler_model import (
    TERMINAL_JOB_STATUSES,
    SchedulerConflictError,
    SchedulerError,
    SchedulerNotFoundError,
    instant_text,
    record_identifier,
    utc_instant,
)

CONTROL_SCHEMA_VERSION = 1
CONTROLLED_JOB_SCHEMA_VERSION = 2
MAX_CONTROL_COMMANDS = 128
MAX_CONTROL_RECORD_BYTES = 1024 * 1024
COOPERATIVE_KINDS = frozenset(
    {
        "search.reindex",
        "search.reindex.incremental",
        "maintenance.source_reconcile",
    }
)
ACTIVE_STATUSES = frozenset({"running", "pausing", "cancelling"})
CONTROL_ACTIONS = ("pause", "resume", "cancel", "retry", "restart")


class CooperativeStop(Exception):
    """An acknowledged durable yield, never a caught domain/validation failure."""

    def __init__(self, job: dict[str, Any]):
        self.job = job
        super().__init__(str(job["status"]))


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _hash(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _instance_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("inst_")
        and len(value) == 37
        and all(c in "0123456789abcdef" for c in value[5:])
    )


def initial_control(*, parent: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "revision": 0,
        "pending": None,
        "commit_started": False,
        "commands": [],
        "parent_job_id": parent,
        "restart": None,
        "observation": None,
        "network_used": False,
        "completion": None,
    }


def promote(job: Mapping[str, Any]) -> dict[str, Any]:
    if job["schema_version"] == CONTROLLED_JOB_SCHEMA_VERSION:
        return dict(job)
    return {**job, "schema_version": 2, "control": initial_control(), "execution_plan": None}


def validate_execution_plan(value: Any, *, job_kind: str) -> dict[str, Any] | None:
    if job_kind != "maintenance.backup_verify":
        if value is None:
            return None
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "schema_version",
                "kind",
                "instance_id",
                "scope",
                "parameters",
                "input_revision",
                "plan_revision",
            }
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["kind"] != job_kind
            or not _instance_id(value["instance_id"])
            or not _hash(value["input_revision"])
            or value["plan_revision"]
            != digest({k: v for k, v in value.items() if k != "plan_revision"})
            or not isinstance(value["parameters"], dict)
            or set(value["parameters"])
            != ({"source_id"} if job_kind == "maintenance.source_reconcile" else set())
            or not isinstance(value["scope"], dict)
            or set(value["scope"]) != {"kind", "id"}
            or (
                job_kind == "maintenance.source_reconcile"
                and value["parameters"]["source_id"] != value["scope"]["id"]
            )
        ):
            raise SchedulerError("maintenance execution plan is invalid")
        return dict(value)
    keys = {
        "schema_version",
        "kind",
        "instance_id",
        "target_ref",
        "target_revision",
        "archive_sha256",
        "size_bytes",
        "backup_id",
        "instance_schema_version",
        "content_fingerprint",
        "files",
        "plan_revision",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["kind"] != job_kind
        or not isinstance(value["target_ref"], str)
        or not value["target_ref"].startswith("mt_")
        or len(value["target_ref"]) != 35
        or any(c not in "0123456789abcdef" for c in value["target_ref"][3:])
        or any(
            not _hash(value[k])
            for k in ("target_revision", "archive_sha256", "plan_revision", "content_fingerprint")
        )
        or not _instance_id(value["instance_id"])
        or not isinstance(value["backup_id"], str)
        or not value["backup_id"].startswith("backup_")
        or len(value["backup_id"]) > 160
        or type(value["size_bytes"]) is not int
        or not 0 <= value["size_bytes"] <= 512 * 1024**3
        or type(value["files"]) is not int
        or not 0 <= value["files"] <= 100_000
        or type(value["instance_schema_version"]) is not int
        or value["instance_schema_version"] not in {1, 2}
    ):
        raise SchedulerError("backup verification execution plan is invalid")
    return dict(value)


def validate_control(value: Any, *, job: Mapping[str, Any]) -> dict[str, Any]:
    keys = {
        "schema_version",
        "revision",
        "pending",
        "commit_started",
        "commands",
        "parent_job_id",
        "restart",
        "observation",
        "network_used",
        "completion",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise SchedulerError("job control fields are incomplete or unsupported")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["revision"]) is not int
        or not 0 <= value["revision"] <= 2**31 - 1
        or type(value["commit_started"]) is not bool
        or type(value["network_used"]) is not bool
    ):
        raise SchedulerError("job control identity is invalid")
    parent = value["parent_job_id"]
    if parent is not None and (
        not isinstance(parent, str) or not record_identifier(parent, "job") or parent == job["id"]
    ):
        raise SchedulerError("restart parent identity is invalid")
    commands = value["commands"]
    if not isinstance(commands, list) or len(commands) > MAX_CONTROL_COMMANDS:
        raise SchedulerError("job control history exceeds its bound")
    if value["revision"] < len(commands):
        raise SchedulerError("job control revision precedes its history")
    if job["status"] == "paused" and job["job_kind"] not in COOPERATIVE_KINDS:
        raise SchedulerError("executor has no cooperative paused state")
    seen = set()
    for row in commands:
        if not isinstance(row, dict) or set(row) != {
            "request_digest",
            "payload_digest",
            "action",
            "expected_revision",
            "result_status",
            "accepted_at",
            "successor_id",
        }:
            raise SchedulerError("job command receipt is invalid")
        if (
            any(
                not _hash(row[key])
                for key in ("request_digest", "payload_digest", "expected_revision")
            )
            or row["request_digest"] in seen
            or row["action"] not in CONTROL_ACTIONS
            or row["result_status"]
            not in {"paused", "pausing", "cancelling", "cancelled", "queued", "restarted"}
        ):
            raise SchedulerError("job command receipt binding is invalid")
        instant_text(row["accepted_at"])
        successor = row["successor_id"]
        if (row["action"] == "restart") != (successor is not None):
            raise SchedulerError("restart command successor is incomplete")
        if successor is not None and (
            not isinstance(successor, str) or not record_identifier(successor, "job")
        ):
            raise SchedulerError("restart successor is invalid")
        seen.add(row["request_digest"])
    pending = value["pending"]
    if pending is not None:
        if (
            not isinstance(pending, dict)
            or set(pending) != {"action", "request_digest", "attempt"}
            or pending["action"] not in {"pause", "cancel"}
            or pending["request_digest"] not in seen
            or type(pending["attempt"]) is not int
            or pending["attempt"] != job["attempt"]
            or job["job_kind"] not in COOPERATIVE_KINDS
            or job["status"] != {"pause": "pausing", "cancel": "cancelling"}[pending["action"]]
            or value["commit_started"]
        ):
            raise SchedulerError("cooperative intent is inconsistent")
        if not any(
            row["request_digest"] == pending["request_digest"]
            and row["action"] == pending["action"]
            for row in commands
        ):
            raise SchedulerError("cooperative intent differs from its receipt")
    elif job["status"] in {"pausing", "cancelling"}:
        raise SchedulerError("cooperative transition has no durable intent")
    completion = value["completion"]
    if completion is not None and (
        completion != "cancel"
        or job["status"] not in {"queued", "retry_wait", "paused"}
        or not commands
        or commands[-1]["action"] != "cancel"
    ):
        raise SchedulerError("immediate command completion intent is invalid")
    if value["commit_started"] and (
        job["job_kind"] not in COOPERATIVE_KINDS
        or job["status"] in {"paused", "pausing", "cancelling"}
    ):
        raise SchedulerError("commit barrier is inconsistent")
    restart = value["restart"]
    if restart is not None:
        from .scheduler_model import validate_job_record

        if not isinstance(restart, dict) or set(restart) != {"request_digest", "job"}:
            raise SchedulerError("restart intent is invalid")
        child = restart["job"]
        if (
            restart["request_digest"] not in seen
            or not isinstance(child, dict)
            or not isinstance(child.get("control"), dict)
            or child["control"].get("restart") is not None
            or child["control"].get("parent_job_id") != job["id"]
            or child.get("status") != "queued"
            or child.get("attempt") != 0
        ):
            raise SchedulerError("restart intent lineage is invalid")
        validate_job_record(child)
        if not any(
            row["request_digest"] == restart["request_digest"]
            and row["successor_id"] == child["id"]
            for row in commands
        ):
            raise SchedulerError("restart intent lacks its command receipt")
    observation = value["observation"]
    if observation is not None:
        if (
            not isinstance(observation, dict)
            or set(observation)
            != {
                "unit",
                "completed",
                "total",
                "plan_revision",
                "attempt",
                "sampled_at",
                "rate_per_second",
            }
            or observation["unit"] not in {"documents", "source_items"}
            or job["job_kind"] not in COOPERATIVE_KINDS
            or observation["unit"]
            != (
                "source_items" if job["job_kind"] == "maintenance.source_reconcile" else "documents"
            )
            or not _hash(observation["plan_revision"])
            or type(observation["attempt"]) is not int
            or not 1 <= observation["attempt"] <= job["attempt"]
            or type(observation["total"]) is not int
            or not 0 <= observation["total"] <= 2**63 - 1
            or type(observation["completed"]) is not int
            or not 0 <= observation["completed"] <= observation["total"]
            or (
                observation["rate_per_second"] is not None
                and (
                    type(observation["rate_per_second"]) not in {int, float}
                    or not 0 <= observation["rate_per_second"] < float("inf")
                )
            )
        ):
            raise SchedulerError("job progress observation is invalid")
        instant_text(observation["sampled_at"])
    if len(json.dumps(job, allow_nan=False).encode()) > MAX_CONTROL_RECORD_BYTES:
        raise SchedulerError("controlled job exceeds its byte bound")
    return dict(value)


def revision(job: Mapping[str, Any], producer: Any = None) -> str:
    active = job["status"] in ACTIVE_STATUSES
    return digest(
        {
            key: job.get(key)
            for key in (
                "id",
                "policy_id",
                "policy_revision",
                "job_kind",
                "scope",
                "status",
                "attempt",
                "retry",
                "retry_not_before",
                "recovery_state",
                "execution_plan",
            )
        }
        | {
            "control": {
                key: value
                for key, value in (job.get("control") or {}).items()
                if not active or key not in {"observation", "network_used"}
            },
            "checkpoint": None if active else job["checkpoint"],
            "producer": None if active else producer,
        }
    )


def public_control_progress(job: Mapping[str, Any]) -> dict[str, Any]:
    observation = (job.get("control") or {}).get("observation")
    return {
        "unit": observation["unit"] if observation else None,
        "completed": observation["completed"] if observation else None,
        "total": observation["total"] if observation else None,
        "count_relation": "exact" if observation else "unknown",
        "rate_per_second": observation["rate_per_second"]
        if observation and job["status"] == "running" and observation["attempt"] == job["attempt"]
        else None,
        "checkpoint": dict(job["checkpoint"]),
        "wait_reason": "safe_boundary"
        if job["status"] in {"pausing", "cancelling"}
        else "retry_not_before"
        if job["status"] == "retry_wait"
        else None,
    }


def capabilities(job: Mapping[str, Any], *, producer: Any = None, now=None) -> dict[str, Any]:
    status = job["status"]
    cooperative = job["job_kind"] in COOPERATIVE_KINDS
    control = job.get("control") or initial_control()
    remaining = job["attempt"] < job["retry"]["max_attempts"]
    allowed = []
    unavailable = {}
    for action in CONTROL_ACTIONS:
        reason = "unsupported_state"
        eligible = False
        if action == "pause":
            eligible = cooperative and status in {"queued", "retry_wait", "running"}
        elif action == "cancel":
            eligible = status in {"queued", "retry_wait", "paused"} or (
                cooperative and status in {"running", "pausing"}
            )
        elif action == "resume":
            eligible = cooperative and status == "paused" and remaining
            if not remaining:
                reason = "attempts_exhausted"
            if eligible and isinstance(producer, dict) and producer.get("resumable") is False:
                eligible, reason = False, "checkpoint_changed"
        elif action == "retry":
            eligible = cooperative and status == "retry_wait" and remaining
            if eligible and utc_instant(job["retry_not_before"]) > utc_instant(now):
                eligible, reason = False, "retry_not_before"
        elif action == "restart":
            eligible = cooperative and (status == "paused" or status in TERMINAL_JOB_STATUSES)
        if status in ACTIVE_STATUSES and (
            control["commit_started"] or job["checkpoint"]["phase"] == "committed"
        ):
            eligible, reason = False, "commit_started"
        if len(control["commands"]) >= MAX_CONTROL_COMMANDS or control["revision"] >= 2**31 - 2:
            eligible, reason = False, "control_history_full"
        if control["completion"] is not None or control["restart"] is not None:
            eligible, reason = False, "command_recovery"
        if not cooperative and action != "cancel":
            reason = "executor_not_cooperative"
        if eligible:
            allowed.append(action)
        else:
            unavailable[action] = reason
    return {
        "job_id": job["id"],
        "revision": revision(job, producer),
        "actions": allowed,
        "unavailable": unavailable,
        "checkpoint": dict(job["checkpoint"]),
        "progress": dict(job["progress"]),
        "cooperative": cooperative,
        "wait_reason": "safe_boundary"
        if status in {"pausing", "cancelling"}
        else "retry_not_before"
        if status == "retry_wait"
        else None,
    }


def validate_restart_lineage(parent, child):
    """Validate the immutable admission fields, allowing subsequent child progress."""
    restart = (parent or {}).get("control", {}).get("restart")
    if (
        parent is None
        or parent["status"] not in TERMINAL_JOB_STATUSES
        or restart is None
        or child.get("control", {}).get("parent_job_id") != parent["id"]
        or any(
            child.get(key) != restart["job"].get(key)
            for key in (
                "id",
                "idempotency_key",
                "policy_id",
                "policy_revision",
                "job_kind",
                "scope",
                "retry",
                "execution_plan",
                "reason",
                "scheduled_for",
                "created_at",
            )
        )
    ):
        raise SchedulerConflictError("restart child lineage changed")


class JobControl:
    def __init__(self, journal, producer):
        self.journal = journal
        self.producer = producer

    def _job(self, job_id):
        job = self.journal.get_job(job_id)
        if job is None:
            raise SchedulerNotFoundError("scheduler job not found")
        return job

    def finish_restart(self, job, *, now=None):
        """Reconcile a durable intent without ever resetting the parent's attempts."""
        restart = job.get("control", {}).get("restart")
        if restart is None:
            return job, None
        if job["status"] == "paused":
            terminal = self.journal.get_receipt("receipt_" + job["id"][4:])
            job = self.journal._finish_locked(
                job,
                status="cancelled",
                now=utc_instant(terminal["completed_at"] if terminal else now),
                progress=job["progress"],
                error_class="cancelled",
                error_code="cancelled_by_user",
                network_used=False,
                canonical_mutation=False,
            )
        if job["status"] not in TERMINAL_JOB_STATUSES:
            raise SchedulerConflictError("restart parent has not stopped")
        from .scheduler import _receipt_matches_terminal_job

        receipt = self.journal.get_receipt("receipt_" + job["id"][4:])
        if receipt is None or not _receipt_matches_terminal_job(receipt, job):
            raise SchedulerConflictError("restart parent terminal evidence is incomplete")
        child = self.journal.get_job(restart["job"]["id"])
        if child is None:
            child = self.journal._write_job(restart["job"])
        validate_restart_lineage(job, child)
        return job, child

    def finish_immediate(self, job, *, now=None):
        if job.get("control", {}).get("completion") != "cancel":
            return job
        terminal = self.journal.get_receipt("receipt_" + job["id"][4:])
        return self.journal._finish_locked(
            job,
            status="cancelled",
            now=utc_instant(terminal["completed_at"] if terminal else now),
            progress=job["progress"],
            error_class="cancelled",
            error_code="cancelled_by_user",
            network_used=False,
            canonical_mutation=False,
        )

    def request(
        self, job_id, action, *, expected_revision, request_id, expected_checkpoint=None, now=None
    ):
        if (
            action not in CONTROL_ACTIONS
            or not _hash(expected_revision)
            or not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 200
        ):
            raise SchedulerError("invalid job control request")
        request_digest = digest(request_id)
        payload = digest([job_id, action, expected_revision, expected_checkpoint])
        with self.journal.hold():
            job = self._job(job_id)
            control = job.get("control") or initial_control()
            for receipt in control["commands"]:
                if receipt["request_digest"] == request_digest:
                    if receipt["payload_digest"] != payload:
                        raise SchedulerConflictError("control request identity was reused")
                    job = self.finish_immediate(job, now=now)
                    job, child = self.finish_restart(job, now=now)
                    return {"job": job, "receipt": receipt, "replayed": True, "successor": child}
            producer = None if job["status"] in ACTIVE_STATUSES else self.producer(job)
            view = capabilities(job, producer=producer, now=now)
            if view["revision"] != expected_revision:
                raise SchedulerConflictError("job control preview is stale")
            if action not in view["actions"]:
                raise SchedulerConflictError(view["unavailable"][action])
            if expected_checkpoint is not None and expected_checkpoint != job["checkpoint"]:
                raise SchedulerConflictError("job checkpoint changed")
            job = promote(job)
            control = dict(job["control"])
            target_status = job["status"]
            child = None
            if action == "pause":
                target_status = "pausing" if job["status"] == "running" else "paused"
                if job["status"] == "retry_wait":
                    job = {**job, "eligible_at": max(job["eligible_at"], job["retry_not_before"])}
            elif action == "cancel":
                target_status = "cancelling" if job["status"] in ACTIVE_STATUSES else "cancelled"
            elif action in {"resume", "retry"}:
                target_status = "queued"
            elif action == "restart":
                policy = self.journal.get_policy(job["policy_id"])
                if (
                    policy is None
                    or policy["scope"] != job["scope"]
                    or policy["job_kind"] != job["job_kind"]
                ):
                    raise SchedulerConflictError("restart policy changed")
                stamp = instant_text(now)
                child = {
                    **job,
                    "id": "job_" + digest([job_id, request_digest])[:32],
                    "policy_revision": policy["revision"],
                    "retry": dict(policy["retry"]),
                    "idempotency_key": digest(["restart", job_id, request_digest]),
                    "reason": "manual",
                    "scheduled_for": stamp,
                    "eligible_at": stamp,
                    "created_at": stamp,
                    "updated_at": stamp,
                    "status": "queued",
                    "attempt": 0,
                    "retry_not_before": None,
                    "lease": None,
                    "checkpoint": {"sequence": 0, "phase": "none", "committed_at": None},
                    "progress": {"processed": 0, "skipped": 0, "errors": 0},
                    "recovery_state": "none",
                    "recovery_count": 0,
                    "attempts": [],
                    "receipt_ref": None,
                    "control": initial_control(parent=job_id),
                }
                if isinstance(producer, dict) and job["execution_plan"] is not None:
                    child["execution_plan"] = producer["execution_plan"]
            receipt = {
                "request_digest": request_digest,
                "payload_digest": payload,
                "action": action,
                "expected_revision": expected_revision,
                "result_status": "restarted" if child else target_status,
                "accepted_at": instant_text(now),
                "successor_id": child["id"] if child else None,
            }
            control.update(
                revision=control["revision"] + 1, commands=[*control["commands"], receipt]
            )
            if target_status in {"pausing", "cancelling"}:
                control["pending"] = {
                    "action": action,
                    "request_digest": request_digest,
                    "attempt": job["attempt"],
                }
            if child:
                control["restart"] = {"request_digest": request_digest, "job": child}
            job = {**job, "control": control}
            if target_status == "cancelled" and child is None:
                job = self.journal._write_job(
                    {**job, "control": {**control, "completion": "cancel"}}
                )
                job = self.finish_immediate(job, now=now)
            else:
                job = self.journal._write_job(
                    {
                        **job,
                        "status": target_status,
                        "retry_not_before": None
                        if target_status != "retry_wait"
                        else job["retry_not_before"],
                    }
                )
            job, child = self.finish_restart(job, now=now)
            return {"job": job, "receipt": receipt, "replayed": False, "successor": child}

    def boundary(
        self, job_id, lease_token, *, commit=False, observation=None, network_used=False, now=None
    ):
        with self.journal.hold():
            job = self._job(job_id)
            self.journal._owned(job, lease_token, utc_instant(now))
            job = promote(job)
            control = dict(job["control"])
            if type(network_used) is not bool:
                raise SchedulerError("cooperative network observation is invalid")
            changed_network = network_used and not control["network_used"]
            control["network_used"] = control["network_used"] or network_used
            job = {**job, "control": control}
            if observation is not None:
                stamp = instant_text(now)
                previous = control["observation"]
                rate = None
                if (
                    previous
                    and previous["attempt"] == job["attempt"]
                    and previous["plan_revision"] == observation["plan_revision"]
                    and previous["unit"] == observation["unit"]
                ):
                    elapsed = (
                        utc_instant(stamp) - utc_instant(previous["sampled_at"])
                    ).total_seconds()
                    if elapsed > 0 and observation["completed"] >= previous["completed"]:
                        rate = (observation["completed"] - previous["completed"]) / elapsed
                control["observation"] = {
                    **observation,
                    "attempt": job["attempt"],
                    "sampled_at": stamp,
                    "rate_per_second": rate,
                }
                job = {**job, "control": control}
            pending = control["pending"]
            if pending:
                control.update(pending=None, revision=control["revision"] + 1)
                job = {**job, "control": control}
                if pending["action"] == "cancel":
                    result = self.journal._finish_locked(
                        job,
                        status="cancelled",
                        now=utc_instant(now),
                        progress=job["progress"],
                        error_class="cancelled",
                        error_code="cancelled_by_user",
                        network_used=False,
                        canonical_mutation=False,
                    )
                else:
                    attempts = [dict(row) for row in job["attempts"]]
                    attempts[-1].update(outcome="paused", completed_at=instant_text(now))
                    result = self.journal._write_job(
                        {
                            **job,
                            "status": "paused",
                            "lease": None,
                            "attempts": attempts,
                            "updated_at": instant_text(now),
                            "recovery_state": "resumable"
                            if job["checkpoint"]["sequence"] > 2
                            else "restart_only",
                        }
                    )
                raise CooperativeStop(result)
            if commit and not control["commit_started"]:
                control.update(commit_started=True, revision=control["revision"] + 1)
                self.journal._write_job({**job, "control": control})
            elif observation is not None or changed_network:
                self.journal._write_job({**job, "control": control})
