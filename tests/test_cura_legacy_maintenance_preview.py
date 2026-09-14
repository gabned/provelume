from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import provelume.maintenance_activity as activity
from provelume.scheduler import schedule_payload
from provelume.service import ProvelumeInstance
from provelume.shell_settings import LauncherSettings, ShellSettingsManager
from provelume.web import create_app


def token(page):
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match is not None
    return match.group(1)


def files(root):
    return {
        p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def instance(tmp_path):
    return ProvelumeInstance.initialise(tmp_path / "instance", name="Legacy maintenance")


@pytest.mark.parametrize("mode", ["current", "preview"])
def test_both_renderers_get_pure_review_and_real_single_use_queue(
    instance, tmp_path, monkeypatch, mode
):
    manager = ShellSettingsManager(
        tmp_path / "launcher.json", LauncherSettings(instance_path=str(instance.root))
    )
    manager.save(manager.defaults)
    manager.set_interface_mode(mode, expected_revision=manager.load().settings.revision)
    app = create_app(instance.root, shell_settings_file=manager.path)

    def forbidden_service_plan(*args, **kwargs):
        pytest.fail("GET used the mutating lifecycle facade")

    monkeypatch.setattr(ProvelumeInstance, "plan_maintenance_action", forbidden_service_plan)
    with TestClient(app) as client:
        before = files(tmp_path)
        page = client.get("/maintenance?lang=en")
        csrf = token(page)
        assert files(tmp_path) == before
        assert "Total execution work is not yet known" in page.text
        assert "temporary bytes required: Unknown" in page.text
        assert 'data-preview-revision="' in page.text
        assert "Rebuildable data write" in page.text
        queued = client.post(
            "/maintenance?lang=en",
            data={
                "csrf_token": csrf,
                "action_id": "maintenance.validate",
            },
        )
        assert queued.status_code == 200 and "Maintenance job queued" in queued.text
        jobs = instance.list_scheduler_jobs()
        assert len(jobs) == 1 and jobs[0]["job_kind"] == "maintenance.validate"
        assert jobs[0]["execution_plan"]["instance_id"] == instance.instance_summary()["id"]
        assert "Load a new preview" in queued.text
        repeated = client.post(
            "/maintenance",
            data={
                "csrf_token": csrf,
                "action_id": "maintenance.validate",
            },
        )
        assert repeated.status_code == 403
        assert "Load a new preview" in repeated.text
        assert instance.list_scheduler_jobs() == jobs


def test_stale_review_rejected_without_replanning_or_creating_policy(
    instance, tmp_path, monkeypatch
):
    with TestClient(create_app(instance.root)) as client:
        csrf = token(client.get("/maintenance?lang=en"))
        source = tmp_path / "source"
        source.mkdir()
        (source / "note.txt").write_text("new authoritative inputs", encoding="utf-8")
        instance.ingest(source, source_name="Changed inputs")
        before_policies = instance.list_schedule_policies()
        before_jobs = instance.list_scheduler_jobs()
        result = client.post(
            "/maintenance?lang=en",
            data={
                "csrf_token": csrf,
                "action_id": "maintenance.validate",
            },
        )
        assert result.status_code == 400
        assert "reviewed inputs changed" in result.text
        assert instance.list_schedule_policies() == before_policies
        assert instance.list_scheduler_jobs() == before_jobs
        assert 'data-preview-revision="' not in result.text


def test_two_tabs_retain_independent_reviewed_revisions(instance, tmp_path):
    with TestClient(create_app(instance.root)) as client:
        old = token(client.get("/maintenance?lang=en"))
        source = tmp_path / "source"
        source.mkdir()
        (source / "note.txt").write_text("second preview state", encoding="utf-8")
        instance.ingest(source, source_name="Second tab")
        new = token(client.get("/maintenance?lang=it"))
        assert old != new
        assert (
            client.post(
                "/maintenance",
                data={
                    "csrf_token": old,
                    "action_id": "maintenance.validate",
                },
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/maintenance?lang=it",
                data={
                    "csrf_token": new,
                    "action_id": "maintenance.validate",
                },
            ).status_code
            == 200
        )
        assert len(instance.list_scheduler_jobs()) == 1


def test_missing_expired_and_process_restart_tokens_cannot_queue(instance, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(activity, "monotonic", lambda: clock[0])
    with TestClient(create_app(instance.root)) as client:
        assert (
            client.post("/maintenance", data={"action_id": "maintenance.validate"}).status_code
            == 403
        )
        csrf = token(client.get("/maintenance"))
        clock[0] = activity.REVIEW_SECONDS
        assert (
            client.post(
                "/maintenance",
                data={
                    "csrf_token": csrf,
                    "action_id": "maintenance.validate",
                },
            ).status_code
            == 403
        )
        fresh = token(client.get("/maintenance"))
    with TestClient(create_app(instance.root)) as restarted:
        assert (
            restarted.post(
                "/maintenance",
                data={
                    "csrf_token": fresh,
                    "action_id": "maintenance.validate",
                },
            ).status_code
            == 403
        )
    assert instance.list_scheduler_jobs() == []
    assert instance.list_schedule_policies() == []


def test_action_source_and_policy_tampering_require_a_new_review(instance):
    with TestClient(create_app(instance.root)) as client:
        for extras in (
            {"action_id": "maintenance.backup_create"},
            {"action_id": "maintenance.validate", "source_id": "src_" + "1" * 32},
            {"action_id": "maintenance.validate", "policy_id": "policy_" + "1" * 32},
        ):
            csrf = token(client.get("/maintenance"))
            result = client.post("/maintenance", data={"csrf_token": csrf, **extras})
            assert result.status_code == 400
    assert instance.list_scheduler_jobs() == []
    assert instance.list_schedule_policies() == []


def test_source_preview_queues_exact_parameters_and_detects_source_changes(instance, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("source evidence", encoding="utf-8")
    registered = instance.register_folder_source(
        source,
        name="Reviewed Source",
        quiescence_seconds=0,
        stable_observations=1,
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )
    source_id = registered["id"]
    with TestClient(create_app(instance.root)) as client:
        csrf = token(client.get("/maintenance"))
        result = client.post(
            "/maintenance",
            data={
                "csrf_token": csrf,
                "action_id": "maintenance.source_reconcile",
                "source_id": source_id,
            },
        )
        assert result.status_code == 200
        job = next(
            j
            for j in instance.list_scheduler_jobs()
            if j["job_kind"] == "maintenance.source_reconcile"
        )
        assert job["execution_plan"]["parameters"] == {"source_id": source_id}
        assert job["scope"] == {"kind": "source", "id": source_id}
        csrf = token(client.get("/maintenance"))
        before = instance.list_scheduler_jobs()
        (source / "note.txt").write_text("changed source evidence", encoding="utf-8")
        policy = next(
            p
            for p in instance.list_schedule_policies()
            if p["job_kind"] == "maintenance.source_reconcile"
        )
        stale = client.post(
            "/maintenance",
            data={
                "csrf_token": csrf,
                "action_id": "maintenance.source_reconcile",
                "source_id": source_id,
                "policy_id": policy["id"],
            },
        )
        assert stale.status_code == 400
        assert instance.list_scheduler_jobs() == before


def test_duplicate_form_fields_cannot_select_an_unreviewed_action(instance):
    with TestClient(create_app(instance.root)) as client:
        csrf = token(client.get("/maintenance"))
        result = client.post(
            "/maintenance",
            content=(
                f"csrf_token={csrf}&action_id=maintenance.validate&action_id=maintenance.library_rebuild"
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert result.status_code == 400
    assert instance.list_scheduler_jobs() == []


def test_concurrent_same_confirmation_consumes_one_review_and_queues_once(instance):
    with TestClient(create_app(instance.root)) as client:
        csrf = token(client.get("/maintenance"))

        def confirm():
            return client.post(
                "/maintenance",
                data={
                    "csrf_token": csrf,
                    "action_id": "maintenance.validate",
                },
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _index: confirm(), range(2)))
        assert sorted(statuses) == [200, 403]
        assert len(instance.list_scheduler_jobs()) == 1
