"""AI producer for SchedulerCoordinator; no independent queue or worker loop."""

from __future__ import annotations

import copy
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import timedelta

from .ai_contract import digest
from .ai_job_contract import (
    AI_JOB_KIND,
    Budget,
    Quote,
    budget_record,
    check,
    fingerprint,
    integer,
    totals,
)
from .ai_provider import CallInputs, Failure, ProviderError, Transmission
from .scheduler_control import ACTIVE_STATUSES
from .scheduler_model import (
    TERMINAL_JOB_STATUSES,
    SchedulerBusyError,
    SchedulerError,
    idempotency_digest,
    instant_text,
    retry_delay_seconds,
    retry_payload,
    schedule_payload,
    utc_instant,
)

RETRYABLE = {Failure.DNS, Failure.CONNECTION, Failure.RATE_LIMIT}


def recover_ai_locked(journal, job, now):
    """Called under the original journal lock, before ordinary lease recovery."""
    if job["job_kind"] != AI_JOB_KIND:
        return False
    ai = job["ai"]
    if job["status"] in TERMINAL_JOB_STATUSES:
        return True
    if ai["terminal"] is not None:
        finish_ai_locked(journal, job, now)
        return True
    lease = job["lease"]
    if lease and (
        utc_instant(lease["expires_at"]) <= now or utc_instant(lease["heartbeat_at"]) > now
    ):
        row = ai["attempts"][-1]
        if row["phase"] == "reserved":
            row.update(phase="released", quiescent=True, units=0, micros=0, usage_source="NOT_SENT")
            ai.update(terminal="failed", blocked="ai_lease_expired_before_dispatch")
        else:
            row.update(phase="uncertain", quiescent=False)
            ai.update(terminal="uncertain", blocked="ai_outcome_uncertain")
        job["recovery_count"] += 1
        job["recovery_state"] = "manual_intervention"
        journal._write_job(job)
        finish_ai_locked(journal, job, now)
        return True
    # Persisted backoff never becomes immediately due on a backward clock jump.
    if job["status"] == "retry_wait":
        if utc_instant(job["retry_not_before"]) <= now:
            job.update(status="queued", retry_not_before=None, updated_at=instant_text(now))
            journal._write_job(job)
        return True
    return True


def finish_ai_locked(journal, job, now):
    intent = job["ai"]["terminal"]
    status = "manual_intervention" if intent == "uncertain" else intent
    error_class = {
        "succeeded": None,
        "failed": "permanent",
        "cancelled": "cancelled",
        "uncertain": "manual_intervention",
    }[intent]
    error_code = {
        "succeeded": None,
        "failed": "ai_execution_blocked",
        "cancelled": "cancelled_by_user",
        "uncertain": "ai_outcome_uncertain",
    }[intent]
    # Recover a receipt written before the terminal job projection without changing its time.
    receipt = journal.get_receipt("receipt_" + job["id"].removeprefix("job_"))
    if receipt:
        now = utc_instant(receipt["completed_at"])
    return journal._finish_locked(
        job,
        status=status,
        now=now,
        progress={
            "processed": int(intent == "succeeded"),
            "skipped": 0,
            "errors": int(intent in {"failed", "uncertain"}),
        },
        error_class=error_class,
        error_code=error_code,
        network_used=job["control"]["network_used"],
        canonical_mutation=False,
    )


class AiJobs:
    """Host binds live authority and approved adapters; no persisted execution grant.

    `current(ref, route)` must reread authoritative source/version, policy, consent,
    profiles and qualification. All host policy changes use `change_authority`.
    This internal dependency is never taken from a request, document or job record.
    """

    def __init__(self, coordinator, *, current=None, adapters=None, quotes=None, fault=None):
        self.coordinator = coordinator
        self.journal = coordinator.journal
        self.current = current
        self.adapters = adapters or {}
        self.quotes = quotes or (lambda _: None)
        self.fault = fault or (lambda _: None)
        self.path = self.journal.root / "ai-control.json"
        self.session_authorized = False

    def enable_current_session(self, *, requested=False):
        """Explicit host action after restart; binding or persisted mode is insufficient."""
        check(requested is True and self.current is not None, "ai_authority_unavailable")
        check(self._control()["mode"] == "enabled", "ai_off")
        self.session_authorized = True

    @contextmanager
    def _transaction(self):
        # Same lock order as scheduler admission and staged restore. A directory
        # swap cannot erase a reservation or settlement written to the old root.
        with self.coordinator._hold_lifecycle("ai-job-transaction"), self.journal.hold():
            yield

    def _control(self):
        check(not self.path.is_symlink(), "ai_job_invalid")
        if not self.path.exists():
            return {
                "schema_version": 1,
                "instance_id": self.journal.instance_id,
                "mode": "off",
                "generation": 0,
                "budget": None,
                "revoked": [],
            }
        check(self.path.is_file(), "ai_job_invalid")
        value = self.journal._read_json(self.path)
        check(
            set(value)
            == {"schema_version", "instance_id", "mode", "generation", "budget", "revoked"}
        )
        check(
            value["schema_version"] == 1 and value["instance_id"] == self.journal.instance_id,
            "ai_wrong_instance",
        )
        check(value["mode"] in {"off", "enabled", "paused"})
        integer(value["generation"])
        if value["budget"] is not None:
            Budget(**value["budget"])
        check(type(value["revoked"]) is list and len(value["revoked"]) <= 1000)
        for ref in value["revoked"]:
            fingerprint(ref)
        return value

    def _save_control(self, value):
        self.journal.store._atomic_json(self.path, value)

    def configure(self, *, mode, budget=None):
        check(mode in {"off", "enabled", "paused"})
        with self._transaction():
            value = self._control()
            if budget is not None:
                record = budget_record(budget)
                check(
                    value["budget"] is None or value["budget"]["currency"] == budget.currency,
                    "ai_currency_changed",
                )
                value["budget"] = record
            check(mode == "off" or value["budget"] is not None, "ai_budget_missing")
            if mode == "off":
                value["generation"] += 1
            value["mode"] = mode
            self._save_control(value)  # Revocation persists before active cancellation requests.
            if mode == "enabled":
                self.session_authorized = self.current is not None
            elif mode == "off":
                self.session_authorized = False
            if mode == "off":
                for job in self.journal._all_jobs():
                    if (
                        job["job_kind"] == AI_JOB_KIND
                        and job["status"] not in TERMINAL_JOB_STATUSES
                    ):
                        self._control_job_locked(job, "disable", utc_instant())
            return self.status()

    def change_authority(self, change, *, revoke=None):
        """Serialize supported host-source mutation against dispatch authorization."""
        with self._transaction():
            if revoke is not None:
                fingerprint(revoke)
                value = self._control()
                check(len(value["revoked"]) < 1000, "ai_queue_full")
                value["revoked"] = sorted(set(value["revoked"]) | {revoke})
                self._save_control(value)
            return change()

    def _inputs(self, ref, route):
        check(self.current is not None, "ai_authority_unavailable")
        try:
            inputs = self.current(ref, route)
        except Exception:
            raise SchedulerError("ai_authority_unavailable") from None
        check(type(inputs) is CallInputs, "ai_authority_unavailable")
        request, profile = inputs.prepare()
        check(request.context.instance_id == self.journal.instance_id, "ai_wrong_instance")
        check(inputs.route_index == route, "ai_route_changed")
        return inputs, request, profile

    def enqueue(self, request_ref, *, request_key, budget, acknowledge_duplicate_risk=False):
        fingerprint(request_ref)
        budget_record(budget)
        check(type(request_key) is str and 1 <= len(request_key) <= 200)
        check(type(acknowledge_duplicate_risk) is bool)
        with self._transaction():
            control = self._control()
            check(control["mode"] != "off", "ai_off")
            inputs, request, _ = self._inputs(request_ref, 0)
            key = idempotency_digest("ai", self.journal.instance_id, request_key)
            existing = self.journal._find_job_by_key(key)
            if existing:
                check(
                    existing["ai"]["binding"] == inputs.plan.binding
                    and existing["ai"]["budget"] == asdict(budget),
                    "ai_dedup_conflict",
                )
                return existing
            check(request_ref not in control["revoked"], "ai_revoked")
            check(budget.currency == control["budget"]["currency"], "ai_currency_changed")
            jobs = self.journal._all_jobs()
            check(
                acknowledge_duplicate_risk
                or not any(
                    j["job_kind"] == AI_JOB_KIND
                    and j["ai"]["request_ref"] == request_ref
                    and j["ai"]["terminal"] == "uncertain"
                    for j in jobs
                ),
                "ai_duplicate_risk_acknowledgement_required",
            )
            check(
                sum(
                    j["job_kind"] == AI_JOB_KIND and j["status"] not in TERMINAL_JOB_STATUSES
                    for j in jobs
                )
                < min(budget.queue, control["budget"]["queue"]),
                "ai_queue_full",
            )
            now = utc_instant()
            ai = {
                "schema_version": 1,
                "request_ref": request_ref,
                "binding": inputs.plan.binding,
                "request": request.as_record(),
                "routes": [r.profile_fingerprint for r in inputs.plan.routes],
                "route": 0,
                "budget": asdict(budget),
                "generation": control["generation"],
                "deadline": instant_text(now + timedelta(seconds=request.limits.max_seconds)),
                "blocked": None,
                "cancel": None,
                "attempts": [],
                "result": None,
                "result_fingerprint": None,
                "terminal": None,
                "restored": False,
                "resume_not_before": None,
                "duplicate_risk_acknowledged": acknowledge_duplicate_risk,
            }
            # Producer-owned manual policy; never enabled for automatic evaluation.
            from uuid import uuid4

            policy = self.journal._write_policy(
                {
                    "schema_version": 1,
                    "id": "policy_" + uuid4().hex,
                    "revision": 1,
                    "job_kind": AI_JOB_KIND,
                    "scope": {"kind": "instance", "id": self.journal.instance_id},
                    "state": "disabled",
                    "schedule": schedule_payload(mode="manual", timezone="UTC"),
                    "retry": retry_payload(
                        max_attempts=request.limits.max_attempts, base_seconds=1
                    ),
                    "created_at": instant_text(now),
                    "updated_at": instant_text(now),
                    "last_evaluated_at": None,
                    "next_nominal_at": None,
                    "next_due_at": None,
                }
            )
            job, _ = self.journal._new_job(
                policy,
                reason="manual",
                nominal=now,
                eligible=now,
                idempotency_key=key,
                now=now,
                ai=ai,
            )
            self.fault("enqueued")
            return job

    def _validate(self, job, now):
        ai, control = job["ai"], self._control()
        check(self.session_authorized, "ai_session_not_enabled")
        check(not ai["restored"], "ai_restored_requires_new_request")
        active = job["status"] in ACTIVE_STATUSES and ai["attempts"][-1]["phase"] in {
            "possible",
            "settled",
            "uncertain",
        }
        check(
            control["mode"] == "enabled" or (control["mode"] == "paused" and active),
            "ai_off" if control["mode"] == "off" else "ai_paused",
        )
        check(
            ai["generation"] == control["generation"]
            and ai["request_ref"] not in control["revoked"],
            "ai_revoked",
        )
        check(ai["cancel"] is None, "ai_cancel_requested")
        check(utc_instant(job["created_at"]) <= now < utc_instant(ai["deadline"]), "ai_deadline")
        inputs, request, profile = self._inputs(ai["request_ref"], ai["route"])
        check(
            inputs.plan.binding == ai["binding"] and request.as_record() == ai["request"],
            "ai_authority_changed",
        )
        check(
            [r.profile_fingerprint for r in inputs.plan.routes] == ai["routes"], "ai_route_changed"
        )
        check(profile.fingerprint in self.adapters, "ai_adapter_unavailable")
        if job["status"] in ACTIVE_STATUSES and ai["attempts"][-1]["phase"] == "reserved":
            row = ai["attempts"][-1]
            if row["quote"] is not None:
                quote = self.quotes(profile.fingerprint)
                check(
                    type(quote) is Quote and digest(asdict(quote)) == row["quote"],
                    "ai_price_changed",
                )
                quote.bound(
                    profile.fingerprint, ai["budget"]["currency"], row["reserved_units"], now
                )
            inventory = self.journal._all_jobs()
            period = now.date().isoformat()
            budget = Budget(**control["budget"])
            all_usage = totals(inventory, period=period)
            job_usage = totals(inventory, period=period, job_id=job["id"])
            check(all_usage["active"] <= budget.concurrency, "ai_concurrency")
            check(
                all_usage["units"] <= budget.period_units
                and job_usage["units"] <= budget.job_units,
                "ai_budget_exhausted",
            )
            for usage, cap in ((all_usage, budget.period_micros), (job_usage, budget.job_micros)):
                if cap is not None:
                    check(
                        not usage["unknown_money"] and usage["micros"] <= cap, "ai_budget_exhausted"
                    )
        return inputs, request, profile, control

    def admit_locked(self, job, now):
        """Prepare reservation; SchedulerStore atomically writes it with the lease."""
        try:
            _, request, profile, control = self._validate(job, now)
            check(job["attempt"] < request.limits.max_attempts, "ai_attempts_exhausted")
            units = request.limits.max_input_bytes + request.limits.max_output_tokens
            budget, current = Budget(**job["ai"]["budget"]), Budget(**control["budget"])
            adapter = self.adapters[profile.fingerprint]
            # Only this checked native adapter may attest no external monetary charge.
            from .ai_job_runtime import NativeJobAdapter

            local = type(adapter) is NativeJobAdapter
            quote = None if local else self.quotes(profile.fingerprint)
            money = 0 if local else None
            if quote is not None:
                check(type(quote) is Quote, "ai_price_unknown")
                money = quote.bound(profile.fingerprint, budget.currency, units, now)
            hard = any(
                v is not None
                for v in (
                    budget.job_micros,
                    budget.period_micros,
                    current.job_micros,
                    current.period_micros,
                )
            )
            check(not hard or money is not None, "ai_price_unknown")
            period = now.date().isoformat()
            jobs = self.journal._all_jobs()
            all_usage = totals(jobs, period=period)
            job_usage = totals(jobs, period=period, job_id=job["id"])
            check(
                all_usage["active"] < min(budget.concurrency, current.concurrency), "ai_concurrency"
            )
            check(
                job_usage["units"] + units <= min(budget.job_units, current.job_units)
                and all_usage["units"] + units <= min(budget.period_units, current.period_units),
                "ai_budget_exhausted",
            )
            for usage, limits in (
                (job_usage, (budget.job_micros, current.job_micros)),
                (all_usage, (budget.period_micros, current.period_micros)),
            ):
                for cap in limits:
                    if cap is not None:
                        check(
                            not usage["unknown_money"] and usage["micros"] + money <= cap,
                            "ai_budget_exhausted",
                        )
            job["ai"]["attempts"].append(
                {
                    "number": job["attempt"] + 1,
                    "route": profile.fingerprint,
                    "period": period,
                    "reserved_units": units,
                    "reserved_micros": money,
                    "quote": digest(asdict(quote)) if quote else None,
                    "pricing": asdict(quote) if quote else None,
                    "phase": "reserved",
                    "quiescent": False,
                    "units": None,
                    "micros": None,
                    "usage_source": "UNKNOWN",
                    "elapsed_ms": 0,
                    "reconciliations": [],
                }
            )
            job["ai"]["blocked"] = None
            return True
        except (SchedulerError, ProviderError) as exc:
            reason = str(exc) if isinstance(exc, SchedulerError) else "ai_authority_changed"
            job["ai"]["blocked"] = reason
            self.journal._write_job(job)
            return False

    def _owned(self, job_id, token, now):
        job = self.journal.get_job(job_id)
        check(job is not None and job["job_kind"] == AI_JOB_KIND)
        self.journal._owned(job, token, now)
        return job

    def execute_claimed(self, claimed, *, now=None):
        job_id, token = claimed["id"], claimed["lease"]["token"]
        started = time.monotonic()
        dispatched = False
        self.fault("reserved")

        def current():
            try:
                with self.journal.hold():
                    clock = utc_instant(now)
                    job = self._owned(job_id, token, clock)
                    return self._validate(job, clock)[0]
            except SchedulerError:
                raise ProviderError(Failure.POLICY) from None

        def cancel():
            try:
                current()
                return (
                    time.monotonic() - started >= claimed["ai"]["request"]["limits"]["max_seconds"]
                )
            except (SchedulerError, SchedulerBusyError, ProviderError):
                return True

        try:
            with self._transaction():
                clock = utc_instant(now)
                job = self._owned(job_id, token, clock)
                inputs, _, profile, _ = self._validate(job, clock)
                self.fault("authorized")
                job["ai"]["attempts"][-1]["phase"] = "possible"
                job["control"]["network_used"] = self.adapters[profile.fingerprint].network_used
                self.journal._write_job(job)
            self.fault("possible")
            dispatched = True
            outcome = self.adapters[profile.fingerprint].exchange(current, cancel=cancel)
            self.fault("response")
            return self.complete(
                job_id,
                token,
                outcome=outcome,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                now=now,
            )
        except ProviderError as exc:
            return self.complete(
                job_id,
                token,
                error=exc,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                now=now,
            )
        except (SchedulerError, SchedulerBusyError):
            # The original lease may already be fenced. Never complete another owner's job.
            try:
                return self.complete(
                    job_id,
                    token,
                    error=ProviderError(
                        Failure.POLICY,
                        Transmission.POSSIBLE if dispatched else Transmission.NOT_SENT,
                    ),
                    now=now,
                )
            except (SchedulerError, SchedulerBusyError):
                return self.journal.get_job(job_id)
        except Exception:
            return self.complete(
                job_id, token, error=ProviderError(Failure.REMOTE, Transmission.POSSIBLE), now=now
            )

    def complete(self, job_id, token, *, outcome=None, error=None, elapsed_ms=0, now=None):
        with self._transaction():
            clock = utc_instant(now)
            job = self.journal.get_job(job_id)
            check(job is not None and job["job_kind"] == AI_JOB_KIND)
            if job["ai"]["terminal"] is not None:
                # Terminal replay returns the existing facts, never changes accounting/output.
                return job
            self.journal._owned(job, token, clock)
            ai, row = job["ai"], job["ai"]["attempts"][-1]
            row["elapsed_ms"] = integer(elapsed_ms)
            from .ai_job_runtime import JobOutcome, LocalFailure

            if type(outcome) is LocalFailure:
                # The managed worker has confirmed termination, but interrupted
                # token consumption is unknown and retains the resource reserve.
                row.update(phase="settled", quiescent=True, micros=0, usage_source="LOCAL")
                if ai["cancel"] == "pause":
                    job["attempts"][-1].update(outcome="paused", completed_at=instant_text(clock))
                    job.update(
                        status="paused",
                        lease=None,
                        retry_not_before=None,
                        updated_at=instant_text(clock),
                    )
                else:
                    ai.update(
                        terminal="cancelled" if ai["cancel"] else "failed",
                        blocked="ai_local_stopped",
                    )
            elif outcome is not None:
                check(type(outcome) is JobOutcome)
                row.update(
                    phase="settled",
                    quiescent=True,
                    units=outcome.units,
                    micros=outcome.micros,
                    usage_source=outcome.usage_source,
                )
                try:
                    self._validate(job, clock)
                except (SchedulerError, ProviderError):
                    ai.update(
                        terminal="cancelled" if ai["cancel"] else "failed",
                        blocked="ai_authority_changed",
                    )
                else:
                    ai.update(
                        result=outcome.result,
                        result_fingerprint=digest(outcome.result),
                        terminal="succeeded",
                    )
            else:
                check(type(error) is ProviderError)
                if error.transmission != Transmission.NOT_SENT:
                    row.update(phase="uncertain", quiescent=False)
                    ai.update(terminal="uncertain", blocked="ai_outcome_uncertain")
                else:
                    row.update(
                        phase="released", quiescent=True, units=0, micros=0, usage_source="NOT_SENT"
                    )
                    if ai["cancel"] == "pause":
                        job["attempts"][-1].update(
                            outcome="paused", completed_at=instant_text(clock)
                        )
                        job.update(
                            status="paused",
                            lease=None,
                            retry_not_before=None,
                            updated_at=instant_text(clock),
                        )
                    elif ai["cancel"]:
                        ai["terminal"] = "cancelled"
                    elif (
                        error.code in RETRYABLE
                        and job["attempt"] < job["retry"]["max_attempts"]
                        and clock < utc_instant(ai["deadline"])
                    ):
                        # One explicit ordered fallback; otherwise retry this route.
                        if ai["route"] + 1 < len(ai["routes"]):
                            ai["route"] += 1
                        delay = retry_delay_seconds(job["retry"], job["attempt"])
                        job["attempts"][-1].update(
                            outcome="retry",
                            completed_at=instant_text(clock),
                            error_class="transient",
                            error_code="ai_retry",
                        )
                        job.update(
                            status="retry_wait",
                            lease=None,
                            updated_at=instant_text(clock),
                            retry_not_before=instant_text(clock + timedelta(seconds=delay)),
                        )
                    else:
                        ai.update(terminal="failed", blocked="ai_execution_blocked")
            # This single write is the accounting/result commit; receipts are projections.
            job = self.journal._write_job(job)
            self.fault("committed")
            if ai["terminal"]:
                job = finish_ai_locked(self.journal, job, clock)
                self.fault("receipt")
            return job

    def _control_job_locked(self, job, action, now):
        if job["status"] in TERMINAL_JOB_STATUSES:
            return job
        check(action in {"pause", "resume", "cancel", "disable"})
        ai = job["ai"]
        if action == "resume":
            check(job["status"] == "paused", "ai_control_unavailable")
            check(job["attempt"] < job["retry"]["max_attempts"], "ai_attempts_exhausted")
            ai["cancel"] = None
            delayed = ai["resume_not_before"]
            job.update(status="retry_wait" if delayed else "queued", retry_not_before=delayed)
            ai["resume_not_before"] = None
        elif job["status"] in ACTIVE_STATUSES:
            ai["cancel"] = action
        elif action == "pause":
            ai["resume_not_before"] = job["retry_not_before"]
            job.update(status="paused", retry_not_before=None)
            ai["cancel"] = "pause"
        else:
            ai.update(cancel=action, terminal="cancelled")
        job["updated_at"] = instant_text(now)
        job = self.journal._write_job(job)
        return finish_ai_locked(self.journal, job, now) if ai["terminal"] else job

    def control_job(self, job_id, action):
        with self._transaction():
            job = self.journal.get_job(job_id)
            check(job is not None and job["job_kind"] == AI_JOB_KIND)
            return self._control_job_locked(job, action, utc_instant())

    def request_control(
        self, job_id, action, *, expected_revision, request_id, expected_checkpoint=None, now=None
    ):
        from .scheduler_control import revision

        check(type(request_id) is str and 1 <= len(request_id) <= 200)
        with self._transaction():
            job = self.journal.get_job(job_id)
            check(job is not None and job["job_kind"] == AI_JOB_KIND)
            request_digest = digest(request_id)
            payload_digest = digest(
                {"action": action, "revision": expected_revision, "checkpoint": expected_checkpoint}
            )
            commands = job["control"]["commands"]
            prior = next((r for r in commands if r["request_digest"] == request_digest), None)
            if prior:
                check(prior["payload_digest"] == payload_digest, "ai_control_conflict")
                return {"job": job, "successor": None, "duplicate": True}
            check(revision(job) == expected_revision, "ai_control_changed")
            check(action in ai_capabilities(job, now=now)["actions"], "ai_control_unavailable")
            check(
                expected_checkpoint is None or expected_checkpoint == job["checkpoint"],
                "ai_control_changed",
            )
            check(len(commands) < 32, "ai_control_unavailable")
            if action == "retry":
                job.update(status="queued", retry_not_before=None)
            clock = utc_instant(now)
            commands.append(
                {
                    "request_digest": request_digest,
                    "payload_digest": payload_digest,
                    "action": action,
                    "expected_revision": expected_revision,
                    "result_status": "queued"
                    if action in {"retry", "resume"}
                    else "paused"
                    if action == "pause"
                    else "cancelled",
                    "accepted_at": instant_text(clock),
                    "successor_id": None,
                }
            )
            job["control"]["revision"] += 1
            # Control command and cancellation intent persist in the same job write.
            result = (
                self.journal._write_job(job)
                if action == "retry"
                else self._control_job_locked(job, action, clock)
            )
            return {"job": result, "successor": None, "duplicate": False}

    def reconcile(
        self,
        job_id,
        *,
        attempt,
        quiescent,
        acknowledge_duplicate_risk,
        evidence,
        units=None,
        micros=None,
        usage_source="UNKNOWN",
    ):
        fingerprint(evidence)
        check(
            quiescent is True and acknowledge_duplicate_risk is True, "ai_reconciliation_required"
        )
        check(usage_source in {"UNKNOWN", "LOCAL", "PROVIDER"}, "ai_reconciliation_required")
        check(
            (units is None and micros is None) or usage_source != "UNKNOWN",
            "ai_reconciliation_required",
        )
        with self._transaction():
            job = self.journal.get_job(job_id)
            check(job is not None and job["job_kind"] == AI_JOB_KIND)
            integer(attempt, 1, len(job["ai"]["attempts"]))
            row = job["ai"]["attempts"][attempt - 1]
            check(row["phase"] in {"uncertain", "settled"}, "ai_reconciliation_required")
            prior = next((e for e in row["reconciliations"] if e["evidence"] == evidence), None)
            if prior:
                check(
                    prior["units"] == units
                    and prior["micros"] == micros
                    and prior["usage_source"] == usage_source,
                    "ai_reconciliation_conflict",
                )
                return job
            check(len(row["reconciliations"]) < 32, "ai_reconciliation_required")
            for key, value in (("units", units), ("micros", micros)):
                if value is not None:
                    integer(value)
                    check(row[key] is None or value >= row[key], "ai_known_consumption")
                    row[key] = value
            row.update(phase="settled", quiescent=True)
            if units is not None or micros is not None:
                row["usage_source"] = usage_source
            row["reconciliations"].append(
                {
                    "evidence": evidence,
                    "units": units,
                    "micros": micros,
                    "usage_source": usage_source,
                    "at": instant_text(utc_instant()),
                }
            )
            # Never requeue/rewrite a terminal receipt. UNKNOWN stays reserved.
            return self.journal._write_job(job)

    def status(self):
        control = self._control()
        jobs = self.journal._all_jobs() if self.journal.jobs.exists() else []
        return {
            "mode": control["mode"],
            "authority_bound": self.current is not None,
            "session_authorized": self.session_authorized,
            "accounting": totals(jobs, period=utc_instant().date().isoformat()),
            "currency": (control["budget"] or {}).get("currency"),
            "dispatch_on_read": False,
        }

    def public(self, job_id):
        from .scheduler import public_job_record

        job = self.journal.get_job(job_id)
        check(job is not None and job["job_kind"] == AI_JOB_KIND)
        result = public_job_record(job)
        result["ai"]["actions"] = (
            ["reconcile"]
            if job["ai"]["terminal"] == "uncertain"
            else ai_capabilities(job)["actions"]
        )
        return copy.deepcopy(result)


def ai_capabilities(job, *, now=None):
    from .scheduler_control import revision

    status = job["status"]
    actions = []
    remaining = job["attempt"] < job["retry"]["max_attempts"]
    if status not in TERMINAL_JOB_STATUSES:
        actions = ["cancel"]
        if status == "paused" and remaining:
            actions += ["resume"]
        elif status in {"queued", "retry_wait", "running"}:
            actions += ["pause"]
        if (
            status == "retry_wait"
            and remaining
            and utc_instant(job["retry_not_before"]) <= utc_instant(now)
        ):
            actions += ["retry"]
    return {
        "job_id": job["id"],
        "revision": revision(job),
        "actions": actions,
        "unavailable": {
            a: "ai_control_unavailable"
            for a in {"pause", "resume", "cancel", "retry", "restart"} - set(actions)
        },
        "checkpoint": dict(job["checkpoint"]),
        "progress": dict(job["progress"]),
        "cooperative": True,
        "wait_reason": job["ai"]["blocked"],
    }
