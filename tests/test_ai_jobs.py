"""Durability and real cross-process contention of the one scheduler journal."""

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from ai_jobs_fakes import BUDGET, REF, UNITS, manager

from provelume.ai_contract import digest
from provelume.ai_job_contract import Budget, Quote, ceil_price, totals
from provelume.ai_job_runtime import JobOutcome
from provelume.ai_jobs import AiJobs
from provelume.ai_provider import Failure, ProviderError, Transmission
from provelume.scheduler import SchedulerCoordinator
from provelume.scheduler_model import SchedulerBusyError, SchedulerError, instant_text, utc_instant
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore


@pytest.fixture
def case(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    jobs, holder = manager(instance.root)
    jobs.configure(mode="enabled", budget=BUDGET)
    return jobs, holder


def enqueue(jobs, key="one", budget=BUDGET):
    return jobs.enqueue(REF, request_key=key, budget=budget)


def claim(jobs, job_id, **kwargs):
    return jobs.journal.claim_next(
        worker_id="s06-test", job_id=job_id, ai_admit=jobs.admit_locked, **kwargs
    )


def test_explicit_default_and_dedup(case):
    jobs, _ = case
    first = enqueue(jobs)
    assert enqueue(jobs)["id"] == first["id"]
    assert jobs.journal.claim_next(worker_id="unbound") is None
    result = jobs.coordinator.run_one(job_id=first["id"])
    assert result["status"] == "succeeded"
    assert result["ai"]["attempts"][0]["units"] is None
    assert jobs.status()["accounting"]["units"] == UNITS
    assert len(jobs.journal.list_receipts()) == 1
    assert "result" not in jobs.public(first["id"])["ai"]
    reopened = ProvelumeInstance(jobs.journal.store.paths.root)
    assert not reopened.ai_jobs.status()["authority_bound"]
    assert ProvelumeInstance.ai_execution_status()["enabled"] is False


@pytest.mark.parametrize("value", [True, -1, 1.2, float("nan"), 2**60])
def test_integer_bounds(value):
    with pytest.raises(SchedulerError):
        Budget(value, 100)


def test_round_up():
    assert ceil_price(1, 1) == 1
    assert ceil_price(1_000_001, 1) == 2
    assert ceil_price(1_000_000, 7) == 7


def test_prices_unknown_invalid_and_shared_money(case):
    jobs, holder = case
    cap = replace(BUDGET, job_micros=2, period_micros=2)
    jobs.configure(mode="enabled", budget=cap)
    job = enqueue(jobs, budget=cap)
    assert claim(jobs, job["id"]) is None
    assert jobs.public(job["id"])["ai"]["blocked"] == "ai_price_unknown"
    now = utc_instant()
    quote = Quote(
        holder[0].profiles[0].fingerprint,
        "USD",
        instant_text(now - timedelta(days=1)),
        instant_text(now + timedelta(days=1)),
        2,
        UNITS,
        digest("fixed-contract"),
        True,
    )
    for bad in [
        replace(quote, currency="EUR"),
        replace(quote, defensible=False),
        replace(quote, valid_until=instant_text(now)),
        replace(quote, maximum_units=1),
    ]:
        jobs.quotes = lambda _, q=bad: q
        assert claim(jobs, job["id"]) is None
    jobs.quotes = lambda _: quote
    assert claim(jobs, job["id"])
    second = enqueue(jobs, "second", budget=cap)
    assert claim(jobs, second["id"]) is None
    assert jobs.public(second["id"])["ai"]["blocked"] == "ai_budget_exhausted"


def test_cancel_before_claim_and_reserved_release(case):
    jobs, _ = case
    job = enqueue(jobs)
    cancelled = jobs.control_job(job["id"], "cancel")
    assert cancelled["status"] == "cancelled" and cancelled["attempt"] == 0
    other = enqueue(jobs, "other")
    reserved = claim(jobs, other["id"])
    jobs.control_job(other["id"], "cancel")
    jobs.execute_claimed(reserved)
    assert jobs.status()["accounting"]["units"] == 0
    assert jobs.status()["accounting"]["active"] == 0


def test_revocation_after_enqueue_and_pause(case):
    jobs, holder = case
    job = enqueue(jobs)
    jobs.configure(mode="paused")
    assert claim(jobs, job["id"]) is None
    jobs.configure(mode="enabled")
    original = holder[0]
    changed = dict(original.current)
    changed["rules"] = (replace(changed["rules"][0], deny=True), *changed["rules"][1:])
    jobs.change_authority(lambda: holder.__setitem__(0, replace(original, current=changed)))
    assert claim(jobs, job["id"]) is None
    jobs.change_authority(lambda: holder.__setitem__(0, original), revoke=REF)
    assert claim(jobs, job["id"]) is None


class Failing:
    network_used = True

    def __init__(self, transmission=Transmission.NOT_SENT):
        self.calls = 0
        self.transmission = transmission

    def exchange(self, current, *, cancel):
        current().prepare()
        self.calls += 1
        raise ProviderError(Failure.CONNECTION, self.transmission)


def test_unknown_no_replay_no_refund_and_fenced_worker(case):
    jobs, _ = case
    fail = Failing(Transmission.POSSIBLE)
    jobs.adapters = {key: fail for key in jobs.adapters}
    job = enqueue(jobs)
    reserved = claim(jobs, job["id"])
    result = jobs.execute_claimed(reserved)
    assert result["status"] == "manual_intervention"
    assert result["ai"]["attempts"][0]["phase"] == "uncertain"
    jobs.journal.recover(now=utc_instant() + timedelta(days=1))
    assert claim(jobs, job["id"]) is None
    assert fail.calls == 1
    assert totals([result], period="2099-01-01")["units"] == UNITS
    jobs.reconcile(
        job["id"],
        attempt=1,
        quiescent=True,
        acknowledge_duplicate_risk=True,
        evidence=digest("operator verified stopped"),
    )
    assert jobs.status()["accounting"]["units"] == UNITS
    assert jobs.status()["accounting"]["active"] == 0


def test_retry_persisted_backoff_and_attempt_bound(case):
    jobs, _ = case
    fail = Failing()
    jobs.adapters = {key: fail for key in jobs.adapters}
    first = enqueue(jobs)
    result = jobs.coordinator.run_one(job_id=first["id"])
    assert result["status"] == "retry_wait"
    assert claim(jobs, first["id"]) is None
    # Controlled logical clock, no timing-dependent sleep.
    now = utc_instant(result["retry_not_before"])
    reserved = claim(jobs, first["id"], now=now)
    result = jobs.execute_claimed(reserved, now=now)
    assert result["status"] == "failed" and fail.calls == 2
    assert claim(jobs, first["id"], now=now + timedelta(seconds=3)) is None


def test_duplicate_callback_and_known_overrun_debt(case):
    jobs, _ = case
    job = claim(jobs, enqueue(jobs)["id"])
    outcome = JobOutcome(
        {"kind": "untrusted_text", "value": "synthetic result"}, UNITS + 7, 3, "PROVIDER"
    )
    result = jobs.complete(job["id"], job["lease"]["token"], outcome=outcome)
    assert jobs.complete(job["id"], job["lease"]["token"], outcome=outcome) == result
    assert len(jobs.journal.list_receipts()) == 1
    assert totals([result], period="2099-01-01")["units"] == 7
    assert "synthetic result" not in json.dumps(jobs.public(job["id"]))


def _contend(root, job_id, ready, start, output):
    jobs, _ = manager(root)
    ready.put(True)
    start.wait(20)
    try:
        # Barrier/process startup is not part of the synthetic authorization clock.
        now = utc_instant(jobs.journal.get_job(job_id)["created_at"])
        result = claim(jobs, job_id, now=now)
        output.put("claimed" if result else "denied")
    except SchedulerBusyError:
        output.put("busy")


@pytest.mark.parametrize("same_job", [True, False])
def test_real_process_contention(case, same_job):
    jobs, _ = case
    budget = replace(BUDGET, period_units=UNITS)
    jobs.configure(mode="enabled", budget=budget)
    one = enqueue(jobs, "one")
    two = one if same_job else enqueue(jobs, "two")
    ctx = multiprocessing.get_context("spawn")
    ready, output, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    children = [
        ctx.Process(
            target=_contend,
            args=(str(jobs.journal.store.paths.root), j["id"], ready, start, output),
        )
        for j in (one, two)
    ]
    for child in children:
        child.start()
    for _ in children:
        assert ready.get(timeout=30)
    start.set()
    outcomes = [output.get(timeout=30) for _ in children]
    for child in children:
        child.join(30)
        assert child.exitcode == 0
    assert outcomes.count("claimed") == 1
    assert jobs.status()["accounting"]["units"] == UNITS
    assert jobs.status()["accounting"]["active"] == 1


def test_thread_contention(case):
    jobs, _ = case
    jobs.configure(mode="enabled", budget=replace(BUDGET, period_units=UNITS))
    ids = [enqueue(jobs, str(i))["id"] for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda job_id: claim(jobs, job_id), ids))
    assert sum(x is not None for x in outcomes) == 1


def _crash(root, job_id, boundary):
    def fault(name):
        if name == boundary:
            os._exit(73)

    jobs, _ = manager(root, fault=fault)
    original = jobs.journal._write_receipt_once

    def write_receipt(value):
        receipt = original(value)
        if boundary == "receipt_written":
            os._exit(73)
        return receipt

    jobs.journal._write_receipt_once = write_receipt
    now = utc_instant(jobs.journal.get_job(job_id)["created_at"])
    jobs.coordinator.run_one(job_id=job_id, lease_seconds=1, now=now)


@pytest.mark.parametrize(
    "boundary,terminal",
    [
        ("reserved", "failed"),
        ("authorized", "failed"),
        ("possible", "manual_intervention"),
        ("response", "manual_intervention"),
        ("committed", "succeeded"),
        ("receipt_written", "succeeded"),
        ("receipt", "succeeded"),
    ],
)
def test_real_crash_boundaries_and_restart(case, boundary, terminal):
    jobs, _ = case
    job = enqueue(jobs)
    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(
        target=_crash, args=(str(jobs.journal.store.paths.root), job["id"], boundary)
    )
    child.start()
    child.join(30)
    assert child.exitcode == 73
    reopened = SchedulerCoordinator(InstanceStore.open(jobs.journal.store.paths.root))
    reopened.journal.recover(now=utc_instant() + timedelta(seconds=2))
    result = reopened.journal.get_job(job["id"])
    assert result["status"] == terminal
    assert result["attempt"] == 1
    assert len(reopened.journal.list_receipts()) == 1
    assert reopened.journal.claim_next(worker_id="no-replay") is None


def test_expired_reserved_attempt_fences_old_worker(case):
    jobs, _ = case
    reserved = claim(jobs, enqueue(jobs)["id"], lease_seconds=1)
    jobs.journal.recover(now=utc_instant() + timedelta(seconds=2))
    original = jobs.journal.get_job(reserved["id"])
    jobs.execute_claimed(reserved)
    assert jobs.journal.get_job(reserved["id"]) == original
    assert original["status"] == "failed"


def test_instance_isolation(case, tmp_path):
    jobs, holder = case
    other = ProvelumeInstance.initialise(tmp_path / "other")
    manager2 = AiJobs(other.scheduler, current=lambda *_: holder[0], adapters=jobs.adapters)
    manager2.configure(mode="enabled", budget=BUDGET)
    with pytest.raises(SchedulerError, match="ai_wrong_instance"):
        enqueue(manager2)
