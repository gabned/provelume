"""Current authority, bounded fallback, controls and portable liability retention."""

import json
import socket
import threading
import zipfile
from dataclasses import replace
from datetime import timedelta

import pytest
from ai_context_fakes import context_plan
from ai_jobs_fakes import BUDGET, REF, UNITS, manager
from ai_provider_fakes import SyntheticAdapter
from test_ai_jobs import Failing, claim, enqueue

from provelume.ai_context import preview_context
from provelume.ai_contract import digest
from provelume.ai_job_runtime import JobOutcome, LocalFailure, ProviderJobAdapter
from provelume.ai_provider import Failure, Transmission
from provelume.portable_transfer import PortableTransferError
from provelume.scheduler_model import SchedulerError, utc_instant
from provelume.service import ProvelumeInstance


@pytest.fixture
def case(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    jobs, holder = manager(instance.root)
    jobs.configure(mode="enabled", budget=BUDGET)
    return jobs, holder


def fallback(jobs, holder):
    before = holder[0]
    second = replace(before.profiles[0], id="synthetic_second")
    profiles = (before.profiles[0], second)
    evidence = (
        before.evidence[0],
        replace(before.evidence[0], profile_fingerprint=second.fingerprint),
    )
    current = dict(before.current)
    current["rules"] = tuple(
        replace(
            r, route=tuple(p.id for p in profiles), allowed_profiles=tuple(p.id for p in profiles)
        )
        if r.route
        else r
        for r in current["rules"]
    )
    preview = preview_context(before.source, before.selections, **current)
    plan = context_plan(
        preview,
        before.source,
        before.selections,
        current,
        {"profiles": profiles, "evidence": evidence},
    )
    holder[0] = replace(
        before, current=current, profiles=profiles, evidence=evidence, plan=plan, preview=preview
    )
    fail = Failing()
    jobs.adapters = {
        profiles[0].fingerprint: fail,
        second.fingerprint: ProviderJobAdapter(SyntheticAdapter()),
    }
    return fail


@pytest.mark.parametrize("blocked", [False, True])
def test_explicit_ordered_fallback_and_revocation(case, blocked):
    jobs, holder = case
    first = fallback(jobs, holder)
    job = enqueue(jobs)
    retry = jobs.coordinator.run_one(job_id=job["id"])
    assert retry["status"] == "retry_wait" and retry["ai"]["route"] == 1
    now = utc_instant(retry["retry_not_before"])
    if blocked:
        jobs.change_authority(lambda: None, revoke=REF)
        assert claim(jobs, job["id"], now=now) is None
    else:
        result = jobs.execute_claimed(claim(jobs, job["id"], now=now), now=now)
        assert result["status"] == "succeeded" and result["attempt"] == 2
        assert jobs.status()["accounting"]["units"] == UNITS
    assert first.calls == 1


def test_fallback_cannot_expand_original_job_envelope(case):
    jobs, holder = case
    fallback(jobs, holder)
    job = enqueue(jobs, budget=replace(BUDGET, job_units=UNITS - 1))
    assert claim(jobs, job["id"]) is None
    assert jobs.public(job["id"])["ai"]["route"] == 0
    assert jobs.public(job["id"])["ai"]["blocked"] == "ai_budget_exhausted"


@pytest.mark.parametrize("mutation", ["version", "consent", "profile", "qualification", "template"])
def test_current_sources_revalidated_after_enqueue(case, mutation):
    jobs, holder = case
    job = enqueue(jobs)
    before = holder[0]
    current = dict(before.current)
    if mutation == "version":
        changed = replace(
            before,
            source=replace(
                before.source, version=replace(before.source.version, version_id="synthetic_other")
            ),
        )
    elif mutation == "consent":
        current["snapshot"] = replace(current["snapshot"], consent_granted=False)
        changed = replace(before, current=current)
    elif mutation == "profile":
        changed = replace(
            before,
            profiles=(
                replace(before.profiles[0], revision=digest("changed")),
                *before.profiles[1:],
            ),
        )
    elif mutation == "qualification":
        changed = replace(before, evidence=())
    else:
        from provelume.ai_context import TaskTemplate

        current["template"] = TaskTemplate("context-check-complete-v1", False)
        changed = replace(before, current=current)
    jobs.change_authority(lambda: holder.__setitem__(0, changed))
    assert claim(jobs, job["id"]) is None
    assert jobs.status()["accounting"]["active"] == 0


def test_pause_preserves_backoff_and_cancel_during_backoff(case):
    jobs, _ = case
    fail = Failing()
    jobs.adapters = {key: fail for key in jobs.adapters}
    job = jobs.coordinator.run_one(job_id=enqueue(jobs)["id"])
    due = job["retry_not_before"]
    jobs.control_job(job["id"], "pause")
    resumed = jobs.control_job(job["id"], "resume")
    assert resumed["retry_not_before"] == due and resumed["status"] == "retry_wait"
    assert claim(jobs, job["id"], now=utc_instant(due) - timedelta(milliseconds=1)) is None
    jobs.control_job(job["id"], "cancel")
    assert claim(jobs, job["id"], now=due) is None and fail.calls == 1


@pytest.mark.parametrize("action", ["cancel", "pause", "off"])
def test_active_controls_with_confirmed_local_quiescence(case, action):
    jobs, _ = case
    entered, released = threading.Event(), threading.Event()

    class Local:
        network_used = False

        def exchange(self, current, *, cancel):
            entered.set()
            assert released.wait(10)
            assert cancel()
            return LocalFailure(Failure.CANCELLED)

    jobs.adapters = {key: Local() for key in jobs.adapters}
    job = enqueue(jobs)
    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.append(jobs.coordinator.run_one(job_id=job["id"]))
    )
    worker.start()
    assert entered.wait(10)
    try:
        if action == "off":
            jobs.configure(mode="off")
        else:
            jobs.control_job(job["id"], action)
    finally:
        released.set()
        worker.join(10)
    assert not worker.is_alive() and len(outcome) == 1
    assert outcome[0]["status"] == ("paused" if action == "pause" else "cancelled")
    assert jobs.status()["accounting"]["active"] == 0
    assert jobs.status()["accounting"]["units"] == UNITS


def test_cancel_completion_race_preserves_known_consumption(case):
    jobs, _ = case
    job = claim(jobs, enqueue(jobs)["id"])
    jobs.control_job(job["id"], "cancel")
    outcome = JobOutcome({"kind": "untrusted_text", "value": "private fixture"}, 9, 2, "PROVIDER")
    result = jobs.complete(job["id"], job["lease"]["token"], outcome=outcome)
    assert result["status"] == "cancelled" and result["ai"]["result"] is None
    assert jobs.status()["accounting"]["units"] == 9
    receipt = jobs.journal.list_receipts()[0]
    assert receipt["schema_version"] == 2 and receipt["ai"]["binding"] == job["ai"]["binding"]
    assert "private fixture" not in json.dumps(receipt)


def test_reconciliation_duplicate_and_known_usage_never_refunded(case):
    jobs, _ = case
    jobs.adapters = {key: Failing(Transmission.POSSIBLE) for key in jobs.adapters}
    job = jobs.coordinator.run_one(job_id=enqueue(jobs)["id"])
    args = dict(
        attempt=1,
        quiescent=True,
        acknowledge_duplicate_risk=True,
        evidence=digest("verified provider statement"),
        units=9,
        micros=5,
        usage_source="PROVIDER",
    )
    first = jobs.reconcile(job["id"], **args)
    assert first["ai"]["attempts"][0]["usage_source"] == "PROVIDER"
    assert first["ai"]["attempts"][0]["reconciliations"][0]["usage_source"] == "PROVIDER"
    assert jobs.reconcile(job["id"], **args) == first
    with pytest.raises(SchedulerError, match="ai_reconciliation_conflict"):
        jobs.reconcile(job["id"], **{**args, "units": 8})
    with pytest.raises(SchedulerError, match="ai_reconciliation_conflict"):
        jobs.reconcile(job["id"], **{**args, "usage_source": "LOCAL"})
    with pytest.raises(SchedulerError, match="ai_reconciliation_required"):
        jobs.reconcile(job["id"], **{**args, "usage_source": "UNKNOWN"})
    with pytest.raises(SchedulerError, match="ai_known_consumption"):
        jobs.reconcile(job["id"], **{**args, "units": 8, "evidence": digest("other")})


def test_preflight_never_dispatches_looks_up_or_reads_credentials(case, monkeypatch):
    jobs, _ = case

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected IO")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    jobs.current = forbidden
    jobs.adapters = {"unusable": forbidden}
    assert jobs.status()["dispatch_on_read"] is False
    assert ProvelumeInstance.ai_execution_status()["enabled"] is False


@pytest.mark.parametrize("portable", [False, True])
def test_restore_retains_post_snapshot_liabilities_and_forces_off(case, tmp_path, portable):
    jobs, _ = case
    instance = ProvelumeInstance(jobs.journal.store.paths.root)
    before = enqueue(jobs)
    if portable:
        archive = tmp_path / "portable.zip"
        instance.export_portable(archive)
    else:
        archive = instance.backup(destination=tmp_path / "backups")["archive"]
    jobs.adapters = {key: Failing(Transmission.POSSIBLE) for key in jobs.adapters}
    later = enqueue(jobs, "post-snapshot")
    jobs.coordinator.run_one(job_id=later["id"])
    if portable:
        instance.import_portable(archive)
    else:
        instance.restore(archive)
    restored, _ = manager(instance.root)
    assert restored.status()["mode"] == "off"
    assert restored.status()["accounting"]["units"] == UNITS
    assert restored.journal.get_job(later["id"])["ai"]["terminal"] == "uncertain"
    assert restored.journal.get_job(before["id"])["status"] == "cancelled"
    restored.configure(mode="enabled")
    assert claim(restored, later["id"]) is None
    with zipfile.ZipFile(archive) as bundle:
        assert not any(n.endswith((".gguf", ".dll", ".so")) for n in bundle.namelist())


def test_portable_wrong_instance_rejected(case, tmp_path):
    jobs, _ = case
    enqueue(jobs)
    source = ProvelumeInstance(jobs.journal.store.paths.root)
    archive = tmp_path / "portable.zip"
    source.export_portable(archive)
    target = ProvelumeInstance.initialise(tmp_path / "other")
    original_id = target.store.read_config()["instance"]["id"]
    with pytest.raises(PortableTransferError) as failure:
        target.import_portable(archive)
    assert isinstance(failure.value.__cause__, SchedulerError)
    assert str(failure.value.__cause__) == "ai_wrong_instance"
    assert target.store.read_config()["instance"]["id"] == original_id


def test_new_request_after_uncertainty_requires_explicit_risk_acknowledgement(case):
    jobs, _ = case
    jobs.adapters = {key: Failing(Transmission.POSSIBLE) for key in jobs.adapters}
    jobs.coordinator.run_one(job_id=enqueue(jobs)["id"])
    with pytest.raises(SchedulerError, match="ai_duplicate_risk_acknowledgement_required"):
        enqueue(jobs, "new")
    other = jobs.enqueue(REF, request_key="new", budget=BUDGET, acknowledge_duplicate_risk=True)
    assert other["ai"]["duplicate_risk_acknowledged"]
    assert jobs.status()["accounting"]["units"] == UNITS


def test_budget_tightened_after_claim_refuses_dispatch(case):
    jobs, _ = case
    job = claim(jobs, enqueue(jobs)["id"])
    jobs.configure(mode="enabled", budget=replace(BUDGET, period_units=UNITS - 1))
    result = jobs.execute_claimed(job)
    assert result["status"] == "failed"
    assert jobs.status()["accounting"]["units"] == 0
