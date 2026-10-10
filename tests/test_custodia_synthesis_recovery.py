"""A real process exit in the body/journal gap; no model or external provider."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_ai_setup import form
from test_ai_synthesis import execute, synthesis
from test_representations import _snapshots

from provelume.ai_contract import digest
from provelume.ai_setup import AiSetup
from provelume.ai_synthesis_recovery import candidate, discard
from provelume.scheduler_model import utc_instant
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def crash_after_body(root):
    fixture = synthesis.__wrapped__(root)
    setup = fixture[0]
    originals = _snapshots(setup.instance.store)
    original = setup.jobs.journal._write_job

    def crash(job):
        if (job.get("ai", {}).get("result") or {}).get("kind") == "derived_ref":
            assert setup.synthesis.path(job["id"]).is_file()
            assert _snapshots(setup.instance.store) == originals
            os._exit(87)
        return original(job)

    setup.jobs.journal._write_job = crash
    execute(fixture)
    raise AssertionError("the actual crash boundary was not reached")


@pytest.fixture
def orphan(tmp_path):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(tmp_path)],
                            capture_output=True, timeout=30)
    assert result.returncode == 87, result.stderr.decode(errors="replace")[-1500:]
    setup = AiSetup(ProvelumeInstance(tmp_path / "instance"))
    job = setup.jobs.journal.list_jobs()[0]
    body = setup.synthesis.path(job["id"])
    assert body.is_file() and job["status"] == "running" and job["ai"]["result"] is None
    assert not setup.jobs.session_authorized
    with pytest.raises(ValueError):
        candidate(setup.synthesis, job["id"])
    setup.instance.scheduler.recover(now=utc_instant() + timedelta(minutes=10))
    return setup, job["id"], body


def reconcile(setup, job_id, evidence="actual test child exited with code 87"):
    setup.jobs.reconcile(job_id, attempt=1, quiescent=True,
                         acknowledge_duplicate_risk=True, evidence=digest(evidence))


def test_expired_lease_protects_body_until_explicit_quiescence(orphan):
    setup, job_id, body = orphan
    originals = _snapshots(setup.instance.store)
    receipt_bytes = {p.name: p.read_bytes() for p in setup.jobs.journal.receipts.glob("*.json")}
    assert setup.jobs.journal.get_job(job_id)["ai"]["attempts"][0]["phase"] == "uncertain"
    with pytest.raises(ValueError):
        candidate(setup.synthesis, job_id)
    with pytest.raises(ValueError):
        discard(setup.synthesis, job_id, "a" * 64)
    assert body.is_file()
    reconcile(setup, job_id)
    accounting = setup.jobs.status()["accounting"]
    job_bytes = (setup.jobs.journal.jobs / (job_id + ".json")).read_bytes()
    observed = candidate(setup.synthesis, job_id)
    assert set(observed) == {"bytes", "revision"} and observed["bytes"] == body.stat().st_size
    discard(setup.synthesis, job_id, observed["revision"])
    assert not body.exists()
    assert setup.jobs.status()["accounting"] == accounting and accounting["units"] > 0
    assert (setup.jobs.journal.jobs / (job_id + ".json")).read_bytes() == job_bytes
    assert {p.name: p.read_bytes() for p in setup.jobs.journal.receipts.glob("*.json")} == (
        receipt_bytes)
    assert _snapshots(setup.instance.store) == originals


@pytest.mark.parametrize("change", ["body", "job", "control", "missing_job", "symlink"])
def test_cleanup_revalidates_body_job_and_owner_without_following_links(orphan, change, tmp_path):
    setup, job_id, body = orphan
    reconcile(setup, job_id)
    observed = candidate(setup.synthesis, job_id)
    outside = tmp_path / "private-canary.txt"
    outside.write_bytes(b"must remain private and unchanged")
    if change == "body":
        body.write_bytes(body.read_bytes() + b" ")
    elif change == "job":
        reconcile(setup, job_id, "newer explicit quiescence evidence")
    elif change == "control":
        setup.jobs.configure(mode="off")
    elif change == "missing_job":
        (setup.jobs.journal.jobs / (job_id + ".json")).unlink()
    else:
        body.unlink()
        try:
            body.symlink_to(outside)
        except OSError:
            pytest.skip("host does not permit symlink creation")
    with pytest.raises(ValueError):
        discard(setup.synthesis, job_id, observed["revision"])
    assert body.exists()
    assert outside.read_bytes() == b"must remain private and unchanged"


def test_cleanup_http_requires_fresh_form_and_explicit_acknowledgement(orphan, tmp_path):
    setup, job_id, body = orphan
    reconcile(setup, job_id)
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    with TestClient(app) as client:
        page = client.get("/operations/ai")
        path = f"/operations/ai/{job_id}/synthesis/cleanup"
        assert path in page.text
        assert "The workshop is on Monday" not in page.text
        selected = re.search(r'<form[^>]+action="' + path + r'.*?</form>', page.text, re.S).group()
        revision = re.search(r'name="revision" value="([a-f0-9]+)"', selected).group(1)
        values = {**form(page), "revision": revision, "acknowledge": "discard-orphan"}
        assert client.post(path, data={**values, "csrf_token": "wrong"}).status_code == 403
        assert body.is_file()
        response = client.post(path, data=values)
        assert response.status_code == 200 and not body.exists()
        assert client.post(path, data=values).status_code == 409


if __name__ == "__main__":
    crash_after_body(Path(sys.argv[1]))
