from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from provelume.maintenance import MaintenanceManager
from provelume.scheduler import (
    SchedulerCoordinator,
    _receipt_matches_terminal_job,
    scheduler_state_findings,
)
from provelume.scheduler_control import public_control_progress
from provelume.scheduler_model import (
    SchedulerConflictError,
    SchedulerError,
    retry_payload,
    schedule_payload,
    utc_instant,
    validate_job_record,
)
from provelume.service import ProvelumeInstance


@pytest.mark.parametrize("candidate_damage", ["missing", "corrupt"])
def test_explicit_resume_denies_lost_candidate_and_fresh_restart_preserves_parent(
    tmp_path, monkeypatch, candidate_damage
):
    instance, coordinator, job = fixture(tmp_path)
    stopped = []

    def stop(_manager, record):
        if record["cursor"] == 1 and not stopped:
            stopped.append(command(coordinator, job["id"], "pause", "pause"))

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", stop)
    assert coordinator.run_one(job_id=job["id"])["status"] == "paused"
    manager = MaintenanceManager(instance.store)
    run = manager.run_for_job(job["id"])
    candidate, _ = manager._candidate_paths(run)
    if candidate_damage == "missing":
        candidate.unlink()
    else:
        candidate.write_bytes(b"synthetic damaged candidate")
    preserved = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in instance.root.rglob("*")
        if path.is_file()
    }
    view = coordinator.job_capabilities(job["id"])
    assert view["unavailable"]["resume"] == "checkpoint_changed"
    assert "restart" in view["actions"]
    assert preserved == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in instance.root.rglob("*")
        if path.is_file()
    }
    restarted = command(coordinator, job["id"], "restart", "fresh")
    child = restarted["successor"]
    assert restarted["job"]["attempt"] == 1 and child["attempt"] == 0
    assert coordinator.run_one(job_id=child["id"])["status"] == "succeeded"
    assert manager.run_for_job(job["id"]) == run


def test_restart_lineage_tampering_denies_claim_and_is_a_validation_finding(tmp_path):
    instance, coordinator, job = fixture(tmp_path)
    command(coordinator, job["id"], "pause", "pause")
    child = command(coordinator, job["id"], "restart", "fresh")["successor"]
    path = coordinator.journal.jobs / (child["id"] + ".json")
    damaged = json.loads(path.read_text())
    damaged["retry"]["max_attempts"] = 8
    path.write_text(json.dumps(damaged))
    before = path.read_bytes()
    assert any(
        row["code"] == "scheduler_restart_lineage_invalid"
        for row in scheduler_state_findings(instance.store)
    )
    with pytest.raises(SchedulerConflictError, match="lineage"):
        coordinator.journal.claim_next(worker_id="test", job_id=child["id"])
    assert path.read_bytes() == before


def test_progress_unit_is_bound_to_capable_executor(tmp_path, monkeypatch):
    _instance, coordinator, job = fixture(tmp_path)

    def stop(_manager, record):
        command(coordinator, job["id"], "pause", "pause")

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", stop)
    result = coordinator.run_one(job_id=job["id"])
    damaged = copy.deepcopy(result)
    damaged["control"]["observation"]["unit"] = "source_items"
    with pytest.raises(SchedulerError, match="observation"):
        validate_job_record(damaged)


def fixture(tmp_path: Path, *, attempts=3):
    source = tmp_path / "s"
    source.mkdir()
    for index in range(3):
        (source / f"{index}.txt").write_text(f"synthetic cooperative document {index}")
    instance = ProvelumeInstance.initialise(tmp_path / "i", name="Control fixture")
    instance.ingest(source, source_name="Synthetic control source")
    coordinator = SchedulerCoordinator(instance.store)
    policy = coordinator.create_policy(
        job_kind="search.reindex",
        state="disabled",
        scope={"kind": "instance", "id": instance.instance_summary()["id"]},
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=attempts),
    )
    job = coordinator.run_now(policy["id"], request_key="initial")["job"]
    return instance, coordinator, job


def original_snapshot(instance):
    return {
        str(path.relative_to(instance.root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for root in (instance.root / "knowledge", instance.root / "originals")
        for path in root.rglob("*")
        if path.is_file()
    }


def command(coordinator, job_id, action, request_id):
    preview = coordinator.preview_job_control(job_id, action)
    return coordinator.control_job(
        job_id,
        action,
        expected_revision=preview["revision"],
        expected_checkpoint=preview["checkpoint"]
        if action in {"resume", "retry", "restart"}
        else None,
        request_id=request_id,
    )


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_real_reindex_stops_after_durable_cursor_without_activation(tmp_path, monkeypatch, action):
    instance, coordinator, job = fixture(tmp_path)
    before = original_snapshot(instance)
    database = instance.root / "indexes/search.sqlite3"
    active_before = database.read_bytes()
    accepted = []

    def stop(_manager, record):
        if record["cursor"] == 1 and not accepted:
            accepted.append(command(coordinator, job["id"], action, "stop"))

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", stop)
    result = coordinator.run_one(job_id=job["id"])
    assert accepted[0]["job"]["status"] == {"pause": "pausing", "cancel": "cancelling"}[action]
    assert result["status"] == {"pause": "paused", "cancel": "cancelled"}[action]
    assert result["lease"] is None
    run = MaintenanceManager(instance.store).run_for_job(job["id"])
    assert run["cursor"] == 1 and run["status"] == "building"
    assert database.read_bytes() == active_before
    assert original_snapshot(instance) == before
    if action == "pause":
        assert result["attempts"][-1]["outcome"] == "paused"
        assert public_control_progress(result)["total"] == 3
        assert public_control_progress(result)["rate_per_second"] is None
        resumed = SchedulerCoordinator(instance.store)
        command(resumed, job["id"], "resume", "resume")
        completed = resumed.run_one(job_id=job["id"])
        assert completed["status"] == "succeeded" and completed["attempt"] == 2
        assert completed["progress"]["processed"] == 3
        assert MaintenanceManager(instance.store).run_for_job(job["id"])["cursor"] == 3
        assert original_snapshot(instance) == before


def test_pause_queued_is_pure_until_command_and_never_auto_claimed(tmp_path):
    instance, coordinator, job = fixture(tmp_path)
    before = {p: p.read_bytes() for p in instance.root.rglob("*") if p.is_file()}
    preview = coordinator.preview_job_control(job["id"], "pause")
    assert public_control_progress(job)["total"] is None
    assert {p: p.read_bytes() for p in instance.root.rglob("*") if p.is_file()} == before
    first = coordinator.control_job(
        job["id"], "pause", expected_revision=preview["revision"], request_id="one"
    )
    assert first["job"]["status"] == "paused" and first["job"]["attempt"] == 0
    assert coordinator.run_one(job_id=job["id"]) is None
    replay = coordinator.control_job(
        job["id"], "pause", expected_revision=preview["revision"], request_id="one"
    )
    assert replay["replayed"] is True and replay["receipt"] == first["receipt"]
    with pytest.raises(SchedulerConflictError):
        coordinator.control_job(
            job["id"], "cancel", expected_revision=preview["revision"], request_id="one"
        )


def test_attempt_exhaustion_requires_explicit_linked_restart(tmp_path, monkeypatch):
    instance, coordinator, job = fixture(tmp_path, attempts=1)
    stopped = []

    def stop(_manager, _record):
        if not stopped:
            stopped.append(command(coordinator, job["id"], "pause", "stop"))

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", stop)
    parent = coordinator.run_one(job_id=job["id"])
    assert parent["status"] == "paused"
    caps = coordinator.job_capabilities(job["id"])
    assert "resume" not in caps["actions"] and caps["unavailable"]["resume"] == "attempts_exhausted"
    preview = coordinator.preview_job_control(job["id"], "restart")
    result = coordinator.control_job(
        job["id"], "restart", expected_revision=preview["revision"], request_id="fresh"
    )
    child = result["successor"]
    assert child["id"] != job["id"] and child["attempt"] == 0
    assert child["control"]["parent_job_id"] == job["id"]
    parent = coordinator.journal.get_job(job["id"])
    receipt = coordinator.journal.get_receipt(Path(parent["receipt_ref"]).stem)
    assert parent["status"] == "cancelled" and parent["attempt"] == 1
    assert _receipt_matches_terminal_job(receipt, parent)
    parent_receipt = copy.deepcopy(receipt)
    replay = coordinator.control_job(
        job["id"], "restart", expected_revision=preview["revision"], request_id="fresh"
    )
    assert replay["successor"]["id"] == child["id"] and replay["replayed"]
    assert coordinator.run_one(job_id=child["id"])["status"] == "succeeded"
    assert coordinator.journal.get_receipt(receipt["id"]) == parent_receipt


def test_commit_barrier_denies_late_pause_and_cancel(tmp_path, monkeypatch):
    instance, coordinator, job = fixture(tmp_path)
    real = MaintenanceManager._activate_generation
    observations = []

    def activate(manager, *args):
        caps = coordinator.job_capabilities(job["id"])
        assert caps["actions"] == []
        assert caps["unavailable"]["pause"] == "commit_started"
        with pytest.raises(SchedulerConflictError):
            coordinator.control_job(
                job["id"], "cancel", expected_revision=caps["revision"], request_id="late"
            )
        observations.append(True)
        return real(manager, *args)

    monkeypatch.setattr(MaintenanceManager, "_activate_generation", activate)
    result = coordinator.run_one(job_id=job["id"])
    assert result["status"] == "succeeded" and observations == [True]


def test_legacy_reads_and_bare_schema_promotion_fail_closed(tmp_path):
    _instance, coordinator, job = fixture(tmp_path)
    assert validate_job_record(job) == job and job["schema_version"] == 1
    with pytest.raises(SchedulerError):
        validate_job_record({**job, "schema_version": 2})
    controlled = command(coordinator, job["id"], "pause", "pause")["job"]
    # Paused records have no lease token to redact and remain full validation input.
    for broken in ({**controlled, "control": {}}, {**controlled, "schema_version": 1}):
        with pytest.raises(SchedulerError):
            validate_job_record(broken)


def test_external_process_intent_reaches_worker_holding_lifecycle(tmp_path, monkeypatch):
    instance, coordinator, job = fixture(tmp_path)
    outputs = []
    code = """
import json, sys
from provelume.scheduler import SchedulerCoordinator
from provelume.storage import InstanceStore
c = SchedulerCoordinator(InstanceStore(sys.argv[1]))
v = c.job_capabilities(sys.argv[2])
r = c.control_job(sys.argv[2], 'pause', expected_revision=v['revision'], request_id='process')
print(json.dumps({'status': r['job']['status']}))
"""

    def boundary(_manager, record):
        if record["cursor"] == 1:
            result = subprocess.run(
                [sys.executable, "-B", "-c", code, str(instance.root), job["id"]],
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            outputs.append(json.loads(result.stdout))

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", boundary)
    assert coordinator.run_one(job_id=job["id"])["status"] == "paused"
    assert outputs == [{"status": "pausing"}]


@pytest.mark.parametrize("action", ["cancel", "restart"])
def test_command_reconciles_crash_after_terminal_receipt_or_before_child(
    tmp_path, monkeypatch, action
):
    instance, coordinator, job = fixture(tmp_path)
    if action == "restart":
        command(coordinator, job["id"], "pause", "pause")
    preview = coordinator.preview_job_control(job["id"], action)
    real = coordinator.journal._write_job
    injected = []

    def interrupted(record):
        if not injected and (
            (action == "cancel" and record["status"] == "cancelled")
            or (action == "restart" and record["id"] != job["id"])
        ):
            injected.append(True)
            raise OSError("synthetic interruption after durable intent")
        return real(record)

    monkeypatch.setattr(coordinator.journal, "_write_job", interrupted)
    with pytest.raises(OSError, match="synthetic interruption"):
        coordinator.control_job(
            job["id"], action, expected_revision=preview["revision"], request_id="crash"
        )
    recovered = SchedulerCoordinator(instance.store)
    recovered.recover()
    result = recovered.control_job(
        job["id"], action, expected_revision=preview["revision"], request_id="crash"
    )
    assert result["replayed"] is True and result["job"]["status"] == "cancelled"
    if action == "restart":
        assert (
            len(
                [
                    row
                    for row in recovered.journal.list_jobs()
                    if row.get("control", {}).get("parent_job_id") == job["id"]
                ]
            )
            == 1
        )
        assert recovered.run_one(job_id=result["successor"]["id"])["status"] == "succeeded"


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_expired_worker_honors_pending_intent_without_reclaim(tmp_path, action):
    instance, coordinator, queued = fixture(tmp_path)
    now = utc_instant()
    running = coordinator.journal.claim_next(
        worker_id="expired-fixture", job_id=queued["id"], lease_seconds=1, now=now
    )
    command(coordinator, running["id"], action, "pending")
    SchedulerCoordinator(instance.store).recover(now=now + timedelta(seconds=2))
    result = coordinator.journal.get_job(running["id"])
    assert result["status"] == {"pause": "paused", "cancel": "cancelled"}[action]
    assert result["attempt"] == 1 and result["lease"] is None
    assert (
        coordinator.journal.claim_next(
            worker_id="new", now=now + timedelta(seconds=3), job_id=result["id"]
        )
        is None
    )


def test_retry_honors_retry_instant_and_same_bounded_attempts(tmp_path):
    _instance, coordinator, queued = fixture(tmp_path)
    now = utc_instant()
    running = coordinator.journal.claim_next(
        worker_id="retry-fixture", job_id=queued["id"], now=now
    )
    waiting = coordinator.journal.fail(
        running["id"],
        running["lease"]["token"],
        error_class="transient",
        error_code="local_io",
        progress=running["progress"],
        now=now,
    )
    caps = coordinator.job_capabilities(waiting["id"], now=now)
    assert caps["unavailable"]["retry"] == "retry_not_before"
    due = utc_instant(waiting["retry_not_before"])
    preview = coordinator.preview_job_control(waiting["id"], "retry", now=due)
    result = coordinator.control_job(
        waiting["id"], "retry", expected_revision=preview["revision"], request_id="retry", now=due
    )
    assert result["job"]["attempt"] == 1 and result["job"]["status"] == "queued"
    claimed = coordinator.journal.claim_next(
        worker_id="retry-fixture", job_id=queued["id"], now=due
    )
    assert claimed["attempt"] == 2 and len(claimed["attempts"]) == 2


def test_control_history_bound_is_durable_and_does_not_prune(tmp_path):
    _instance, coordinator, job = fixture(tmp_path)
    from provelume.scheduler_control import digest, promote

    full = promote(job)
    full["control"]["revision"] = 128
    full["control"]["commands"] = [
        {
            "request_digest": digest(index),
            "payload_digest": digest([index]),
            "action": "pause",
            "expected_revision": digest(job),
            "result_status": "paused",
            "accepted_at": job["created_at"],
            "successor_id": None,
        }
        for index in range(128)
    ]
    coordinator.journal._write_job(full)
    caps = coordinator.job_capabilities(job["id"])
    assert caps["actions"] == [] and set(caps["unavailable"].values()) == {"control_history_full"}
    with pytest.raises(SchedulerConflictError):
        coordinator.control_job(
            job["id"], "cancel", expected_revision=caps["revision"], request_id="overflow"
        )
    assert len(coordinator.journal.get_job(job["id"])["control"]["commands"]) == 128
