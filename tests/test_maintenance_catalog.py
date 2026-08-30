from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from provelume import ingest as ingest_module
from provelume import maintenance as maintenance_module
from provelume.cli import main
from provelume.index import index_status
from provelume.library_projection_model import LIBRARY_MANIFEST
from provelume.maintenance import MaintenanceManager
from provelume.maintenance_model import MaintenanceUnavailableError
from provelume.scheduler import retry_payload, schedule_payload
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _instance_with_documents(
    tmp_path: Path,
    *,
    count: int = 2,
) -> tuple[ProvelumeInstance, Path]:
    source = tmp_path / "source"
    source.mkdir()
    for index in range(count):
        (source / f"note-{index}.txt").write_bytes(
            f"durable maintenance evidence {index}\n".encode()
        )
    instance = ProvelumeInstance.initialise(
        tmp_path / "instance",
        name="Maintenance fixture",
    )
    instance.ingest(source, source_name="Synthetic maintenance source")
    return instance, source


def _instance_scope(instance: ProvelumeInstance) -> dict[str, str]:
    return {"kind": "instance", "id": instance.instance_summary()["id"]}


def _database_rows(instance: ProvelumeInstance) -> list[tuple[str, str]]:
    connection = sqlite3.connect(instance.root / "indexes" / "search.sqlite3")
    try:
        return connection.execute(
            "SELECT document_id, version_id FROM search ORDER BY document_id, version_id"
        ).fetchall()
    finally:
        connection.close()


def test_catalog_is_closed_and_reindex_plans_are_read_only(tmp_path: Path) -> None:
    instance, _source = _instance_with_documents(tmp_path)
    catalog = instance.maintenance_catalog()
    assert [item["id"] for item in catalog] == [
        "search.reindex.full",
        "search.reindex.incremental",
        "maintenance.library_rebuild",
        "maintenance.source_reconcile",
        "maintenance.validate",
        "maintenance.original_assurance",
        "maintenance.duplicate_scan",
        "maintenance.backup_create",
        "maintenance.backup_verify",
    ]
    assert all(
        item["network_used"] is False
        and item["canonical_mutation"] is False
        and item["automatic_deletion"] is False
        for item in catalog
    )
    unavailable = {
        item["id"]: item["unavailable_reason"]
        for item in catalog
        if not item["available"]
    }
    assert unavailable == {
        "maintenance.source_reconcile": "planned_s04",
        "maintenance.backup_create": "explicit_target_required",
        "maintenance.backup_verify": "explicit_target_required",
    }

    state_root = instance.root / "state" / "maintenance"
    candidate_root = instance.root / "indexes" / "reindex-candidates"
    full = instance.plan_maintenance_action("search.reindex.full")
    incremental = instance.plan_maintenance_action("search.reindex.incremental")
    assert full["ready"] is True
    assert full["plan"]["strategy"] == "full"
    assert full["plan"]["estimated_items"] == 2
    assert incremental["plan"]["strategy"] == "incremental"
    assert incremental["plan"]["estimated_items"] == 0
    assert not state_root.exists()
    assert not candidate_root.exists()
    assert instance.get_maintenance_run("../../provelume") is None
    with pytest.raises(MaintenanceUnavailableError, match="planned_s04"):
        instance.queue_maintenance_action("maintenance.source_reconcile")
    with pytest.raises(MaintenanceUnavailableError, match="explicit_target_required"):
        instance.create_maintenance_policy(
            "maintenance.backup_create",
            state="disabled",
            schedule=schedule_payload(mode="manual", timezone="UTC"),
        )


def test_full_reindex_activates_one_verified_generation_without_canonical_mutation(
    tmp_path: Path,
) -> None:
    instance, _source = _instance_with_documents(tmp_path)
    canonical_before = instance.store.knowledge_fingerprint()
    result = instance.run_maintenance_action(
        "search.reindex.full",
        request_key="full-generation",
    )
    job = result["job"]
    assert job["status"] == "succeeded"
    assert job["progress"] == {"processed": 2, "skipped": 0, "errors": 0}
    run = instance.maintenance.run_for_job(job["id"])
    assert run is not None
    assert run["status"] == "completed"
    assert run["cursor"] == 2
    assert run["plan"]["strategy"] == "full"
    assert instance.store.knowledge_fingerprint() == canonical_before
    assert index_status(instance.store) == "ready"
    assert len(_database_rows(instance)) == 2

    metadata = json.loads(
        (instance.root / "indexes" / "search.meta.json").read_text(encoding="utf-8")
    )
    assert metadata["generation_id"] == run["generation_id"]
    assert metadata["job_id"] == job["id"]
    assert metadata["plan_digest"] == run["plan_digest"]
    receipt = instance.scheduler.journal.get_receipt(
        f"receipt_{job['id'].removeprefix('job_')}"
    )
    assert receipt is not None
    assert receipt["network_used"] is False
    assert receipt["canonical_mutation"] is False
    assert receipt["automatic_deletion"] is False
    assert not list((instance.root / "indexes" / "reindex-candidates").glob("*"))
    replay = instance.run_maintenance_action(
        "search.reindex.full",
        request_key="full-generation",
    )
    assert replay["queued"]["created"] is False
    assert replay["job"]["id"] == job["id"]
    assert len(instance.list_maintenance_runs()) == 1


def test_incremental_reindex_selects_only_changed_version_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source = _instance_with_documents(tmp_path)
    before = {item["title"]: item for item in instance.list_documents()}
    alpha = before["note-0.txt"]
    monkeypatch.setattr(
        ingest_module,
        "refresh_search_index",
        lambda _store, _document_ids, **_kwargs: len(before),
    )
    (source / "note-0.txt").write_bytes(b"replacement incremental vocabulary\n")
    instance.ingest_run(source)
    changed = instance.get_document(alpha["id"])
    assert changed is not None
    assert changed["current_version"]["id"] != alpha["current_version"]["id"]
    assert index_status(instance.store) == "out_of_date"

    plan = instance.plan_maintenance_action("search.reindex.incremental")
    assert plan["plan"]["strategy"] == "incremental"
    assert plan["plan"]["selected_document_ids"] == [alpha["id"]]
    assert plan["plan"]["estimated_items"] == 1
    canonical_before = instance.store.knowledge_fingerprint()
    result = instance.run_maintenance_action(
        "search.reindex.incremental",
        request_key="incremental-generation",
    )
    assert result["job"]["status"] == "succeeded"
    assert result["job"]["progress"] == {
        "processed": 1,
        "skipped": 0,
        "errors": 0,
    }
    assert instance.store.knowledge_fingerprint() == canonical_before
    assert instance.search("replacement incremental")[0]["document_id"] == alpha["id"]
    assert instance.search("durable maintenance evidence 1")[0]["title"] == "note-1.txt"
    assert instance.search("durable maintenance evidence 0") == []
    metadata = json.loads(
        (instance.root / "indexes" / "search.meta.json").read_text(encoding="utf-8")
    )
    assert metadata["build_mode"] == "incremental"
    assert metadata["build_strategy"] == "incremental"


def test_stale_lease_resumes_after_exact_item_checkpoint_without_duplicate_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source = _instance_with_documents(tmp_path, count=3)
    base = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="search.reindex",
        scope=_instance_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"],
        request_key="checkpoint-crash",
        now=base,
    )["job"]
    crashes = 0

    def crash_once(_self, _record):
        nonlocal crashes
        crashes += 1
        if crashes == 1:
            raise KeyboardInterrupt("synthetic process stop")

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", crash_once)
    with pytest.raises(KeyboardInterrupt, match="synthetic process stop"):
        instance.scheduler.run_one(job_id=queued["id"], lease_seconds=1, now=base)
    interrupted = instance.scheduler.journal.get_job(queued["id"])
    assert interrupted is not None
    assert interrupted["status"] == "running"
    assert interrupted["progress"]["processed"] == 1
    durable = instance.maintenance.run_for_job(queued["id"])
    assert durable is not None and durable["cursor"] == 1

    recovery_at = base + timedelta(seconds=2)
    recovery = instance.scheduler.recover(now=recovery_at)
    assert recovery["expired_leases"] == 1
    recovered = instance.scheduler.journal.get_job(queued["id"])
    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["recovery_state"] == "resumable"
    finished = instance.scheduler.run_one(job_id=queued["id"], now=recovery_at)
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["attempt"] == 2
    assert finished["progress"] == {"processed": 3, "skipped": 0, "errors": 0}
    rows = _database_rows(instance)
    assert len(rows) == len(set(rows)) == 3


def test_recovery_restarts_a_content_mismatched_checkpoint_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source = _instance_with_documents(tmp_path)
    base = datetime(2026, 8, 30, 8, 30, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="search.reindex",
        scope=_instance_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"], request_key="candidate-content-mismatch", now=base
    )["job"]

    def stop_once(_self, _record):
        raise KeyboardInterrupt("synthetic candidate stop")

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", stop_once)
    with pytest.raises(KeyboardInterrupt, match="candidate stop"):
        instance.scheduler.run_one(job_id=queued["id"], lease_seconds=1, now=base)
    interrupted = instance.maintenance.run_for_job(queued["id"])
    assert interrupted is not None and interrupted["cursor"] == 1
    candidate = instance.root / interrupted["candidate"]["database_ref"]
    connection = sqlite3.connect(candidate)
    try:
        connection.execute("UPDATE search SET content = 'mismatched checkpoint content'")
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(
        MaintenanceManager,
        "_after_item_checkpoint",
        lambda _self, _record: None,
    )
    recovery_at = base + timedelta(seconds=2)
    instance.scheduler.recover(now=recovery_at)
    finished = instance.scheduler.run_one(job_id=queued["id"], now=recovery_at)
    assert finished is not None and finished["status"] == "succeeded"
    run = instance.maintenance.run_for_job(queued["id"])
    assert run is not None and run["plan_revision"] == 2
    assert finished["progress"] == {"processed": 3, "skipped": 0, "errors": 0}
    assert len(_database_rows(instance)) == 2


def test_replay_reconciles_activation_completed_before_job_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source = _instance_with_documents(tmp_path)
    base = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="search.reindex",
        scope=_instance_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"], request_key="activation-crash", now=base
    )["job"]
    calls = 0

    def stop_between_database_and_sidecar(_self, _record):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt("synthetic post-activation stop")

    monkeypatch.setattr(
        MaintenanceManager,
        "_after_database_activation",
        stop_between_database_and_sidecar,
    )
    with pytest.raises(KeyboardInterrupt, match="post-activation"):
        instance.scheduler.run_one(job_id=queued["id"], lease_seconds=1, now=base)
    run = instance.maintenance.run_for_job(queued["id"])
    assert run is not None and run["status"] == "activating"
    embedded = instance.maintenance._embedded_generation_metadata(
        instance.root / "indexes" / "search.sqlite3"
    )
    assert embedded is not None
    assert embedded["generation_id"] == run["generation_id"]

    monkeypatch.setattr(
        MaintenanceManager,
        "_after_database_activation",
        lambda _self, _record: None,
    )
    recovery_at = base + timedelta(seconds=2)
    instance.scheduler.recover(now=recovery_at)
    finished = instance.scheduler.run_one(job_id=queued["id"], now=recovery_at)
    assert finished is not None and finished["status"] == "succeeded"
    assert finished["attempt"] == 2
    completed = instance.maintenance.run_for_job(queued["id"])
    assert completed is not None and completed["status"] == "completed"
    metadata = json.loads(
        (instance.root / "indexes" / "search.meta.json").read_text(encoding="utf-8")
    )
    assert metadata["generation_id"] == completed["generation_id"]
    assert len(_database_rows(instance)) == 2


def test_reader_uses_embedded_metadata_between_database_and_sidecar_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source = _instance_with_documents(tmp_path)
    document = next(item for item in instance.list_documents() if item["title"] == "note-0.txt")
    monkeypatch.setattr(
        ingest_module,
        "refresh_search_index",
        lambda _store, _document_ids, **_kwargs: 2,
    )
    (source / "note-0.txt").write_bytes(b"activation window vocabulary\n")
    instance.ingest_run(source)
    assert index_status(instance.store) == "out_of_date"

    base = datetime(2026, 8, 30, 9, 10, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="search.reindex.incremental",
        scope=_instance_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"], request_key="reader-activation-window", now=base
    )["job"]

    def stop_after_database(_self, _record):
        raise KeyboardInterrupt("synthetic reader-window stop")

    monkeypatch.setattr(
        MaintenanceManager,
        "_after_database_activation",
        stop_after_database,
    )
    with pytest.raises(KeyboardInterrupt, match="reader-window"):
        instance.scheduler.run_one(job_id=queued["id"], lease_seconds=1, now=base)
    run = instance.maintenance.run_for_job(queued["id"])
    assert run is not None and run["status"] == "activating"
    assert index_status(instance.store) == "ready"
    assert instance.search("activation window")[0]["document_id"] == document["id"]
    embedded = instance.maintenance._embedded_generation_metadata(
        instance.root / "indexes" / "search.sqlite3"
    )
    assert embedded is not None and embedded["generation_id"] == run["generation_id"]

    monkeypatch.setattr(
        MaintenanceManager,
        "_after_database_activation",
        lambda _self, _record: None,
    )
    recovery_at = base + timedelta(seconds=2)
    instance.scheduler.recover(now=recovery_at)
    finished = instance.scheduler.run_one(job_id=queued["id"], now=recovery_at)
    assert finished is not None and finished["status"] == "succeeded"
    completed = instance.maintenance.run_for_job(queued["id"])
    assert completed is not None and completed["status"] == "completed"


def test_post_activation_recovery_revises_a_generation_made_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source = _instance_with_documents(tmp_path)
    base = datetime(2026, 8, 30, 9, 15, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="search.reindex",
        scope=_instance_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"], request_key="activation-stale", now=base
    )["job"]

    def stop_after_database(_self, _record):
        raise KeyboardInterrupt("synthetic stale-generation stop")

    monkeypatch.setattr(
        MaintenanceManager,
        "_after_database_activation",
        stop_after_database,
    )
    with pytest.raises(KeyboardInterrupt, match="stale-generation"):
        instance.scheduler.run_one(job_id=queued["id"], lease_seconds=1, now=base)
    (source / "note-2.txt").write_bytes(b"post-activation canonical evidence\n")
    instance.ingest_run(source)

    monkeypatch.setattr(
        MaintenanceManager,
        "_after_database_activation",
        lambda _self, _record: None,
    )
    recovery_at = base + timedelta(seconds=2)
    instance.scheduler.recover(now=recovery_at)
    finished = instance.scheduler.run_one(job_id=queued["id"], now=recovery_at)
    assert finished is not None and finished["status"] == "succeeded"
    run = instance.maintenance.run_for_job(queued["id"])
    assert run is not None
    assert run["plan_revision"] == 2
    assert run["plan"]["estimated_items"] == 3
    assert len(_database_rows(instance)) == 3
    assert instance.search("post-activation canonical")[0]["title"] == "note-2.txt"


def test_interrupted_reindex_revises_plan_after_canonical_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source = _instance_with_documents(tmp_path)
    base = datetime(2026, 8, 30, 9, 30, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="search.reindex",
        scope=_instance_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"], request_key="changed-plan", now=base
    )["job"]
    calls = 0

    def stop_once(_self, _record):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt("synthetic changed-plan stop")

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", stop_once)
    with pytest.raises(KeyboardInterrupt, match="changed-plan"):
        instance.scheduler.run_one(job_id=queued["id"], lease_seconds=1, now=base)
    (source / "note-2.txt").write_bytes(b"new canonical evidence after interruption\n")
    instance.ingest_run(source)

    recovery_at = base + timedelta(seconds=2)
    instance.scheduler.recover(now=recovery_at)
    finished = instance.scheduler.run_one(job_id=queued["id"], now=recovery_at)
    assert finished is not None and finished["status"] == "succeeded"
    run = instance.maintenance.run_for_job(queued["id"])
    assert run is not None
    assert run["plan_revision"] == 2
    assert run["plan"]["estimated_items"] == 3
    assert finished["progress"] == {"processed": 4, "skipped": 0, "errors": 0}
    assert len(_database_rows(instance)) == 3
    assert instance.search("after interruption")[0]["title"] == "note-2.txt"


def test_transient_reindex_io_retry_preserves_monotonic_checkpoint_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source = _instance_with_documents(tmp_path)
    base = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    policy = instance.scheduler.journal.create_policy(
        job_kind="search.reindex",
        scope=_instance_scope(instance),
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
        retry=retry_payload(max_attempts=3, base_seconds=1, max_seconds=2),
        now=base,
    )
    queued = instance.scheduler.journal.run_now(
        policy["id"], request_key="io-retry", now=base
    )["job"]
    calls = 0

    def fail_once(_self, _record):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic candidate fsync failure")

    monkeypatch.setattr(MaintenanceManager, "_after_item_checkpoint", fail_once)
    waiting = instance.scheduler.run_one(job_id=queued["id"], now=base)
    assert waiting is not None
    assert waiting["status"] == "retry_wait"
    assert waiting["progress"] == {"processed": 1, "skipped": 0, "errors": 1}

    retry_at = base + timedelta(seconds=1)
    instance.scheduler.recover(now=retry_at)
    finished = instance.scheduler.run_one(job_id=queued["id"], now=retry_at)
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["attempt"] == 2
    assert finished["progress"] == {"processed": 2, "skipped": 0, "errors": 1}
    assert len(_database_rows(instance)) == 2


def test_temporary_space_refusal_preserves_active_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source = _instance_with_documents(tmp_path)
    database_before = (instance.root / "indexes" / "search.sqlite3").read_bytes()
    metadata_before = (instance.root / "indexes" / "search.meta.json").read_bytes()
    monkeypatch.setattr(
        maintenance_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1, used=1, free=0),
    )
    plan = instance.plan_maintenance_action("search.reindex.full")
    assert plan["ready"] is False
    result = instance.run_maintenance_action(
        "search.reindex.full",
        request_key="no-temporary-space",
    )
    assert result["job"]["status"] == "failed"
    assert result["job"]["attempts"][-1]["error_code"] == (
        "insufficient_temporary_space"
    )
    assert (instance.root / "indexes" / "search.sqlite3").read_bytes() == database_before
    assert (instance.root / "indexes" / "search.meta.json").read_bytes() == metadata_before
    assert instance.list_maintenance_runs() == []


def test_safe_catalogue_executors_emit_content_free_receipts(tmp_path: Path) -> None:
    instance, _source = _instance_with_documents(tmp_path)
    canonical_before = instance.store.knowledge_fingerprint()
    for action_id in (
        "maintenance.library_rebuild",
        "maintenance.validate",
        "maintenance.original_assurance",
        "maintenance.duplicate_scan",
    ):
        result = instance.run_maintenance_action(
            action_id,
            request_key=f"run-{action_id}",
        )
        job = result["job"]
        assert job["status"] == "succeeded", (action_id, job)
        receipt = instance.scheduler.journal.get_receipt(
            f"receipt_{job['id'].removeprefix('job_')}"
        )
        assert receipt is not None
        assert receipt["network_used"] is False
        assert receipt["canonical_mutation"] is False
        assert receipt["automatic_deletion"] is False
    assert instance.store.knowledge_fingerprint() == canonical_before
    assert (instance.root / "library" / LIBRARY_MANIFEST).is_file()
    assert instance.validate_instance(deep=True)["status"] == "valid"


def test_maintenance_state_is_backed_up_exported_validated_and_exposed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance, _source = _instance_with_documents(tmp_path)
    result = instance.run_maintenance_action(
        "search.reindex.full",
        request_key="surface-generation",
    )
    run = instance.maintenance.run_for_job(result["job"]["id"])
    assert run is not None
    relative = f"state/maintenance/reindex-runs/{run['id']}.json"
    backup = instance.backup(destination=tmp_path / "backups", reason="maintenance-test")
    with zipfile.ZipFile(backup["archive"]) as archive:
        assert f"payload/{relative}" in archive.namelist()
    portable = instance.export_portable(tmp_path / "exports", derived_state="rebuild")
    with zipfile.ZipFile(portable["archive"]) as archive:
        assert f"instance/{relative}" in archive.namelist()

    assert main(["maintenance-catalog", str(instance.root)]) == 0
    cli_catalog = json.loads(capsys.readouterr().out)
    assert cli_catalog[0]["id"] == "search.reindex.full"
    assert main(
        ["maintenance-plan", str(instance.root), "search.reindex.incremental"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True

    app = create_app(instance.root)
    with TestClient(app) as client:
        api_catalog = client.get("/api/v1/maintenance")
        assert api_catalog.status_code == 200
        assert len(api_catalog.json()) == 9
        assert client.get(f"/api/v1/maintenance/runs/{run['id']}").status_code == 200
        assert client.post("/api/v1/maintenance").status_code == 405
        english = client.get("/maintenance?lang=en")
        italian = client.get("/maintenance?lang=it")
        assert english.status_code == italian.status_code == 200
        assert "Maintenance catalogue" in english.text
        assert "Catalogo manutenzione" in italian.text
        assert "Full FTS reindex" in english.text
        assert "Reindicizzazione FTS completa" in italian.text
        assert str(instance.root) not in english.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', english.text)
        assert csrf is not None
        queued = client.post(
            "/maintenance?lang=en",
            data={
                "csrf_token": csrf.group(1),
                "action_id": "maintenance.validate",
            },
        )
        assert queued.status_code == 200
        assert "Maintenance job queued" in queued.text

    run_path = instance.root / relative
    run_path.unlink()
    instance.restore(backup["archive"])
    restored = ProvelumeInstance(instance.root)
    assert restored.get_maintenance_run(run["id"]) == run

    imported = ProvelumeInstance.initialise(tmp_path / "portable-target")
    imported.import_portable(portable["archive"])
    imported = ProvelumeInstance(imported.root)
    assert imported.get_maintenance_run(run["id"]) == run

    run_path = restored.root / relative
    corrupted = json.loads(run_path.read_text(encoding="utf-8"))
    corrupted["network_used"] = True
    run_path.write_text(json.dumps(corrupted), encoding="utf-8")
    report = restored.validate_instance(deep=True)
    assert report["status"] == "invalid"
    assert any(error["code"] == "maintenance_record_invalid" for error in report["errors"])
