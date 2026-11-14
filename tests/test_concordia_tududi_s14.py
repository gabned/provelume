"""Tududi profile tests over actual scheduler/intake/vault seams and synthetic API bytes."""

import json
import re
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from provelume.productivity_contract import ProductivityError
from provelume.productivity_http import ProductivityHttpError
from provelume.productivity_intake import ProductivityIntake
from provelume.productivity_jobs import ProductivityJobs
from provelume.review_decisions import read_json
from provelume.service import ProvelumeInstance
from provelume.tududi_connection import TududiConnection
from provelume.tududi_contract import map_task
from provelume.tududi_intake import reset_source
from provelume.tududi_qualification import (
    SyntheticTududi,
    SyntheticVault,
    qualify_tududi,
    synthetic_task,
)
from provelume.web import create_app


@pytest.fixture
def journey(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "Instance")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    vault, server = SyntheticVault(), SyntheticTududi()
    manager = TududiConnection(instance.store, vault=vault, http=server)
    return instance, manager, vault, server


def connect(manager, *, endpoint="https://tududi.example.invalid", identity=None, revision=0):
    return manager.connect(
        {"endpoint": endpoint, "token": "tt_synthetic_token", "server_version": "2.1.0"},
        name="Synthetic Tududi",
        identity=identity,
        expected_revision=revision,
        confirmed=True,
    )["identity_id"]


def source(manager, identity, scope="project"):
    return manager.select_source(
        identity,
        name="Selected " + scope,
        scope=scope,
        remote_id="project1" if scope == "project" else "parent" if scope == "task" else None,
        confirmed=True,
    )["source_id"]


def run(instance, manager, selected, key):
    jobs = ProductivityJobs(instance.store, tududi=manager)
    instance.scheduler._productivity_manager_factory = lambda _store: jobs
    job = jobs.queue(selected, request_key=key)["job"]
    result = instance.scheduler.run_one(job_id=job["id"])
    return result, read_json(
        instance.store, f"state/productivity-providers/tududi-runs/{job['id']}.json"
    )


@pytest.mark.parametrize("scope", ["account", "project", "task"])
def test_actual_scheduler_all_scopes_originals_comments_subtasks_and_replay(journey, scope):
    instance, manager, _vault, server = journey
    selected = source(manager, connect(manager), scope)
    result, receipt = run(instance, manager, selected, "first")
    assert result["status"] == "succeeded" and receipt["status"] == "completed", result
    rows = ProductivityIntake(instance.store).records(selected)
    assert {row["item"]["remote_id"] for row in rows} == (
        {"parent", "child"} if scope == "task" else {"parent", "child", "timed"}
    )
    assert all(row["availability"] == "in_completed_snapshot" for row in rows)
    for row in rows:
        assert (
            json.loads(instance.document_original(row["document_id"])["data"])["uid"]
            == (row["item"]["remote_id"])
        )
        assert row["item"]["provenance"]["comments"] == [
            "Exact retained comment",
            "Exact retained reply",
        ]
        assert row["item"]["provenance"]["assignees"] == ["person1"]
        assert row["item"]["provenance"]["task_context"]["start_date"] == "2026-11-06"
    result, receipt = run(instance, manager, selected, "replay")
    assert result["status"] == "succeeded" and receipt["status"] == "completed"
    assert all(len(instance.store.versions_for_document(row["document_id"])) == 1 for row in rows)
    assert instance.validate_instance()["status"] == "valid"
    if scope != "task":
        lists = [
            parse_qs(urlsplit(call["url"]).query)
            for call in server.calls
            if urlsplit(call["url"]).path == "/api/v1/tasks"
        ]
        assert all(params["status"] == ["all"] and params["type"] == ["all"] for params in lists)


def test_independent_accounts_endpoints_and_no_canonical_secret_references(journey):
    instance, manager, vault, server = journey
    first = connect(manager)
    selected = source(manager, first)
    server.user = "user2"
    second = connect(manager, endpoint="https://other-tududi.example.invalid")
    manager.disconnect(first, expected_revision=1, confirmed=True)
    assert manager.record(second)["status"] == "authorized"
    assert manager.host.policy(selected)["mode"] == "manual"
    with pytest.raises(ProductivityError, match="authorization_required"):
        manager.resolve(first)
    assert vault.values
    for path in instance.root.rglob("*"):
        if path.is_file():
            assert b"tt_synthetic_token" not in path.read_bytes()
            assert b"productivity_tududi_grant_" not in path.read_bytes()


def test_different_account_or_endpoint_cannot_replace_existing_identity(journey):
    _instance, manager, vault, server = journey
    identity = connect(manager)
    before, link = manager.record(identity), vault.read(manager.link(identity))
    server.user = "wrong-account"
    with pytest.raises(ProductivityError, match="account_mismatch"):
        connect(manager, identity=identity, revision=1)
    with pytest.raises(ProductivityError, match="stale"):
        connect(manager, identity=identity, revision=1, endpoint="https://other.example.invalid")
    assert manager.record(identity) == before and vault.read(manager.link(identity)) == link


@pytest.mark.parametrize("version", ["2.0.0", "2.1.1", "unknown", "latest"])
def test_unsupported_version_is_visible_without_contact_or_credentials(journey, version):
    _instance, manager, vault, server = journey
    with pytest.raises(ProductivityError, match="unsupported"):
        manager.connect(
            {
                "endpoint": "https://tududi.example.invalid",
                "token": "tt_synthetic_token",
                "server_version": version,
            },
            name="Unsupported",
            confirmed=True,
        )
    assert server.calls == [] and vault.values == {}


def test_date_only_timed_archived_and_dst_ambiguity_are_not_guessed():
    def mapped(value):
        return map_task(
            value,
            comments=[],
            hashes=[],
            time_zone="Europe/Rome",
            endpoint="https://tududi.example.invalid",
        )

    row = synthetic_task("date")
    assert mapped(row)["due"] == {"kind": "date", "value": "2026-11-07", "time_zone": None}
    row = synthetic_task("timed", timed=True)
    assert mapped(row)["due"]["value"] == "2026-11-07T12:30:00+01:00"
    row.update(status=3)
    assert mapped(row)["provenance"]["task_context"]["status"] == "archived"
    assert mapped(row)["state"] == "open"
    for day in ("2026-03-29", "2026-10-25"):
        row.update(due_date=day, due_time="02:30")
        with pytest.raises(ProductivityError, match="time_zone"):
            mapped(row)


def test_bounded_continuation_does_not_publish_a_partial_complete_snapshot(journey):
    instance, manager, _vault, server = journey
    server.tasks = {str(index): synthetic_task(str(index)) for index in range(20)}
    server.roots = list(server.tasks)
    selected = source(manager, connect(manager))
    result, receipt = run(instance, manager, selected, "first-50-responses")
    assert result["status"] == "succeeded" and receipt["status"] == "continuation_available"
    assert ProductivityIntake(instance.store).checkpoint(selected) is None
    for index in range(2):
        calls = len(server.calls)
        result, receipt = run(instance, manager, selected, "continue-" + str(index))
        assert len(server.calls) - calls <= 50
        if receipt["status"] == "completed":
            break
    assert result["status"] == "succeeded" and receipt["status"] == "completed", result
    assert len(ProductivityIntake(instance.store).records(selected)) == 20


def test_rate_wait_and_revoked_token_preserve_completed_source(journey):
    instance, manager, _vault, server = journey
    selected = source(manager, connect(manager))
    result, _receipt = run(instance, manager, selected, "initial")
    assert result["status"] == "succeeded"
    before = deepcopy(ProductivityIntake(instance.store).checkpoint(selected))
    for status, expected in [(401, "authorization_required"), (429, "rate_limited")]:
        server.failure = ProductivityHttpError(status, 300 if status == 429 else None)
        result, receipt = run(instance, manager, selected, "refused-" + str(status))
        assert result["status"] == "manual_intervention" and receipt["error_code"] == expected
        assert ProductivityIntake(instance.store).checkpoint(selected) == before
    calls = len(server.calls)
    server.failure = None
    with pytest.raises(ProductivityError, match="rate_limited"):
        manager.catalogue(manager.view()["identities"][0]["id"], confirmed=True)
    assert len(server.calls) == calls


def test_policy_revocation_during_response_prevents_object_promotion(journey):
    instance, manager, _vault, server = journey
    identity = connect(manager)
    selected = source(manager, identity)
    server.before_response = lambda: manager.connectors.disable_source(identity, selected)
    result, receipt = run(instance, manager, selected, "disabled")
    assert result["status"] == "manual_intervention"
    assert receipt["status"] == "failed"
    assert instance.store.list_canonical("objects") == []
    assert ProductivityIntake(instance.store).checkpoint(selected) is None


def test_changed_root_inventory_and_malformed_pagination_cannot_complete(journey, monkeypatch):
    instance, manager, _vault, server = journey
    selected = source(manager, connect(manager))
    original, lists = server.request, 0

    def changed(url, **options):
        nonlocal lists
        if urlsplit(url).path == "/api/v1/tasks":
            lists += 1
            if lists == 2:
                server.roots.reverse()
        return original(url, **options)

    monkeypatch.setattr(server, "request", changed)
    result, receipt = run(instance, manager, selected, "membership-changed")
    assert result["status"] == "manual_intervention" and receipt["error_code"] == "stale"
    assert ProductivityIntake(instance.store).checkpoint(selected) is None


def test_explicit_reset_retains_historical_objects_without_false_cancellation(journey):
    instance, manager, _vault, server = journey
    selected = source(manager, connect(manager))
    result, _receipt = run(instance, manager, selected, "initial")
    assert result["status"] == "succeeded"
    before = deepcopy(instance.store.list_canonical("objects"))
    server.roots = []
    reset_source(manager, selected, expected_policy_revision=1, confirmed=True)
    result, receipt = run(instance, manager, selected, "reset")
    assert result["status"] == "succeeded" and receipt["status"] == "completed", result
    assert instance.store.list_canonical("objects") == before
    assert all(
        row["availability"] == "not_in_completed_snapshot"
        for row in ProductivityIntake(instance.store).records(selected)
    )


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
def test_passive_ui_catalogue_selection_readonly_comments_and_csrf(journey, tmp_path, language):
    instance, manager, vault, server = journey
    identity = connect(manager)
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._tududi_manager = manager
    app.state.provelume.scheduler._productivity_manager_factory = lambda _store: ProductivityJobs(
        instance.store, tududi=manager
    )
    client = TestClient(app)
    before = (len(server.calls), vault.reads)
    response = client.get("/tududi/connect?lang=" + language)
    assert response.status_code == 200 and (len(server.calls), vault.reads) == before
    assert "tududi.lead" not in response.text and "tt_synthetic_token" not in response.text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def control(action, **fields):
        return client.post(
            "/tududi/connect?lang=" + language,
            data={"csrf_token": csrf, "confirm": "yes", "action": action, **fields},
        )

    assert client.post("/tududi/connect", data={"csrf_token": "wrong"}).status_code == 403
    response = control("catalogue", identity=identity)
    assert "Synthetic project" in response.text
    response = control(
        "select",
        identity=identity,
        scope="task",
        name="UI task",
        remote_id="https://tududi.example.invalid/task/parent",
    )
    assert "notice=saved" in str(response.url)
    selected = manager.view()["sources"][0]["id"]
    response = control("read", source_id=selected, revision="1")
    assert "notice=saved" in str(response.url)
    obj = instance.store.list_canonical("objects")[0]
    before = (len(server.calls), vault.reads)
    response = client.get(f"/objects/{obj['id']}?lang={language}")
    assert response.status_code == 200 and (len(server.calls), vault.reads) == before
    assert "Exact retained reply" in response.text and 'id="connector-provenance"' in response.text
    assert client.get(f"/objects/{obj['id']}/edit").status_code == 403


def test_installed_qualification_path_is_synthetic_offline_and_worker_typed(tmp_path):
    result = qualify_tududi(tmp_path / "Qualification")
    assert result["result"] == "PASS" and not result["network_used"]
    assert result["http_worker"] == "ENDPOINT_REFUSAL_PASS" and result["real_tududi"] == "NOT_RUN"
    assert not result["server_version_verified"] and not result["token_scopes_verified"]


def test_timezone_change_before_promotion_is_not_reinterpreted_silently(journey):
    instance, manager, _vault, server = journey
    selected = source(manager, connect(manager))

    def change_zone():
        if server.calls[-1]["url"].endswith("/comments"):
            server.time_zone = "America/New_York"

    server.before_response = change_zone
    result, receipt = run(instance, manager, selected, "zone-change")
    assert result["status"] == "manual_intervention" and receipt["error_code"] == "time_zone"
    assert instance.store.list_canonical("objects") == []
    assert ProductivityIntake(instance.store).checkpoint(selected) is None


def test_unrelated_private_profile_settings_never_become_task_originals(journey, monkeypatch):
    instance, manager, _vault, server = journey
    selected = source(manager, connect(manager))
    original = server.request

    def private(url, **options):
        raw = original(url, **options)
        if url.endswith("/profile"):
            value = json.loads(raw)
            value["unrelated_setting"] = "SENSITIVE_PROFILE_ONLY"
            return json.dumps(value).encode()
        return raw

    monkeypatch.setattr(server, "request", private)
    result, receipt = run(instance, manager, selected, "private-profile")
    assert result["status"] == "succeeded" and receipt["status"] == "completed", result
    assert not any(
        b"SENSITIVE_PROFILE_ONLY" in path.read_bytes()
        for path in instance.root.rglob("*")
        if path.is_file()
    )


def test_project_filter_is_verified_against_each_selected_root_task(journey):
    instance, manager, _vault, server = journey
    selected = source(manager, connect(manager))
    server.tasks["parent"]["Project"]["uid"] = "wrong-project"
    result, receipt = run(instance, manager, selected, "server-ignored-project-filter")
    assert result["status"] == "manual_intervention" and receipt["error_code"] == "selection"
    assert instance.store.list_canonical("objects") == []


def test_incomplete_pagination_is_unknown_not_an_empty_completed_source(journey, monkeypatch):
    instance, manager, _vault, server = journey
    selected = source(manager, connect(manager))
    original = server.request

    def incomplete(url, **options):
        if urlsplit(url).path == "/api/v1/tasks":
            return json.dumps(
                {
                    "tasks": [],
                    "pagination": {"total": 2, "limit": 25, "offset": 0, "hasMore": False},
                }
            ).encode()
        return original(url, **options)

    monkeypatch.setattr(server, "request", incomplete)
    result, receipt = run(instance, manager, selected, "incomplete-list")
    assert result["status"] == "manual_intervention" and receipt["error_code"] == "response"
    assert ProductivityIntake(instance.store).checkpoint(selected) is None


def test_failed_external_reconnection_retains_previous_grant(journey, monkeypatch):
    _instance, manager, vault, _server = journey
    identity = connect(manager)
    record, reference = manager.record(identity), vault.read(manager.link(identity))
    grant, write = vault.read(reference["name"]), vault.write

    def fail(slot, value):
        if slot == manager.link(identity) and value != reference:
            raise OSError("synthetic vault failure")
        write(slot, value)

    monkeypatch.setattr(vault, "write", fail)
    with pytest.raises(OSError):
        connect(manager, identity=identity, revision=1)
    assert manager.record(identity) == record and vault.read(manager.link(identity)) == reference
    assert vault.read(reference["name"]) == grant
    assert sum(key.startswith("productivity_tududi_grant_") for key in vault.values) == 1
