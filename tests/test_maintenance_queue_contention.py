from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import provelume.instance_lifecycle as lifecycle
from provelume.instance_repair import InstanceRepairError, InstanceRepairManager
from provelume.scheduler import SchedulerStore, schedule_payload
from provelume.service import ProvelumeInstance
from provelume.web import create_app


@pytest.fixture
def instance(tmp_path):
    return ProvelumeInstance.initialise(tmp_path / "instance", name="Queue contention")


def source_app(instance, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    note = source / "note.txt"
    note.write_text("reviewed source", encoding="utf-8")
    registered = instance.register_folder_source(
        source,
        name="Reviewed Source",
        quiescence_seconds=0,
        stable_observations=1,
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )
    return create_app(instance.root), registered["id"], note


def hold_background_cycle(monkeypatch):
    entered, release, contended = (threading.Event() for _ in range(3))
    evaluate = SchedulerStore.evaluate
    acquire = lifecycle._acquire_os_lock

    def held_evaluate(self, *args, **kwargs):
        entered.set()
        assert release.wait(10), "test did not release the background cycle"
        return evaluate(self, *args, **kwargs)

    def observed_acquire(descriptor):
        try:
            return acquire(descriptor)
        except lifecycle.InstanceLifecycleBusy:
            contended.set()
            raise

    monkeypatch.setattr(SchedulerStore, "evaluate", held_evaluate)
    monkeypatch.setattr(lifecycle, "_acquire_os_lock", observed_acquire)
    return entered, release, contended


def confirmation(client, source_id, *, language="en"):
    page = client.get("/maintenance?lang=" + language)
    assert page.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token is not None
    return {
        "csrf_token": token.group(1),
        "action_id": "maintenance.source_reconcile",
        "source_id": source_id,
    }


@pytest.mark.parametrize("change_source", [False, True])
def test_queue_waits_for_real_cycle_and_revalidates_before_any_effect(
    instance, tmp_path, monkeypatch, change_source
):
    app, source_id, note = source_app(instance, tmp_path)
    policies_before = instance.list_schedule_policies()
    entered, release, contended = hold_background_cycle(monkeypatch)
    with TestClient(app) as client:
        try:
            assert entered.wait(5)
            data = confirmation(client, source_id)

            def release_on_contention():
                assert contended.wait(5), "queue did not encounter the real lifecycle lock"
                if change_source:
                    note.write_text("changed after preview", encoding="utf-8")
                release.set()

            with ThreadPoolExecutor(max_workers=1) as pool:
                released = pool.submit(release_on_contention)
                result = client.post("/maintenance?lang=en", data=data)
                released.result(timeout=5)
            assert contended.is_set()
            jobs = instance.list_scheduler_jobs()
            if change_source:
                assert result.status_code == 400
                assert "The reviewed inputs changed" in result.text
                assert jobs == []
                assert instance.list_schedule_policies() == policies_before
            else:
                assert result.status_code == 200
                assert len(jobs) == 1
                assert jobs[0]["job_kind"] == "maintenance.source_reconcile"
                assert jobs[0]["scope"] == {"kind": "source", "id": source_id}
                assert jobs[0]["execution_plan"]["parameters"] == {"source_id": source_id}
            assert client.post("/maintenance", data=data).status_code == 403
            assert instance.list_scheduler_jobs() == jobs
        finally:
            release.set()


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("en", "Another Instance operation is active. Load a new preview"),
        ("it", "Un’altra operazione dell’Instance è attiva. Carica una nuova anteprima"),
    ],
)
def test_sustained_contention_returns_busy_without_queue_or_automatic_replay(
    instance, tmp_path, monkeypatch, language, message
):
    app, source_id, _note = source_app(instance, tmp_path)
    policies_before = instance.list_schedule_policies()
    entered, release, contended = hold_background_cycle(monkeypatch)
    with TestClient(app) as client:
        try:
            assert entered.wait(5)
            data = confirmation(client, source_id, language=language)
            result = client.post("/maintenance?lang=" + language, data=data)
            assert contended.is_set()
            assert result.status_code == 409
            assert message in result.text
            assert instance.list_scheduler_jobs() == []
            assert instance.list_schedule_policies() == policies_before
            release.set()
            assert client.post("/maintenance", data=data).status_code == 403
            assert instance.list_scheduler_jobs() == []
        finally:
            release.set()


def test_other_lifecycle_operations_remain_immediate_and_never_sleep(instance, monkeypatch):
    manager = lifecycle.InstanceLifecycleManager(instance.store)

    def forbidden_sleep(_seconds):
        pytest.fail("default lifecycle acquisition waited")

    with manager._hold(purpose="held-operation"):
        monkeypatch.setattr(lifecycle, "sleep", forbidden_sleep)
        with (
            pytest.raises(lifecycle.InstanceLifecycleBusy),
            manager._hold(purpose="other-operation"),
        ):
            pytest.fail("conflicting operation entered")


@pytest.mark.parametrize(
    "budget", [-1, 2.01, float("inf"), float("nan"), True, "1", None, 10**1000]
)
def test_invalid_wait_budget_is_rejected(instance, budget):
    manager = lifecycle.InstanceLifecycleManager(instance.store)
    with (
        pytest.raises(ValueError, match="between zero and two seconds"),
        manager._hold(purpose="invalid-budget", wait_seconds=budget),
    ):
        pytest.fail("invalid wait budget entered the mutation body")


def test_body_failure_releases_lock_without_replaying_body(instance):
    manager = lifecycle.InstanceLifecycleManager(instance.store)
    entries = []
    with (
        pytest.raises(RuntimeError, match="body failed"),
        manager._hold(purpose="failing-body", wait_seconds=2),
    ):
        entries.append("entered")
        raise RuntimeError("body failed")
    with manager._hold(purpose="after-failure"):
        assert entries == ["entered"]


def test_recovery_barrier_failure_releases_lock_and_never_enters_body(instance, monkeypatch):
    manager = lifecycle.InstanceLifecycleManager(instance.store)
    monkeypatch.setattr(InstanceRepairManager, "has_recovery_barrier", lambda self: True)

    def failed_recovery(self):
        raise InstanceRepairError("diagnostic recovery failure")

    monkeypatch.setattr(InstanceRepairManager, "_recover_pending_locked", failed_recovery)
    with (
        pytest.raises(lifecycle.InstanceLifecycleError, match="repair recovery is pending"),
        manager._hold(purpose="barrier-test", wait_seconds=2),
    ):
        pytest.fail("recovery barrier allowed mutation")
    monkeypatch.setattr(InstanceRepairManager, "has_recovery_barrier", lambda self: False)
    with manager._hold(purpose="after-barrier-failure"):
        pass
