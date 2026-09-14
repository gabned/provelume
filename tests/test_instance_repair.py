from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from provelume.instance_backup import BackupError, create_backup
from provelume.instance_lifecycle import InstanceLifecycleError, InstanceLifecycleManager
from provelume.instance_repair import REPAIR_PROFILE, InstanceRepairError, InstanceRepairManager
from provelume.instance_repair_backup import verify_capsule
from provelume.instance_repair_model import encoded
from provelume.instance_validation import inspect_instance
from provelume.scheduler import SchedulerStore
from provelume.scheduler_model import SchedulerBusyError
from provelume.service import ProvelumeInstance


def files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and "locks" not in path.parts
    }


@pytest.fixture
def damaged(tmp_path: Path):
    instance = ProvelumeInstance.initialise(tmp_path / "i", name="Synthetic repair")
    source = tmp_path / "s.txt"
    source.write_text("A synthetic retained Original.\n", encoding="utf-8")
    instance.ingest(source, source_name="Repair fixture")
    job = instance.run_maintenance_action("search.reindex.full", request_key="repair-seed")["job"]
    assert job["status"] == "succeeded"
    run = instance.maintenance.run_for_job(job["id"])
    target = instance.root / f"state/maintenance/reindex-runs/{run['id']}.json"
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    artifact = target.with_name("." + target.name + ".stranded")
    artifact.write_bytes(target.read_bytes())
    report = inspect_instance(instance.root, deep=True)
    assert report["status"] == "invalid" and report["content_fingerprint"] is None
    assert len(report["errors"]) == 1
    assert report["errors"][0]["code"] == "maintenance_record_invalid"
    manager = InstanceRepairManager(instance.store)
    relative = artifact.relative_to(instance.root).as_posix()
    return instance, manager, artifact, target, relative


def prepared(damaged):
    _, manager, _, _, relative = damaged
    plan = manager.preview(REPAIR_PROFILE, relative)
    assert plan["status"] == "eligible", plan
    backup = manager.prepare_backup(plan, "prepare")
    assert backup["verified"] is True
    return plan, backup


def apply(manager, plan, backup, request="apply"):
    return manager.apply(
        backup["backup_id"], plan["input_revision"], request, backup["archive_sha256"], confirm=True
    )


def test_actual_repair_backup_confirmation_replay_and_explicit_rollback(damaged, tmp_path):
    instance, manager, artifact, target, relative = damaged
    before = files(instance.root)
    controls = files(manager.lifecycle.control_root)
    preview = manager.preview(REPAIR_PROFILE, relative)
    assert preview["status"] == "eligible"
    assert files(instance.root) == before
    assert files(manager.lifecycle.control_root) == controls
    with pytest.raises(BackupError):
        create_backup(instance.store, destination=tmp_path / "ordinary.zip")
    plan, backup = prepared(damaged)
    assert files(instance.root) == before
    assert manager.prepare_backup(plan, "prepare") == backup
    with pytest.raises(InstanceRepairError, match="explicit_confirmation_required"):
        manager.apply(
            backup["backup_id"], plan["input_revision"], "apply", backup["archive_sha256"]
        )
    result = apply(manager, plan, backup)
    assert result["status"] == "repaired"
    assert result["resulting_validation_status"] == "valid"
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    expected = dict(before)
    expected.pop(str(artifact.relative_to(instance.root)))
    assert files(instance.root) == expected
    assert Path(backup["quarantine_path"]).read_bytes() == target.read_bytes()
    snapshot = files(manager.lifecycle.control_root)
    assert apply(manager, plan, backup) == result
    # Lifecycle lock metadata is an explicit operational write, receipts/capsule are stable.
    assert {
        k: v for k, v in files(manager.lifecycle.control_root).items() if k != "lifecycle.lock.json"
    } == {k: v for k, v in snapshot.items() if k != "lifecycle.lock.json"}
    rollback = manager.preview_rollback(result["receipt_id"])
    assert rollback["resulting_validation_status"] == "invalid"
    restored = manager.rollback(
        result["receipt_id"], rollback["input_revision"], "rollback", confirm=True
    )
    assert restored["status"] == "rolled_back_to_pre_repair_invalid_state"
    assert files(instance.root) == before
    assert (
        manager.rollback(result["receipt_id"], rollback["input_revision"], "rollback", confirm=True)
        == restored
    )
    assert not manager.pending_path.exists()
    assert manager.blocked_path.exists()
    for _ in range(2):
        with pytest.raises(InstanceLifecycleError, match="known invalid"):
            InstanceLifecycleManager(instance.store).prepare()
    second = apply(manager, plan, backup, request="repair-again")
    assert second["status"] == "repaired"
    assert not manager.blocked_path.exists()


@pytest.mark.parametrize("contents", [b"partial", b"{}", b"", b"newer record"])
def test_different_or_partial_artifact_never_eligible(damaged, contents):
    _, manager, artifact, _, relative = damaged
    artifact.write_bytes(contents)
    assert manager.preview(REPAIR_PROFILE, relative)["reason"] == "artifact_not_identical"
    assert not manager.root.exists()


@pytest.mark.parametrize("change", ["target", "job", "receipt", "other_error"])
def test_stale_context_denied_before_move(damaged, change):
    instance, manager, artifact, target, _ = damaged
    plan, backup = prepared(damaged)
    if change == "target":
        target.write_bytes(target.read_bytes() + b" ")
    elif change in {"job", "receipt"}:
        row = next(row for row in plan["context"] if f"/{change}s/" in row["path"])
        path = instance.root / row["path"]
        path.write_bytes(path.read_bytes() + b" ")
    else:
        (target.parent / "unknown.txt").write_bytes(b"unrelated")
    before = files(instance.root)
    with pytest.raises(InstanceRepairError):
        apply(manager, plan, backup)
    assert artifact.exists() and files(instance.root) == before
    assert not manager.pending_path.exists()


def test_corrupt_backup_and_wrong_confirmation_digest_fail_closed(damaged):
    instance, manager, artifact, _, _ = damaged
    plan, backup = prepared(damaged)
    with pytest.raises(InstanceRepairError, match="backup_hash_mismatch"):
        manager.apply(
            backup["backup_id"], plan["input_revision"], "bad-hash", "0" * 64, confirm=True
        )
    archive = Path(backup["archive_path"])
    data = archive.read_bytes()
    archive.write_bytes(data[:50])
    before = files(instance.root)
    with pytest.raises(InstanceRepairError):
        apply(manager, plan, backup)
    assert files(instance.root) == before and artifact.exists()


def test_busy_scheduler_writer_denies_repair(damaged):
    instance, manager, artifact, _, _ = damaged
    plan, backup = prepared(damaged)
    with SchedulerStore(instance.store).hold(), pytest.raises(SchedulerBusyError):
        apply(manager, plan, backup)
    assert artifact.exists() and not manager.pending_path.exists()


def test_post_move_failure_compensates_exact_write_set(damaged, monkeypatch):
    instance, manager, _, _, _ = damaged
    plan, backup = prepared(damaged)
    before = files(instance.root)

    def fail(_operation):
        raise OSError("synthetic post-move verification failure")

    monkeypatch.setattr(manager, "_after_move", fail)
    result = apply(manager, plan, backup)
    assert result["status"] == "repair_failed_restored"
    assert result["error"] == "operation_failed_before_commit"
    assert result["resulting_validation_status"] == "invalid"
    assert files(instance.root) == before
    assert not manager.pending_path.exists()
    assert apply(manager, plan, backup) == result


@pytest.mark.parametrize("ordinary", ["prepare", "guard"])
def test_crash_recovers_before_ordinary_mutation_and_blocks_invalid_state(
    damaged, monkeypatch, ordinary
):
    instance, manager, artifact, _, _ = damaged
    plan, backup = prepared(damaged)
    before = files(instance.root)

    def crash(_operation):
        raise SystemExit("synthetic abrupt stop")

    monkeypatch.setattr(manager, "_after_move", crash)
    with pytest.raises(SystemExit):
        apply(manager, plan, backup)
    assert not artifact.exists() and manager.pending_path.exists()
    lifecycle = InstanceLifecycleManager(instance.store)
    with pytest.raises(InstanceLifecycleError, match="known invalid"):
        if ordinary == "prepare":
            lifecycle.prepare()
        else:
            with lifecycle._hold(purpose="synthetic-ordinary-mutation"):
                pytest.fail("ordinary mutation was allowed")
    assert artifact.exists() and files(instance.root) == before
    assert not manager.pending_path.exists()
    with pytest.raises(InstanceLifecycleError, match="known invalid"):
        lifecycle.prepare()


def test_committed_crash_finalizes_without_second_move(damaged, monkeypatch):
    instance, manager, artifact, _, _ = damaged
    plan, backup = prepared(damaged)

    def crash(_pending):
        raise SystemExit("synthetic after durable commit")

    monkeypatch.setattr(manager, "_finish", crash)
    with pytest.raises(SystemExit):
        apply(manager, plan, backup)
    assert manager.pending_path.exists() and not artifact.exists()
    recovered = InstanceRepairManager(instance.store).recover_pending()
    assert recovered["status"] == "repaired"
    assert not manager.pending_path.exists() and not artifact.exists()


def test_unknown_pending_and_conflicting_destination_preserve_evidence(damaged, monkeypatch):
    instance, manager, artifact, _, _ = damaged
    plan, backup = prepared(damaged)

    def crash(_operation):
        raise SystemExit("crash")

    monkeypatch.setattr(manager, "_after_move", crash)
    with pytest.raises(SystemExit):
        apply(manager, plan, backup)
    artifact.write_bytes(b"concurrent unknown bytes")
    before = files(instance.root)
    with pytest.raises(InstanceRepairError, match="uncertain_repair_effect"):
        InstanceRepairManager(instance.store).recover_pending()
    assert manager.pending_path.exists() and files(instance.root) == before


@pytest.mark.parametrize("entry", ["../escape", "affected.bin", "AFFECTED.BIN", "unlisted.bin"])
def test_archive_inventory_rejects_unlisted_duplicate_and_traversal(damaged, entry):
    _, _, _, _, _ = damaged
    _, backup = prepared(damaged)
    path = Path(backup["archive_path"])
    if entry == "affected.bin":
        with (
            pytest.warns(UserWarning, match="Duplicate name"),
            zipfile.ZipFile(path, "a") as archive,
        ):
            archive.writestr(entry, b"unsupported")
    else:
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr(entry, b"unsupported")
    with pytest.raises(InstanceRepairError):
        verify_capsule(path)


def test_rollback_refuses_changed_context_and_never_overwrites(damaged):
    instance, manager, artifact, _, _ = damaged
    plan, backup = prepared(damaged)
    result = apply(manager, plan, backup)
    artifact.write_bytes(b"a new file")
    before = files(instance.root)
    with pytest.raises(InstanceRepairError):
        manager.rollback(result["receipt_id"], result["output_revision"], "rollback", confirm=True)
    assert files(instance.root) == before


def test_pure_preview_denies_unrelated_pending_and_unsafe_paths(damaged):
    _, manager, _, _, relative = damaged
    assert manager.preview(REPAIR_PROFILE, "../" + relative)["status"] == "unavailable"
    manager.lifecycle.pending_path.write_text(json.dumps({"unknown": True}))
    assert manager.preview(REPAIR_PROFILE, relative)["reason"] == "other_recovery_pending"


def test_capacity_and_enumeration_limits_are_unavailable(damaged, monkeypatch):
    from provelume import instance_repair as module

    _, manager, _, _, relative = damaged
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
    assert manager.preview(REPAIR_PROFILE, relative)["reason"] == "insufficient_space"
    monkeypatch.setattr(module, "MAX_REPAIR_ENTRIES", 1)
    assert manager.preview(REPAIR_PROFILE, relative)["reason"] == "inventory_incomplete"
    assert not manager.root.exists()


def test_backup_from_another_instance_is_rejected_before_write(damaged, tmp_path):
    _, _, _, _, _ = damaged
    plan, backup = prepared(damaged)
    foreign = ProvelumeInstance.initialise(tmp_path / "foreign", name="Another synthetic Instance")
    manager = InstanceRepairManager(foreign.store)
    directory = manager.root / backup["backup_id"]
    directory.mkdir(parents=True)
    (directory / "before.zip").write_bytes(Path(backup["archive_path"]).read_bytes())
    before = files(foreign.root)
    with pytest.raises(InstanceRepairError, match="foreign_backup"):
        apply(manager, plan, backup)
    assert files(foreign.root) == before and not manager.pending_path.exists()


@pytest.mark.parametrize("phase", ["prepared", "committed"])
def test_partial_or_newer_pending_records_remain_blocked(damaged, phase):
    instance, manager, _, _, _ = damaged
    prepared(damaged)
    manager.pending_path.write_bytes(encoded({"schema_version": 2, "phase": phase}))
    before = files(instance.root)
    with pytest.raises(InstanceLifecycleError):
        InstanceLifecycleManager(instance.store).prepare()
    assert files(instance.root) == before and manager.pending_path.exists()


def test_crash_before_move_is_recovered_without_quarantine(damaged, monkeypatch):
    instance, manager, artifact, _, _ = damaged
    plan, backup = prepared(damaged)
    before = files(instance.root)

    def crash(_source, _target):
        raise SystemExit("before rename")

    monkeypatch.setattr(manager, "_move", crash)
    with pytest.raises(SystemExit):
        apply(manager, plan, backup)
    assert artifact.exists() and manager.pending_path.exists()
    result = InstanceRepairManager(instance.store).recover_pending()
    assert result["status"] == "repair_failed_restored"
    assert files(instance.root) == before


def test_crash_during_rollback_compensates_to_valid_repaired_state(damaged, monkeypatch):
    instance, manager, artifact, _, _ = damaged
    plan, backup = prepared(damaged)
    receipt = apply(manager, plan, backup)
    before = files(instance.root)

    def crash(_operation):
        raise SystemExit("after rollback rename")

    monkeypatch.setattr(manager, "_after_move", crash)
    with pytest.raises(SystemExit):
        manager.rollback(
            receipt["receipt_id"], receipt["output_revision"], "rollback", confirm=True
        )
    assert artifact.exists() and manager.pending_path.exists()
    recovered = InstanceRepairManager(instance.store).recover_pending()
    assert recovered["status"] == "rollback_failed_compensated"
    assert recovered["resulting_validation_status"] == "valid"
    assert not artifact.exists() and files(instance.root) == before


def test_same_request_cannot_authorize_a_different_binding(damaged):
    _, manager, _, _, _ = damaged
    plan, backup = prepared(damaged)
    receipt = apply(manager, plan, backup)
    with pytest.raises(InstanceRepairError, match="request_conflict"):
        manager.apply(
            backup["backup_id"], "0" * 64, "apply", backup["archive_sha256"], confirm=True
        )
    assert manager.get_receipt(receipt["receipt_id"]) == receipt


def test_real_live_scheduler_lease_denies_preview(damaged):
    instance, manager, _, _, relative = damaged
    queued = instance.queue_maintenance_action("search.reindex.full", request_key="live-writer")
    claimed = instance.scheduler.journal.claim_next(
        worker_id="repair-test", job_id=queued["job"]["id"]
    )
    assert claimed is not None and claimed["lease"] is not None
    before = files(instance.root)
    assert manager.preview(REPAIR_PROFILE, relative)["reason"] == "writer_active"
    assert files(instance.root) == before and not manager.root.exists()


@pytest.mark.parametrize("kind", ["directory", "oversized"])
def test_nonregular_and_oversized_artifact_is_unsupported(damaged, kind):
    from provelume.instance_repair_model import MAX_REPAIR_FILE_BYTES

    _, manager, artifact, _, relative = damaged
    artifact.unlink()
    if kind == "directory":
        artifact.mkdir()
    else:
        with artifact.open("wb") as handle:
            handle.truncate(MAX_REPAIR_FILE_BYTES + 1)
    assert manager.preview(REPAIR_PROFILE, relative)["status"] == "unavailable"
    assert not manager.root.exists()


def test_unknown_barrier_cannot_be_cleared_by_an_unrelated_repair(damaged):
    instance, manager, artifact, _, relative = damaged
    plan, backup = prepared(damaged)
    manager.blocked_path.write_bytes(encoded({"schema_version": 2, "unknown": "retained"}))
    before = files(instance.root)
    barrier = manager.blocked_path.read_bytes()
    assert manager.preview(REPAIR_PROFILE, relative)["reason"] == "invalid_repair_barrier"
    with pytest.raises(InstanceRepairError, match="invalid_repair_barrier"):
        apply(manager, plan, backup)
    assert artifact.exists() and files(instance.root) == before
    assert manager.blocked_path.read_bytes() == barrier
