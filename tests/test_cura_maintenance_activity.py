from __future__ import annotations

import hashlib
import io
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.instance_validation import inspect_instance
from provelume.service import ProvelumeInstance
from provelume.web import create_app, create_recovery_app


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "form":
            self.current = {"action": attrs.get("action"), "fields": {}}
            self.forms.append(self.current)
        if (
            tag == "input"
            and self.current is not None
            and attrs.get("name")
            and attrs.get("type") != "checkbox"
        ):
            self.current["fields"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def _form(response, *, action=None, action_id=None, kind=None):
    assert response.status_code == 200, response.text
    forms = Forms(response.text).forms
    return next(
        f
        for f in forms
        if (action is None or f["action"].split("?")[0] == action)
        and (action_id is None or f["fields"].get("action_id") == action_id)
        and (kind is None or f["fields"].get("kind") == kind)
    )


def _submit(client, form, **changes):
    return client.post(form["action"], data={**form["fields"], **changes})


def _snapshot(root: Path):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def _client(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "i")
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    return instance, TestClient(app)


def test_operations_pages_share_pure_read_model_and_guard_forms(tmp_path):
    instance, client = _client(tmp_path)
    before = _snapshot(tmp_path)
    page = client.get("/maintenance/overview?lang=it")
    assert page.status_code == 200
    assert "Operazioni e manutenzione" in page.text and "om.title" not in page.text
    api = client.get("/api/v1/maintenance/overview").json()
    assert api["complete"] and api["total_jobs"] == 0
    assert len(api["job_kinds"]) >= 14
    assert _snapshot(tmp_path) == before
    form = _form(page, action="/maintenance/capacity")
    wrong = _submit(client, form, mode="paused", instance_id="inst_" + "0" * 32)
    assert wrong.status_code == 409
    invalid = _submit(client, form, mode="paused", csrf_token="wrong")
    assert invalid.status_code == 403
    oversized = _submit(client, form, mode="x" * 9000)
    assert oversized.status_code == 413
    assert _snapshot(tmp_path) == before


def test_reviewed_job_queue_controls_and_stale_preview(tmp_path):
    instance, client = _client(tmp_path)
    page = client.get("/maintenance/overview")
    form = _form(page, action_id="search.reindex.full")
    preview = _submit(client, form)
    confirm = _form(preview, action="/maintenance/confirm")
    assert instance.list_scheduler_jobs() == []
    result = _submit(client, confirm, confirmed="yes")
    assert result.status_code == 200, result.text
    jobs = instance.list_scheduler_jobs()
    assert len(jobs) == 1 and jobs[0]["status"] == "queued"
    job_id = jobs[0]["id"]
    detail = client.get("/maintenance/jobs/" + job_id)
    assert detail.status_code == 200 and "/preview/pause" in detail.text
    pause = client.get(f"/maintenance/jobs/{job_id}/preview/pause")
    paused = _submit(client, _form(pause), confirmed="yes")
    assert paused.status_code == 200, paused.text
    assert instance.get_scheduler_job(job_id)["status"] == "paused"
    repeated = _submit(client, _form(pause), confirmed="yes")
    assert repeated.status_code == 409
    assert instance.get_scheduler_job(job_id)["status"] == "paused"
    stale = client.get(f"/maintenance/jobs/{job_id}/preview/resume")
    instance.scheduler.control_job(
        job_id,
        "cancel",
        expected_revision=instance.scheduler.job_capabilities(job_id)["revision"],
        request_id="direct-cancel-stale-preview",
    )
    result = _submit(client, _form(stale), confirmed="yes")
    assert result.status_code == 409
    assert instance.get_scheduler_job(job_id)["status"] == "cancelled"


def test_backup_verification_runs_exact_selected_archive_through_scheduler(tmp_path):
    instance, client = _client(tmp_path)
    backup = instance.backup(destination=tmp_path / "before.zip")
    before = Path(backup["archive"]).read_bytes()
    preview = _submit(
        client, _form(client.get("/maintenance/backup")), archive_path=str(tmp_path / "before.zip")
    )
    assert "archive_sha256" in preview.text
    response = _submit(client, _form(preview), confirmed="yes")
    assert response.status_code == 200, response.text
    job = instance.list_scheduler_jobs()[0]
    assert job["job_kind"] == "maintenance.backup_verify" and job["status"] == "queued"
    instance.scheduler.run_one(job_id=job["id"])
    result = instance.get_scheduler_job(job["id"])
    assert result["status"] == "succeeded"
    assert Path(backup["archive"]).read_bytes() == before
    detail = client.get("/maintenance/jobs/" + job["id"])
    assert detail.status_code == 200 and "matches the exact job" in detail.text


def test_diagnostic_review_precedes_export_and_output_is_content_free(tmp_path):
    instance, client = _client(tmp_path)
    source = tmp_path / "PRIVATE-TITLE.txt"
    source.write_text("PRIVATE-CONTENT-SENTINEL", encoding="utf-8")
    instance.ingest(source)
    destination = tmp_path / "diagnostics.zip"
    preview = _submit(
        client, _form(client.get("/maintenance/diagnostics")), destination=str(destination)
    )
    assert preview.status_code == 200 and not destination.exists()
    response = _submit(client, _form(preview), confirmed="yes")
    assert response.status_code == 200, response.text
    data = destination.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = b"\n".join(archive.read(name) for name in archive.namelist())
    assert b"PRIVATE-CONTENT-SENTINEL" not in members and b"PRIVATE-TITLE" not in members
    assert str(tmp_path).encode() not in members
    assert hashlib.sha256(data).hexdigest() in response.text


def test_stale_heavy_preview_creates_neither_job_nor_policy(tmp_path):
    instance, client = _client(tmp_path)
    page = client.get("/maintenance/overview")
    preview = _submit(client, _form(page, action_id="search.reindex.full"))
    source = tmp_path / "changed-after-preview.txt"
    source.write_text("new reviewed-input invalidation", encoding="utf-8")
    instance.ingest(source)
    before = _snapshot(tmp_path)
    result = _submit(client, _form(preview), confirmed="yes")
    assert result.status_code == 409
    assert instance.list_scheduler_jobs() == []
    assert instance.list_schedule_policies() == []
    # Lifecycle lock metadata may change; durable scheduler state may not appear.
    after = _snapshot(tmp_path)
    assert {k: v for k, v in after.items() if "/scheduler/" in k} == {
        k: v for k, v in before.items() if "/scheduler/" in k
    }


def test_unsupported_repair_explains_scope_without_mutation(tmp_path):
    _, client = _client(tmp_path)
    before = _snapshot(tmp_path)
    page = client.get("/maintenance/repair")
    result = _submit(client, _form(page), relative_path="knowledge/documents/important.json")
    assert result.status_code == 409
    assert "does not support other paths or damage" in result.text
    assert _snapshot(tmp_path) == before


def test_retained_selection_recovery_survives_restart_without_deleting_output(tmp_path):
    instance, client = _client(tmp_path)
    destination = tmp_path / "retained-diagnostics.zip"
    preview = _submit(
        client, _form(client.get("/maintenance/diagnostics")), destination=str(destination)
    )
    assert _submit(client, _form(preview), confirmed="yes").status_code == 200
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    # New process-local router state; durable previews/selections must still be manageable.
    client = TestClient(create_app(instance.root, shell_settings_file=tmp_path / "shell.json"))
    before = _snapshot(tmp_path)
    page = client.get("/maintenance/selections")
    assert _snapshot(tmp_path) == before
    assert digest in page.text and str(destination) not in page.text
    revoke = _submit(client, _form(page, kind="target_revoke"))
    assert "prevents future work" in revoke.text
    assert _snapshot(tmp_path) == before
    result = _submit(client, _form(revoke), confirmed="yes")
    assert result.status_code == 200 and "revoked" in result.text
    assert _submit(client, _form(revoke), confirmed="yes").status_code == 409
    page = client.get("/maintenance/selections")
    forget = _submit(client, _form(page, kind="diagnostic_forget"))
    assert "delivery history" in forget.text
    assert _submit(client, _form(forget), confirmed="yes").status_code == 200
    page = client.get("/maintenance/selections")
    assert Forms(page.text).forms == []
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == digest


def test_recovery_mode_previews_without_prepare_then_backup_apply_and_rollback(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "i")
    source = tmp_path / "seed.txt"
    source.write_text("synthetic repair", encoding="utf-8")
    instance.ingest(source)
    instance.run_maintenance_action("search.reindex.full")
    run = next((instance.store.paths.state / "maintenance/reindex-runs").glob("*.json"))
    stray = run.with_name("." + run.name + ".synthetic")
    stray.write_bytes(run.read_bytes())
    relative = stray.relative_to(instance.root).as_posix()
    assert inspect_instance(instance.root, deep=True)["status"] == "invalid"
    canonical = _snapshot(instance.store.paths.knowledge)
    originals = _snapshot(instance.store.paths.originals)
    before = _snapshot(tmp_path)
    client = TestClient(
        create_recovery_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    )
    page = client.get("/maintenance/repair")
    assert page.status_code == 200 and "Recovery mode" in page.text
    assert client.get("/api/v1/documents").status_code == 404
    assert _snapshot(tmp_path) == before
    preview = _submit(client, _form(page), relative_path=relative)
    assert preview.status_code == 200, preview.text
    assert _snapshot(tmp_path) == before
    backup = _submit(client, _form(preview), confirmed="yes")
    assert backup.status_code == 200 and stray.exists()
    assert "verified_backup" in backup.text
    repaired = _submit(client, _form(backup), confirmed="yes")
    assert repaired.status_code == 200, repaired.text
    assert not stray.exists() and inspect_instance(instance.root, deep=True)["status"] == "valid"
    assert _snapshot(instance.store.paths.knowledge) == canonical
    assert _snapshot(instance.store.paths.originals) == originals
    import re

    rollback_url = re.search(r'href="(/maintenance/repair/rollback/[^\"]+)"', repaired.text).group(
        1
    )
    rollback = client.get(rollback_url.replace("&amp;", "&"))
    result = _submit(client, _form(rollback), confirmed="yes")
    assert result.status_code == 200, result.text
    assert stray.read_bytes() == run.read_bytes()
    assert inspect_instance(instance.root, deep=True)["status"] == "invalid"
    assert "known invalid" in result.text


def test_capacity_policy_requires_review_and_explicit_confirmation(tmp_path):
    _, client = _client(tmp_path)
    page = client.get("/maintenance/overview")
    preview = _submit(client, _form(page, action="/maintenance/capacity"), mode="paused")
    confirm = _form(preview)
    missing = _submit(client, confirm)
    assert missing.status_code == 400
    accepted = _submit(client, confirm, confirmed="yes")
    assert accepted.status_code == 200, accepted.text
    assert "Hold new intake" in client.get("/maintenance/overview").text


def test_restarted_recovery_interface_reconciles_exact_interrupted_repair(tmp_path, monkeypatch):
    from provelume.instance_repair import InstanceRepairManager
    from provelume.instance_repair_model import REPAIR_PROFILE

    instance = ProvelumeInstance.initialise(tmp_path / "i")
    source = tmp_path / "seed.txt"
    source.write_text("synthetic interrupted repair", encoding="utf-8")
    instance.ingest(source)
    instance.run_maintenance_action("search.reindex.full")
    run = next((instance.store.paths.state / "maintenance/reindex-runs").glob("*.json"))
    stray = run.with_name("." + run.name + ".synthetic")
    stray.write_bytes(run.read_bytes())
    relative = stray.relative_to(instance.root).as_posix()
    repair = InstanceRepairManager(instance.store)
    plan = repair.preview(REPAIR_PROFILE, relative)
    backup = repair.prepare_backup(plan, "browser-crash-backup")

    def crash_after_move(_operation):
        raise SystemExit("synthetic process interruption after rename")

    monkeypatch.setattr(repair, "_after_move", crash_after_move)
    with pytest.raises(SystemExit, match="synthetic process interruption"):
        repair.apply(
            backup["backup_id"],
            plan["input_revision"],
            "original-repair-request",
            backup["archive_sha256"],
            confirm=True,
        )
    assert repair.pending_path.exists() and not stray.exists()
    before = _snapshot(tmp_path)
    client = TestClient(
        create_recovery_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    )
    page = client.get("/maintenance/repair")
    assert page.status_code == 200 and "/maintenance/repair/reconcile" in page.text
    preview = client.get("/maintenance/repair/reconcile")
    assert "not committed" in preview.text and "known invalid state" in preview.text
    assert _snapshot(tmp_path) == before
    form = _form(preview)
    result = _submit(client, form, confirmed="yes")
    assert result.status_code == 200, result.text
    assert "original-repair-request" in result.text and "compensated" in result.text
    assert stray.read_bytes() == run.read_bytes() and not repair.pending_path.exists()
    assert inspect_instance(instance.root, deep=True)["status"] == "invalid"
    assert _submit(client, form, confirmed="yes").status_code == 409
    next_preview = _submit(client, _form(client.get("/maintenance/repair")), relative_path=relative)
    assert next_preview.status_code == 200, next_preview.text


def test_ui_catalog_keys_and_inputs_are_escaped(tmp_path):
    _, client = _client(tmp_path)
    page = client.get("/maintenance/overview?lang=it")
    assert "scheduler.kind." not in page.text and "maintenance.action." not in page.text
    result = _submit(
        client,
        _form(client.get("/maintenance/repair")),
        relative_path="<img src=x onerror=alert(1)>",
    )
    assert result.status_code == 409
    assert "<img src=x" not in result.text
