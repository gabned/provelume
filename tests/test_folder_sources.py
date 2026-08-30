from __future__ import annotations

import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import provelume.folder_sources as folder_sources_module
from provelume.cli import main
from provelume.ingestion_runs import IngestionLedger
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.scheduler import schedule_payload
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _instance(tmp_path: Path) -> ProvelumeInstance:
    return ProvelumeInstance.initialise(tmp_path / "instance", name="Folder Source fixture")


def _register(
    instance: ProvelumeInstance,
    source: Path,
    *,
    source_class: str = "local",
    quiescence_seconds: int = 0,
    stable_observations: int = 1,
) -> dict[str, object]:
    return instance.register_folder_source(
        source,
        name="Synthetic folder",
        source_class=source_class,
        quiescence_seconds=quiescence_seconds,
        stable_observations=stable_observations,
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )


def test_quiescence_clock_reversal_and_explicit_policy_are_durable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "guide.md").write_text("# Stable\n", encoding="utf-8")
    instance = _instance(tmp_path)
    registered = _register(
        instance,
        source,
        quiescence_seconds=30,
        stable_observations=2,
    )
    source_id = str(registered["id"])
    policy = registered["policy"]
    assert isinstance(policy, dict)
    assert policy["job_kind"] == "source.refresh"
    assert policy["scope"] == {"kind": "source", "id": source_id}
    assert policy["state"] == "enabled"
    assert policy["schedule"]["mode"] == "manual"

    start = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    first = instance.observe_folder_source(source_id, now=start)
    second = instance.observe_folder_source(source_id, now=start + timedelta(seconds=29))
    ready = instance.observe_folder_source(source_id, now=start + timedelta(seconds=30))

    assert first["phase"] == "quiescing"
    assert first["stable_observations"] == 1
    assert second["phase"] == "quiescing"
    assert second["stable_observations"] == 2
    assert ready["phase"] == "ready"
    assert ready["file_count"] == 1
    assert ready["total_bytes"] == len(b"# Stable\n")
    assert "path" not in ready

    reversed_clock = instance.observe_folder_source(
        source_id,
        now=start - timedelta(minutes=5),
    )
    assert reversed_clock["phase"] == "quiescing"
    assert reversed_clock["clock_change_count"] == 1
    assert reversed_clock["stable_observations"] == 1
    assert ProvelumeInstance(instance.root).folder_sources.observer(source_id) == reversed_clock


def test_scheduler_refresh_is_idempotent_observable_and_never_deletes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("journaled folder refresh\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])

    first = instance.refresh_folder_source(source_id, request_key="first")
    first_job = first["job"]
    assert isinstance(first_job, dict)
    assert first_job["status"] == "succeeded"
    assert first_job["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    first_receipt = instance.scheduler.journal.get_receipt(
        str(first_job["receipt_ref"]).rsplit("/", 1)[-1].removesuffix(".json")
    )
    assert first_receipt is not None
    assert first_receipt["network_used"] is False
    assert first_receipt["canonical_mutation"] is True
    assert first_receipt["automatic_deletion"] is False
    assert instance.folder_sources.observer(source_id)["phase"] == "current"

    counts = {
        kind: len(instance.store.list_canonical(kind))
        for kind in ("acquisitions", "originals", "documents", "versions")
    }
    second = instance.refresh_folder_source(source_id, request_key="second")
    second_job = second["job"]
    assert isinstance(second_job, dict)
    assert second_job["status"] == "succeeded"
    assert second_job["progress"] == {"processed": 0, "skipped": 1, "errors": 0}
    assert {kind: len(instance.store.list_canonical(kind)) for kind in counts} == counts
    second_receipt = instance.scheduler.journal.get_receipt(
        str(second_job["receipt_ref"]).rsplit("/", 1)[-1].removesuffix(".json")
    )
    assert second_receipt is not None
    assert second_receipt["canonical_mutation"] is False
    assert instance.search("journaled")[0]["source_id"] == source_id


def test_mount_loss_reappearance_and_pause_preserve_canonical_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "removable"
    detached = tmp_path / "detached"
    source.mkdir()
    (source / "note.txt").write_text("removable knowledge\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source, source_class="removable")["id"])
    assert (
        instance.refresh_folder_source(source_id, request_key="seed")["job"]["status"]
        == "succeeded"
    )
    canonical = {
        kind: instance.store.list_canonical(kind)
        for kind in ("sources", "acquisitions", "originals", "documents", "versions")
    }

    source.rename(detached)
    missing = instance.observe_folder_source(source_id)
    assert missing["availability"] == "missing"
    assert missing["phase"] == "missing"
    assert {kind: instance.store.list_canonical(kind) for kind in canonical} == canonical

    detached.rename(source)
    reappeared = instance.observe_folder_source(source_id)
    assert reappeared["availability"] == "available"
    assert reappeared["phase"] == "current"
    paused = instance.set_folder_source_state(source_id, "paused")
    assert paused["lifecycle_state"] == "paused"
    assert paused["policy"]["state"] == "paused"
    assert instance.observe_folder_source(source_id)["phase"] == "paused"
    enabled = instance.set_folder_source_state(source_id, "enabled")
    assert enabled["policy"]["state"] == "enabled"
    assert instance.observe_folder_source(source_id)["phase"] == "current"
    assert {kind: instance.store.list_canonical(kind) for kind in canonical} == canonical


def test_mount_loss_between_observation_and_ingestion_stays_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "removable"
    detached = tmp_path / "detached"
    source.mkdir()
    (source / "note.txt").write_text("disconnect race\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source, source_class="removable")["id"])
    original_run = folder_sources_module._run_ingestion_filesystem_locked

    def disconnect_before_ingestion(*args, **kwargs):
        source.rename(detached)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(
        folder_sources_module,
        "_run_ingestion_filesystem_locked",
        disconnect_before_ingestion,
    )
    with InstanceLifecycleManager(instance.store)._hold(purpose="disconnect-race"):
        result = instance.folder_sources.refresh(source_id)

    assert result["status"] == "skipped"
    assert result["reason"] == "missing"
    assert result["observer"]["availability"] == "missing"
    assert result["observer"]["phase"] == "missing"
    assert result["progress"] == {"processed": 0, "skipped": 1, "errors": 0}
    assert instance.store.list_canonical("acquisitions") == []
    assert result["automatic_deletion"] is False
    detached.rename(source)


def test_interrupted_item_commit_resumes_same_run_without_duplicate_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("resume exact acquisition\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    manager = instance.folder_sources
    original_write_item = IngestionLedger.write_item
    interrupted = False

    def interrupt_after_acquisition(self, item):
        nonlocal interrupted
        if item.status == "completed" and not interrupted:
            interrupted = True
            raise RuntimeError("synthetic crash after canonical acquisition")
        return original_write_item(self, item)

    monkeypatch.setattr(IngestionLedger, "write_item", interrupt_after_acquisition)
    with (
        pytest.raises(RuntimeError, match="synthetic crash"),
        InstanceLifecycleManager(instance.store)._hold(purpose="synthetic-refresh"),
    ):
        manager.refresh(
            source_id,
            scheduler_job_id="job_" + "1" * 32,
        )

    running = instance.list_ingestion_runs()[0]
    assert running["status"] == "running"
    assert len(instance.store.list_canonical("acquisitions")) == 1
    committed_acquisition = instance.store.list_canonical("acquisitions")[0]
    assert committed_acquisition["outcome"] == "created"
    active_run_id = manager.observer(source_id)["active_run_id"]
    detached = tmp_path / "detached"
    source.rename(detached)
    with InstanceLifecycleManager(instance.store)._hold(purpose="missing-after-commit"):
        missing = manager.refresh(
            source_id,
            scheduler_job_id="job_" + "1" * 32,
        )
    assert missing["status"] == "skipped"
    assert missing["reason"] == "missing"
    assert manager.observer(source_id)["active_run_id"] == active_run_id
    paused = instance.set_folder_source_state(source_id, "paused")
    assert paused["observer"]["active_run_id"] == active_run_id
    assert instance.observe_folder_source(source_id)["active_run_id"] == active_run_id
    enabled = instance.set_folder_source_state(source_id, "enabled")
    assert enabled["observer"]["active_run_id"] == active_run_id
    detached.rename(source)
    monkeypatch.setattr(IngestionLedger, "write_item", original_write_item)

    with InstanceLifecycleManager(instance.store)._hold(purpose="synthetic-replay"):
        replayed = manager.refresh(
            source_id,
            scheduler_job_id="job_" + "1" * 32,
        )

    assert replayed["status"] == "refreshed"
    assert replayed["run"]["run"]["id"] == active_run_id
    assert replayed["run"]["run"]["status"] == "completed"
    assert len(instance.store.list_canonical("acquisitions")) == 1
    assert instance.store.list_canonical("acquisitions")[0] == committed_acquisition
    assert len(instance.store.list_canonical("originals")) == 1
    assert len(instance.store.list_canonical("versions")) == 1
    assert manager.observer(source_id)["phase"] == "current"


def test_changed_snapshot_after_interruption_reconciles_before_new_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    first_path = source / "a.txt"
    second_path = source / "b.txt"
    first_path.write_text("first old\n", encoding="utf-8")
    second_path.write_text("second old\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    manager = instance.folder_sources
    original_write_item = IngestionLedger.write_item
    interrupted = False

    def interrupt_after_first_commit(self, item):
        nonlocal interrupted
        if item.status == "completed" and not interrupted:
            interrupted = True
            raise RuntimeError("synthetic snapshot interruption")
        return original_write_item(self, item)

    monkeypatch.setattr(IngestionLedger, "write_item", interrupt_after_first_commit)
    job_id = "job_" + "4" * 32
    with (
        pytest.raises(RuntimeError, match="snapshot interruption"),
        InstanceLifecycleManager(instance.store)._hold(purpose="changing-snapshot-crash"),
    ):
        manager.refresh(source_id, scheduler_job_id=job_id)
    committed = instance.store.list_canonical("acquisitions")[0]
    assert committed["outcome"] == "created"
    monkeypatch.setattr(IngestionLedger, "write_item", original_write_item)
    first_path.write_text("first new\n", encoding="utf-8")
    second_path.write_text("second new\n", encoding="utf-8")

    with InstanceLifecycleManager(instance.store)._hold(purpose="reconcile-old-snapshot"):
        reconciled = manager.refresh(source_id, scheduler_job_id=job_id)
    assert reconciled["status"] == "failed"
    assert reconciled["reason"] == "input_io_error"
    assert reconciled["run"]["run"]["status"] == "completed_with_errors"
    assert instance.store.list_canonical("acquisitions") == [committed]

    with InstanceLifecycleManager(instance.store)._hold(purpose="ingest-new-snapshot"):
        converged = manager.refresh(source_id, scheduler_job_id=job_id)
    assert converged["status"] == "refreshed"
    assert converged["observer"]["phase"] == "current"
    assert len(instance.store.list_canonical("acquisitions")) == 3
    assert len(instance.store.list_canonical("versions")) == 3
    assert instance.search("first new")[0]["source_id"] == source_id
    assert instance.search("second new")[0]["source_id"] == source_id


def test_transient_failed_snapshot_retries_failed_items_with_bounded_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    note = source / "note.txt"
    note.write_text("retry readable snapshot\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    original_read_bytes = Path.read_bytes
    fail_once = True

    def transient_read_failure(path: Path) -> bytes:
        nonlocal fail_once
        if path == note and fail_once:
            fail_once = False
            raise PermissionError("synthetic transient read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", transient_read_failure)
    first = instance.refresh_folder_source(source_id, request_key="transient-read")
    first_job = first["job"]
    assert isinstance(first_job, dict)
    assert first_job["status"] == "retry_wait"
    assert first_job["attempts"][-1]["error_class"] == "transient"
    assert first_job["attempts"][-1]["error_code"] == "local_io"
    failed_run = instance.list_ingestion_runs()[0]
    assert failed_run["status"] == "failed"
    assert failed_run["failed_items"] == 1

    retry_at = datetime.fromisoformat(str(first_job["retry_not_before"]))
    completed = instance.scheduler.run_one(job_id=str(first_job["id"]), now=retry_at)
    assert completed is not None
    assert completed["status"] == "succeeded"
    assert completed["attempt"] == 2
    assert completed["progress"] == {"processed": 1, "skipped": 0, "errors": 2}
    runs = instance.list_ingestion_runs()
    assert runs[0]["status"] == "completed"
    assert runs[0]["retry_of_run_id"] == failed_run["id"]
    assert len(instance.store.list_canonical("acquisitions")) == 1
    assert instance.store.list_canonical("acquisitions")[0]["outcome"] == "created"
    assert instance.folder_sources.observer(source_id)["phase"] == "current"


def test_retry_creation_crash_reuses_reserved_run_and_failed_item_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    note = source / "note.txt"
    note.write_text("resume retry creation\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    manager = instance.folder_sources
    original_read_bytes = Path.read_bytes
    fail_once = True

    def transient_read_failure(path: Path) -> bytes:
        nonlocal fail_once
        if path == note and fail_once:
            fail_once = False
            raise PermissionError("synthetic first-attempt failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", transient_read_failure)
    job_id = "job_" + "3" * 32
    with InstanceLifecycleManager(instance.store)._hold(purpose="failed-first-attempt"):
        failed = manager.refresh(source_id, scheduler_job_id=job_id)
    assert failed["status"] == "failed"
    failed_run_id = str(failed["run"]["run"]["id"])
    original_retry = folder_sources_module._retry_ingestion_run_locked

    def interrupt_before_retry_record(*args, **kwargs):
        raise RuntimeError("synthetic crash before retry record")

    monkeypatch.setattr(
        folder_sources_module,
        "_retry_ingestion_run_locked",
        interrupt_before_retry_record,
    )
    with (
        pytest.raises(RuntimeError, match="before retry record"),
        InstanceLifecycleManager(instance.store)._hold(purpose="interrupted-retry-create"),
    ):
        manager.refresh(source_id, scheduler_job_id=job_id)
    reserved_run_id = manager.observer(source_id)["active_run_id"]
    assert isinstance(reserved_run_id, str)
    assert IngestionLedger(instance.store).get_run(reserved_run_id) is None

    monkeypatch.setattr(
        folder_sources_module,
        "_retry_ingestion_run_locked",
        original_retry,
    )
    with InstanceLifecycleManager(instance.store)._hold(purpose="resume-retry-create"):
        resumed = manager.refresh(source_id, scheduler_job_id=job_id)

    assert resumed["status"] == "refreshed"
    assert resumed["run"]["run"]["id"] == reserved_run_id
    assert resumed["run"]["run"]["retry_of_run_id"] == failed_run_id
    assert len(instance.store.list_canonical("acquisitions")) == 1
    assert manager.observer(source_id)["phase"] == "current"


def test_expired_source_job_replays_committed_effect_into_one_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("lease replay\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    queued = instance.queue_folder_source_refresh(source_id, request_key="lease-replay")
    job_id = str(queued["job"]["id"])
    journal = instance.scheduler.journal
    started = datetime.now(UTC)
    claimed = journal.claim_next(
        worker_id="interrupted-worker",
        job_id=job_id,
        lease_seconds=5,
        now=started,
    )
    assert claimed is not None
    token = str(claimed["lease"]["token"])
    prepared = journal.checkpoint(
        job_id,
        token,
        sequence=1,
        phase="prepared",
        progress=claimed["progress"],
        now=started,
    )
    journal.checkpoint(
        job_id,
        token,
        sequence=2,
        phase="executing",
        progress=prepared["progress"],
        now=started,
    )
    with InstanceLifecycleManager(instance.store)._hold(purpose="committed-before-exit"):
        committed = instance.folder_sources.refresh(
            source_id,
            scheduler_job_id=job_id,
        )
    assert committed["observer"]["phase"] == "current"
    assert len(instance.store.list_canonical("acquisitions")) == 1

    recovery_time = datetime.fromisoformat(str(claimed["lease"]["expires_at"])) + timedelta(
        seconds=1
    )
    recovery = instance.scheduler.recover(now=recovery_time)
    assert recovery["expired_leases"] == 1
    recovered = journal.get_job(job_id)
    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["recovery_state"] == "resumable"

    finished = instance.scheduler.run_one(job_id=job_id, now=recovery_time)
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["attempt"] == 2
    assert finished["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    assert len(instance.store.list_canonical("acquisitions")) == 1
    receipt_id = str(finished["receipt_ref"]).rsplit("/", 1)[-1].removesuffix(".json")
    receipt = journal.get_receipt(receipt_id)
    assert receipt is not None
    assert receipt["canonical_mutation"] is True
    assert receipt["automatic_deletion"] is False


def test_change_during_refresh_returns_to_quiescence_then_converges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    note = source / "note.txt"
    note.write_text("first snapshot\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    original_run = folder_sources_module._run_ingestion_filesystem_locked
    changed = False

    def mutate_after_capture(*args, **kwargs):
        nonlocal changed
        result = original_run(*args, **kwargs)
        if not changed:
            changed = True
            note.write_text("second snapshot\n", encoding="utf-8")
        return result

    monkeypatch.setattr(
        folder_sources_module,
        "_run_ingestion_filesystem_locked",
        mutate_after_capture,
    )
    with InstanceLifecycleManager(instance.store)._hold(purpose="changing-refresh"):
        first = instance.folder_sources.refresh(source_id)

    assert first["status"] == "refreshed"
    assert first["observer"]["phase"] == "quiescing"
    assert first["observer"]["last_error_code"] == "source_changed_during_refresh"
    monkeypatch.setattr(
        folder_sources_module,
        "_run_ingestion_filesystem_locked",
        original_run,
    )
    with InstanceLifecycleManager(instance.store)._hold(purpose="converging-refresh"):
        second = instance.folder_sources.refresh(source_id)
    assert second["observer"]["phase"] == "current"
    assert len(instance.store.list_canonical("versions")) == 2
    assert instance.search("second")[0]["source_id"] == source_id


def test_network_class_is_explicit_in_receipt_without_application_transport(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mounted-network"
    source.mkdir()
    (source / "note.txt").write_text("mounted path\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source, source_class="network")["id"])

    result = instance.refresh_folder_source(source_id, request_key="network-mount")
    job = result["job"]
    assert isinstance(job, dict)
    receipt_id = str(job["receipt_ref"]).rsplit("/", 1)[-1].removesuffix(".json")
    receipt = instance.scheduler.journal.get_receipt(receipt_id)
    assert receipt is not None
    assert receipt["network_used"] is True
    assert receipt["automatic_deletion"] is False
    view = instance.folder_sources.public_view(source_id)
    assert view["network_access"] == "mounted_filesystem"
    assert "path" not in view
    assert instance.network_status()["policy"]["external_access"] is False


def test_observer_state_validates_and_round_trips_backup_and_portable_export(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("durable observer\n", encoding="utf-8")
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    ready = instance.observe_folder_source(source_id)
    assert ready["phase"] == "ready"
    assert instance.validate_instance()["status"] == "valid"

    backup_path = tmp_path / "instance-backup.zip"
    instance.backup(destination=backup_path, reason="folder-source-test")
    observer_ref = f"state/folder-sources/observers/{source_id}.json"
    with zipfile.ZipFile(backup_path) as archive:
        assert f"payload/{observer_ref}" in archive.namelist()

    instance.set_folder_source_state(source_id, "paused")
    instance.restore(backup_path)
    restored = ProvelumeInstance(instance.root)
    assert restored.folder_sources.observer(source_id) == ready

    portable_path = tmp_path / "folder-source-portable.zip"
    restored.export_portable(portable_path)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(portable_path)
    imported = ProvelumeInstance(target.root)
    assert imported.folder_sources.observer(source_id) == ready
    assert imported.folder_sources.public_view(source_id)["policy_id"] == registered_policy_id(
        restored, source_id
    )


def registered_policy_id(instance: ProvelumeInstance, source_id: str) -> str:
    value = instance.folder_sources.public_view(source_id)["policy_id"]
    assert isinstance(value, str)
    return value


def test_cli_api_and_local_browser_expose_controls_without_public_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("operator controls\n", encoding="utf-8")
    root = tmp_path / "instance"
    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "folder-source-register",
                str(root),
                str(source),
                "--name",
                "Operator folder",
                "--quiescence-seconds",
                "0",
                "--stable-observations",
                "1",
            ]
        )
        == 0
    )
    registered = json.loads(capsys.readouterr().out)
    source_id = registered["id"]
    assert main(["folder-source-refresh", str(root), source_id]) == 0
    assert json.loads(capsys.readouterr().out)["job"]["status"] == "succeeded"

    client = TestClient(create_app(root))
    api = client.get("/api/v1/folder-sources")
    assert api.status_code == 200
    assert api.json()[0]["id"] == source_id
    assert "path" not in api.json()[0]
    assert client.post("/api/v1/folder-sources").status_code == 405
    english = client.get("/sources?lang=en")
    italian = client.get("/sources?lang=it")
    assert english.status_code == italian.status_code == 200
    assert "Folder Sources" in english.text
    assert "Source da cartelle" in italian.text
    token_match = re.search(r'name="csrf_token" value="([^"]+)"', english.text)
    assert token_match is not None
    assert (
        client.post(
            "/sources?lang=en",
            data={"csrf_token": "wrong", "source_id": source_id, "action": "paused"},
        ).status_code
        == 403
    )
    paused = client.post(
        "/sources?lang=en",
        data={
            "csrf_token": token_match.group(1),
            "source_id": source_id,
            "action": "paused",
        },
    )
    assert paused.status_code == 200
    assert "paused" in paused.text


def test_closed_observer_schema_rejects_private_or_unknown_fields(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    instance.observe_folder_source(source_id)
    path = instance.store.paths.state / "folder-sources" / "observers" / f"{source_id}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["private_content"] = "must never be journaled"
    path.write_text(json.dumps(value), encoding="utf-8")

    report = instance.validate_instance()
    assert report["status"] == "invalid"
    finding = next(
        item for item in report["errors"] if item["code"] == "folder_source_state_invalid"
    )
    assert finding["path"].endswith(f"{source_id}.json")


def test_deep_validation_rejects_observer_and_config_lifecycle_mismatch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    instance = _instance(tmp_path)
    source_id = str(_register(instance, source)["id"])
    instance.observe_folder_source(source_id)
    path = instance.store.paths.state / "folder-sources" / "observers" / f"{source_id}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["lifecycle_state"] = "paused"
    value["phase"] = "paused"
    path.write_text(json.dumps(value), encoding="utf-8")

    report = instance.validate_instance()
    assert report["status"] == "invalid"
    finding = next(
        item for item in report["errors"] if item["code"] == "folder_source_state_invalid"
    )
    assert "lifecycle does not match" in finding["message"]
