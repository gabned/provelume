from __future__ import annotations

import json

import pytest

from provelume.scheduler import SchedulerCoordinator
from provelume.scheduler_control import public_control_progress
from provelume.scheduler_model import schedule_payload
from provelume.service import ProvelumeInstance
from provelume.source_reconciliation import SourceReconciliationManager
from provelume.storage import CANONICAL_KINDS


def fixture(tmp_path, *, source_class="local"):
    folder = tmp_path / "source"
    folder.mkdir()
    for index in range(3):
        (folder / f"{index}.txt").write_text(f"synthetic Source {index}")
    instance = ProvelumeInstance.initialise(tmp_path / "i", name="Cooperative Source")
    source = instance.register_folder_source(
        folder,
        name="Synthetic Source",
        source_class=source_class,
        quiescence_seconds=0,
        stable_observations=1,
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )
    assert (
        instance.refresh_folder_source(source["id"], request_key="seed")["job"]["status"]
        == "succeeded"
    )
    coordinator = SchedulerCoordinator(instance.store)
    policy = coordinator.create_policy(
        job_kind="maintenance.source_reconcile",
        state="disabled",
        scope={"kind": "source", "id": source["id"]},
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )
    job = coordinator.run_now(policy["id"], request_key="reconcile")["job"]
    return instance, folder, coordinator, job


def command(coordinator, job, action, request):
    preview = coordinator.preview_job_control(job["id"], action)
    return coordinator.control_job(
        job["id"], action, expected_revision=preview["revision"], request_id=request
    )


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_source_stops_at_real_cursor_and_preserves_canonical_inputs(tmp_path, monkeypatch, action):
    instance, _folder, coordinator, job = fixture(tmp_path, source_class="network")
    before = json.dumps(
        {kind: instance.store.list_canonical(kind) for kind in CANONICAL_KINDS}, sort_keys=True
    )
    called = []

    def stop(_manager, run):
        if run["cursor"] == 1 and not called:
            called.append(command(coordinator, job, action, "stop"))

    monkeypatch.setattr(SourceReconciliationManager, "_after_item_checkpoint", stop)
    result = coordinator.run_one(job_id=job["id"])
    assert result["status"] == {"pause": "paused", "cancel": "cancelled"}[action]
    run = SourceReconciliationManager(instance.store).run_for_job(job["id"])
    assert run["cursor"] == 1 and run["status"] != "completed"
    assert public_control_progress(result)["total"] == len(run["plan"]["items"])
    if action == "pause":
        restarted = SchedulerCoordinator(instance.store)
        command(restarted, job, "resume", "resume")
        completed = restarted.run_one(job_id=job["id"])
        assert completed["status"] == "succeeded" and completed["progress"]["processed"] == 3
    else:
        receipt = coordinator.journal.get_receipt("receipt_" + job["id"][4:])
        assert receipt["network_used"] is True and receipt["canonical_mutation"] is False
    assert (
        json.dumps(
            {kind: instance.store.list_canonical(kind) for kind in CANONICAL_KINDS}, sort_keys=True
        )
        == before
    )


def test_pause_during_discovery_has_unknown_total_and_rescans_on_resume(tmp_path, monkeypatch):
    instance, _folder, coordinator, job = fixture(tmp_path)
    scan = SourceReconciliationManager._scan_rows
    requested = []

    def pause_before_chunks(manager, *args, **kwargs):
        if not requested and hasattr(manager, "_control_poll"):
            requested.append(command(coordinator, job, "pause", "discovery"))
        return scan(manager, *args, **kwargs)

    monkeypatch.setattr(SourceReconciliationManager, "_scan_rows", pause_before_chunks)
    stopped = coordinator.run_one(job_id=job["id"])
    assert stopped["status"] == "paused" and stopped["recovery_state"] == "restart_only"
    assert SourceReconciliationManager(instance.store).run_for_job(job["id"]) is None
    assert public_control_progress(stopped)["total"] is None
    command(coordinator, job, "resume", "resume")
    assert coordinator.run_one(job_id=job["id"])["status"] == "succeeded"


def test_changed_source_requires_fresh_restart_instead_of_claiming_exact_resume(
    tmp_path, monkeypatch
):
    _instance, folder, coordinator, job = fixture(tmp_path)
    called = []

    def stop(_manager, _run):
        if not called:
            called.append(command(coordinator, job, "pause", "pause"))

    monkeypatch.setattr(SourceReconciliationManager, "_after_item_checkpoint", stop)
    assert coordinator.run_one(job_id=job["id"])["status"] == "paused"
    (folder / "0.txt").write_text("changed synthetic source bytes")
    caps = coordinator.job_capabilities(job["id"])
    assert "resume" not in caps["actions"] and caps["unavailable"]["resume"] == "checkpoint_changed"
    fresh = command(coordinator, job, "restart", "fresh")["successor"]
    assert coordinator.run_one(job_id=fresh["id"])["status"] == "succeeded"
