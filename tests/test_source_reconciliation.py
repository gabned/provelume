from __future__ import annotations

import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.maintenance_model import MaintenanceError
from provelume.scheduler import retry_payload, schedule_payload
from provelume.service import ProvelumeInstance
from provelume.source_reconciliation import SourceReconciliationManager
from provelume.source_reconciliation_model import (
    SOURCE_OPERATIONAL_STATES,
    SourceReconciliationStateError,
)
from provelume.storage import CANONICAL_KINDS
from provelume.web import create_app


def _canonical_snapshot(
    instance: ProvelumeInstance,
) -> dict[str, list[dict[str, object]]]:
    return {
        kind: instance.store.list_canonical(kind)
        for kind in CANONICAL_KINDS
    }


def _registered_instance(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    source_class: str = "local",
) -> tuple[ProvelumeInstance, Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    for locator, content in files.items():
        target = source / locator
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    instance = ProvelumeInstance.initialise(
        tmp_path / "instance",
        name="Source reconciliation fixture",
    )
    registered = instance.register_folder_source(
        source,
        name="Synthetic reconciliation Source",
        source_class=source_class,
        quiescence_seconds=0,
        stable_observations=1,
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )
    source_id = str(registered["id"])
    seeded = instance.refresh_folder_source(source_id, request_key="seed-canonical")
    assert seeded["job"]["status"] == "succeeded"
    return instance, source, source_id


def _run_reconciliation(
    instance: ProvelumeInstance,
    source_id: str,
    *,
    request_key: str,
) -> dict[str, object]:
    return instance.run_maintenance_action(
        "maintenance.source_reconcile",
        source_id=source_id,
        request_key=request_key,
    )


def test_operational_lifecycle_vocabulary_is_closed() -> None:
    assert SOURCE_OPERATIONAL_STATES == (
        "active",
        "paused",
        "missing",
        "error",
        "superseded",
        "reauthorization_required",
    )


def test_source_reconciliation_is_exact_content_free_and_read_only(
    tmp_path: Path,
) -> None:
    instance, source, source_id = _registered_instance(
        tmp_path,
        {
            "alpha.txt": b"alpha private source bytes\n",
            "nested/beta.md": b"# beta private source bytes\n",
        },
    )
    canonical_before = _canonical_snapshot(instance)

    result = _run_reconciliation(
        instance,
        source_id,
        request_key="exact-current-snapshot",
    )
    job = result["job"]
    assert isinstance(job, dict)
    assert job["status"] == "succeeded"
    assert job["scope"] == {"kind": "source", "id": source_id}
    assert job["progress"] == {"processed": 2, "skipped": 0, "errors": 0}

    run = instance.source_reconciliation.run_for_job(str(job["id"]))
    assert run is not None
    assert run["status"] == "completed"
    assert run["plan_revision"] == 1
    assert run["cursor"] == 2
    assert run["counts"] == {
        "current": 2,
        "changed": 0,
        "renamed": 0,
        "untracked": 0,
        "missing": 0,
    }
    assert all(
        set(item) == {"identity", "content_hash", "size_bytes", "classification"}
        for item in run["plan"]["items"]
    )
    cursor = instance.get_source_reconciliation_cursor(source_id)
    assert cursor["state"] == "active"
    assert cursor["code"] == "current"
    assert cursor["resync_required"] is False
    assert cursor["last_run_id"] == run["id"]
    assert cursor["last_run_revision"] == 1
    assert cursor["last_success_at"] == run["completed_at"]

    encoded = json.dumps({"run": run, "cursor": cursor}, sort_keys=True)
    assert str(source) not in encoded
    assert "alpha.txt" not in encoded
    assert "nested/beta.md" not in encoded
    assert "private source bytes" not in encoded
    assert _canonical_snapshot(instance) == canonical_before
    receipt = instance.scheduler.journal.get_receipt(
        str(job["receipt_ref"]).rsplit("/", 1)[-1].removesuffix(".json")
    )
    assert receipt is not None
    assert receipt["network_used"] is False
    assert receipt["canonical_mutation"] is False
    assert receipt["automatic_deletion"] is False
    assert instance.validate_instance(deep=True)["status"] == "valid"


def test_changed_rename_untracked_and_missing_are_classified_without_ingestion(
    tmp_path: Path,
) -> None:
    instance, source, source_id = _registered_instance(
        tmp_path,
        {
            "changed.txt": b"original changed bytes\n",
            "renamed.txt": b"stable rename bytes\n",
            "missing.txt": b"later missing bytes\n",
        },
    )
    canonical_before = _canonical_snapshot(instance)
    (source / "changed.txt").write_bytes(b"replacement bytes\n")
    (source / "renamed.txt").rename(source / "moved.txt")
    (source / "missing.txt").unlink()
    (source / "new.txt").write_bytes(b"untracked bytes\n")

    result = _run_reconciliation(instance, source_id, request_key="classify-delta")
    job = result["job"]
    assert isinstance(job, dict) and job["status"] == "succeeded"
    run = instance.source_reconciliation.run_for_job(str(job["id"]))
    assert run is not None
    assert run["counts"] == {
        "current": 0,
        "changed": 1,
        "renamed": 1,
        "untracked": 1,
        "missing": 1,
    }
    assert run["cursor"] == 4
    assert job["progress"] == {"processed": 4, "skipped": 0, "errors": 0}
    cursor = instance.get_source_reconciliation_cursor(source_id)
    assert cursor["state"] == "active"
    assert cursor["code"] == "resync_required"
    assert cursor["resync_required"] is True
    assert cursor["counts"] == run["counts"]
    assert _canonical_snapshot(instance) == canonical_before

    replay = _run_reconciliation(instance, source_id, request_key="classify-again")
    replay_job = replay["job"]
    assert isinstance(replay_job, dict) and replay_job["status"] == "succeeded"
    assert replay_job["id"] != job["id"]
    assert instance.get_source_reconciliation_cursor(source_id)["revision"] == 2
    assert _canonical_snapshot(instance) == canonical_before


def test_paused_and_missing_mount_lifecycle_is_visible_and_non_destructive(
    tmp_path: Path,
) -> None:
    instance, source, source_id = _registered_instance(
        tmp_path,
        {"note.txt": b"durable removable evidence\n"},
        source_class="removable",
    )
    canonical_before = _canonical_snapshot(instance)
    instance.set_folder_source_state(source_id, "paused")
    paused = _run_reconciliation(instance, source_id, request_key="paused-state")
    paused_job = paused["job"]
    assert isinstance(paused_job, dict) and paused_job["status"] == "succeeded"
    assert paused_job["progress"] == {"processed": 0, "skipped": 1, "errors": 0}
    paused_cursor = instance.get_source_reconciliation_cursor(source_id)
    assert paused_cursor["state"] == "paused"
    assert paused_cursor["code"] == "source_paused"
    assert paused_cursor["last_success_at"] is None

    instance.set_folder_source_state(source_id, "enabled")
    detached = tmp_path / "detached"
    source.rename(detached)
    missing = _run_reconciliation(instance, source_id, request_key="missing-state")
    missing_job = missing["job"]
    assert isinstance(missing_job, dict) and missing_job["status"] == "succeeded"
    assert missing_job["progress"] == {"processed": 0, "skipped": 1, "errors": 0}
    missing_cursor = instance.get_source_reconciliation_cursor(source_id)
    assert missing_cursor["state"] == "missing"
    assert missing_cursor["code"] == "source_missing"
    assert missing_cursor["resync_required"] is True
    assert missing_cursor["last_success_at"] is None
    assert _canonical_snapshot(instance) == canonical_before
    detached.rename(source)


def test_source_scope_is_explicit_and_policy_selection_cannot_cross_sources(
    tmp_path: Path,
) -> None:
    instance, _source, source_id = _registered_instance(
        tmp_path,
        {"note.txt": b"first Source\n"},
    )
    second = tmp_path / "second"
    second.mkdir()
    (second / "note.txt").write_bytes(b"second Source\n")
    second_id = str(
        instance.register_folder_source(
            second,
            name="Second Source",
            quiescence_seconds=0,
            stable_observations=1,
            schedule=schedule_payload(mode="manual", timezone="UTC"),
        )["id"]
    )
    with pytest.raises(MaintenanceError, match="require an exact managed Source"):
        instance.queue_maintenance_action("maintenance.source_reconcile")
    first_policy = instance.create_maintenance_policy(
        "maintenance.source_reconcile",
        source_id=source_id,
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )
    second_policy = instance.create_maintenance_policy(
        "maintenance.source_reconcile",
        source_id=second_id,
        state="paused",
        schedule=schedule_payload(
            mode="interval",
            timezone="UTC",
            interval_seconds=3600,
        ),
    )
    assert first_policy["scope"] == {"kind": "source", "id": source_id}
    assert second_policy["scope"] == {"kind": "source", "id": second_id}
    with pytest.raises(MaintenanceError, match="policy not found"):
        instance.queue_maintenance_action(
            "maintenance.source_reconcile",
            source_id=source_id,
            policy_id=second_policy["id"],
        )


def test_scheduler_checkpoint_gap_advances_cursor_without_double_counting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, source_id = _registered_instance(
        tmp_path,
        {
            "one.txt": b"one\n",
            "two.txt": b"two\n",
            "three.txt": b"three\n",
        },
    )
    base = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="maintenance.source_reconcile",
        scope={"kind": "source", "id": source_id},
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"],
        request_key="cursor-split",
        now=base,
    )["job"]
    interrupted = False

    def stop_after_scheduler_cursor(
        _self: SourceReconciliationManager,
        _run: dict[str, object],
    ) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt("synthetic Source cursor split")

    monkeypatch.setattr(
        SourceReconciliationManager,
        "_after_scheduler_checkpoint",
        stop_after_scheduler_cursor,
    )
    with pytest.raises(KeyboardInterrupt, match="synthetic Source cursor split"):
        instance.scheduler.run_one(
            job_id=str(queued["id"]),
            lease_seconds=1,
            now=base,
        )
    run = instance.source_reconciliation.run_for_job(str(queued["id"]))
    assert run is not None and run["cursor"] == 0
    split_job = instance.scheduler.journal.get_job(str(queued["id"]))
    assert split_job is not None
    assert split_job["progress"] == {"processed": 1, "skipped": 0, "errors": 0}

    recovery = instance.scheduler.recover(now=base + timedelta(seconds=2))
    assert recovery["expired_leases"] == 1
    completed = instance.scheduler.run_one(
        job_id=str(queued["id"]),
        now=base + timedelta(seconds=2),
    )
    assert completed is not None and completed["status"] == "succeeded"
    assert completed["progress"] == {"processed": 3, "skipped": 0, "errors": 0}
    run = instance.source_reconciliation.run_for_job(str(queued["id"]))
    assert run is not None
    assert run["plan_revision"] == 1
    assert run["cursor"] == 3
    assert run["counts"]["current"] == 3


def test_stale_lease_replans_changed_snapshot_and_retains_superseded_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source, source_id = _registered_instance(
        tmp_path,
        {"one.txt": b"one\n", "two.txt": b"two\n"},
    )
    canonical_before = _canonical_snapshot(instance)
    base = datetime(2026, 8, 30, 11, 0, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="maintenance.source_reconcile",
        scope={"kind": "source", "id": source_id},
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"],
        request_key="changed-recovery",
        now=base,
    )["job"]
    interrupted = False

    def stop_after_item(
        _self: SourceReconciliationManager,
        _run: dict[str, object],
    ) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt("synthetic Source item stop")

    monkeypatch.setattr(
        SourceReconciliationManager,
        "_after_item_checkpoint",
        stop_after_item,
    )
    with pytest.raises(KeyboardInterrupt, match="synthetic Source item stop"):
        instance.scheduler.run_one(
            job_id=str(queued["id"]),
            lease_seconds=1,
            now=base,
        )
    (source / "two.txt").write_bytes(b"two changed after interruption\n")
    assert instance.scheduler.recover(now=base + timedelta(seconds=2))[
        "expired_leases"
    ] == 1
    completed = instance.scheduler.run_one(
        job_id=str(queued["id"]),
        now=base + timedelta(seconds=2),
    )
    assert completed is not None and completed["status"] == "succeeded"
    assert completed["progress"] == {"processed": 3, "skipped": 0, "errors": 0}
    run = instance.source_reconciliation.run_for_job(str(queued["id"]))
    assert run is not None
    assert run["plan_revision"] == 2
    assert run["superseded_revisions"] == 1
    assert run["counts"]["current"] == 1
    assert run["counts"]["changed"] == 1
    cursor = instance.get_source_reconciliation_cursor(source_id)
    assert cursor["state"] == "active"
    assert cursor["code"] == "resync_required"
    assert cursor["revision"] == 2
    assert _canonical_snapshot(instance) == canonical_before


def test_completed_run_replays_after_terminal_state_without_duplicate_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, source_id = _registered_instance(
        tmp_path,
        {"one.txt": b"one\n", "two.txt": b"two\n"},
    )
    base = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="maintenance.source_reconcile",
        scope={"kind": "source", "id": source_id},
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"],
        request_key="terminal-replay",
        now=base,
    )["job"]
    interrupted = False

    def stop_after_terminal_cursor(
        _self: SourceReconciliationManager,
        _run: dict[str, object],
        _cursor: dict[str, object],
    ) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt("synthetic terminal cursor stop")

    monkeypatch.setattr(
        SourceReconciliationManager,
        "_after_terminal_state",
        stop_after_terminal_cursor,
    )
    with pytest.raises(KeyboardInterrupt, match="synthetic terminal cursor stop"):
        instance.scheduler.run_one(
            job_id=str(queued["id"]),
            lease_seconds=1,
            now=base,
        )
    run = instance.source_reconciliation.run_for_job(str(queued["id"]))
    cursor = instance.get_source_reconciliation_cursor(source_id)
    assert run is not None and run["status"] == "completed"
    assert cursor["revision"] == 1
    assert cursor["last_run_revision"] == 1

    assert instance.scheduler.recover(now=base + timedelta(seconds=2))[
        "expired_leases"
    ] == 1
    completed = instance.scheduler.run_one(
        job_id=str(queued["id"]),
        now=base + timedelta(seconds=2),
    )
    assert completed is not None and completed["status"] == "succeeded"
    assert completed["progress"] == {"processed": 2, "skipped": 0, "errors": 0}
    assert instance.get_source_reconciliation_cursor(source_id)["revision"] == 1
    assert len(instance.list_source_reconciliation_runs()) == 1


def test_terminal_run_without_lifecycle_cursor_is_reconciled_on_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, source_id = _registered_instance(
        tmp_path,
        {"note.txt": b"terminal split evidence\n"},
    )
    base = datetime(2026, 8, 30, 12, 30, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="maintenance.source_reconcile",
        scope={"kind": "source", "id": source_id},
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"],
        request_key="terminal-run-split",
        now=base,
    )["job"]
    interrupted = False

    def stop_before_lifecycle_cursor(
        _self: SourceReconciliationManager,
        _run: dict[str, object],
    ) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt("synthetic run/cursor split")

    monkeypatch.setattr(
        SourceReconciliationManager,
        "_after_run_terminal",
        stop_before_lifecycle_cursor,
    )
    with pytest.raises(KeyboardInterrupt, match="synthetic run/cursor split"):
        instance.scheduler.run_one(
            job_id=str(queued["id"]),
            lease_seconds=1,
            now=base,
        )
    run = instance.source_reconciliation.run_for_job(str(queued["id"]))
    assert run is not None and run["status"] == "completed"
    assert instance.get_source_reconciliation_cursor(source_id)["revision"] == 0
    assert instance.validate_instance(deep=True)["status"] == "valid"

    assert instance.scheduler.recover(now=base + timedelta(seconds=2))[
        "expired_leases"
    ] == 1
    completed = instance.scheduler.run_one(
        job_id=str(queued["id"]),
        now=base + timedelta(seconds=2),
    )
    assert completed is not None and completed["status"] == "succeeded"
    cursor = instance.get_source_reconciliation_cursor(source_id)
    assert cursor["revision"] == 1
    assert cursor["last_run_revision"] == 1


def test_source_change_during_execution_retries_one_bounded_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source, source_id = _registered_instance(
        tmp_path,
        {"one.txt": b"one\n", "two.txt": b"two\n"},
    )
    canonical_before = _canonical_snapshot(instance)
    base = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="maintenance.source_reconcile",
        scope={"kind": "source", "id": source_id},
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=2, base_seconds=1, max_seconds=1),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"],
        request_key="superseded-retry",
        now=base,
    )["job"]
    changed = False

    def change_source_after_item(
        _self: SourceReconciliationManager,
        _run: dict[str, object],
    ) -> None:
        nonlocal changed
        if not changed:
            changed = True
            (source / "two.txt").write_bytes(b"changed while executing\n")

    monkeypatch.setattr(
        SourceReconciliationManager,
        "_after_item_checkpoint",
        change_source_after_item,
    )
    first = instance.scheduler.run_one(job_id=str(queued["id"]), now=base)
    assert first is not None and first["status"] == "retry_wait"
    assert first["progress"] == {"processed": 2, "skipped": 0, "errors": 1}
    assert first["attempts"][-1]["error_code"] == "source_reconciliation_superseded"
    superseded_cursor = instance.get_source_reconciliation_cursor(source_id)
    assert superseded_cursor["state"] == "superseded"
    assert superseded_cursor["code"] == "source_changed"

    assert instance.scheduler.recover(now=base + timedelta(seconds=2))[
        "retries_ready"
    ] == 1
    completed = instance.scheduler.run_one(
        job_id=str(queued["id"]),
        now=base + timedelta(seconds=2),
    )
    assert completed is not None and completed["status"] == "succeeded"
    assert completed["progress"] == {"processed": 4, "skipped": 0, "errors": 1}
    run = instance.source_reconciliation.run_for_job(str(queued["id"]))
    assert run is not None
    assert run["plan_revision"] == 2
    assert run["superseded_revisions"] == 1
    assert instance.get_source_reconciliation_cursor(source_id)["state"] == "active"
    assert _canonical_snapshot(instance) == canonical_before


def test_permission_loss_requires_reauthorization_and_network_receipts_are_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, source_id = _registered_instance(
        tmp_path,
        {"note.txt": b"mounted network bytes\n"},
        source_class="network",
    )
    policy = instance.create_maintenance_policy(
        "maintenance.source_reconcile",
        source_id=source_id,
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=1, base_seconds=1, max_seconds=1),
    )

    def unreadable(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise PermissionError("private operating-system detail")

    monkeypatch.setattr(SourceReconciliationManager, "_scan_rows", unreadable)
    result = instance.run_maintenance_action(
        "maintenance.source_reconcile",
        source_id=source_id,
        policy_id=str(policy["id"]),
        request_key="unreadable-source",
    )
    job = result["job"]
    assert isinstance(job, dict) and job["status"] == "manual_intervention"
    assert job["attempts"][-1]["error_code"] == "source_reauthorization_required"
    cursor = instance.get_source_reconciliation_cursor(source_id)
    assert cursor["state"] == "reauthorization_required"
    assert cursor["code"] == "authorization_required"
    assert "private operating-system detail" not in json.dumps(cursor)
    receipt = instance.scheduler.journal.get_receipt(
        str(job["receipt_ref"]).rsplit("/", 1)[-1].removesuffix(".json")
    )
    assert receipt is not None
    assert receipt["network_used"] is True
    assert receipt["canonical_mutation"] is False
    assert receipt["automatic_deletion"] is False
    assert instance.validate_instance(deep=True)["status"] == "valid"

    io_root = tmp_path / "io-error"
    io_root.mkdir()
    io_instance, _io_source, io_source_id = _registered_instance(
        io_root,
        {"note.txt": b"local I/O evidence\n"},
    )
    io_policy = io_instance.create_maintenance_policy(
        "maintenance.source_reconcile",
        source_id=io_source_id,
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=1, base_seconds=1, max_seconds=1),
    )

    def io_error(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise OSError("private local path detail")

    monkeypatch.setattr(SourceReconciliationManager, "_scan_rows", io_error)
    io_result = io_instance.run_maintenance_action(
        "maintenance.source_reconcile",
        source_id=io_source_id,
        policy_id=str(io_policy["id"]),
        request_key="closed-io-error",
    )
    io_job = io_result["job"]
    assert isinstance(io_job, dict) and io_job["status"] == "failed"
    assert io_job["attempts"][-1]["error_code"] == "local_io"
    io_cursor = io_instance.get_source_reconciliation_cursor(io_source_id)
    assert io_cursor["state"] == "error"
    assert io_cursor["code"] == "source_io"
    assert "private local path detail" not in json.dumps(io_cursor)


def test_canonical_unsafe_locator_is_a_closed_state_error(tmp_path: Path) -> None:
    instance, _source, source_id = _registered_instance(
        tmp_path,
        {"note.txt": b"canonical locator evidence\n"},
    )
    document = instance.store.list_canonical("documents")[0]
    document_path = instance.store.paths.canonical_dir("documents") / (
        f"{document['id']}.json"
    )
    corrupted = {**document, "locator": "../outside.txt"}
    document_path.write_text(json.dumps(corrupted), encoding="utf-8")

    with pytest.raises(SourceReconciliationStateError, match="locator is unsafe"):
        instance.source_reconciliation.build_plan(source_id)


def test_reconciliation_state_is_backed_up_exported_validated_and_exposed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance, source, source_id = _registered_instance(
        tmp_path,
        {"note.txt": b"portable reconciliation evidence\n"},
    )
    result = _run_reconciliation(instance, source_id, request_key="surface-state")
    job = result["job"]
    assert isinstance(job, dict)
    run = instance.source_reconciliation.run_for_job(str(job["id"]))
    assert run is not None
    cursor_relative = f"state/source-reconciliation/cursors/{source_id}.json"
    run_relative = f"state/source-reconciliation/runs/{run['id']}.json"

    second_policy = instance.create_maintenance_policy(
        "maintenance.source_reconcile",
        source_id=source_id,
        state="paused",
        schedule=schedule_payload(
            mode="interval",
            timezone="Europe/Rome",
            interval_seconds=3600,
        ),
    )
    app = create_app(instance.root)
    with TestClient(app) as client:
        cursors = client.get("/api/v1/maintenance/source-cursors")
        detail = client.get(
            f"/api/v1/maintenance/source-cursors/{source_id}"
        )
        runs = client.get("/api/v1/maintenance/source-runs")
        run_detail = client.get(
            f"/api/v1/maintenance/source-runs/{run['id']}"
        )
        assert cursors.status_code == detail.status_code == 200
        assert runs.status_code == run_detail.status_code == 200
        assert (
            client.get("/api/v1/maintenance/source-cursors/src_" + "0" * 32).status_code
            == 404
        )
        assert detail.json()["code"] == "current"
        assert run_detail.json()["id"] == run["id"]
        api_text = json.dumps(
            {
                "cursors": cursors.json(),
                "runs": runs.json(),
            }
        )
        assert str(source) not in api_text
        assert "note.txt" not in api_text

        english = client.get("/maintenance?lang=en")
        italian = client.get("/maintenance?lang=it")
        assert english.status_code == italian.status_code == 200
        assert "Source reconciliation lifecycle" in english.text
        assert "Ciclo di vita della riconciliazione Source" in italian.text
        assert "Synthetic reconciliation Source" in english.text
        assert source_id in english.text
        assert str(source) not in english.text
        assert str(instance.root) not in english.text
        assert 'name="source_id"' in english.text
        assert second_policy["id"] in english.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', english.text)
        assert csrf is not None
        queued = client.post(
            "/maintenance?lang=en",
            data={
                "csrf_token": csrf.group(1),
                "action_id": "maintenance.source_reconcile",
                "source_id": source_id,
                "policy_id": second_policy["id"],
            },
        )
        assert queued.status_code == 200
        assert "Maintenance job queued" in queued.text
        assert instance.list_scheduler_jobs(policy_id=str(second_policy["id"]))

    assert main(["maintenance-source-cursors", str(instance.root)]) == 0
    cli_cursors = json.loads(capsys.readouterr().out)
    assert cli_cursors[0]["source_id"] == source_id
    assert main(["maintenance-source-runs", str(instance.root)]) == 0
    cli_runs = json.loads(capsys.readouterr().out)
    assert any(item["id"] == run["id"] for item in cli_runs)
    assert main(
        ["maintenance-source-run", str(instance.root), str(run["id"])]
    ) == 0
    assert json.loads(capsys.readouterr().out)["source_id"] == source_id

    backup = instance.backup(
        destination=tmp_path / "backups",
        reason="source-reconciliation-test",
    )
    with zipfile.ZipFile(backup["archive"]) as archive:
        assert f"payload/{cursor_relative}" in archive.namelist()
        assert f"payload/{run_relative}" in archive.namelist()
    portable = instance.export_portable(
        tmp_path / "exports",
        derived_state="rebuild",
    )
    with zipfile.ZipFile(portable["archive"]) as archive:
        assert f"instance/{cursor_relative}" in archive.namelist()
        assert f"instance/{run_relative}" in archive.namelist()

    cursor_path = instance.root / cursor_relative
    run_path = instance.root / run_relative
    cursor_path.unlink()
    run_path.unlink()
    instance.restore(backup["archive"])
    restored = ProvelumeInstance(instance.root)
    assert restored.get_source_reconciliation_run(str(run["id"])) == run
    assert restored.validate_instance(deep=True)["status"] == "valid"

    original_cursor = restored.get_source_reconciliation_cursor(source_id)
    rebound = {**original_cursor}
    rebound["configuration_fingerprint"] = "0" * 64
    cursor_path.write_text(json.dumps(rebound), encoding="utf-8")
    report = restored.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(
        error["code"] == "source_reconciliation_binding_invalid"
        for error in report["errors"]
    )
    cursor_path.write_text(json.dumps(original_cursor), encoding="utf-8")

    imported = ProvelumeInstance.initialise(tmp_path / "portable-target")
    imported.import_portable(portable["archive"])
    imported = ProvelumeInstance(imported.root)
    assert imported.get_source_reconciliation_run(str(run["id"])) == run
    assert imported.validate_instance(deep=True)["status"] == "valid"

    corrupted = json.loads(cursor_path.read_text(encoding="utf-8"))
    corrupted["absolute_path"] = str(source)
    cursor_path.write_text(json.dumps(corrupted), encoding="utf-8")
    report = restored.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(
        error["code"] == "source_reconciliation_record_invalid"
        for error in report["errors"]
    )
    with TestClient(create_app(restored.root), raise_server_exceptions=False) as client:
        response = client.get(f"/api/v1/maintenance/source-cursors/{source_id}")
        assert response.status_code == 500

    imported_job_path = (
        imported.store.paths.state / "scheduler" / "jobs" / f"{job['id']}.json"
    )
    imported_job_path.write_text("{}", encoding="utf-8")
    report = imported.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(
        error["code"] == "source_reconciliation_binding_invalid"
        for error in report["errors"]
    )


def test_public_source_reconciliation_contract_is_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = (
        root
        / "docs"
        / "architecture"
        / "source-reconciliation-cursors-and-lifecycle.md"
    ).read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    for required in (
        "`current`",
        "`changed`",
        "`renamed`",
        "`untracked`",
        "`missing`",
        "`reauthorization_required`",
        "network_used: true",
        "canonical_mutation: false",
        "automatic_deletion: false",
        "never written to the reconciliation journal",
        "portable export/import",
    ):
        assert required in contract
    assert "issue [#128]" in readme
    assert (
        "Package, embedded build identity, tag and latest public release remain `0.7.0`"
        in readme
    )
