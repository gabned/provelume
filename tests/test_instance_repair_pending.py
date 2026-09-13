from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_instance_repair import apply, files, prepared
from test_instance_repair import damaged as damaged_fixture

from provelume.instance_repair import InstanceRepairError, InstanceRepairManager
from provelume.instance_repair_model import encoded
from provelume.instance_validation import inspect_instance
from provelume.scheduler import SchedulerStore
from provelume.scheduler_model import SchedulerBusyError

damaged = damaged_fixture


def interrupted(damaged, monkeypatch, *, operation="apply", phase="prepared", before=False):
    instance, manager, _, _, _ = damaged
    plan, backup = prepared(damaged)
    origin = apply(manager, plan, backup) if operation == "rollback" else None

    def crash(*_args):
        raise SystemExit("synthetic process interruption")

    with monkeypatch.context() as patch:
        patch.setattr(manager, "_move" if before else (
            "_after_move" if phase == "prepared" else "_finish"
        ), crash)
        with pytest.raises(SystemExit):
            if origin is None:
                apply(manager, plan, backup)
            else:
                manager.rollback(
                    origin["receipt_id"], origin["output_revision"], "rollback", confirm=True
                )
    return InstanceRepairManager(instance.store), backup


def all_files(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("operation", ["apply", "rollback"])
@pytest.mark.parametrize("phase", ["prepared", "committed"])
def test_reviewed_recovery_exact_outcome_pure_preview_and_durable_replay(
    damaged, monkeypatch, tmp_path, operation, phase
):
    instance, _, artifact, target, _ = damaged
    manager, _ = interrupted(damaged, monkeypatch, operation=operation, phase=phase)
    before = all_files(tmp_path)
    pending = json.loads(manager.pending_path.read_bytes())
    view = manager.preview_pending_recovery()
    assert view["status"] == "eligible", view
    assert view["phase"] == phase and view["operation"] == operation
    assert all_files(tmp_path) == before
    assert view["receipt_id"] == pending["receipt"]["receipt_id"]
    expected_valid = (operation == "apply") == (phase == "committed")
    assert view["resulting_validation_status"] == ("valid" if expected_valid else "invalid")
    outcome = manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    assert outcome == view["binding"]["expected_receipt"]
    assert outcome["request_id"] == pending["receipt"]["request_id"]
    assert outcome["receipt_id"] == pending["receipt"]["receipt_id"]
    assert artifact.exists() is not expected_valid
    if artifact.exists():
        assert artifact.read_bytes() == target.read_bytes()
    assert inspect_instance(instance.root, deep=True)["status"] == outcome[
        "resulting_validation_status"
    ]
    assert not manager.pending_path.exists()
    restarted = InstanceRepairManager(instance.store)
    assert (
        restarted.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
        == outcome
    )
    assert restarted.preview_pending_recovery()["status"] == "none"


def test_prepared_before_move_finishes_without_rename(damaged, monkeypatch):
    manager, _ = interrupted(damaged, monkeypatch, before=True)
    view = manager.preview_pending_recovery()
    assert view["status"] == "eligible" and view["binding"]["source_present"] is True
    monkeypatch.setattr(manager, "_move", lambda *_args: pytest.fail("already in before position"))
    result = manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    assert result["status"] == "repair_failed_restored"


@pytest.mark.parametrize("crash_after_finish", [False, True])
def test_reviewed_recovery_crash_resumes_only_original_authorization(
    damaged, monkeypatch, crash_after_finish
):
    instance, _, artifact, _, _ = damaged
    manager, _ = interrupted(damaged, monkeypatch)
    view = manager.preview_pending_recovery()
    real_finish = manager._finish

    def crash(pending):
        if crash_after_finish:
            real_finish(pending)
        raise SystemExit("recovery interrupted before response")

    monkeypatch.setattr(manager, "_finish", crash)
    with pytest.raises(SystemExit):
        manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    assert artifact.exists()
    restarted = InstanceRepairManager(instance.store)
    monkeypatch.setattr(restarted, "_move", lambda *_args: pytest.fail("second compensation"))
    result = restarted.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    assert result == view["binding"]["expected_receipt"]
    assert not restarted.pending_path.exists()


def test_no_pending_and_unconfirmed_request_do_not_create_control_files(damaged, tmp_path):
    _, manager, _, _, _ = damaged
    before = all_files(tmp_path)
    assert manager.preview_pending_recovery() == {
        "schema_version": 1, "status": "none", "reason": "no_pending_repair"
    }
    with pytest.raises(InstanceRepairError, match="explicit_confirmation_required"):
        manager.recover_pending_reviewed("0" * 64, "review")
    assert all_files(tmp_path) == before
    with pytest.raises(InstanceRepairError, match="no_pending_repair"):
        manager.recover_pending_reviewed("0" * 64, "review", confirm=True)
    assert not manager.root.exists()


@pytest.mark.parametrize("change", ["pending", "context", "capsule", "position"])
def test_changed_review_never_authorizes_recovery(damaged, monkeypatch, change):
    instance, _, artifact, target, _ = damaged
    manager, backup = interrupted(damaged, monkeypatch)
    view = manager.preview_pending_recovery()
    if change == "pending":
        pending = json.loads(manager.pending_path.read_bytes())
        pending["receipt"]["created_at"] = "2026-09-13T00:00:00+00:00"
        manager.pending_path.write_bytes(encoded(pending))
    elif change == "context":
        target.write_bytes(target.read_bytes() + b" ")
    elif change == "capsule":
        Path(backup["archive_path"]).write_bytes(b"changed archive")
    else:
        artifact.write_bytes(b"conflicting destination")
    before, controls = files(instance.root), files(manager.root)
    with pytest.raises(InstanceRepairError):
        manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    assert files(instance.root) == before and files(manager.root) == controls
    assert manager.pending_path.exists()


@pytest.mark.parametrize("contents", [b"partial", b"{}", b'{"schema_version":2}', b"null"])
def test_corrupt_pending_stays_unavailable_without_writes(damaged, contents, tmp_path):
    _, manager, _, _, _ = damaged
    manager.root.mkdir(parents=True)
    manager.pending_path.write_bytes(contents)
    before = all_files(tmp_path)
    assert manager.preview_pending_recovery()["status"] == "unavailable"
    assert all_files(tmp_path) == before


def test_pending_preview_detects_drift_after_first_position_check(damaged, monkeypatch):
    manager, _ = interrupted(damaged, monkeypatch)
    original = manager._position
    calls = []

    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calls:
            calls.append(1)
            manager.pending_path.write_bytes(manager.pending_path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(manager, "_position", change)
    view = manager.preview_pending_recovery()
    assert view["status"] == "unavailable" and view["reason"] == "snapshot_changed"


def test_busy_scheduler_denies_reviewed_recovery(damaged, monkeypatch):
    instance, _, _, _, _ = damaged
    manager, _ = interrupted(damaged, monkeypatch)
    view = manager.preview_pending_recovery()
    before = files(instance.root)
    with SchedulerStore(instance.store).hold(), pytest.raises(SchedulerBusyError):
        manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    assert manager.pending_path.exists() and files(instance.root) == before


def test_historical_replay_never_recovers_a_new_pending(damaged, monkeypatch):
    instance, _, _, _, relative = damaged
    manager, backup = interrupted(damaged, monkeypatch)
    view = manager.preview_pending_recovery()
    result = manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    new_plan = manager.preview("repair.maintenance_redundant_atomic_artifact", relative)

    def crash(_operation):
        raise SystemExit("different newly confirmed repair")

    monkeypatch.setattr(manager, "_after_move", crash)
    with pytest.raises(SystemExit):
        apply(manager, new_plan, backup, request="new-apply")
    before, controls = files(instance.root), files(manager.root)
    assert (
        manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True) == result
    )
    assert files(instance.root) == before and files(manager.root) == controls
    with pytest.raises(InstanceRepairError, match="request_conflict"):
        manager.recover_pending_reviewed("0" * 64, "review", confirm=True)


def test_foreign_reviewed_request_never_returns_other_instance_receipt(damaged, monkeypatch):
    instance, _, _, _, _ = damaged
    manager, _ = interrupted(damaged, monkeypatch)
    view = manager.preview_pending_recovery()
    manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    from provelume.service import ProvelumeInstance

    other = ProvelumeInstance.initialise(instance.root.parent / "other")
    foreign = InstanceRepairManager(other.store)
    source = next((manager.root / "recovery-requests").glob("*.json"))
    destination = foreign.root / "recovery-requests" / source.name
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())
    with pytest.raises(InstanceRepairError, match="foreign_recovery_request"):
        foreign.recover_pending_reviewed(view["input_revision"], "review", confirm=True)


def test_owner_read_rejects_pending_replaced_after_review_authorization(damaged, monkeypatch):
    instance, _, artifact, _, _ = damaged
    manager, _ = interrupted(damaged, monkeypatch)
    view = manager.preview_pending_recovery()
    write = manager._write

    def replace(path, value, **kwargs):
        write(path, value, **kwargs)
        if path.parent.name == "recovery-requests":
            manager.pending_path.write_bytes(manager.pending_path.read_bytes() + b" ")

    monkeypatch.setattr(manager, "_write", replace)
    before = files(instance.root)
    with pytest.raises(InstanceRepairError, match="stale_pending_recovery"):
        manager.recover_pending_reviewed(view["input_revision"], "review", confirm=True)
    assert not artifact.exists() and files(instance.root) == before
    assert manager.pending_path.exists()
