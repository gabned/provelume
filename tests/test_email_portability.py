from __future__ import annotations

import socket
from pathlib import Path

import pytest

from provelume.service import ProvelumeInstance


@pytest.fixture(autouse=True)
def qualified_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "provelume.email_contract.qualified_runtime_target",
        lambda: "ubuntu-24.04-x86_64-cpython312",
    )


def _data() -> bytes:
    return (
        b"Message-ID: <portable@example.invalid>\r\n"
        b"Subject: Portable synthetic\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=portable\r\n\r\n"
        b"--portable\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"unique-email-search-token\r\n"
        b"--portable\r\n"
        b"Content-Type: application/octet-stream\r\n"
        b"Content-Disposition: attachment; filename=private.bin\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"c3ludGhldGljLWF0dGFjaG1lbnQ=\r\n"
        b"--portable--\r\n"
    )


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, Path, dict[str, object]]:
    source_path = tmp_path / "portable.eml"
    source_path.write_bytes(_data())
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_email_source(
        name="Portable EML",
        path=source_path,
        profile="eml-file-v1",
    )
    instance.set_email_source_state(str(source["id"]), "enabled")
    queued = instance.queue_email_intake(str(source["id"]))
    assert instance.run_email_job(str(queued["job"]["id"]))["status"] == "succeeded"
    return instance, source_path, instance.list_email_messages()[0]


def test_search_and_viewer_use_only_verified_passive_email_body(tmp_path: Path) -> None:
    instance, _source_path, message = _seed(tmp_path)
    document_id = str(message["document_id"])
    original = instance.store.original_bytes(str(message["original_id"]))
    assert instance.rebuild_index() == 1
    assert instance.search("unique-email-search-token")[0]["document_id"] == document_id
    viewed = instance.document_content(document_id)
    assert viewed is not None
    assert viewed["source"] == "verified_email_body"
    assert "unique-email-search-token" in viewed["markdown"]
    assert viewed["original_text"] is None

    instance.remove_email_derived(str(message["id"]))
    assert instance.search("unique-email-search-token") == []
    viewed = instance.document_content(document_id)
    assert viewed is not None and viewed["source"] == "unavailable"
    assert viewed["markdown"] is None and viewed["original_text"] is None
    assert instance.store.original_bytes(str(message["original_id"])) == original

    instance.rebuild_email_derived(str(message["id"]))
    assert instance.search("unique-email-search-token")[0]["document_id"] == document_id
    assert instance.store.original_bytes(str(message["original_id"])) == original


def test_backup_export_import_and_rebuild_need_no_mailbox_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source_path, message = _seed(tmp_path)
    original = instance.store.original_bytes(str(message["original_id"]))
    backup = instance.backup(destination=tmp_path / "backup.zip")
    source_path.unlink()

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("portable email operation attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    archive = tmp_path / "portable.zip"
    exported = instance.export_portable(archive)
    assert exported["status"] == "completed"
    target = ProvelumeInstance.initialise(tmp_path / "target")
    imported = target.import_portable(archive)
    assert imported["status"] == "imported"
    restored = ProvelumeInstance(tmp_path / "target")
    imported_message = restored.get_email_message(str(message["id"]))
    assert imported_message is not None
    assert restored.store.original_bytes(str(message["original_id"])) == original
    assert restored.rebuild_index() == 1
    assert restored.search("unique-email-search-token")
    assert restored.validate_instance(deep=True)["status"] == "valid"

    instance.remove_email_derived(str(message["id"]))
    assert instance.get_email_message(str(message["id"]))["derived_status"] == "removed"
    assert instance.restore(backup["archive"])["status"] == "restored"
    reopened = ProvelumeInstance(tmp_path / "instance")
    assert reopened.get_email_message(str(message["id"]))["derived_status"] == "available"
    assert reopened.store.original_bytes(str(message["original_id"])) == original


def test_permanent_purge_removes_email_lineage_but_never_source_mailbox(
    tmp_path: Path,
) -> None:
    instance, source_path, message = _seed(tmp_path)
    document_id = str(message["document_id"])
    source_bytes = source_path.read_bytes()
    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    purged = instance.purge_document(
        document_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )
    assert purged["status"] == "completed"
    assert instance.store.read_canonical("documents", document_id) is None
    assert instance.store.list_canonical("email-messages") == []
    assert instance.store.list_canonical("email-observations") == []
    assert instance.store.list_canonical("email-attachments") == []
    assert instance.store.list_canonical("originals") == []
    assert source_path.read_bytes() == source_bytes
    assert instance.validate_instance(deep=True)["status"] == "valid"
