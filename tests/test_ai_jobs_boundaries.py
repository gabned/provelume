"""Lifecycle availability, restart grants and serialized dispatch revocation."""

import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest
from ai_jobs_fakes import BUDGET, manager
from test_ai_jobs import claim, enqueue

from provelume.ai_job_runtime import JobOutcome, NativeJobAdapter
from provelume.ai_jobs import AiJobs
from provelume.ai_provider import ProviderError, Transmission
from provelume.scheduler import SchedulerCoordinator
from provelume.scheduler_model import utc_instant
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore


@pytest.fixture
def case(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    jobs, holder = manager(instance.root)
    jobs.configure(mode="enabled", budget=BUDGET)
    return instance, jobs, holder


def test_rebinding_after_restart_does_not_enable_dispatch(case):
    instance, jobs, holder = case
    job = enqueue(jobs)
    restarted = AiJobs(
        SchedulerCoordinator(InstanceStore.open(instance.root)),
        current=jobs.current,
        adapters=jobs.adapters,
    )
    assert claim(restarted, job["id"]) is None
    assert restarted.public(job["id"])["ai"]["blocked"] == "ai_session_not_enabled"
    restarted.enable_current_session(requested=True)
    assert claim(restarted, job["id"])


def test_background_cycle_does_not_start_explicit_ai_job(case):
    _, jobs, _ = case
    job = enqueue(jobs)
    jobs.coordinator.cycle()
    assert jobs.journal.get_job(job["id"])["attempt"] == 0


@pytest.mark.parametrize("boundary", ["reserved", "possible"])
def test_revocation_race_prevents_send_at_authorization_boundaries(case, boundary):
    _, jobs, _ = case

    def fault(name):
        if name == boundary:
            jobs.configure(mode="off")

    jobs.fault = fault
    result = jobs.coordinator.run_one(job_id=enqueue(jobs)["id"])
    assert result["status"] == "cancelled"
    assert jobs.status()["accounting"]["active"] == 0
    assert jobs.status()["accounting"]["units"] == 0


def test_deadline_blocks_claim_without_reservation(case):
    _, jobs, _ = case
    job = enqueue(jobs)
    assert claim(jobs, job["id"], now=utc_instant(job["ai"]["deadline"])) is None
    assert jobs.public(job["id"])["ai"]["blocked"] == "ai_deadline"
    assert jobs.status()["accounting"]["units"] == 0


@pytest.mark.parametrize("restore", [False, True])
def test_active_inference_does_not_hold_instance_lifecycle(case, tmp_path, restore):
    instance, jobs, _ = case
    entered, released = threading.Event(), threading.Event()

    class Controlled:
        network_used = False

        def exchange(self, current, *, cancel):
            entered.set()
            assert released.wait(30)
            return JobOutcome({"kind": "untrusted_text", "value": "synthetic"}, 9, 0, "LOCAL")

    jobs.adapters = {k: Controlled() for k in jobs.adapters}
    job = enqueue(jobs)
    backup = instance.backup(destination=tmp_path / "backups") if restore else None
    completed = []
    worker = threading.Thread(
        target=lambda: completed.append(jobs.coordinator.run_one(job_id=job["id"]))
    )
    worker.start()
    assert entered.wait(10)
    try:
        if restore:
            instance.restore(backup["archive"])
        else:
            source = tmp_path / "notes"
            source.mkdir()
            (source / "note.txt").write_text("Synthetic orchid deterministic document.")
            instance.ingest(source)
            assert instance.search("orchid")
    finally:
        released.set()
        worker.join(10)
    assert not worker.is_alive() and len(completed) == 1
    if restore:
        assert completed[0]["status"] == "manual_intervention"
        assert completed[0]["ai"]["result"] is None
        assert jobs.status()["mode"] == "off"
    else:
        assert completed[0]["status"] == "succeeded"


def test_busy_native_adapter_never_closes_other_worker():
    owned, release = threading.Event(), threading.Event()
    lock = threading.RLock()

    def existing():
        with lock:
            owned.set()
            assert release.wait(10)

    thread = threading.Thread(target=existing)
    thread.start()
    assert owned.wait(10)
    runtime = SimpleNamespace(_lock=lock, close=lambda: pytest.fail("closed unrelated worker"))
    try:
        with pytest.raises(ProviderError) as exc:
            NativeJobAdapter(runtime, None).exchange(
                lambda: pytest.fail("unexpected preflight"), cancel=lambda: False
            )
        assert exc.value.transmission == Transmission.NOT_SENT
    finally:
        release.set()
        thread.join(10)


def test_global_pause_allows_already_authorized_result(case):
    _, jobs, _ = case

    def fault(name):
        if name == "possible":
            jobs.configure(mode="paused")

    jobs.fault = fault
    result = jobs.coordinator.run_one(job_id=enqueue(jobs)["id"])
    assert result["status"] == "succeeded"


def test_late_old_callback_cannot_modify_retry_attempt(case):
    from test_ai_jobs import Failing

    _, jobs, _ = case
    jobs.adapters = {k: Failing() for k in jobs.adapters}
    old = claim(jobs, enqueue(jobs)["id"])
    retry = jobs.execute_claimed(old)
    now = utc_instant(retry["retry_not_before"]) + timedelta(milliseconds=1)
    new = claim(jobs, old["id"], now=now)
    with pytest.raises(ValueError):
        jobs.complete(
            old["id"],
            old["lease"]["token"],
            outcome=JobOutcome({"kind": "untrusted_text", "value": "late"}),
            now=now,
        )
    assert jobs.journal.get_job(old["id"]) == new
