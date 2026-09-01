from __future__ import annotations

import os
import platform
import socket
from pathlib import Path

import pytest

from provelume.email_contract import (
    EMAIL_PARSER_ID,
    EMAIL_PARSER_VERSION,
    qualified_runtime_target,
)
from provelume.service import ProvelumeInstance

pytestmark = pytest.mark.skipif(
    os.environ.get("PROVELUME_REAL_EMAIL_SMOKE") != "1",
    reason="real local email qualification smoke is opt-in",
)

_RAW = (
    b"Message-ID: <real-smoke@example.invalid>\r\n"
    b"Subject: Synthetic qualification smoke\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: multipart/mixed; boundary=real-smoke\r\n\r\n"
    b"--real-smoke\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"real-email-smoke-token\r\n"
    b"--real-smoke\r\n"
    b"Content-Type: application/octet-stream\r\n"
    b"Content-Disposition: attachment; filename=synthetic.bin\r\n"
    b"Content-Transfer-Encoding: base64\r\n\r\n"
    b"c3ludGhldGljLXNtb2tl\r\n"
    b"--real-smoke--\r\n"
)


def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("real local email smoke attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "gethostbyname", forbidden)


def _run_source(
    tmp_path: Path,
    source_path: Path,
    profile: str,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    capability = instance.email_capability(local=False)
    selected = next(item for item in capability["profiles"] if item["profile"] == profile)
    assert selected["available"] is True
    assert selected["parser_id"] == EMAIL_PARSER_ID
    assert selected["parser_version"] == EMAIL_PARSER_VERSION
    assert selected["network_access"] == "none"
    assert capability["attachment_ocr"]["intake_dependency"] is False
    assert capability["attachment_ocr"]["execution_started"] is False

    source = instance.create_email_source(
        name="Synthetic qualification Source",
        path=source_path,
        profile=profile,
    )
    assert source["state"] == "disabled"
    assert instance.list_email_jobs() == []
    instance.set_email_source_state(str(source["id"]), "enabled")
    assert instance.list_email_jobs() == []
    queued = instance.queue_email_intake(str(source["id"]))
    job = instance.run_email_job(str(queued["job"]["id"]))
    assert job is not None and job["status"] == "succeeded"
    assert job["progress"] == {"processed": 1, "skipped": 0, "errors": 0}

    message = instance.list_email_messages()[0]
    assert instance.store.original_bytes(str(message["original_id"])) == _RAW
    assert message["parser"]["id"] == EMAIL_PARSER_ID
    assert message["body"]["selection_rule"] == "first-safe-text-plain-depth-first"
    attachment = instance.list_email_attachments(message_id=str(message["id"]))[0]
    assert instance.store.original_bytes(str(attachment["original_id"])) == (
        b"synthetic-smoke"
    )
    assert attachment["representation"]["ocr"]["execution_started"] is False
    assert instance.rebuild_index() == 1
    assert instance.search("real-email-smoke-token")
    instance.remove_email_derived(str(message["id"]))
    assert instance.search("real-email-smoke-token") == []
    instance.rebuild_email_derived(str(message["id"]))
    assert instance.search("real-email-smoke-token")
    assert instance.validate_instance(deep=True)["status"] == "valid"


def test_real_eml_parser_and_intake_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = qualified_runtime_target()
    assert target.endswith("-x86_64-cpython312"), target
    assert target.startswith(("ubuntu-24.04-", "windows-")), target
    eml = tmp_path / "real-smoke.eml"
    eml.write_bytes(_RAW)
    _deny_network(monkeypatch)
    _run_source(tmp_path, eml, "eml-file-v1")


@pytest.mark.skipif(platform.system() == "Windows", reason="Maildir is Ubuntu-only")
def test_real_maildir_parser_and_intake_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert qualified_runtime_target() == "ubuntu-24.04-x86_64-cpython312"
    maildir = tmp_path / "maildir"
    for name in ("cur", "new", "tmp"):
        (maildir / name).mkdir(parents=True)
    (maildir / "new" / "1700000000.synthetic").write_bytes(_RAW)
    _deny_network(monkeypatch)
    _run_source(tmp_path, maildir, "maildir-cur-new-v1")
