from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import provelume.transcript_activity as transcript_activity
from provelume.cli import main
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _seed(tmp_path: Path) -> tuple[Path, Path, str, str]:
    transcript = tmp_path / "private-name.srt"
    data = (
        b"1\n00:00:00,000 --> 00:00:01,000\n"
        b"<script>alert(1)</script> https://remote.invalid\n"
    )
    transcript.write_bytes(data)
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)
    source = instance.create_transcript_source(
        name="Private browser Source",
        path=transcript,
        profile="srt-v1",
        selection_kind="file",
    )
    source_id = str(source["id"])
    instance.set_transcript_source_state(source_id, "enabled")
    queued = instance.queue_transcript_intake(source_id)
    result = instance.run_transcript_job(str(queued["job"]["id"]))
    assert result is not None and result["status"] == "succeeded"
    revision_id = str(instance.list_transcript_revisions()[0]["id"])
    return root, transcript, source_id, revision_id


def _csrf(page: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match is not None
    return match.group(1)


def test_read_only_api_browser_en_it_accessibility_and_inert_rendering(tmp_path: Path) -> None:
    root, transcript, source_id, revision_id = _seed(tmp_path)
    client = TestClient(create_app(root))
    page = client.get("/transcripts")
    assert page.status_code == 200
    assert "Local transcript intake" in page.text
    assert str(transcript) in page.text
    assert "network: none" in page.text
    assert 'aria-label="Explicit file or folder"' in page.text
    italian = client.get("/transcripts", params={"lang": "it"})
    assert italian.status_code == 200
    assert "Intake locale delle trascrizioni" in italian.text
    assert 'aria-label="File o cartella espliciti"' in italian.text

    capability = client.get("/api/v1/transcripts/capability").json()
    assert capability["network_access"] == "none"
    assert {item["id"] for item in capability["profiles"]} == {
        "srt-v1",
        "webvtt-v1",
    }
    source = client.get(f"/api/v1/transcripts/sources/{source_id}").json()
    assert "path" not in source
    assert source["name_redacted"] is True
    assert "Private browser Source" not in json.dumps(source)
    checkpoint = client.get(
        f"/api/v1/transcripts/sources/{source_id}/checkpoint"
    ).json()
    assert checkpoint["complete"] is True
    summary = client.get("/api/v1/transcripts/revisions").json()[0]
    assert summary["private_content_included"] is False
    detail = client.get(
        f"/api/v1/transcripts/revisions/{revision_id}",
        params={"include_content": True},
    ).json()
    assert detail["private_content_included"] is True
    assert "<script>alert(1)</script>" in detail["text"]
    original = client.get(f"/api/v1/transcripts/revisions/{revision_id}/original")
    assert original.status_code == 200
    assert original.content == transcript.read_bytes()
    assert original.headers["x-provelume-original-sha256"] == summary["original_sha256"]

    for path in (
        "/api/v1/transcripts/sources",
        "/api/v1/transcripts/jobs",
        "/api/v1/transcripts/revisions",
    ):
        assert client.post(path, json={}).status_code == 405

    revision_page = client.get(f"/transcripts/revisions/{revision_id}")
    assert revision_page.status_code == 200
    assert "<script>alert(1)</script>" not in revision_page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in revision_page.text
    assert "javascript" not in revision_page.text.casefold()


def test_browser_mutations_require_loopback_csrf_type_and_bounds(tmp_path: Path) -> None:
    root, _transcript, source_id, _revision_id = _seed(tmp_path)
    client = TestClient(create_app(root))
    page = client.get("/transcripts")
    token = _csrf(page.text)
    assert client.post(
        "/transcripts",
        data={"csrf_token": "bad", "action": "resync", "source_id": source_id},
    ).status_code == 403
    assert client.post(
        "/transcripts",
        json={"csrf_token": token, "action": "resync", "source_id": source_id},
    ).status_code == 415
    oversized = client.post(
        "/transcripts",
        content=b"x" * (transcript_activity.MAX_TRANSCRIPT_CONTROL_BODY_BYTES + 1),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert oversized.status_code == 413
    reset = client.post(
        "/transcripts",
        data={"csrf_token": token, "action": "resync", "source_id": source_id},
    )
    assert reset.status_code == 200
    assert "resync:" in reset.text


def test_non_loopback_browser_redacts_selection_and_mutating_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, transcript, _source_id, _revision_id = _seed(tmp_path)
    monkeypatch.setattr(transcript_activity, "_loopback", lambda _request: False)
    client = TestClient(create_app(root))
    page = client.get("/transcripts")
    assert page.status_code == 200
    assert str(transcript) not in page.text
    assert "Private browser Source" not in page.text
    assert 'name="csrf_token"' not in page.text
    assert 'action="/transcripts' not in page.text
    assert client.post("/transcripts", data={}).status_code == 403


def test_cli_exposes_same_source_job_original_and_representation_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, transcript, source_id, revision_id = _seed(tmp_path)
    assert main(["transcript-capability", str(root), "--source-id", source_id]) == 0
    capability = json.loads(capsys.readouterr().out)
    assert capability["network_access"] == "none"
    assert capability["source"]["path"] == str(transcript)
    assert main(["transcript-source-checkpoint", str(root), source_id]) == 0
    checkpoint = json.loads(capsys.readouterr().out)
    assert checkpoint["complete"] is True
    assert main(["transcript-revision", str(root), revision_id, "--content"]) == 0
    revision = json.loads(capsys.readouterr().out)
    assert revision["private_content_included"] is True
    assert "<script>alert(1)</script>" in revision["text"]
    assert main(["transcript-original", str(root), revision_id]) == 0
    original = json.loads(capsys.readouterr().out)
    assert original["integrity_verified"] is True
    assert original["bytes_base64"] is None


def test_original_api_fails_with_conflict_on_integrity_mismatch(tmp_path: Path) -> None:
    root, _transcript, _source_id, revision_id = _seed(tmp_path)
    instance = ProvelumeInstance(root)
    revision = instance.store.read_canonical("transcript-revisions", revision_id)
    assert revision is not None
    original = instance.store.read_canonical("originals", str(revision["original_id"]))
    assert original is not None
    (root / str(original["storage_ref"])).write_bytes(b"tampered")
    client = TestClient(create_app(root))
    response = client.get(f"/api/v1/transcripts/revisions/{revision_id}/original")
    assert response.status_code == 409
    assert response.json()["detail"] == "transcript_derived_invalid"
