from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _seed(tmp_path: Path) -> tuple[Path, ProvelumeInstance, list[str], dict]:
    root = tmp_path / "instance"
    first = tmp_path / "source-a"
    second = tmp_path / "source-b"
    first.mkdir()
    second.mkdir()
    (first / "a.txt").write_text("private alpha body\n", encoding="utf-8")
    (second / "b.txt").write_text("private alpha body\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(root)
    first_result = instance.ingest(first, source_name="Sensitive Source Alpha")[0]
    second_result = instance.ingest(second, source_name="Sensitive Source Beta")[0]
    source_ids = sorted([first_result["source_id"], second_result["source_id"]])
    job = instance.queue_qualification(source_ids)["job"]
    assert instance.run_qualification(job["id"])["status"] == "succeeded"
    finding = next(
        item
        for item in instance.list_qualification_findings(limit=500)
        if item["finding_type"] == "possible-exact-byte-duplicate"
    )
    instance.decide_qualification_finding(
        finding["id"],
        action="acknowledge",
        actor_id="reviewer.local",
        reason="Synthetic decision history.",
        expected_revision=0,
    )
    return root, instance, source_ids, finding


def test_api_is_read_only_and_exposes_sanitized_qualification_state(tmp_path: Path) -> None:
    root, _instance, source_ids, finding = _seed(tmp_path)
    client = TestClient(create_app(root))
    matrix = client.get("/api/v1/qualification/matrix")
    assert matrix.status_code == 200
    assert matrix.json()["matrix_version"] == "2026-09-01.1"
    gmail = next(item for item in matrix.json()["profiles"] if item["id"] == "gmail-synthetic-v1")
    assert gmail["authenticated_real_qualification"] == "unqualified"
    assert client.get("/api/v1/qualification/limits").status_code == 200
    assert (
        client.get(f"/api/v1/qualification/sources/{source_ids[0]}/checkpoint").status_code == 200
    )
    jobs = client.get("/api/v1/qualification/jobs")
    assert jobs.status_code == 200
    assert jobs.json()[0]["lease"]["present"] is False
    assert "token" not in json.dumps(jobs.json())
    listed = client.get(
        "/api/v1/qualification/findings",
        params={"source_id": source_ids[0], "workflow_state": "acknowledged"},
    )
    assert [item["id"] for item in listed.json()] == [finding["id"]]
    detail = client.get(f"/api/v1/qualification/findings/{finding['id']}")
    assert detail.status_code == 200
    assert detail.json()["decisions"][0]["actor_id"] == "reviewer.local"
    history = client.get(f"/api/v1/qualification/findings/{finding['id']}/decisions")
    assert history.status_code == 200
    decision_id = history.json()[0]["id"]
    assert client.get(f"/api/v1/qualification/decisions/{decision_id}").status_code == 200
    assert client.post("/api/v1/qualification/jobs", json={}).status_code == 405
    assert (
        client.post(f"/api/v1/qualification/findings/{finding['id']}", json={}).status_code == 405
    )
    serialized = json.dumps(
        {"jobs": jobs.json(), "findings": listed.json(), "detail": detail.json()}
    )
    assert "private alpha body" not in serialized
    assert "Sensitive Source" not in serialized


def test_browser_en_it_accessibility_csrf_and_inert_operational_views(tmp_path: Path) -> None:
    root, _instance, source_ids, finding = _seed(tmp_path)
    client = TestClient(create_app(root))
    english = client.get("/qualification?lang=en")
    italian = client.get("/qualification?lang=it")
    assert english.status_code == italian.status_code == 200
    assert "Cross-source qualification" in english.text
    assert "Qualificazione cross-source" in italian.text
    assert "<fieldset>" in english.text
    assert 'scope="col"' in english.text
    assert 'role="status"' not in english.text
    assert "Sensitive Source" not in english.text
    assert "private alpha body" not in english.text
    assert (
        "real-provider-qualification-unavailable" not in english.text
        or "private" not in english.text
    )
    detail = client.get(f"/qualification/findings/{finding['id']}?lang=en")
    assert detail.status_code == 200
    assert 'aria-labelledby="observation-title"' in detail.text
    assert "Canonical source data remains unchanged" in detail.text
    token = re.search(r'name="csrf_token" value="([^"]+)"', english.text)
    assert token is not None
    rejected = client.post(
        "/qualification?lang=en",
        data={"action": "resync", "source_id": source_ids[0], "csrf_token": "wrong"},
    )
    assert rejected.status_code == 403
    accepted = client.post(
        "/qualification?lang=en",
        data={
            "action": "queue",
            "source_id": source_ids,
            "csrf_token": token.group(1),
        },
    )
    assert accepted.status_code == 200
    assert "Qualification control applied" in accepted.text


def test_cli_matrix_jobs_findings_and_decisions(tmp_path: Path, capsys) -> None:
    root, _instance, _source_ids, finding = _seed(tmp_path)
    assert main(["qualification-matrix", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["matrix_version"] == "2026-09-01.1"
    assert main(["qualification-jobs", str(root), "--limit", "10"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["status"] == "succeeded"
    assert (
        main(
            [
                "qualification-findings",
                str(root),
                "--workflow-state",
                "acknowledged",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)[0]["id"] == finding["id"]
    assert main(["qualification-decisions", str(root), "--finding-id", finding["id"]]) == 0
    assert json.loads(capsys.readouterr().out)[0]["revision"] == 1


def test_browser_rejects_script_like_human_reason(tmp_path: Path) -> None:
    root, _instance, _source_ids, finding = _seed(tmp_path)
    client = TestClient(create_app(root))
    detail = client.get(f"/qualification/findings/{finding['id']}?lang=en")
    token = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)
    assert token is not None
    response = client.post(
        "/qualification?lang=en",
        data={
            "csrf_token": token.group(1),
            "action": "decide",
            "decision_action": "reject",
            "finding_id": finding["id"],
            "expected_revision": "1",
            "actor_id": "reviewer.local",
            "reason": "https://example.test/<script>",
        },
    )
    assert response.status_code == 400
    assert "qualification_invalid_decision" in response.text
