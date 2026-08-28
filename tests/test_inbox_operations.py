from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.inbox import InboxManager
from provelume.operations import OperationLedger
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _staged_path(instance_root: Path, locator: str) -> Path:
    return instance_root / "inbox" / "items" / Path(*PurePosixPath(locator).parts)


def test_inbox_copy_preserves_source_and_exposes_navigable_operation(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    source = external / "note.txt"
    source.write_text("Inbox operation evidence\n", encoding="utf-8")
    instance_root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(instance_root)

    result = InboxManager(instance.store).submit(source)

    submission = result["submission"]
    assert submission["status"] == "completed"
    assert submission["mode"] == "copy"
    assert source.read_text(encoding="utf-8") == "Inbox operation evidence\n"
    locator = submission["items"][0]["locator"]
    assert _staged_path(instance_root, locator).read_bytes() == source.read_bytes()
    assert instance.search("evidence")[0]["title"] == "note.txt"

    restarted = ProvelumeInstance(instance_root)
    operation = OperationLedger(restarted.store).get(submission["operation_id"])
    assert operation is not None
    assert operation["status"] == "completed"
    assert operation["related"]["submission_id"] == submission["id"]
    assert [event["code"] for event in operation["events"]] == [
        "inbox.enumeration_started",
        "inbox.item_staged",
        "inbox.item_completed",
    ]
    serialized = json.dumps(operation)
    assert str(external) not in serialized
    assert operation["metrics"]["items_completed"] == 1


def test_drop_processing_moves_only_after_verified_commit(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(instance_root)
    inbox = InboxManager(instance.store)
    inbox.ensure()
    dropped = inbox.drop / "nested" / "capture.md"
    dropped.parent.mkdir(parents=True)
    dropped.write_text("# Captured\n\nMoved after commit.\n", encoding="utf-8")

    result = inbox.process_drop()

    submission = result["submission"]
    assert submission["status"] == "completed"
    assert submission["mode"] == "move_after_commit"
    assert submission["items"][0]["moved_source"] is True
    assert not dropped.exists()
    staged = _staged_path(instance_root, submission["items"][0]["locator"])
    assert staged.read_text(encoding="utf-8").startswith("# Captured")
    assert len(instance.store.list_canonical("originals")) == 1
    assert instance.store.original_bytes(
        instance.store.list_canonical("originals")[0]["id"]
    ) == staged.read_bytes()


def test_move_after_commit_unlinks_submitted_symlink_not_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("symlink-safe bytes\n", encoding="utf-8")
    submitted = tmp_path / "submitted.txt"
    try:
        submitted.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable on this runner: {exc}")
    instance_root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(instance_root)

    result = InboxManager(instance.store).submit(
        submitted,
        move_after_commit=True,
    )

    submission = result["submission"]
    assert submission["status"] == "completed"
    assert submission["items"][0]["moved_source"] is True
    assert not submitted.is_symlink()
    assert target.read_text(encoding="utf-8") == "symlink-safe bytes\n"
    staged = _staged_path(instance_root, submission["items"][0]["locator"])
    assert staged.name == "submitted.txt"
    assert staged.read_bytes() == target.read_bytes()


def test_failed_extraction_keeps_external_and_preserved_original(tmp_path: Path) -> None:
    source = tmp_path / "broken.txt"
    source.write_bytes(b"\xff\xfe")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    result = InboxManager(instance.store).submit(source, move_after_commit=True)

    submission = result["submission"]
    assert submission["status"] == "failed"
    assert submission["items"][0]["status"] == "failed"
    assert submission["items"][0]["error_code"] == "extraction_failed"
    assert submission["items"][0]["moved_source"] is False
    assert source.read_bytes() == b"\xff\xfe"
    originals = instance.store.list_canonical("originals")
    assert len(originals) == 1
    assert instance.store.original_bytes(originals[0]["id"]) == b"\xff\xfe"
    operation = OperationLedger(instance.store).get(submission["operation_id"])
    assert operation is not None
    assert operation["status"] == "failed"


def test_read_only_inbox_views_do_not_create_directories(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    ProvelumeInstance.initialise(instance_root)
    assert not (instance_root / "inbox").exists()
    assert not (instance_root / "state" / "operations").exists()
    client = TestClient(create_app(instance_root))

    assert client.get("/api/v1/inbox").status_code == 200
    assert client.get("/api/v1/inbox/submissions").status_code == 200
    assert client.get("/inbox").status_code == 200
    assert client.get("/operations").status_code == 200
    assert not (instance_root / "inbox").exists()
    assert not (instance_root / "state" / "operations").exists()


def test_invalid_operation_record_is_skipped(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(instance_root)
    ledger = OperationLedger(instance.store)
    operation = ledger.start("test.valid", "Valid operation")
    ledger.append(operation.id, "test.started", "The valid operation started.")
    ledger.close(operation.id, status="completed", summary="Valid evidence.")
    invalid = ledger.records / f"op_{'0' * 32}.json"
    invalid.write_text("{}\n", encoding="utf-8")

    records = ledger.list()

    assert [record["id"] for record in records] == [operation.id]
    assert ledger.kinds() == ["test.valid"]
    client = TestClient(create_app(instance_root))
    response = client.get("/operations")
    assert response.status_code == 200
    assert "Valid operation" in response.text


def test_operation_and_inbox_http_surfaces_are_read_only(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("Browser-visible operation\n", encoding="utf-8")
    instance_root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(instance_root)
    result = InboxManager(instance.store).submit(source)
    operation_id = result["submission"]["operation_id"]
    submission_id = result["submission"]["id"]
    client = TestClient(create_app(instance_root))

    assert client.get("/operations").status_code == 200
    detail_page = client.get(f"/operations/{operation_id}")
    assert detail_page.status_code == 200
    assert "inbox.item_completed" in detail_page.text
    assert client.get("/inbox").status_code == 200
    assert client.get("/api/v1/operations").json()[0]["id"] == operation_id
    assert client.get(f"/api/v1/operations/{operation_id}").status_code == 200
    assert client.get("/api/v1/inbox").json()["submissions"] == 1
    assert client.get(f"/api/v1/inbox/submissions/{submission_id}").status_code == 200
    assert client.post("/api/v1/operations").status_code == 405
    assert client.post("/api/v1/inbox").status_code == 405
    assert client.get("/api/v1/inbox/submissions/inbox_../../x").status_code == 404


def test_inbox_and_operations_cli(tmp_path: Path, capsys) -> None:
    source = tmp_path / "note.txt"
    source.write_text("CLI operation\n", encoding="utf-8")
    instance_root = tmp_path / "instance"
    assert main(["init", str(instance_root)]) == 0
    capsys.readouterr()

    assert main(["inbox-submit", str(instance_root), str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    operation_id = result["submission"]["operation_id"]

    assert main(["operations", str(instance_root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == operation_id
    assert main(["operation", str(instance_root), operation_id]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    assert main(["inbox-status", str(instance_root)]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["submissions"] == 1
