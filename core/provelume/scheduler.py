from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from .scheduler_model import (
    ERROR_CLASSES,
    EXECUTABLE_JOB_KINDS,
    JOB_STATUSES,
    MAX_LEASE_SECONDS,
    POLICY_STATES,
    RUN_REASONS,
    SCHEDULER_JOB_KINDS,
    SCHEDULER_SCHEMA_VERSION,
    TERMINAL_JOB_STATUSES,
    SchedulerBusyError,
    SchedulerConflictError,
    SchedulerError,
    SchedulerLeaseError,
    SchedulerNotFoundError,
    eligible_instant,
    idempotency_digest,
    instant_text,
    next_nominal_after,
    next_nominal_from_previous,
    normalise_retry,
    normalise_schedule,
    normalise_scope,
    record_identifier,
    retry_delay_seconds,
    retry_payload,
    schedule_payload,
    utc_instant,
    validate_error,
    validate_job_record,
    validate_policy_record,
    validate_progress,
    validate_receipt_record,
    validate_worker_id,
)
from .storage import InstanceStore

DEFAULT_LEASE_SECONDS = 120
MAX_MISSED_SCAN = 10_000
SCHEDULER_LOCK_NAME = "scheduler-journal.oslock"


def _receipt_matches_job(
    receipt: Mapping[str, Any],
    job: Mapping[str, Any],
) -> bool:
    return all(
        (
            receipt["job_id"] == job["id"],
            receipt["policy_id"] == job["policy_id"],
            receipt["policy_revision"] == job["policy_revision"],
            receipt["job_kind"] == job["job_kind"],
            receipt["scope"] == job["scope"],
            receipt["attempts"] == job["attempt"],
        )
    )


def _receipt_matches_terminal_job(
    receipt: Mapping[str, Any],
    job: Mapping[str, Any],
) -> bool:
    if (
        not _receipt_matches_job(receipt, job)
        or receipt["status"] != job["status"]
        or receipt["progress"] != job["progress"]
        or receipt["completed_at"] != job["updated_at"]
        or receipt["duration_ms"] != _attempt_duration_ms(job["attempts"])
    ):
        return False
    attempts = job["attempts"]
    if not attempts:
        return int(job["attempt"]) == 0 and receipt["status"] == "cancelled"
    final_attempt = attempts[-1]
    if receipt["status"] == "cancelled" and final_attempt["outcome"] == "retry":
        return True
    return (
        final_attempt["completed_at"] == receipt["completed_at"]
        and final_attempt["error_class"] == receipt["error_class"]
        and final_attempt["error_code"] == receipt["error_code"]
    )


def public_job_record(job: Mapping[str, Any]) -> dict[str, Any]:
    """Remove lease authority while retaining observable timing and worker state."""

    result = dict(job)
    lease = job.get("lease")
    if isinstance(lease, Mapping):
        result["lease"] = {
            "worker_id": lease["worker_id"],
            "acquired_at": lease["acquired_at"],
            "heartbeat_at": lease["heartbeat_at"],
            "expires_at": lease["expires_at"],
            "token_present": True,
        }
    return result


def _attempt_duration_ms(attempts: Sequence[Mapping[str, Any]]) -> int:
    duration = 0
    for attempt in attempts:
        completed_at = attempt.get("completed_at")
        if completed_at is None:
            continue
        elapsed = utc_instant(completed_at) - utc_instant(attempt["started_at"])
        duration += max(0, int(elapsed.total_seconds() * 1000))
    return duration


def _acquire_os_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise SchedulerBusyError("another scheduler mutation is active") from exc
        return
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError) as exc:
        raise SchedulerBusyError("another scheduler mutation is active") from exc


def _release_os_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


class SchedulerStore:
    """Durable, content-free policy and job records for one Instance."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "scheduler"
        self.policies = self.root / "policies"
        self.jobs = self.root / "jobs"
        self.receipts = self.root / "receipts"
        self.lock_path = store.paths.state / "locks" / SCHEDULER_LOCK_NAME

    @property
    def instance_id(self) -> str:
        return str(self.store.read_config()["instance"]["id"])

    @property
    def source_ids(self) -> set[str]:
        return {str(item["id"]) for item in self.store.list_canonical("sources")}

    def _ensure_directories(self) -> None:
        for path in (
            self.root,
            self.policies,
            self.jobs,
            self.receipts,
            self.lock_path.parent,
        ):
            if path.exists() and (path.is_symlink() or not path.is_dir()):
                raise SchedulerError("scheduler state directory is invalid")
            path.mkdir(parents=True, exist_ok=True)

    def _readable_directory(self, path: Path) -> bool:
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise SchedulerError("scheduler state directory is invalid")
        if not path.exists():
            return False
        if path.is_symlink() or not path.is_dir():
            raise SchedulerError("scheduler state directory is invalid")
        return True

    @contextmanager
    def hold(self) -> Iterator[None]:
        self._ensure_directories()
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise SchedulerBusyError("scheduler lock file cannot be opened") from exc
        locked = False
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\n")
                os.fsync(descriptor)
            _acquire_os_lock(descriptor)
            locked = True
            yield
        finally:
            try:
                if locked:
                    _release_os_lock(descriptor)
            finally:
                os.close(descriptor)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise SchedulerError("scheduler state is not a regular file")
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SchedulerError("scheduler state is unreadable") from exc
        if not isinstance(value, dict):
            raise SchedulerError("scheduler state must be a JSON object")
        return value

    def _policy(self, value: Any) -> dict[str, Any]:
        return validate_policy_record(
            value,
            instance_id=self.instance_id,
            known_source_ids=self.source_ids,
        )

    def _write_policy(self, value: Mapping[str, Any]) -> dict[str, Any]:
        policy = self._policy(value)
        self.store._atomic_json(self.policies / f"{policy['id']}.json", policy)
        return policy

    def _write_job(self, value: Mapping[str, Any]) -> dict[str, Any]:
        job = validate_job_record(value)
        self.store._atomic_json(self.jobs / f"{job['id']}.json", job)
        return job

    def _write_receipt_once(self, value: Mapping[str, Any]) -> dict[str, Any]:
        receipt = validate_receipt_record(value)
        self.receipts.mkdir(parents=True, exist_ok=True)
        path = self.receipts / f"{receipt['id']}.json"
        encoded = (
            json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            current = self._read_json(path)
            if current != receipt:
                raise SchedulerConflictError(
                    "terminal job receipt is immutable"
                ) from exc
            return receipt
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return receipt

    def get_policy(self, policy_id: str) -> dict[str, Any] | None:
        if not record_identifier(policy_id, "policy"):
            return None
        if not self._readable_directory(self.policies):
            return None
        path = self.policies / f"{policy_id}.json"
        return self._policy(self._read_json(path)) if path.is_file() else None

    def list_policies(self) -> list[dict[str, Any]]:
        if not self._readable_directory(self.policies):
            return []
        result = [self._policy(self._read_json(path)) for path in self.policies.glob("*.json")]
        return sorted(result, key=lambda item: (str(item["created_at"]), str(item["id"])))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        if not record_identifier(job_id, "job"):
            return None
        if not self._readable_directory(self.jobs):
            return None
        path = self.jobs / f"{job_id}.json"
        return validate_job_record(self._read_json(path)) if path.is_file() else None

    def list_jobs(
        self,
        *,
        status: str | None = None,
        policy_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status is not None and status not in JOB_STATUSES:
            raise SchedulerError("unsupported scheduler job status")
        if limit < 1:
            return []
        result = []
        for job in self._all_jobs():
            if status is not None and job["status"] != status:
                continue
            if policy_id is not None and job["policy_id"] != policy_id:
                continue
            result.append(job)
        result.sort(
            key=lambda item: (str(item["created_at"]), str(item["id"])),
            reverse=True,
        )
        return result[: min(limit, 500)]

    def _all_jobs(self) -> list[dict[str, Any]]:
        if not self._readable_directory(self.jobs):
            return []
        return [
            validate_job_record(self._read_json(path))
            for path in self.jobs.glob("*.json")
        ]

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        if not record_identifier(receipt_id, "receipt"):
            return None
        if not self._readable_directory(self.receipts):
            return None
        path = self.receipts / f"{receipt_id}.json"
        return validate_receipt_record(self._read_json(path)) if path.is_file() else None

    def list_receipts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        result = self._all_receipts()
        result.sort(
            key=lambda item: (str(item["completed_at"]), str(item["id"])),
            reverse=True,
        )
        return result[: min(limit, 500)]

    def _all_receipts(self) -> list[dict[str, Any]]:
        if not self._readable_directory(self.receipts):
            return []
        return [
            validate_receipt_record(self._read_json(path))
            for path in self.receipts.glob("*.json")
        ]

    @staticmethod
    def _occurrence(
        policy: Mapping[str, Any],
        nominal: datetime,
    ) -> tuple[str, str]:
        eligible = eligible_instant(
            nominal,
            policy_id=str(policy["id"]),
            revision=int(policy["revision"]),
            schedule=policy["schedule"],
        )
        return instant_text(nominal), instant_text(eligible)

    def create_policy(
        self,
        *,
        job_kind: str,
        scope: Mapping[str, str],
        state: str = "disabled",
        schedule: Mapping[str, Any],
        retry: Mapping[str, Any] | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        if job_kind not in SCHEDULER_JOB_KINDS:
            raise SchedulerError("unsupported scheduler job kind")
        if state not in POLICY_STATES:
            raise SchedulerError("unsupported scheduler policy state")
        selected_now = utc_instant(now)
        selected_schedule = normalise_schedule(schedule)
        selected_retry = normalise_retry(retry or retry_payload())
        selected_scope = normalise_scope(
            scope,
            instance_id=self.instance_id,
            known_source_ids=self.source_ids,
            job_kind=job_kind,
        )
        policy_id = f"policy_{uuid4().hex}"
        nominal_text = None
        due_text = None
        if state == "enabled":
            nominal = next_nominal_after(selected_now, selected_schedule)
            if nominal is not None:
                nominal_text, due_text = self._occurrence(
                    {
                        "id": policy_id,
                        "revision": 1,
                        "schedule": selected_schedule,
                    },
                    nominal,
                )
        policy = {
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "id": policy_id,
            "revision": 1,
            "job_kind": job_kind,
            "scope": selected_scope,
            "state": state,
            "schedule": selected_schedule,
            "retry": selected_retry,
            "created_at": instant_text(selected_now),
            "updated_at": instant_text(selected_now),
            "last_evaluated_at": None,
            "next_nominal_at": nominal_text,
            "next_due_at": due_text,
        }
        with self.hold():
            return self._write_policy(policy)

    def update_policy(
        self,
        policy_id: str,
        *,
        state: str | None = None,
        schedule: Mapping[str, Any] | None = None,
        retry: Mapping[str, Any] | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected_now = utc_instant(now)
        with self.hold():
            current = self.get_policy(policy_id)
            if current is None:
                raise SchedulerNotFoundError("scheduler policy not found")
            selected_state = current["state"] if state is None else state
            if selected_state not in POLICY_STATES:
                raise SchedulerError("unsupported scheduler policy state")
            selected_schedule = normalise_schedule(schedule or current["schedule"])
            selected_retry = normalise_retry(retry or current["retry"])
            revision = int(current["revision"]) + 1
            nominal_text = None
            due_text = None
            if selected_state == "enabled":
                nominal = next_nominal_after(selected_now, selected_schedule)
                if nominal is not None:
                    nominal_text, due_text = self._occurrence(
                        {
                            "id": policy_id,
                            "revision": revision,
                            "schedule": selected_schedule,
                        },
                        nominal,
                    )
            updated = {
                **current,
                "revision": revision,
                "state": selected_state,
                "schedule": selected_schedule,
                "retry": selected_retry,
                "updated_at": instant_text(selected_now),
                "last_evaluated_at": None,
                "next_nominal_at": nominal_text,
                "next_due_at": due_text,
            }
            return self._write_policy(updated)

    def _find_job_by_key(self, key: str) -> dict[str, Any] | None:
        for job in self._all_jobs():
            if job["idempotency_key"] == key:
                return job
        return None

    def _new_job(
        self,
        policy: Mapping[str, Any],
        *,
        reason: str,
        nominal: datetime,
        eligible: datetime,
        idempotency_key: str,
        now: datetime,
    ) -> tuple[dict[str, Any], bool]:
        if reason not in RUN_REASONS:
            raise SchedulerError("unsupported scheduler run reason")
        existing = self._find_job_by_key(idempotency_key)
        if existing is not None:
            return existing, False
        job = {
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "id": f"job_{uuid4().hex}",
            "policy_id": policy["id"],
            "policy_revision": policy["revision"],
            "job_kind": policy["job_kind"],
            "scope": dict(policy["scope"]),
            "idempotency_key": idempotency_key,
            "reason": reason,
            "scheduled_for": instant_text(nominal),
            "eligible_at": instant_text(eligible),
            "created_at": instant_text(now),
            "updated_at": instant_text(now),
            "status": "queued",
            "attempt": 0,
            "retry": dict(policy["retry"]),
            "retry_not_before": None,
            "lease": None,
            "checkpoint": {"sequence": 0, "phase": "none", "committed_at": None},
            "progress": {"processed": 0, "skipped": 0, "errors": 0},
            "recovery_state": "none",
            "recovery_count": 0,
            "attempts": [],
            "receipt_ref": None,
        }
        return self._write_job(job), True

    def run_now(
        self,
        policy_id: str,
        *,
        request_key: str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected_now = utc_instant(now)
        with self.hold():
            policy = self.get_policy(policy_id)
            if policy is None:
                raise SchedulerNotFoundError("scheduler policy not found")
            if policy["job_kind"] not in EXECUTABLE_JOB_KINDS:
                raise SchedulerError("this job kind has no local executor")
            identity = request_key.strip() if isinstance(request_key, str) else uuid4().hex
            if not identity or len(identity) > 200:
                raise SchedulerError("manual idempotency key is invalid")
            key = idempotency_digest(
                "manual",
                str(policy["id"]),
                str(policy["revision"]),
                identity,
            )
            job, created = self._new_job(
                policy,
                reason="manual",
                nominal=selected_now,
                eligible=selected_now,
                idempotency_key=key,
                now=selected_now,
            )
            return {"job": job, "created": created}

    def _advance_occurrences(
        self,
        policy: Mapping[str, Any],
        *,
        first_nominal: datetime,
        now: datetime,
    ) -> dict[str, Any]:
        nominal = first_nominal
        nominal_text, due_text = self._occurrence(policy, nominal)
        due = utc_instant(due_text)
        latest_nominal = nominal
        latest_due = due
        occurrences = 1
        capped = False
        while True:
            following = next_nominal_from_previous(nominal, policy["schedule"])
            if following is None:
                return {
                    "future_nominal": None,
                    "future_due": None,
                    "latest_nominal": latest_nominal,
                    "latest_due": latest_due,
                    "occurrences": occurrences,
                    "capped": capped,
                }
            following_nominal_text, following_due_text = self._occurrence(policy, following)
            following_due = utc_instant(following_due_text)
            if following_due > now:
                return {
                    "future_nominal": utc_instant(following_nominal_text),
                    "future_due": following_due,
                    "latest_nominal": latest_nominal,
                    "latest_due": latest_due,
                    "occurrences": occurrences,
                    "capped": capped,
                }
            latest_nominal = following
            latest_due = following_due
            nominal = following
            occurrences += 1
            if occurrences >= MAX_MISSED_SCAN:
                capped = True
                future = next_nominal_after(now, policy["schedule"])
                if future is None:
                    return {
                        "future_nominal": None,
                        "future_due": None,
                        "latest_nominal": latest_nominal,
                        "latest_due": latest_due,
                        "occurrences": occurrences,
                        "capped": capped,
                    }
                _future_text, future_due_text = self._occurrence(policy, future)
                return {
                    "future_nominal": future,
                    "future_due": utc_instant(future_due_text),
                    "latest_nominal": latest_nominal,
                    "latest_due": latest_due,
                    "occurrences": occurrences,
                    "capped": capped,
                }

    def _recover_locked(self, now: datetime) -> dict[str, int]:
        recovered = 0
        retries_ready = 0
        reconciled_receipts = 0
        clock_changes = 0
        if not self.jobs.exists():
            return {
                "expired_leases": recovered,
                "retries_ready": retries_ready,
                "receipts_reconciled": reconciled_receipts,
                "clock_changes": clock_changes,
            }
        for path in sorted(self.jobs.glob("*.json")):
            job = validate_job_record(self._read_json(path))
            if job["status"] in TERMINAL_JOB_STATUSES:
                continue
            receipt_id = f"receipt_{str(job['id']).removeprefix('job_')}"
            receipt_path = self.receipts / f"{receipt_id}.json"
            if receipt_path.is_file():
                receipt = validate_receipt_record(self._read_json(receipt_path))
                if not _receipt_matches_job(receipt, job):
                    raise SchedulerConflictError("scheduler receipt does not match its job")
                attempts = [dict(item) for item in job["attempts"]]
                if attempts and attempts[-1]["outcome"] == "running":
                    attempts[-1] = {
                        **attempts[-1],
                        "completed_at": receipt["completed_at"],
                        "outcome": (
                            "succeeded" if receipt["status"] == "succeeded" else "failed"
                        ),
                        "error_class": receipt["error_class"],
                        "error_code": receipt["error_code"],
                    }
                job = {
                    **job,
                    "status": receipt["status"],
                    "updated_at": receipt["completed_at"],
                    "lease": None,
                    "retry_not_before": None,
                    "progress": receipt["progress"],
                    "attempts": attempts,
                    "receipt_ref": f"state/scheduler/receipts/{receipt_id}.json",
                }
                self._write_job(job)
                reconciled_receipts += 1
                continue
            if job["status"] == "retry_wait":
                retry_at = job.get("retry_not_before")
                clock_reversed = now < utc_instant(job["updated_at"])
                if retry_at is not None and (
                    utc_instant(retry_at) <= now or clock_reversed
                ):
                    job = {
                        **job,
                        "status": "queued",
                        "retry_not_before": None,
                        "updated_at": instant_text(now),
                    }
                    self._write_job(job)
                    retries_ready += 1
                    clock_changes += int(clock_reversed)
                continue
            lease = job.get("lease")
            if job["status"] != "running" or not isinstance(lease, Mapping):
                continue
            clock_reversed = now < utc_instant(str(lease["heartbeat_at"]))
            if not clock_reversed and utc_instant(str(lease["expires_at"])) > now:
                continue
            checkpoint = job["checkpoint"]
            if checkpoint["phase"] == "committed":
                recovery_state = "manual_intervention"
            elif job["job_kind"] == "source.refresh" and int(checkpoint["sequence"]) > 0:
                recovery_state = "resumable"
            else:
                recovery_state = "restart_only"
            terminal_recovery = (
                recovery_state == "manual_intervention"
                or int(job["attempt"]) >= int(job["retry"]["max_attempts"])
            )
            attempts = [dict(item) for item in job["attempts"]]
            error_code = (
                "committed_checkpoint_needs_review"
                if recovery_state == "manual_intervention"
                else "lease_recovery_exhausted"
                if terminal_recovery
                else "lease_clock_reversed"
                if clock_reversed
                else "lease_expired"
            )
            if attempts and attempts[-1]["outcome"] == "running":
                attempts[-1] = {
                    **attempts[-1],
                    "completed_at": instant_text(now),
                    "outcome": "failed" if terminal_recovery else "retry",
                    "error_class": (
                        "manual_intervention" if terminal_recovery else "transient"
                    ),
                    "error_code": error_code,
                }
            if terminal_recovery:
                job = {
                    **job,
                    "attempts": attempts,
                    "lease": None,
                    "recovery_state": "manual_intervention",
                    "recovery_count": int(job["recovery_count"]) + 1,
                }
                self._finish_locked(
                    job,
                    status="manual_intervention",
                    now=now,
                    progress=job["progress"],
                    error_class="manual_intervention",
                    error_code=error_code,
                    network_used=False,
                    canonical_mutation=False,
                )
            else:
                self._write_job(
                    {
                        **job,
                        "status": "queued",
                        "updated_at": instant_text(now),
                        "lease": None,
                        "retry_not_before": None,
                        "recovery_state": recovery_state,
                        "recovery_count": int(job["recovery_count"]) + 1,
                        "attempts": attempts,
                    }
                )
            recovered += 1
            clock_changes += int(clock_reversed)
        return {
            "expired_leases": recovered,
            "retries_ready": retries_ready,
            "receipts_reconciled": reconciled_receipts,
            "clock_changes": clock_changes,
        }

    def recover(self, *, now: datetime | str | None = None) -> dict[str, int]:
        selected_now = utc_instant(now)
        if not self.root.exists():
            return {
                "expired_leases": 0,
                "retries_ready": 0,
                "receipts_reconciled": 0,
                "clock_changes": 0,
            }
        with self.hold():
            return self._recover_locked(selected_now)

    def evaluate(self, *, now: datetime | str | None = None) -> dict[str, Any]:
        selected_now = utc_instant(now)
        created_jobs: list[str] = []
        duplicate_jobs: list[str] = []
        skipped_policies: list[str] = []
        clock_changes: list[str] = []
        capped_policies: list[str] = []
        if not self.root.exists():
            return {
                "schema_version": SCHEDULER_SCHEMA_VERSION,
                "evaluated_at": instant_text(selected_now),
                "created_jobs": [],
                "duplicate_jobs": [],
                "skipped_policies": [],
                "clock_changes": [],
                "capped_policies": [],
                "recovery": {
                    "expired_leases": 0,
                    "retries_ready": 0,
                    "receipts_reconciled": 0,
                    "clock_changes": 0,
                },
                "network_used": False,
                "automatic_deletion": False,
            }
        with self.hold():
            recovery = self._recover_locked(selected_now)
            for policy in self.list_policies():
                if policy["state"] != "enabled" or policy["schedule"]["mode"] == "manual":
                    continue
                last = policy.get("last_evaluated_at")
                if last is not None and selected_now < utc_instant(last):
                    nominal = next_nominal_after(selected_now, policy["schedule"])
                    nominal_text = None
                    due_text = None
                    if nominal is not None:
                        nominal_text, due_text = self._occurrence(policy, nominal)
                    self._write_policy(
                        {
                            **policy,
                            "last_evaluated_at": instant_text(selected_now),
                            "next_nominal_at": nominal_text,
                            "next_due_at": due_text,
                            "updated_at": instant_text(selected_now),
                        }
                    )
                    clock_changes.append(str(policy["id"]))
                    continue
                nominal_value = policy.get("next_nominal_at")
                due_value = policy.get("next_due_at")
                if nominal_value is None or due_value is None:
                    nominal = next_nominal_after(selected_now, policy["schedule"])
                    if nominal is None:
                        continue
                    nominal_value, due_value = self._occurrence(policy, nominal)
                nominal = utc_instant(nominal_value)
                due = utc_instant(due_value)
                if due > selected_now:
                    self._write_policy(
                        {
                            **policy,
                            "last_evaluated_at": instant_text(selected_now),
                            "next_nominal_at": instant_text(nominal),
                            "next_due_at": instant_text(due),
                            "updated_at": instant_text(selected_now),
                        }
                    )
                    continue
                advanced = self._advance_occurrences(
                    policy,
                    first_nominal=nominal,
                    now=selected_now,
                )
                if advanced["capped"]:
                    capped_policies.append(str(policy["id"]))
                backlog = int(advanced["occurrences"]) > 1
                missed_policy = str(policy["schedule"]["missed_run_policy"])
                selected_reason = "scheduled"
                selected_nominal = nominal
                selected_due = due
                if backlog:
                    if missed_policy == "skip":
                        skipped_policies.append(str(policy["id"]))
                        selected_reason = ""
                    elif missed_policy == "coalesce":
                        selected_reason = "coalesced"
                        selected_nominal = selected_now
                        selected_due = selected_now
                    else:
                        selected_reason = "catch_up"
                        selected_nominal = advanced["latest_nominal"]
                        selected_due = advanced["latest_due"]
                if selected_reason:
                    key = idempotency_digest(
                        "scheduled",
                        str(policy["id"]),
                        str(policy["revision"]),
                        selected_reason,
                        instant_text(nominal),
                    )
                    job, created = self._new_job(
                        policy,
                        reason=selected_reason,
                        nominal=selected_nominal,
                        eligible=selected_due,
                        idempotency_key=key,
                        now=selected_now,
                    )
                    (created_jobs if created else duplicate_jobs).append(str(job["id"]))
                future_nominal = advanced["future_nominal"]
                future_due = advanced["future_due"]
                self._write_policy(
                    {
                        **policy,
                        "last_evaluated_at": instant_text(selected_now),
                        "next_nominal_at": (
                            instant_text(future_nominal) if future_nominal is not None else None
                        ),
                        "next_due_at": (
                            instant_text(future_due) if future_due is not None else None
                        ),
                        "updated_at": instant_text(selected_now),
                    }
                )
        return {
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "evaluated_at": instant_text(selected_now),
            "created_jobs": created_jobs,
            "duplicate_jobs": duplicate_jobs,
            "skipped_policies": skipped_policies,
            "clock_changes": clock_changes,
            "capped_policies": capped_policies,
            "recovery": recovery,
            "network_used": False,
            "automatic_deletion": False,
        }

    def claim_next(
        self,
        *,
        worker_id: str,
        allowed_kinds: Sequence[str] = EXECUTABLE_JOB_KINDS,
        job_id: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: datetime | str | None = None,
    ) -> dict[str, Any] | None:
        selected_worker = validate_worker_id(worker_id)
        selected_now = utc_instant(now)
        if (
            type(lease_seconds) is not int
            or lease_seconds < 1
            or lease_seconds > MAX_LEASE_SECONDS
        ):
            raise SchedulerError("lease duration is outside the supported range")
        kinds = tuple(allowed_kinds)
        if not kinds or any(kind not in EXECUTABLE_JOB_KINDS for kind in kinds):
            raise SchedulerError("worker requested an unsupported executor kind")
        if not self.root.exists():
            return None
        if job_id is not None and self.get_job(job_id) is None:
            raise SchedulerNotFoundError("scheduler job not found")
        with self.hold():
            self._recover_locked(selected_now)
            candidates = []
            for job in self._all_jobs():
                if job["status"] != "queued" or job["job_kind"] not in kinds:
                    continue
                if job_id is not None and job["id"] != job_id:
                    continue
                if utc_instant(job["eligible_at"]) > selected_now:
                    continue
                candidates.append(job)
            if not candidates:
                return None
            candidates.sort(
                key=lambda item: (
                    str(item["eligible_at"]),
                    str(item["created_at"]),
                    str(item["id"]),
                )
            )
            job = candidates[0]
            attempt = int(job["attempt"]) + 1
            if attempt > int(job["retry"]["max_attempts"]):
                raise SchedulerConflictError("queued job exceeded its attempt bound")
            token = f"lease_{uuid4().hex}"
            expires = selected_now + timedelta(seconds=lease_seconds)
            attempts = [dict(item) for item in job["attempts"]]
            attempts.append(
                {
                    "attempt": attempt,
                    "started_at": instant_text(selected_now),
                    "completed_at": None,
                    "outcome": "running",
                    "error_class": None,
                    "error_code": None,
                }
            )
            return self._write_job(
                {
                    **job,
                    "status": "running",
                    "attempt": attempt,
                    "updated_at": instant_text(selected_now),
                    "retry_not_before": None,
                    "lease": {
                        "token": token,
                        "worker_id": selected_worker,
                        "acquired_at": instant_text(selected_now),
                        "heartbeat_at": instant_text(selected_now),
                        "expires_at": instant_text(expires),
                    },
                    "attempts": attempts,
                }
            )

    @staticmethod
    def _owned(job: Mapping[str, Any], lease_token: str, now: datetime) -> None:
        lease = job.get("lease")
        if (
            job.get("status") != "running"
            or not isinstance(lease, Mapping)
            or lease.get("token") != lease_token
        ):
            raise SchedulerLeaseError("job lease is not owned by this worker")
        if utc_instant(str(lease["expires_at"])) <= now:
            raise SchedulerLeaseError("job lease expired before this mutation")

    def heartbeat(
        self,
        job_id: str,
        lease_token: str,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected_now = utc_instant(now)
        if (
            type(lease_seconds) is not int
            or lease_seconds < 1
            or lease_seconds > MAX_LEASE_SECONDS
        ):
            raise SchedulerError("lease duration is outside the supported range")
        with self.hold():
            job = self.get_job(job_id)
            if job is None:
                raise SchedulerNotFoundError("scheduler job not found")
            self._owned(job, lease_token, selected_now)
            lease = dict(job["lease"])
            lease["heartbeat_at"] = instant_text(selected_now)
            lease["expires_at"] = instant_text(
                selected_now + timedelta(seconds=lease_seconds)
            )
            return self._write_job(
                {**job, "lease": lease, "updated_at": instant_text(selected_now)}
            )

    def checkpoint(
        self,
        job_id: str,
        lease_token: str,
        *,
        sequence: int,
        phase: str,
        progress: Mapping[str, int],
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected_now = utc_instant(now)
        selected_progress = validate_progress(progress)
        if phase not in {"prepared", "executing", "committed"}:
            raise SchedulerError("unsupported checkpoint phase")
        with self.hold():
            job = self.get_job(job_id)
            if job is None:
                raise SchedulerNotFoundError("scheduler job not found")
            self._owned(job, lease_token, selected_now)
            if type(sequence) is not int or sequence != int(job["checkpoint"]["sequence"]) + 1:
                raise SchedulerConflictError("checkpoint sequence must advance by exactly one")
            if any(
                selected_progress[key] < int(job["progress"][key])
                for key in selected_progress
            ):
                raise SchedulerConflictError("checkpoint progress cannot move backward")
            return self._write_job(
                {
                    **job,
                    "checkpoint": {
                        "sequence": sequence,
                        "phase": phase,
                        "committed_at": instant_text(selected_now),
                    },
                    "progress": selected_progress,
                    "updated_at": instant_text(selected_now),
                }
            )

    def _finish_locked(
        self,
        job: Mapping[str, Any],
        *,
        status: str,
        now: datetime,
        progress: Mapping[str, int],
        error_class: str | None,
        error_code: str | None,
        network_used: bool,
        canonical_mutation: bool,
    ) -> dict[str, Any]:
        if status not in TERMINAL_JOB_STATUSES:
            raise SchedulerError("job must finish with a terminal status")
        if error_class is not None and error_class not in ERROR_CLASSES:
            raise SchedulerError("unsupported scheduler error class")
        if error_code is not None:
            validate_error(error_code, "error code")
        selected_progress = validate_progress(progress)
        attempts = [dict(item) for item in job["attempts"]]
        if attempts and attempts[-1]["outcome"] == "running":
            attempts[-1] = {
                **attempts[-1],
                "completed_at": instant_text(now),
                "outcome": "succeeded" if status == "succeeded" else "failed",
                "error_class": error_class,
                "error_code": error_code,
            }
        receipt_id = f"receipt_{str(job['id']).removeprefix('job_')}"
        receipt = self._write_receipt_once(
            {
                "schema_version": SCHEDULER_SCHEMA_VERSION,
                "id": receipt_id,
                "job_id": job["id"],
                "policy_id": job["policy_id"],
                "policy_revision": job["policy_revision"],
                "job_kind": job["job_kind"],
                "scope": dict(job["scope"]),
                "status": status,
                "attempts": int(job["attempt"]),
                "duration_ms": _attempt_duration_ms(attempts),
                "completed_at": instant_text(now),
                "progress": selected_progress,
                "error_class": error_class,
                "error_code": error_code,
                "network_used": bool(network_used),
                "canonical_mutation": bool(canonical_mutation),
                "automatic_deletion": False,
            }
        )
        return self._write_job(
            {
                **job,
                "status": status,
                "updated_at": instant_text(now),
                "retry_not_before": None,
                "lease": None,
                "progress": selected_progress,
                "attempts": attempts,
                "receipt_ref": f"state/scheduler/receipts/{receipt['id']}.json",
            }
        )

    def succeed(
        self,
        job_id: str,
        lease_token: str,
        *,
        progress: Mapping[str, int],
        network_used: bool = False,
        canonical_mutation: bool = False,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected_now = utc_instant(now)
        with self.hold():
            job = self.get_job(job_id)
            if job is None:
                raise SchedulerNotFoundError("scheduler job not found")
            self._owned(job, lease_token, selected_now)
            return self._finish_locked(
                job,
                status="succeeded",
                now=selected_now,
                progress=progress,
                error_class=None,
                error_code=None,
                network_used=network_used,
                canonical_mutation=canonical_mutation,
            )

    def fail(
        self,
        job_id: str,
        lease_token: str,
        *,
        error_class: str,
        error_code: str,
        progress: Mapping[str, int],
        network_used: bool = False,
        canonical_mutation: bool = False,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected_now = utc_instant(now)
        if error_class not in ERROR_CLASSES:
            raise SchedulerError("unsupported scheduler error class")
        selected_error = validate_error(error_code, "error code")
        selected_progress = validate_progress(progress)
        with self.hold():
            job = self.get_job(job_id)
            if job is None:
                raise SchedulerNotFoundError("scheduler job not found")
            self._owned(job, lease_token, selected_now)
            attempts = [dict(item) for item in job["attempts"]]
            if attempts and attempts[-1]["outcome"] == "running":
                attempts[-1] = {
                    **attempts[-1],
                    "completed_at": instant_text(selected_now),
                    "outcome": "retry" if error_class == "transient" else "failed",
                    "error_class": error_class,
                    "error_code": selected_error,
                }
            if (
                error_class == "transient"
                and int(job["attempt"]) < int(job["retry"]["max_attempts"])
            ):
                delay = retry_delay_seconds(job["retry"], int(job["attempt"]))
                return self._write_job(
                    {
                        **job,
                        "status": "retry_wait",
                        "updated_at": instant_text(selected_now),
                        "retry_not_before": instant_text(
                            selected_now + timedelta(seconds=delay)
                        ),
                        "lease": None,
                        "progress": selected_progress,
                        "attempts": attempts,
                    }
                )
            status = (
                "manual_intervention"
                if error_class == "manual_intervention"
                else "cancelled"
                if error_class == "cancelled"
                else "failed"
            )
            prepared = {**job, "attempts": attempts, "lease": None}
            return self._finish_locked(
                prepared,
                status=status,
                now=selected_now,
                progress=selected_progress,
                error_class=error_class,
                error_code=selected_error,
                network_used=network_used,
                canonical_mutation=canonical_mutation,
            )

    def cancel(
        self,
        job_id: str,
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected_now = utc_instant(now)
        with self.hold():
            job = self.get_job(job_id)
            if job is None:
                raise SchedulerNotFoundError("scheduler job not found")
            if job["status"] in TERMINAL_JOB_STATUSES:
                return job
            if job["status"] == "running":
                raise SchedulerConflictError("a running job must stop cooperatively")
            return self._finish_locked(
                job,
                status="cancelled",
                now=selected_now,
                progress=job["progress"],
                error_class="cancelled",
                error_code="cancelled_by_user",
                network_used=False,
                canonical_mutation=False,
            )

    def status(self) -> dict[str, Any]:
        policies = self.list_policies()
        jobs = self._all_jobs()
        receipts = self._all_receipts()
        policy_counts = Counter(str(item["state"]) for item in policies)
        job_counts = Counter(str(item["status"]) for item in jobs)
        next_due = sorted(
            str(item["next_due_at"])
            for item in policies
            if item.get("next_due_at") is not None and item["state"] == "enabled"
        )
        return {
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "policies": len(policies),
            "policy_states": {state: policy_counts[state] for state in POLICY_STATES},
            "jobs": len(jobs),
            "job_states": {state: job_counts[state] for state in JOB_STATUSES},
            "receipts": len(receipts),
            "next_due_at": next_due[0] if next_due else None,
            "executable_job_kinds": list(EXECUTABLE_JOB_KINDS),
            "deferred_job_kinds": [],
            "network_used": False,
            "automatic_deletion": False,
        }


class SchedulerCoordinator:
    """Evaluate durable policies and execute bounded, explicit local job kinds."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.journal = SchedulerStore(store)

    def recover(self, *, now: datetime | str | None = None) -> dict[str, int]:
        if not self.journal.root.exists():
            return self.journal.recover(now=now)
        with self._hold_lifecycle("scheduler-recovery"):
            return self.journal.recover(now=now)

    @contextmanager
    def _hold_lifecycle(self, purpose: str) -> Iterator[None]:
        from .instance_lifecycle import (
            InstanceLifecycleBusy,
            InstanceLifecycleError,
            InstanceLifecycleManager,
        )

        try:
            with InstanceLifecycleManager(self.store)._hold(purpose=purpose):
                yield
        except InstanceLifecycleBusy as exc:
            raise SchedulerBusyError("another Instance operation is active") from exc
        except InstanceLifecycleError as exc:
            raise SchedulerError("scheduler lifecycle lock is unavailable") from exc

    def create_policy(
        self,
        *,
        job_kind: str,
        scope: Mapping[str, str],
        state: str,
        schedule: Mapping[str, Any],
        retry: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._hold_lifecycle("scheduler-policy-create"):
            return self.journal.create_policy(
                job_kind=job_kind,
                scope=scope,
                state=state,
                schedule=schedule,
                retry=retry,
            )

    def update_policy(
        self,
        policy_id: str,
        *,
        state: str | None = None,
        schedule: Mapping[str, Any] | None = None,
        retry: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._hold_lifecycle("scheduler-policy-update"):
            return self.journal.update_policy(
                policy_id,
                state=state,
                schedule=schedule,
                retry=retry,
            )

    def run_now(
        self,
        policy_id: str,
        *,
        request_key: str | None = None,
    ) -> dict[str, Any]:
        with self._hold_lifecycle("scheduler-run-now"):
            return self.journal.run_now(policy_id, request_key=request_key)

    @staticmethod
    def _progress(*, processed: int = 0, skipped: int = 0, errors: int = 0) -> dict[str, int]:
        return {"processed": processed, "skipped": skipped, "errors": errors}

    def _execute(
        self,
        job: Mapping[str, Any],
    ) -> tuple[bool, dict[str, int], str, str, bool, bool]:
        if job["job_kind"] == "source.refresh":
            from .folder_source_model import FolderSourceError
            from .folder_sources import FolderSourceManager
            from .ingest import IngestionInputError

            try:
                result = FolderSourceManager(self.store).refresh(
                    str(job["scope"]["id"]),
                    scheduler_job_id=str(job["id"]),
                )
            except OSError:
                return (
                    False,
                    self._progress(errors=1),
                    "transient",
                    "local_io",
                    False,
                    False,
                )
            except (FolderSourceError, IngestionInputError):
                return (
                    False,
                    self._progress(errors=1),
                    "permanent",
                    "invalid_state",
                    False,
                    False,
                )
            progress = dict(result["progress"])
            network_used = bool(result["network_used"])
            canonical_mutation = bool(result["canonical_mutation"])
            if result["status"] != "failed":
                return True, progress, "", "", network_used, canonical_mutation
            transient = result.get("reason") in {
                "input_io_error",
                "input_missing",
                "input_unreadable",
            }
            return (
                False,
                progress,
                "transient" if transient else "permanent",
                "local_io" if transient else "source_refresh_failed",
                network_used,
                canonical_mutation,
            )
        if job["job_kind"] == "search.reindex":
            from .index import rebuild_search_index

            try:
                indexed = rebuild_search_index(self.store)
            except (OSError, sqlite3.Error):
                return (
                    False,
                    self._progress(errors=1),
                    "transient",
                    "local_io",
                    False,
                    False,
                )
            except (KeyError, TypeError, ValueError):
                return (
                    False,
                    self._progress(errors=1),
                    "permanent",
                    "invalid_state",
                    False,
                    False,
                )
            return True, self._progress(processed=indexed), "", "", False, False
        if job["job_kind"] == "maintenance.validate":
            from .instance_validation import inspect_instance

            report = inspect_instance(self.store.paths.root, deep=True)
            findings = len(report.get("errors", []))
            if report.get("status") != "valid":
                return (
                    False,
                    self._progress(processed=1, errors=findings or 1),
                    "permanent",
                    "instance_validation_failed",
                    False,
                    False,
                )
            return True, self._progress(processed=1), "", "", False, False
        return (
            False,
            self._progress(errors=1),
            "manual_intervention",
            "executor_unavailable",
            False,
            False,
        )

    def _run_one_locked(
        self,
        *,
        worker_id: str = "local-runtime",
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: datetime | str | None = None,
        live_clock: bool = False,
        job_id: str | None = None,
    ) -> dict[str, Any] | None:
        selected_now = datetime.now(UTC) if live_clock else utc_instant(now)
        job = self.journal.claim_next(
            worker_id=worker_id,
            allowed_kinds=EXECUTABLE_JOB_KINDS,
            job_id=job_id,
            lease_seconds=lease_seconds,
            now=selected_now,
        )
        if job is None:
            return None
        lease_token = str(job["lease"]["token"])
        stop_heartbeat = Event()
        heartbeat_thread = None
        if live_clock:
            interval = max(1, min(30, lease_seconds // 3))

            def maintain_lease() -> None:
                while not stop_heartbeat.wait(interval):
                    try:
                        self.journal.heartbeat(
                            str(job["id"]),
                            lease_token,
                            lease_seconds=lease_seconds,
                        )
                    except SchedulerBusyError:
                        continue
                    except SchedulerError:
                        return

            heartbeat_thread = Thread(
                target=maintain_lease,
                name="provelume-scheduler-heartbeat",
                daemon=True,
            )
            heartbeat_thread.start()
        try:
            checkpoint_now = None if live_clock else selected_now
            job = self.journal.checkpoint(
                str(job["id"]),
                lease_token,
                sequence=int(job["checkpoint"]["sequence"]) + 1,
                phase="prepared",
                progress=job["progress"],
                now=checkpoint_now,
            )
            job = self.journal.checkpoint(
                str(job["id"]),
                lease_token,
                sequence=int(job["checkpoint"]["sequence"]) + 1,
                phase="executing",
                progress=job["progress"],
                now=checkpoint_now,
            )
            (
                ok,
                attempt_progress,
                error_class,
                error_code,
                network_used,
                canonical_mutation,
            ) = self._execute(job)
            progress = {
                key: int(job["progress"][key]) + int(attempt_progress[key])
                for key in job["progress"]
            }
            if ok:
                job = self.journal.checkpoint(
                    str(job["id"]),
                    lease_token,
                    sequence=int(job["checkpoint"]["sequence"]) + 1,
                    phase="committed",
                    progress=progress,
                    now=(None if live_clock else selected_now),
                )
        finally:
            stop_heartbeat.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join()
        completed_at = max(selected_now, datetime.now(UTC)) if live_clock else selected_now
        if ok:
            return self.journal.succeed(
                str(job["id"]),
                lease_token,
                progress=progress,
                network_used=network_used,
                canonical_mutation=canonical_mutation,
                now=completed_at,
            )
        return self.journal.fail(
            str(job["id"]),
            lease_token,
            error_class=error_class,
            error_code=error_code,
            progress=progress,
            network_used=network_used,
            canonical_mutation=canonical_mutation,
            now=completed_at,
        )

    def run_one(
        self,
        *,
        worker_id: str = "local-runtime",
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: datetime | str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.journal.root.exists():
            return None
        with self._hold_lifecycle("scheduler-job-execution"):
            return self._run_one_locked(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now=now,
                live_clock=now is None,
                job_id=job_id,
            )

    def cycle(
        self,
        *,
        worker_id: str = "local-runtime",
        max_jobs: int = 1,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        if type(max_jobs) is not int or max_jobs < 1 or max_jobs > 100:
            raise SchedulerError("max_jobs must be between 1 and 100")
        selected_now = utc_instant(now)
        if not self.journal.root.exists():
            return {
                "schema_version": SCHEDULER_SCHEMA_VERSION,
                "evaluation": self.journal.evaluate(now=selected_now),
                "jobs": [],
                "network_used": False,
                "automatic_deletion": False,
            }
        with self._hold_lifecycle("scheduler-cycle"):
            evaluation = self.journal.evaluate(now=selected_now)
            completed = []
            for _ in range(max_jobs):
                result = self._run_one_locked(
                    worker_id=worker_id,
                    now=selected_now,
                    live_clock=now is None,
                )
                if result is None:
                    break
                completed.append(result)
        return {
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "evaluation": evaluation,
            "jobs": completed,
            "network_used": False,
            "automatic_deletion": False,
        }


def scheduler_state_findings(store: InstanceStore) -> list[dict[str, str]]:
    """Validate durable scheduler state without executing work or making a network request."""

    scheduler = SchedulerStore(store)
    if not scheduler.root.exists():
        return []
    findings: list[dict[str, str]] = []
    if scheduler.root.is_symlink() or not scheduler.root.is_dir():
        return [
            {
                "code": "scheduler_directory_invalid",
                "message": "scheduler state root is invalid",
                "path": "state/scheduler",
            }
        ]
    allowed_children = {"policies", "jobs", "receipts"}
    for child in sorted(scheduler.root.iterdir()):
        if child.name not in allowed_children:
            findings.append(
                {
                    "code": "scheduler_record_invalid",
                    "message": "scheduler state contains an unsupported entry",
                    "path": child.relative_to(store.paths.root).as_posix(),
                }
            )
    policies: dict[str, dict[str, Any]] = {}
    jobs: dict[str, dict[str, Any]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for kind, directory, validator in (
        ("policy", scheduler.policies, scheduler._policy),
        ("job", scheduler.jobs, validate_job_record),
        ("receipt", scheduler.receipts, validate_receipt_record),
    ):
        if not directory.exists():
            continue
        if not directory.is_dir() or directory.is_symlink():
            findings.append(
                {
                    "code": "scheduler_directory_invalid",
                    "message": f"scheduler {kind} directory is invalid",
                    "path": directory.relative_to(store.paths.root).as_posix(),
                }
            )
            continue
        selected = policies if kind == "policy" else jobs if kind == "job" else receipts
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(store.paths.root).as_posix()
            if path.suffix != ".json" or path.is_symlink() or not path.is_file():
                findings.append(
                    {
                        "code": "scheduler_record_invalid",
                        "message": f"scheduler {kind} record is not a regular file",
                        "path": relative,
                    }
                )
                continue
            try:
                record = validator(scheduler._read_json(path))
                if path.stem != record["id"]:
                    raise SchedulerError("scheduler filename does not match its record ID")
            except SchedulerError as exc:
                findings.append(
                    {
                        "code": "scheduler_record_invalid",
                        "message": str(exc),
                        "path": relative,
                    }
                )
                continue
            record_id = str(record["id"])
            if record_id in selected:
                findings.append(
                    {
                        "code": "scheduler_record_duplicate",
                        "message": f"scheduler {kind} record ID is duplicated",
                        "path": relative,
                    }
                )
                continue
            selected[record_id] = record
    for job in jobs.values():
        path = f"state/scheduler/jobs/{job['id']}.json"
        policy = policies.get(str(job["policy_id"]))
        if policy is None:
            findings.append(
                {
                    "code": "scheduler_policy_missing",
                    "message": "scheduler job references a missing policy",
                    "path": path,
                }
            )
        elif (
            job["job_kind"] != policy["job_kind"]
            or job["scope"] != policy["scope"]
            or int(job["policy_revision"]) > int(policy["revision"])
        ):
            findings.append(
                {
                    "code": "scheduler_policy_mismatch",
                    "message": "scheduler job does not match its policy identity",
                    "path": path,
                }
            )
        if job["receipt_ref"] is not None:
            receipt_id = Path(str(job["receipt_ref"])).stem
            receipt = receipts.get(receipt_id)
            if (
                receipt is None
                or not _receipt_matches_terminal_job(receipt, job)
            ):
                findings.append(
                    {
                        "code": "scheduler_receipt_missing",
                        "message": "terminal scheduler job receipt is missing or mismatched",
                        "path": path,
                    }
                )
    for receipt in receipts.values():
        job = jobs.get(str(receipt["job_id"]))
        if job is None:
            findings.append(
                {
                    "code": "scheduler_job_missing",
                    "message": "scheduler receipt references a missing job",
                    "path": f"state/scheduler/receipts/{receipt['id']}.json",
                }
            )
        elif (
            job["receipt_ref"]
            != f"state/scheduler/receipts/{receipt['id']}.json"
            or not _receipt_matches_terminal_job(receipt, job)
        ):
            findings.append(
                {
                    "code": "scheduler_job_receipt_mismatch",
                    "message": "scheduler receipt evidence does not match its terminal job",
                    "path": f"state/scheduler/receipts/{receipt['id']}.json",
                }
            )
    return findings


__all__ = [
    "SchedulerCoordinator",
    "SchedulerStore",
    "schedule_payload",
    "retry_payload",
    "scheduler_state_findings",
    "public_job_record",
]
