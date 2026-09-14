from __future__ import annotations

import pytest

from provelume.maintenance import MaintenanceManager
from provelume.maintenance_targets import LocalTargetRegistry, MaintenanceTargetError
from provelume.scheduler import SchedulerCoordinator
from provelume.scheduler_model import SchedulerConflictError, SchedulerError, schedule_payload
from provelume.service import ProvelumeInstance


def fixture(tmp_path, kind="maintenance.validate"):
    instance = ProvelumeInstance.initialise(tmp_path / "i", name="Reviewed plan fixture")
    scheduler = SchedulerCoordinator(instance.store)
    policy = scheduler.create_policy(
        job_kind=kind,
        state="disabled",
        scope={"kind": "instance", "id": instance.instance_summary()["id"]},
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )
    return instance, scheduler, policy


def test_all_instance_maintenance_previews_state_actual_observation_scope(tmp_path):
    instance, _scheduler, _policy = fixture(tmp_path)
    manager = MaintenanceManager(instance.store)
    for kind in (
        "search.reindex.full",
        "search.reindex.incremental",
        "maintenance.library_rebuild",
        "maintenance.validate",
        "maintenance.original_assurance",
        "maintenance.duplicate_scan",
        "maintenance.resource_snapshot",
    ):
        preview = manager.plan_action(kind, parameters={})
        assert preview["scope"] == {"kind": "instance", "id": instance.instance_summary()["id"]}
        assert preview["authority"] and preview["estimate"]["count_relation"] == "exact"
        assert preview["execution_plan"]["plan_revision"] == preview["plan_revision"]
        if not kind.startswith("search.reindex"):
            assert preview["estimate"]["total_work_relation"] == "unknown"
            assert preview["estimate"]["temporary_bytes_required"] is None
    assert manager.catalog(include_explicit=True)[-1]["schedulable"] is False


def test_reviewed_plan_is_immutable_rechecked_and_replay_cannot_change_payload(tmp_path):
    instance, scheduler, policy = fixture(tmp_path)
    manager = MaintenanceManager(instance.store)
    preview = manager.plan_action("maintenance.validate", parameters={})
    job = scheduler.run_now(
        policy["id"],
        parameters={},
        expected_plan_revision=preview["plan_revision"],
        request_key="reviewed",
    )["job"]
    assert job["schema_version"] == 2 and job["execution_plan"] == preview["execution_plan"]
    assert scheduler.run_one(job_id=job["id"])["status"] == "succeeded"
    assert (
        scheduler.run_now(
            policy["id"],
            parameters={},
            expected_plan_revision=preview["plan_revision"],
            request_key="reviewed",
        )["created"]
        is False
    )
    with pytest.raises(SchedulerError):
        scheduler.run_now(policy["id"], request_key="reviewed")


def test_mutated_canonical_input_denies_pre_execution_without_running_old_plan(tmp_path):
    instance, scheduler, policy = fixture(tmp_path)
    preview = MaintenanceManager(instance.store).plan_action("maintenance.validate", parameters={})
    job = scheduler.run_now(
        policy["id"],
        parameters={},
        expected_plan_revision=preview["plan_revision"],
        request_key="reviewed",
    )["job"]
    source = tmp_path / "source"
    source.mkdir()
    (source / "new.txt").write_text("new synthetic input after confirmation")
    instance.ingest(source, source_name="Synthetic new input")
    with pytest.raises(SchedulerConflictError):
        scheduler.run_now(
            policy["id"],
            parameters={},
            expected_plan_revision=preview["plan_revision"],
            request_key="stale",
        )
    result = scheduler.run_one(job_id=job["id"])
    assert result["status"] == "manual_intervention"
    assert result["progress"]["errors"] == 1


@pytest.mark.parametrize("change_archive", [False, True])
def test_actual_backup_job_checks_exact_registered_archive_and_owns_receipt(
    tmp_path, change_archive
):
    instance, scheduler, policy = fixture(tmp_path, "maintenance.backup_verify")
    archive = tmp_path / "before.zip"
    instance.backup(destination=archive)
    target = LocalTargetRegistry(instance.store).register_archive(archive)
    parameters = {key: target[key] for key in ("target_ref", "target_revision")}
    preview = MaintenanceManager(instance.store).plan_action(
        "maintenance.backup_verify", parameters=parameters
    )
    assert preview["estimate"]["bytes"] == archive.stat().st_size
    job = scheduler.run_now(
        policy["id"],
        parameters=parameters,
        expected_plan_revision=preview["plan_revision"],
        request_key="verify",
    )["job"]
    if change_archive:
        archive.write_bytes(archive.read_bytes() + b"synthetic changed input")
    result = scheduler.run_one(job_id=job["id"])
    assert result["status"] == ("manual_intervention" if change_archive else "succeeded")
    receipts = [r for r in scheduler.journal.list_receipts() if r["job_id"] == job["id"]]
    assert len(receipts) == 1 and receipts[0]["network_used"] is False
    assert receipts[0]["canonical_mutation"] is False


def test_backup_policy_cannot_schedule_without_a_reviewed_immutable_target(tmp_path):
    _instance, scheduler, policy = fixture(tmp_path, "maintenance.backup_verify")
    with pytest.raises(ValueError):
        scheduler.run_now(policy["id"], request_key="missing-target")
    with pytest.raises(SchedulerError, match="explicit manual plan"):
        scheduler.journal.update_policy(
            policy["id"],
            schedule=schedule_payload(mode="interval", timezone="UTC", interval_seconds=60),
            state="enabled",
        )


def test_backup_capability_admits_only_a_verified_explicit_target(tmp_path):
    instance, _scheduler, _policy = fixture(tmp_path, "maintenance.backup_verify")
    manager = MaintenanceManager(instance.store)
    action_id = "maintenance.backup_verify"
    for item in (
        manager.action(action_id),
        next(row for row in manager.catalog() if row["id"] == action_id),
        next(row for row in manager.catalog(include_explicit=True) if row["id"] == action_id),
    ):
        assert item["available"] is False and item["schedulable"] is False
    archive = tmp_path / "selected.zip"
    instance.backup(destination=archive)
    target = LocalTargetRegistry(instance.store).register_archive(archive)
    parameters = {key: target[key] for key in ("target_ref", "target_revision")}
    for item in (
        manager.action(action_id, parameters=parameters),
        next(
            row
            for row in manager.catalog(include_explicit=True, parameters=parameters)
            if row["id"] == action_id
        ),
    ):
        assert item["available"] is True and item["schedulable"] is True
        assert item["scheduler_job_kind"] == action_id and item["unavailable_reason"] is None
    stale = {**parameters, "target_revision": "0" * 64}
    with pytest.raises(MaintenanceTargetError):
        manager.action(action_id, parameters=stale)
    with pytest.raises(MaintenanceTargetError):
        manager.catalog(include_explicit=True, parameters=stale)
