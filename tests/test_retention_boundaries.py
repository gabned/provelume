from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import provelume.retention as retention_module
from provelume.cli import main
from provelume.inbox import InboxManager
from provelume.instance_lifecycle import (
    InstanceLifecycleError,
    InstanceLifecycleManager,
)
from provelume.instance_validation import inspect_instance
from provelume.library_projection_model import LIBRARY_MANIFEST
from provelume.paths import safe_instance_path
from provelume.retention import DocumentRetentionManager
from provelume.retention_model import (
    PurgeAuthorizationError,
    PurgeTransactionError,
    RetentionConflictError,
    RetentionNotFoundError,
)
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore
from provelume.web import create_app


def _ingested_markdown(
    tmp_path: Path,
    *,
    name: str = "retention-note.md",
    content: bytes = b"# Retention note\n\nunique-retention-token\n",
) -> tuple[ProvelumeInstance, Path, dict[str, object]]:
    source = tmp_path / name
    source.write_bytes(content)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    return instance, source, instance.list_documents()[0]


def _manifest(instance: ProvelumeInstance) -> dict[str, object]:
    return json.loads(
        (instance.store.paths.library / LIBRARY_MANIFEST).read_text(encoding="utf-8")
    )


def _original(
    instance: ProvelumeInstance,
    document_id: str,
) -> tuple[dict[str, object], Path, bytes]:
    version = instance.current_version(document_id)
    assert version is not None
    original = instance.store.read_canonical("originals", str(version["original_id"]))
    assert original is not None
    path = safe_instance_path(instance.root, str(original["storage_ref"]))
    return original, path, path.read_bytes()


def _canonical_lineage_bytes(
    instance: ProvelumeInstance,
    document_id: str,
) -> dict[str, bytes]:
    selected: dict[str, bytes] = {}
    for kind in (
        "documents",
        "versions",
        "acquisitions",
        "originals",
        "provenance",
        "classifications",
    ):
        for path in sorted(instance.store.paths.canonical_dir(kind).glob("*.json")):
            if document_id.encode("utf-8") in path.read_bytes() or kind == "originals":
                selected[path.relative_to(instance.root).as_posix()] = path.read_bytes()
    return selected


def test_archive_and_projection_removal_preserve_original_and_classification(
    tmp_path: Path,
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    area = instance.create_hierarchy_node("area", "Long-lived work")
    instance.classify_document(document_id, str(area["id"]))
    instance.rebuild_library()
    original, original_path, original_bytes = _original(instance, document_id)
    classification = instance.document_classification(document_id)

    archived = instance.archive_document(document_id)

    assert archived["changed"] is True
    assert archived["originals_deleted"] == 0
    assert archived["disposition"]["status"] == "archived"
    assert str(_manifest(instance)["primary_paths"][document_id]).startswith(
        "archive/"
    )
    assert instance.document_classification(document_id) == classification
    assert instance.store.read_canonical("originals", str(original["id"])) == original
    assert original_path.read_bytes() == original_bytes

    assert instance.document_disposition("../../outside") is None
    with pytest.raises(RetentionNotFoundError, match="document not found"):
        instance.archive_document("../../outside")

    repeated = instance.archive_document(document_id)
    assert repeated["changed"] is False
    assert repeated["operation"] is None

    unarchived = instance.unarchive_document(document_id)
    assert unarchived["disposition"]["status"] == "active"
    assert str(_manifest(instance)["primary_paths"][document_id]).startswith(
        "areas/"
    )

    removed = instance.remove_document_from_library(document_id)
    assert removed["disposition"]["projected"] is False
    assert document_id not in _manifest(instance)["primary_paths"]
    assert instance.get_document(document_id) is not None
    assert original_path.read_bytes() == original_bytes

    restored = instance.restore_document_to_library(document_id)
    assert restored["disposition"]["projected"] is True
    assert document_id in _manifest(instance)["primary_paths"]
    assert original_path.read_bytes() == original_bytes


def test_recoverable_trash_hides_search_and_projection_then_restores_lineage(
    tmp_path: Path,
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    instance.rebuild_library()
    lineage_before = _canonical_lineage_bytes(instance, document_id)
    original, original_path, original_bytes = _original(instance, document_id)
    assert [
        item["document_id"] for item in instance.search("unique-retention-token")
    ] == [
        document_id
    ]

    trashed = instance.trash_document(document_id)

    assert trashed["disposition"]["status"] == "trashed"
    assert trashed["disposition"]["projected"] is False
    assert instance.list_documents() == []
    assert [item["id"] for item in instance.list_documents(disposition="trashed")] == [
        document_id
    ]
    assert instance.search("unique-retention-token") == []
    assert document_id not in _manifest(instance)["primary_paths"]
    assert instance.get_document(document_id) is not None
    assert original_path.read_bytes() == original_bytes
    assert instance.store.read_canonical("originals", str(original["id"])) == original

    client = TestClient(create_app(instance.root))
    assert client.get("/api/v1/documents").json() == []
    trashed_api = client.get(
        "/api/v1/documents",
        params={"disposition": "trashed"},
    )
    assert [item["id"] for item in trashed_api.json()] == [document_id]
    assert (
        client.get(f"/api/v1/documents/{document_id}/disposition").json()["status"]
        == "trashed"
    )
    assert client.post(f"/api/v1/documents/{document_id}/disposition").status_code == 405
    assert client.post(f"/api/v1/documents/{document_id}/purge").status_code == 404
    assert client.get("/browse", params={"disposition": "invalid"}).status_code == 400

    restored = instance.restore_document_from_trash(document_id)

    assert restored["disposition"]["status"] == "active"
    assert restored["disposition"]["projected"] is True
    assert [
        item["document_id"] for item in instance.search("unique-retention-token")
    ] == [
        document_id
    ]
    assert document_id in _manifest(instance)["primary_paths"]
    assert _canonical_lineage_bytes(instance, document_id) == lineage_before
    assert original_path.read_bytes() == original_bytes


def test_permanent_purge_requires_fresh_preview_confirmation_and_boundaries(
    tmp_path: Path,
) -> None:
    instance, source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    original, original_path, original_bytes = _original(instance, document_id)
    source_bytes = source.read_bytes()
    with pytest.raises(RetentionConflictError, match="recoverable trash"):
        instance.purge_document_preview(document_id)

    instance.trash_document(document_id)
    backup = instance.backup(reason="pre-purge-boundary-evidence")
    preview = instance.purge_document_preview(document_id)

    assert preview["status"] == "confirmation_required"
    assert str(preview["confirmation_token"]).startswith("purge_")
    assert preview["impact"]["managed_backup_archives_observed"] == 1
    assert preview["impact"]["boundaries"]["broader_erasure_claimed"] is False
    with pytest.raises(PurgeAuthorizationError, match="acknowledgement"):
        instance.purge_document(
            document_id,
            str(preview["confirmation_token"]),
        )
    with pytest.raises(PurgeAuthorizationError, match="missing or invalid"):
        instance.purge_document(
            document_id,
            "wrong-token",
            acknowledge_boundaries=True,
        )
    assert instance.get_document(document_id) is not None
    assert original_path.read_bytes() == original_bytes

    instance.restore_document_from_trash(document_id)
    instance.trash_document(document_id)
    with pytest.raises(PurgeAuthorizationError, match="stale"):
        instance.purge_document(
            document_id,
            str(preview["confirmation_token"]),
            acknowledge_boundaries=True,
        )
    preview = instance.purge_document_preview(document_id)
    result = instance.purge_document(
        document_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )

    receipt = result["receipt"]
    assert result["status"] == "completed"
    assert receipt["status"] == "completed"
    assert receipt["live_instance"]["original_files_removed"] == 1
    assert receipt["boundaries"]["managed_backup_archives_observed"] == 1
    assert receipt["boundaries"]["managed_backup_archives_modified"] == 0
    assert receipt["boundaries"]["external_backups_and_replicas"] == "not_observable"
    assert receipt["boundaries"]["broader_erasure_claimed"] is False
    assert instance.get_document(document_id) is None
    assert instance.store.versions_for_document(document_id) == []
    assert instance.store.read_canonical("originals", str(original["id"])) is None
    assert not original_path.exists()
    assert source.read_bytes() == source_bytes
    assert Path(str(backup["archive"])).is_file()
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    assert instance.library_status()["status"] == "ready"

    serialized = json.dumps(receipt, sort_keys=True)
    assert document_id not in serialized
    assert str(document["title"]) not in serialized
    repeated = instance.purge_document(
        document_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )
    assert repeated["status"] == "already_completed"
    assert repeated["receipt"] == receipt


def test_permanent_purge_removes_operational_records_linked_by_acquisition(
    tmp_path: Path,
) -> None:
    instance, source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    acquisition = next(
        item
        for item in instance.store.list_canonical("acquisitions")
        if item["document_id"] == document_id
    )
    runs = instance.list_ingestion_runs()
    assert len(runs) == 1
    run_id = str(runs[0]["id"])
    item_paths = sorted(
        (instance.store.paths.state / "ingestion" / "items").glob("item_*.json")
    )
    assert len(item_paths) == 1
    item_path = item_paths[0]
    item_bytes = item_path.read_bytes()
    assert document_id.encode("utf-8") not in item_bytes
    assert str(acquisition["id"]).encode("utf-8") in item_bytes
    assert source.name.encode("utf-8") in item_bytes

    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    result = instance.purge_document(
        document_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )

    assert result["status"] == "completed"
    assert item_path.exists() is False
    detail = instance.get_ingestion_run(run_id)
    assert detail is not None
    assert detail["items"] == []
    assert source.name not in json.dumps(detail, sort_keys=True)
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_permanent_purge_serializes_all_canonical_ingestion_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    retry_source = tmp_path / "retry-after-purge.md"
    retry_source.write_bytes(b"retry content")
    failed = instance.ingest_run(retry_source, max_file_bytes=1)
    assert failed["run"]["status"] == "failed"
    competing_source = tmp_path / "concurrent-ingestion.md"
    competing_source.write_bytes(b"must not race purge")

    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    manager = instance.retention
    real_stage = manager._stage_targets
    blocked_paths: list[str] = []

    def stage_after_rejected_ingestion(pending: dict[str, object]) -> None:
        attempts = (
            ("filesystem", lambda: instance.ingest(competing_source)),
            ("retry", lambda: instance.retry_ingestion(str(failed["run"]["id"]))),
            ("inbox", lambda: InboxManager(instance.store).submit(competing_source)),
        )
        for label, attempt in attempts:
            with pytest.raises(
                InstanceLifecycleError,
                match="another Instance lifecycle operation is active",
            ):
                attempt()
            blocked_paths.append(label)
        real_stage(pending)

    monkeypatch.setattr(manager, "_stage_targets", stage_after_rejected_ingestion)
    result = manager.purge(
        document_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )

    assert result["status"] == "completed"
    assert blocked_paths == ["filesystem", "retry", "inbox"]
    assert not any(
        item.get("locator") == competing_source.name
        for item in instance.store.list_canonical("documents")
    )
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_purge_retains_original_still_referenced_by_another_document(
    tmp_path: Path,
) -> None:
    shared = b"# Shared exact bytes\n\nshared-retention-token\n"
    first_source = tmp_path / "first" / "shared.md"
    second_source = tmp_path / "second" / "shared.md"
    first_source.parent.mkdir()
    second_source.parent.mkdir()
    first_source.write_bytes(shared)
    second_source.write_bytes(shared)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(first_source)
    instance.ingest(second_source)
    documents = instance.list_documents()
    first_id = str(documents[0]["id"])
    second_id = str(documents[1]["id"])
    first_original, original_path, original_bytes = _original(instance, first_id)
    second_original, _second_path, _second_bytes = _original(instance, second_id)
    assert first_original["id"] == second_original["id"]

    instance.trash_document(first_id)
    preview = instance.purge_document_preview(first_id)
    result = instance.purge_document(
        first_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )

    assert result["receipt"]["live_instance"]["original_files_removed"] == 0
    assert result["receipt"]["live_instance"]["shared_originals_retained"] == 1
    assert instance.get_document(first_id) is None
    assert instance.get_document(second_id) is not None
    assert instance.store.read_canonical("originals", str(first_original["id"])) is not None
    assert original_path.read_bytes() == original_bytes
    assert [
        item["document_id"] for item in instance.search("shared-retention-token")
    ] == [
        second_id
    ]


def test_failed_purge_rolls_back_and_can_retry_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    manager = instance.retention
    real_stage = manager._stage_targets

    def fail_after_staging(pending: dict[str, object]) -> None:
        real_stage(pending)
        raise OSError("synthetic failure after staging")

    monkeypatch.setattr(manager, "_stage_targets", fail_after_staging)
    with pytest.raises(OSError, match="synthetic failure"):
        manager.purge(
            document_id,
            str(preview["confirmation_token"]),
            acknowledge_boundaries=True,
        )

    assert manager.pending_path.exists() is False
    assert instance.get_document(document_id) is not None
    assert source.is_file()
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    assert instance.library_status()["status"] == "ready"

    monkeypatch.setattr(manager, "_stage_targets", real_stage)
    result = manager.purge(
        document_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )
    assert result["status"] == "completed"


def test_purge_rejects_target_changed_after_preview_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    manager = instance.retention
    real_stage = manager._stage_targets

    def change_bound_target(pending: dict[str, object]) -> None:
        targets = pending["targets"]
        assert isinstance(targets, list)
        first = targets[0]
        assert isinstance(first, dict)
        path = safe_instance_path(instance.root, str(first["path"]))
        path.write_bytes(path.read_bytes() + b"\n")
        real_stage(pending)

    monkeypatch.setattr(manager, "_stage_targets", change_bound_target)
    with pytest.raises(PurgeTransactionError, match="target changed"):
        manager.purge(
            document_id,
            str(preview["confirmation_token"]),
            acknowledge_boundaries=True,
        )

    assert manager.pending_path.exists() is False
    assert instance.get_document(document_id) is not None
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_interrupted_precommit_purge_is_restored_on_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    manager = instance.retention
    real_stage = manager._stage_targets

    def interrupt_after_staging(pending: dict[str, object]) -> None:
        real_stage(pending)
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_stage_targets", interrupt_after_staging)
    with pytest.raises(KeyboardInterrupt):
        manager.purge(
            document_id,
            str(preview["confirmation_token"]),
            acknowledge_boundaries=True,
        )
    assert manager.pending_path.is_file()

    reopened = ProvelumeInstance(instance.root)

    assert reopened.retention_recovery == {
        "action": "restored_pre_purge_state",
        "receipt": None,
    }
    assert reopened.get_document(document_id) is not None
    assert reopened.document_disposition(document_id)["status"] == "trashed"
    assert source.is_file()
    assert inspect_instance(reopened.root, deep=True)["status"] == "valid"


def test_interrupted_committed_purge_finishes_cleanup_on_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    manager = instance.retention

    def interrupt_before_cleanup(_pending: dict[str, object]) -> dict[str, object]:
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_finalize_committed", interrupt_before_cleanup)
    with pytest.raises(KeyboardInterrupt):
        manager.purge(
            document_id,
            str(preview["confirmation_token"]),
            acknowledge_boundaries=True,
        )
    assert manager.pending_path.is_file()

    reopened = ProvelumeInstance(instance.root)

    assert reopened.retention_recovery is not None
    assert reopened.retention_recovery["action"] == "completed_committed_purge"
    assert reopened.retention_recovery["receipt"]["status"] == "completed"
    assert reopened.get_document(document_id) is None
    assert source.is_file()
    assert inspect_instance(reopened.root, deep=True)["status"] == "valid"


def test_restore_recovers_committed_purge_before_restoring_older_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    backup = instance.backup(reason="before-purge-restore-ordering")
    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    manager = instance.retention

    def interrupt_before_cleanup(_pending: dict[str, object]) -> dict[str, object]:
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_finalize_committed", interrupt_before_cleanup)
    with pytest.raises(KeyboardInterrupt):
        manager.purge(
            document_id,
            str(preview["confirmation_token"]),
            acknowledge_boundaries=True,
        )
    assert manager.pending_path.is_file()

    restored = InstanceLifecycleManager(InstanceStore(instance.root)).restore(
        str(backup["archive"])
    )
    reopened = ProvelumeInstance(instance.root)

    assert restored["status"] == "restored"
    assert manager.pending_path.exists() is False
    assert reopened.get_document(document_id) is not None
    assert reopened.retention_recovery is None
    assert inspect_instance(reopened.root, deep=True)["status"] == "valid"


def test_pending_purge_rejects_tampered_external_preview_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    manager = instance.retention
    real_stage = manager._stage_targets

    def interrupt_after_staging(pending: dict[str, object]) -> None:
        real_stage(pending)
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_stage_targets", interrupt_after_staging)
    with pytest.raises(KeyboardInterrupt):
        manager.purge(
            document_id,
            str(preview["confirmation_token"]),
            acknowledge_boundaries=True,
        )

    protected = tmp_path / "must-not-be-deleted.txt"
    protected.write_text("retained", encoding="utf-8")
    pending = json.loads(manager.pending_path.read_text(encoding="utf-8"))
    pending["preview_path"] = str(protected)
    manager.store._atomic_json(manager.pending_path, pending)

    with pytest.raises(PurgeTransactionError, match="pending purge evidence is invalid"):
        DocumentRetentionManager(instance.store).recover_pending()
    assert protected.read_text(encoding="utf-8") == "retained"


def test_large_operational_state_file_is_reported_outside_content_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    state_record = instance.store.paths.state / "custom" / "large-record.json"
    state_record.parent.mkdir(parents=True)
    state_record.write_text(
        json.dumps({"document_id": document_id, "padding": "bounded"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(retention_module, "MAX_PURGE_STATE_SCAN_BYTES", 8)

    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)

    assert preview["impact"]["state_files_not_content_scanned"] > 0
    assert (
        preview["impact"]["boundaries"]["large_operational_state_files"]
        == "not content-scanned"
    )
    result = instance.purge_document(
        document_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )
    assert (
        result["receipt"]["boundaries"][
            "large_operational_state_files_not_content_scanned"
        ]
        > 0
    )
    assert document_id in state_record.read_text(encoding="utf-8")


def test_deep_validation_rejects_invalid_canonical_disposition(
    tmp_path: Path,
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])
    instance.archive_document(document_id)
    disposition = instance.document_disposition(document_id)
    assert disposition is not None
    path = instance.store.paths.canonical_dir("dispositions") / (
        f"{disposition['id']}.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "deleted"
    instance.store._atomic_json(path, payload)

    validation = inspect_instance(instance.root, deep=True)

    assert validation["status"] == "invalid"
    assert "disposition_state_invalid" in {
        finding["code"] for finding in validation["errors"]
    }


def test_retention_cli_keeps_purge_local_and_explicit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance, _source, document = _ingested_markdown(tmp_path)
    document_id = str(document["id"])

    assert main(["archive-document", str(instance.root), document_id]) == 0
    archived = json.loads(capsys.readouterr().out)
    assert archived["disposition"]["status"] == "archived"
    assert main(["trash-document", str(instance.root), document_id]) == 0
    capsys.readouterr()
    assert main(["purge-preview", str(instance.root), document_id]) == 0
    preview = json.loads(capsys.readouterr().out)
    token = str(preview["confirmation_token"])

    assert (
        main(
            [
                "purge-document",
                str(instance.root),
                document_id,
                "--confirm",
                token,
            ]
        )
        == 2
    )
    error = json.loads(capsys.readouterr().out)
    assert error["error_type"] == "PurgeAuthorizationError"
    assert (
        main(
            [
                "purge-document",
                str(instance.root),
                document_id,
                "--confirm",
                token,
                "--acknowledge-boundaries",
            ]
        )
        == 0
    )
    completed = json.loads(capsys.readouterr().out)
    assert completed["status"] == "completed"
