from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEDULER_SCHEMA_VERSION = 1
SCHEDULER_JOB_KINDS = (
    "source.refresh",
    "search.reindex",
    "search.reindex.incremental",
    "maintenance.library_rebuild",
    "maintenance.validate",
    "maintenance.original_assurance",
    "maintenance.duplicate_scan",
    "maintenance.source_reconcile",
    "maintenance.resource_snapshot",
)
EXECUTABLE_JOB_KINDS = SCHEDULER_JOB_KINDS
SOURCE_SCOPED_JOB_KINDS = frozenset(
    {"source.refresh", "maintenance.source_reconcile"}
)
POLICY_STATES = ("disabled", "enabled", "paused")
SCHEDULE_MODES = ("manual", "interval", "calendar")
MISSED_RUN_POLICIES = ("skip", "coalesce", "catch_up_one")
DST_POLICIES = ("earliest", "latest", "skip", "shift_forward")
JOB_STATUSES = (
    "queued",
    "running",
    "retry_wait",
    "succeeded",
    "failed",
    "manual_intervention",
    "cancelled",
)
TERMINAL_JOB_STATUSES = frozenset(
    {"succeeded", "failed", "manual_intervention", "cancelled"}
)
ERROR_CLASSES = ("transient", "permanent", "manual_intervention", "cancelled")
ERROR_CODES = (
    "cancelled_by_user",
    "committed_checkpoint_needs_review",
    "executor_unavailable",
    "instance_validation_failed",
    "insufficient_temporary_space",
    "invalid_state",
    "lease_clock_reversed",
    "lease_expired",
    "lease_recovery_exhausted",
    "local_io",
    "maintenance_action_failed",
    "reindex_state_invalid",
    "resource_statistics_changed",
    "resource_statistics_failed",
    "resource_statistics_limit",
    "source_refresh_failed",
    "source_reconciliation_failed",
    "source_reauthorization_required",
    "source_reconciliation_superseded",
)
RECOVERY_STATES = ("none", "resumable", "restart_only", "manual_intervention")
RUN_REASONS = ("manual", "scheduled", "coalesced", "catch_up")
PROGRESS_KEYS = ("processed", "skipped", "errors")

MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 365 * 24 * 60 * 60
MAX_JITTER_SECONDS = 24 * 60 * 60
MAX_RETRY_ATTEMPTS = 8
MAX_RETRY_SECONDS = 7 * 24 * 60 * 60
MAX_LEASE_SECONDS = 24 * 60 * 60

_POLICY_ID = re.compile(r"policy_[0-9a-f]{32}\Z")
_JOB_ID = re.compile(r"job_[0-9a-f]{32}\Z")
_RECEIPT_ID = re.compile(r"receipt_[0-9a-f]{32}\Z")
_LEASE_TOKEN = re.compile(r"lease_[0-9a-f]{32}\Z")
_INSTANCE_ID = re.compile(r"inst_[0-9a-f]{32}\Z")
_SOURCE_ID = re.compile(r"(?:src|source)_[A-Za-z0-9_.:-]{1,200}\Z")
_WORKER_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")


class SchedulerError(ValueError):
    pass


class SchedulerBusyError(RuntimeError):
    pass


class SchedulerConflictError(SchedulerError):
    pass


class SchedulerNotFoundError(SchedulerError):
    pass


class SchedulerLeaseError(SchedulerError):
    pass


def utc_instant(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        try:
            selected = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SchedulerError("invalid scheduler timestamp") from exc
    elif isinstance(value, datetime):
        selected = value
    else:
        raise SchedulerError("invalid scheduler timestamp")
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise SchedulerError("scheduler timestamps must include an offset")
    return selected.astimezone(UTC)


def instant_text(value: datetime | str | None = None) -> str:
    return utc_instant(value).isoformat()


def _integer(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise SchedulerError(f"{label} must be between {minimum} and {maximum}")
    return value


def _clock(value: Any, label: str) -> str:
    if not isinstance(value, str) or _CLOCK.fullmatch(value) is None:
        raise SchedulerError(f"{label} must use HH:MM")
    return value


def _timezone(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise SchedulerError("an explicit IANA timezone is required")
    selected = value.strip()
    try:
        ZoneInfo(selected)
    except ZoneInfoNotFoundError as exc:
        raise SchedulerError("timezone is not available in the IANA database") from exc
    return selected


def normalise_scope(
    value: Any,
    *,
    instance_id: str,
    known_source_ids: set[str],
    job_kind: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"kind", "id"}:
        raise SchedulerError("scheduler scope must contain exactly kind and id")
    kind = value.get("kind")
    selected_id = value.get("id")
    if kind == "instance":
        if selected_id != instance_id or _INSTANCE_ID.fullmatch(str(selected_id)) is None:
            raise SchedulerError("scheduler Instance scope does not match this Instance")
        if job_kind in SOURCE_SCOPED_JOB_KINDS:
            raise SchedulerError(f"{job_kind} requires an exact Source scope")
    elif kind == "source":
        if (
            not isinstance(selected_id, str)
            or _SOURCE_ID.fullmatch(selected_id) is None
            or selected_id not in known_source_ids
        ):
            raise SchedulerError("scheduler Source scope is not available")
        if job_kind not in SOURCE_SCOPED_JOB_KINDS:
            raise SchedulerError("this job kind requires Instance scope")
    else:
        raise SchedulerError("scheduler scope kind must be instance or source")
    return {"kind": str(kind), "id": str(selected_id)}


def normalise_schedule(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SchedulerError("schedule must be an object")
    expected = {
        "mode",
        "timezone",
        "interval_seconds",
        "calendar_time",
        "weekdays",
        "dst_policy",
        "quiet_window",
        "jitter_seconds",
        "missed_run_policy",
    }
    if set(value) != expected:
        raise SchedulerError("schedule fields are incomplete or unsupported")
    mode = value.get("mode")
    if mode not in SCHEDULE_MODES:
        raise SchedulerError("unsupported scheduler mode")
    timezone_name = _timezone(value.get("timezone"))
    interval = value.get("interval_seconds")
    calendar_time = value.get("calendar_time")
    weekdays = value.get("weekdays")
    if mode == "interval":
        interval = _integer(
            interval,
            "interval_seconds",
            minimum=MIN_INTERVAL_SECONDS,
            maximum=MAX_INTERVAL_SECONDS,
        )
        if calendar_time is not None or weekdays != []:
            raise SchedulerError("interval schedules cannot contain calendar fields")
    elif mode == "calendar":
        if interval is not None:
            raise SchedulerError("calendar schedules cannot contain an interval")
        calendar_time = _clock(calendar_time, "calendar_time")
        if (
            not isinstance(weekdays, list)
            or not weekdays
            or any(type(day) is not int or day < 0 or day > 6 for day in weekdays)
            or weekdays != sorted(set(weekdays))
        ):
            raise SchedulerError("calendar weekdays must be a unique sorted subset of 0..6")
    else:
        if interval is not None or calendar_time is not None or weekdays != []:
            raise SchedulerError("manual schedules cannot contain timed fields")

    dst_policy = value.get("dst_policy")
    if dst_policy not in DST_POLICIES:
        raise SchedulerError("unsupported DST policy")
    missed = value.get("missed_run_policy")
    if missed not in MISSED_RUN_POLICIES:
        raise SchedulerError("unsupported missed-run policy")
    jitter = _integer(
        value.get("jitter_seconds"),
        "jitter_seconds",
        minimum=0,
        maximum=MAX_JITTER_SECONDS,
    )
    quiet = value.get("quiet_window")
    if quiet is not None:
        if not isinstance(quiet, Mapping) or set(quiet) != {"start", "end"}:
            raise SchedulerError("quiet_window must contain exactly start and end")
        start = _clock(quiet.get("start"), "quiet_window.start")
        end = _clock(quiet.get("end"), "quiet_window.end")
        if start == end:
            raise SchedulerError("quiet window cannot cover the full day")
        quiet = {"start": start, "end": end}
    return {
        "mode": mode,
        "timezone": timezone_name,
        "interval_seconds": interval,
        "calendar_time": calendar_time,
        "weekdays": list(weekdays),
        "dst_policy": dst_policy,
        "quiet_window": quiet,
        "jitter_seconds": jitter,
        "missed_run_policy": missed,
    }


def normalise_retry(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {
        "max_attempts",
        "base_seconds",
        "max_seconds",
    }:
        raise SchedulerError("retry fields are incomplete or unsupported")
    attempts = _integer(
        value.get("max_attempts"),
        "max_attempts",
        minimum=1,
        maximum=MAX_RETRY_ATTEMPTS,
    )
    base = _integer(
        value.get("base_seconds"),
        "base_seconds",
        minimum=1,
        maximum=MAX_RETRY_SECONDS,
    )
    maximum = _integer(
        value.get("max_seconds"),
        "max_seconds",
        minimum=base,
        maximum=MAX_RETRY_SECONDS,
    )
    return {"max_attempts": attempts, "base_seconds": base, "max_seconds": maximum}


def schedule_payload(
    *,
    mode: str,
    timezone: str,
    interval_seconds: int | None = None,
    calendar_time: str | None = None,
    weekdays: list[int] | None = None,
    dst_policy: str = "earliest",
    quiet_start: str | None = None,
    quiet_end: str | None = None,
    jitter_seconds: int = 0,
    missed_run_policy: str = "coalesce",
) -> dict[str, Any]:
    quiet = None
    if quiet_start is not None or quiet_end is not None:
        quiet = {"start": quiet_start, "end": quiet_end}
    return normalise_schedule(
        {
            "mode": mode,
            "timezone": timezone,
            "interval_seconds": interval_seconds,
            "calendar_time": calendar_time,
            "weekdays": list(weekdays or []),
            "dst_policy": dst_policy,
            "quiet_window": quiet,
            "jitter_seconds": jitter_seconds,
            "missed_run_policy": missed_run_policy,
        }
    )


def retry_payload(
    *,
    max_attempts: int = 3,
    base_seconds: int = 60,
    max_seconds: int = 900,
) -> dict[str, int]:
    return normalise_retry(
        {
            "max_attempts": max_attempts,
            "base_seconds": base_seconds,
            "max_seconds": max_seconds,
        }
    )


def _valid_local_candidates(naive: datetime, zone: ZoneInfo) -> list[datetime]:
    candidates: list[datetime] = []
    seen: set[datetime] = set()
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        instant = local.astimezone(UTC)
        round_trip = instant.astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive and instant not in seen:
            candidates.append(instant)
            seen.add(instant)
    return sorted(candidates)


def resolve_local_time(
    local_date: date,
    clock: str,
    *,
    timezone: str,
    dst_policy: str,
) -> datetime | None:
    selected_time = time.fromisoformat(_clock(clock, "calendar_time"))
    naive = datetime.combine(local_date, selected_time)
    zone = ZoneInfo(_timezone(timezone))
    candidates = _valid_local_candidates(naive, zone)
    if candidates:
        return candidates[-1] if dst_policy == "latest" else candidates[0]
    if dst_policy == "skip":
        return None
    if dst_policy != "shift_forward":
        return None
    for minutes in range(1, 181):
        shifted = naive + timedelta(minutes=minutes)
        candidates = _valid_local_candidates(shifted, zone)
        if candidates:
            return candidates[0]
    raise SchedulerError("DST gap exceeds the bounded three-hour recovery window")


def next_nominal_after(after: datetime | str, schedule: Mapping[str, Any]) -> datetime | None:
    selected = utc_instant(after)
    normalised = normalise_schedule(schedule)
    mode = normalised["mode"]
    if mode == "manual":
        return None
    if mode == "interval":
        return selected + timedelta(seconds=int(normalised["interval_seconds"]))
    zone = ZoneInfo(str(normalised["timezone"]))
    local_date = selected.astimezone(zone).date()
    weekdays = set(normalised["weekdays"])
    for offset in range(0, 371):
        candidate_date = local_date + timedelta(days=offset)
        if candidate_date.weekday() not in weekdays:
            continue
        candidate = resolve_local_time(
            candidate_date,
            str(normalised["calendar_time"]),
            timezone=str(normalised["timezone"]),
            dst_policy=str(normalised["dst_policy"]),
        )
        if candidate is not None and candidate > selected:
            return candidate
    raise SchedulerError("calendar schedule has no bounded next occurrence")


def next_nominal_from_previous(
    previous: datetime | str,
    schedule: Mapping[str, Any],
) -> datetime | None:
    normalised = normalise_schedule(schedule)
    if normalised["mode"] == "interval":
        return utc_instant(previous) + timedelta(
            seconds=int(normalised["interval_seconds"])
        )
    return next_nominal_after(previous, normalised)


def _jitter_seconds(
    *,
    policy_id: str,
    revision: int,
    maximum: int,
) -> int:
    if maximum <= 0:
        return 0
    # A stable policy-revision offset spreads otherwise coincident policies while
    # preserving the order of their occurrences. Independently jittering each
    # nominal instant can invert adjacent deadlines when jitter exceeds cadence.
    seed = f"{policy_id}:{revision}".encode()
    return int.from_bytes(hashlib.sha256(seed).digest()[:8], "big") % (maximum + 1)


def _quiet_end(
    instant: datetime,
    *,
    schedule: Mapping[str, Any],
) -> datetime:
    quiet = schedule.get("quiet_window")
    if quiet is None:
        return instant
    zone = ZoneInfo(str(schedule["timezone"]))
    local = instant.astimezone(zone)
    start = time.fromisoformat(str(quiet["start"]))
    end = time.fromisoformat(str(quiet["end"]))
    clock = local.timetz().replace(tzinfo=None)
    crosses_midnight = start > end
    inside = (clock >= start or clock < end) if crosses_midnight else start <= clock < end
    if not inside:
        return instant
    end_date = local.date()
    if crosses_midnight and clock >= start:
        end_date += timedelta(days=1)
    resolved = resolve_local_time(
        end_date,
        str(quiet["end"]),
        timezone=str(schedule["timezone"]),
        dst_policy="shift_forward",
    )
    if resolved is None:
        raise SchedulerError("quiet-window end could not be resolved")
    return max(instant, resolved)


def eligible_instant(
    nominal: datetime | str,
    *,
    policy_id: str,
    revision: int,
    schedule: Mapping[str, Any],
) -> datetime:
    normalised = normalise_schedule(schedule)
    selected = utc_instant(nominal)
    selected += timedelta(
        seconds=_jitter_seconds(
            policy_id=policy_id,
            revision=revision,
            maximum=int(normalised["jitter_seconds"]),
        )
    )
    return _quiet_end(selected, schedule=normalised)


def idempotency_digest(*parts: str) -> str:
    if not parts or any(not isinstance(part, str) or not part for part in parts):
        raise SchedulerError("idempotency identity is incomplete")
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def retry_delay_seconds(retry: Mapping[str, Any], attempt: int) -> int:
    normalised = normalise_retry(retry)
    selected_attempt = _integer(
        attempt,
        "attempt",
        minimum=1,
        maximum=MAX_RETRY_ATTEMPTS,
    )
    return min(
        int(normalised["max_seconds"]),
        int(normalised["base_seconds"]) * (2 ** (selected_attempt - 1)),
    )


def validate_policy_record(
    value: Any,
    *,
    instance_id: str,
    known_source_ids: set[str],
) -> dict[str, Any]:
    expected = {
        "schema_version",
        "id",
        "revision",
        "job_kind",
        "scope",
        "state",
        "schedule",
        "retry",
        "created_at",
        "updated_at",
        "last_evaluated_at",
        "next_nominal_at",
        "next_due_at",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SchedulerError("scheduler policy fields are incomplete or unsupported")
    policy_id = value.get("id")
    job_kind = value.get("job_kind")
    state = value.get("state")
    if (
        value.get("schema_version") != SCHEDULER_SCHEMA_VERSION
        or not isinstance(policy_id, str)
        or _POLICY_ID.fullmatch(policy_id) is None
        or job_kind not in SCHEDULER_JOB_KINDS
        or state not in POLICY_STATES
    ):
        raise SchedulerError("scheduler policy identity is invalid")
    revision = _integer(value.get("revision"), "revision", minimum=1, maximum=2**31 - 1)
    scope = normalise_scope(
        value.get("scope"),
        instance_id=instance_id,
        known_source_ids=known_source_ids,
        job_kind=str(job_kind),
    )
    schedule = normalise_schedule(value.get("schedule"))
    retry = normalise_retry(value.get("retry"))
    created = instant_text(value.get("created_at"))
    updated = instant_text(value.get("updated_at"))
    last = value.get("last_evaluated_at")
    nominal = value.get("next_nominal_at")
    due = value.get("next_due_at")
    last = instant_text(last) if last is not None else None
    nominal = instant_text(nominal) if nominal is not None else None
    due = instant_text(due) if due is not None else None
    if (nominal is None) != (due is None):
        raise SchedulerError("scheduler next occurrence is incomplete")
    if schedule["mode"] == "manual" and nominal is not None:
        raise SchedulerError("manual scheduler policy cannot have a next occurrence")
    if state != "enabled" and nominal is not None:
        raise SchedulerError("inactive scheduler policy cannot have a next occurrence")
    if state == "enabled" and schedule["mode"] != "manual" and nominal is None:
        raise SchedulerError("enabled timed policy requires a next occurrence")
    return {
        "schema_version": SCHEDULER_SCHEMA_VERSION,
        "id": policy_id,
        "revision": revision,
        "job_kind": job_kind,
        "scope": scope,
        "state": state,
        "schedule": schedule,
        "retry": retry,
        "created_at": created,
        "updated_at": updated,
        "last_evaluated_at": last,
        "next_nominal_at": nominal,
        "next_due_at": due,
    }


def validate_worker_id(value: Any) -> str:
    if not isinstance(value, str) or _WORKER_ID.fullmatch(value) is None:
        raise SchedulerError(
            "worker ID must use lowercase letters, digits, dot, dash or underscore"
        )
    return value


def validate_error(value: Any, label: str) -> str:
    if not isinstance(value, str) or value not in ERROR_CODES:
        raise SchedulerError(f"invalid {label}")
    return value


def validate_progress(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(PROGRESS_KEYS):
        raise SchedulerError("job progress fields are incomplete or unsupported")
    return {
        key: _integer(value.get(key), key, minimum=0, maximum=2**63 - 1)
        for key in PROGRESS_KEYS
    }


def _record_scope(value: Any, *, job_kind: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"kind", "id"}:
        raise SchedulerError("scheduler record scope is invalid")
    kind = value.get("kind")
    selected_id = value.get("id")
    if (
        kind == "instance"
        and isinstance(selected_id, str)
        and _INSTANCE_ID.fullmatch(selected_id) is not None
        and job_kind not in SOURCE_SCOPED_JOB_KINDS
    ):
        return {"kind": kind, "id": selected_id}
    if (
        kind == "source"
        and isinstance(selected_id, str)
        and _SOURCE_ID.fullmatch(selected_id) is not None
        and job_kind in SOURCE_SCOPED_JOB_KINDS
    ):
        return {"kind": kind, "id": selected_id}
    raise SchedulerError("scheduler record scope does not match its job kind")


def validate_job_record(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "id",
        "policy_id",
        "policy_revision",
        "job_kind",
        "scope",
        "idempotency_key",
        "reason",
        "scheduled_for",
        "eligible_at",
        "created_at",
        "updated_at",
        "status",
        "attempt",
        "retry",
        "retry_not_before",
        "lease",
        "checkpoint",
        "progress",
        "recovery_state",
        "recovery_count",
        "attempts",
        "receipt_ref",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SchedulerError("scheduler job fields are incomplete or unsupported")
    job_id = value.get("id")
    policy_id = value.get("policy_id")
    job_kind = value.get("job_kind")
    status = value.get("status")
    reason = value.get("reason")
    if (
        value.get("schema_version") != SCHEDULER_SCHEMA_VERSION
        or not isinstance(job_id, str)
        or _JOB_ID.fullmatch(job_id) is None
        or not isinstance(policy_id, str)
        or _POLICY_ID.fullmatch(policy_id) is None
        or job_kind not in SCHEDULER_JOB_KINDS
        or status not in JOB_STATUSES
        or reason not in RUN_REASONS
        or not isinstance(value.get("idempotency_key"), str)
        or _SHA256.fullmatch(str(value.get("idempotency_key"))) is None
    ):
        raise SchedulerError("scheduler job identity is invalid")
    scope = _record_scope(value.get("scope"), job_kind=str(job_kind))
    attempt = _integer(
        value.get("attempt"),
        "attempt",
        minimum=0,
        maximum=MAX_RETRY_ATTEMPTS,
    )
    policy_revision = _integer(
        value.get("policy_revision"),
        "policy_revision",
        minimum=1,
        maximum=2**31 - 1,
    )
    retry = normalise_retry(value.get("retry"))
    for label in ("scheduled_for", "eligible_at", "created_at", "updated_at"):
        instant_text(value.get(label))
    retry_not_before = value.get("retry_not_before")
    if retry_not_before is not None:
        retry_not_before = instant_text(retry_not_before)
    if status == "retry_wait" and retry_not_before is None:
        raise SchedulerError("retry-wait job must have a retry instant")
    if status != "retry_wait" and retry_not_before is not None:
        raise SchedulerError("only retry-wait jobs may have a retry instant")
    lease = value.get("lease")
    normalised_lease = None
    if lease is not None:
        if not isinstance(lease, Mapping) or set(lease) != {
            "token",
            "worker_id",
            "acquired_at",
            "heartbeat_at",
            "expires_at",
        }:
            raise SchedulerError("job lease fields are incomplete or unsupported")
        if (
            not isinstance(lease.get("token"), str)
            or _LEASE_TOKEN.fullmatch(str(lease.get("token"))) is None
        ):
            raise SchedulerError("job lease token is invalid")
        worker_id = validate_worker_id(lease.get("worker_id"))
        normalised_lease = {
            "token": lease["token"],
            "worker_id": worker_id,
            "acquired_at": instant_text(lease.get("acquired_at")),
            "heartbeat_at": instant_text(lease.get("heartbeat_at")),
            "expires_at": instant_text(lease.get("expires_at")),
        }
    if status == "running" and lease is None:
        raise SchedulerError("running job must have a lease")
    if status != "running" and lease is not None:
        raise SchedulerError("only running jobs may retain a lease")
    checkpoint = value.get("checkpoint")
    if not isinstance(checkpoint, Mapping) or set(checkpoint) != {
        "sequence",
        "phase",
        "committed_at",
    }:
        raise SchedulerError("job checkpoint fields are incomplete or unsupported")
    checkpoint_sequence = _integer(
        checkpoint.get("sequence"),
        "checkpoint sequence",
        minimum=0,
        maximum=2**31 - 1,
    )
    checkpoint_phase = checkpoint.get("phase")
    if checkpoint_phase not in {"none", "prepared", "executing", "committed"}:
        raise SchedulerError("job checkpoint phase is invalid")
    committed_at = checkpoint.get("committed_at")
    if committed_at is not None:
        committed_at = instant_text(committed_at)
    if checkpoint_phase == "none" and (checkpoint_sequence != 0 or committed_at is not None):
        raise SchedulerError("empty job checkpoint is inconsistent")
    if checkpoint_phase != "none" and (checkpoint_sequence == 0 or committed_at is None):
        raise SchedulerError("job checkpoint evidence is incomplete")
    progress = validate_progress(value.get("progress"))
    if value.get("recovery_state") not in RECOVERY_STATES:
        raise SchedulerError("job recovery state is invalid")
    recovery_count = _integer(
        value.get("recovery_count"),
        "recovery_count",
        minimum=0,
        maximum=2**31 - 1,
    )
    attempts = value.get("attempts")
    if (
        not isinstance(attempts, list)
        or len(attempts) > MAX_RETRY_ATTEMPTS
        or len(attempts) != attempt
    ):
        raise SchedulerError("job attempt history is invalid")
    normalised_attempts = []
    for expected_attempt, row in enumerate(attempts, start=1):
        if not isinstance(row, Mapping) or set(row) != {
            "attempt",
            "started_at",
            "completed_at",
            "outcome",
            "error_class",
            "error_code",
        }:
            raise SchedulerError("job attempt fields are incomplete or unsupported")
        selected_attempt = _integer(
            row.get("attempt"),
            "attempt",
            minimum=1,
            maximum=MAX_RETRY_ATTEMPTS,
        )
        if selected_attempt != expected_attempt:
            raise SchedulerError("job attempts must be consecutive")
        started_at = instant_text(row.get("started_at"))
        completed_at = row.get("completed_at")
        if completed_at is not None:
            completed_at = instant_text(completed_at)
        if row.get("outcome") not in {"running", "succeeded", "retry", "failed"}:
            raise SchedulerError("job attempt outcome is invalid")
        error_class = row.get("error_class")
        error_code = row.get("error_code")
        if error_class is not None and error_class not in ERROR_CLASSES:
            raise SchedulerError("job attempt error class is invalid")
        if error_code is not None:
            validate_error(error_code, "error code")
        outcome = str(row.get("outcome"))
        if outcome == "running" and (
            completed_at is not None or error_class is not None or error_code is not None
        ):
            raise SchedulerError("running job attempt has terminal evidence")
        if outcome != "running" and completed_at is None:
            raise SchedulerError("completed job attempt has no completion instant")
        if outcome in {"retry", "failed"} and (
            error_class is None or error_code is None
        ):
            raise SchedulerError("failed job attempt has no closed error")
        if outcome == "retry" and error_class != "transient":
            raise SchedulerError("retry attempt must have a transient error")
        if outcome == "succeeded" and (error_class is not None or error_code is not None):
            raise SchedulerError("successful job attempt cannot contain an error")
        normalised_attempts.append(
            {
                "attempt": selected_attempt,
                "started_at": started_at,
                "completed_at": completed_at,
                "outcome": outcome,
                "error_class": error_class,
                "error_code": error_code,
            }
        )
    if status == "running" and (
        not normalised_attempts or normalised_attempts[-1]["outcome"] != "running"
    ):
        raise SchedulerError("running job has no running attempt")
    if status != "running" and any(
        row["outcome"] == "running" for row in normalised_attempts
    ):
        raise SchedulerError("non-running job retains a running attempt")
    if status == "retry_wait" and normalised_attempts[-1]["outcome"] != "retry":
        raise SchedulerError("retry-wait job has inconsistent attempt evidence")
    if status == "queued" and normalised_attempts and normalised_attempts[-1][
        "outcome"
    ] != "retry":
        raise SchedulerError("recovered queued job has inconsistent attempt evidence")
    if status in TERMINAL_JOB_STATUSES and normalised_attempts:
        expected_outcomes = (
            {"succeeded"}
            if status == "succeeded"
            else {"failed", "retry"}
            if status == "cancelled"
            else {"failed"}
        )
        if normalised_attempts[-1]["outcome"] not in expected_outcomes:
            raise SchedulerError("terminal job has inconsistent attempt evidence")
    receipt_ref = value.get("receipt_ref")
    expected_receipt_ref = (
        f"state/scheduler/receipts/receipt_{str(job_id).removeprefix('job_')}.json"
    )
    if receipt_ref is not None and receipt_ref != expected_receipt_ref:
        raise SchedulerError("job receipt reference is invalid")
    if status in TERMINAL_JOB_STATUSES and receipt_ref is None:
        raise SchedulerError("terminal job must reference an immutable receipt")
    if status not in TERMINAL_JOB_STATUSES and receipt_ref is not None:
        raise SchedulerError("non-terminal job cannot reference a receipt")
    return {
        "schema_version": SCHEDULER_SCHEMA_VERSION,
        "id": job_id,
        "policy_id": policy_id,
        "policy_revision": policy_revision,
        "job_kind": job_kind,
        "scope": scope,
        "idempotency_key": value["idempotency_key"],
        "reason": reason,
        "scheduled_for": instant_text(value["scheduled_for"]),
        "eligible_at": instant_text(value["eligible_at"]),
        "created_at": instant_text(value["created_at"]),
        "updated_at": instant_text(value["updated_at"]),
        "status": status,
        "attempt": attempt,
        "retry": retry,
        "retry_not_before": retry_not_before,
        "lease": normalised_lease,
        "checkpoint": {
            "sequence": checkpoint_sequence,
            "phase": checkpoint_phase,
            "committed_at": committed_at,
        },
        "progress": progress,
        "recovery_state": value["recovery_state"],
        "recovery_count": recovery_count,
        "attempts": normalised_attempts,
        "receipt_ref": receipt_ref,
    }


def validate_receipt_record(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "id",
        "job_id",
        "policy_id",
        "policy_revision",
        "job_kind",
        "scope",
        "status",
        "attempts",
        "duration_ms",
        "completed_at",
        "progress",
        "error_class",
        "error_code",
        "network_used",
        "canonical_mutation",
        "automatic_deletion",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SchedulerError("scheduler receipt fields are incomplete or unsupported")
    receipt_id = value.get("id")
    job_id = value.get("job_id")
    policy_id = value.get("policy_id")
    if (
        value.get("schema_version") != SCHEDULER_SCHEMA_VERSION
        or not isinstance(receipt_id, str)
        or _RECEIPT_ID.fullmatch(receipt_id) is None
        or not isinstance(job_id, str)
        or _JOB_ID.fullmatch(job_id) is None
        or not isinstance(policy_id, str)
        or _POLICY_ID.fullmatch(policy_id) is None
        or value.get("job_kind") not in SCHEDULER_JOB_KINDS
        or value.get("status") not in TERMINAL_JOB_STATUSES
    ):
        raise SchedulerError("scheduler receipt identity is invalid")
    if receipt_id != f"receipt_{str(job_id).removeprefix('job_')}":
        raise SchedulerError("scheduler receipt ID does not match its job")
    job_kind = str(value.get("job_kind"))
    scope = _record_scope(value.get("scope"), job_kind=job_kind)
    policy_revision = _integer(
        value.get("policy_revision"),
        "policy_revision",
        minimum=1,
        maximum=2**31 - 1,
    )
    attempts = _integer(
        value.get("attempts"),
        "attempts",
        minimum=0,
        maximum=MAX_RETRY_ATTEMPTS,
    )
    duration_ms = _integer(
        value.get("duration_ms"),
        "duration_ms",
        minimum=0,
        maximum=2**63 - 1,
    )
    completed_at = instant_text(value.get("completed_at"))
    progress = validate_progress(value.get("progress"))
    error_class = value.get("error_class")
    error_code = value.get("error_code")
    if error_class is not None and error_class not in ERROR_CLASSES:
        raise SchedulerError("scheduler receipt error class is invalid")
    if error_code is not None:
        validate_error(error_code, "error code")
    status = str(value.get("status"))
    if status == "succeeded" and (error_class is not None or error_code is not None):
        raise SchedulerError("successful scheduler receipt cannot contain an error")
    if status != "succeeded" and (error_class is None or error_code is None):
        raise SchedulerError("unsuccessful scheduler receipt requires a closed error")
    if status == "cancelled" and (
        error_class != "cancelled" or error_code != "cancelled_by_user"
    ):
        raise SchedulerError("cancelled scheduler receipt has inconsistent error evidence")
    if status == "manual_intervention" and error_class != "manual_intervention":
        raise SchedulerError("manual-intervention receipt has inconsistent error evidence")
    if status == "failed" and error_class not in {"transient", "permanent"}:
        raise SchedulerError("failed scheduler receipt has inconsistent error evidence")
    if type(value.get("network_used")) is not bool:
        raise SchedulerError("scheduler receipt network flag is invalid")
    if type(value.get("canonical_mutation")) is not bool:
        raise SchedulerError("scheduler receipt canonical-mutation flag is invalid")
    if value.get("automatic_deletion") is not False:
        raise SchedulerError("scheduler receipts cannot authorize automatic deletion")
    return {
        "schema_version": SCHEDULER_SCHEMA_VERSION,
        "id": receipt_id,
        "job_id": job_id,
        "policy_id": policy_id,
        "policy_revision": policy_revision,
        "job_kind": job_kind,
        "scope": scope,
        "status": status,
        "attempts": attempts,
        "duration_ms": duration_ms,
        "completed_at": completed_at,
        "progress": progress,
        "error_class": error_class,
        "error_code": error_code,
        "network_used": value["network_used"],
        "canonical_mutation": value["canonical_mutation"],
        "automatic_deletion": False,
    }


def record_identifier(value: str, kind: str) -> bool:
    patterns = {"policy": _POLICY_ID, "job": _JOB_ID, "receipt": _RECEIPT_ID}
    pattern = patterns.get(kind)
    return pattern is not None and pattern.fullmatch(value) is not None
