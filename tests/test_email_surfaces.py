from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import provelume.email_activity as email_activity
from provelume.cli import main
from provelume.service import ProvelumeInstance
from provelume.web import create_app


@pytest.fixture(autouse=True)
def qualified_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "provelume.email_contract.qualified_runtime_target",
        lambda: "ubuntu-24.04-x86_64-cpython312",
    )


def _seed(tmp_path: Path) -> tuple[Path, Path, str]:
    eml = tmp_path / "surface.eml"
    eml.write_bytes(
        b"Message-ID: <surface@example.invalid>\r\n"
        b"Subject: <script>alert(1)</script>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"<img src=https://tracker.invalid/pixel onerror=alert(1)>"
    )
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)
    source = instance.create_email_source(
        name="Surface EML",
        path=eml,
        profile="eml-file-v1",
    )
    instance.set_email_source_state(str(source["id"]), "enabled")
    return root, eml, str(source["id"])


def _csrf(page: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match is not None
    return match.group(1)


def test_read_only_api_and_passive_browser_are_en_it_and_escaped(tmp_path: Path) -> None:
    root, eml, source_id = _seed(tmp_path)
    client = TestClient(create_app(root))
    page = client.get("/email")
    assert page.status_code == 200
    assert "Local email intake" in page.text
    assert str(eml) in page.text
    assert "runtime download" in page.text.casefold()
    italian = client.get("/email", params={"lang": "it"})
    assert italian.status_code == 200
    assert "Intake email locale" in italian.text

    capability = client.get("/api/v1/email/capability").json()
    assert capability["network_access"] == "none"
    assert capability["attachment_ocr"]["state"] == "disabled"
    assert capability["attachment_ocr"]["available"] is False
    assert capability["attachment_ocr"]["intake_dependency"] is False
    assert capability["attachment_ocr"]["execution_started"] is False
    assert {item["profile"] for item in capability["profiles"] if item["available"]} == {
        "eml-file-v1",
        "maildir-cur-new-v1",
    }
    source = client.get(f"/api/v1/email/sources/{source_id}").json()
    assert "path" not in source
    assert source["automatic_activity"] is False
    assert client.post("/api/v1/email/sources", json={}).status_code == 405
    assert client.post("/api/v1/email/messages", json={}).status_code == 405
    assert client.post("/api/v1/email/jobs", json={}).status_code == 405

    token = _csrf(page.text)
    bad_token = client.post(
        "/email",
        data={"csrf_token": "invalid", "action": "queue", "source_id": source_id},
    )
    assert bad_token.status_code == 403
    wrong_type = client.post(
        "/email",
        json={"csrf_token": token, "action": "queue", "source_id": source_id},
    )
    assert wrong_type.status_code == 415
    oversized = client.post(
        "/email",
        content=b"x" * (email_activity.MAX_EMAIL_CONTROL_BODY_BYTES + 1),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert oversized.status_code == 413

    queued = client.post(
        "/email",
        data={"csrf_token": token, "action": "queue", "source_id": source_id},
    )
    assert queued.status_code == 200
    job_id = ProvelumeInstance(root).list_email_jobs()[0]["id"]
    run = client.post(
        "/email",
        data={"csrf_token": token, "action": "run", "job_id": job_id},
    )
    assert run.status_code == 200
    message = client.get("/api/v1/email/messages").json()[0]
    message_page = client.get(f"/email/messages/{message['id']}")
    assert message_page.status_code == 200
    assert "<script>alert(1)</script>" not in message_page.text
    assert "<img src=https://tracker.invalid" not in message_page.text
    assert "\\u003cscript\\u003e" in message_page.text
    assert client.get("/api/v1/email/threads").json()[0]["source_scoped"] is True


def test_non_loopback_browser_hides_path_and_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, eml, _source_id = _seed(tmp_path)
    monkeypatch.setattr(email_activity, "_loopback_request", lambda _request: False)
    client = TestClient(create_app(root))
    page = client.get("/email")
    assert page.status_code == 200
    assert str(eml) not in page.text
    assert 'name="csrf_token"' not in page.text
    assert 'action="/email' not in page.text
    assert client.post("/email", data={}).status_code == 403


def test_email_cli_uses_the_same_local_capability_and_source_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, eml, source_id = _seed(tmp_path)
    assert main(["email-capability", str(root), "--source-id", source_id]) == 0
    capability = json.loads(capsys.readouterr().out)
    assert capability["network_access"] == "none"
    assert capability["attachment_ocr"]["intake_dependency"] is False
    assert capability["source"]["path"] == str(eml)
    assert main(["email-source-list", str(root)]) == 0
    sources = json.loads(capsys.readouterr().out)
    assert sources[0]["id"] == source_id
    assert sources[0]["path"] == str(eml)
