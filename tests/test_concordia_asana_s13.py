"""Real PKCE/intake/scheduler with closed synthetic Asana responses only."""

import json
from copy import deepcopy
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from test_google_connection import MemoryVault

from provelume.asana_connection import SCOPES, AsanaConnection
from provelume.asana_intake import PLAN_ROOT, reset_source
from provelume.productivity_contract import ProductivityError
from provelume.productivity_http import ProductivityHttpError
from provelume.productivity_intake import ProductivityIntake
from provelume.productivity_jobs import ProductivityJobs
from provelume.review_decisions import read_json
from provelume.service import ProvelumeInstance
from provelume.web import create_app

REDIRECT = "http://127.0.0.1:18765/asana/oauth/callback"


def task(identity, *, parent=None, subtasks=0):
    return {"gid": identity, "name": "Synthetic " + identity, "notes": "Exact source description",
            "completed": False, "due_on": "2026-11-07", "due_at": None,
            "modified_at": "2026-11-07T10:00:00Z", "parent": {"gid": parent} if parent else None,
            "assignee": {"gid": "synthetic-user"}, "memberships": [{"project": {"gid": "p1"}}],
            "permalink_url": "https://app.asana.com/0/p1/" + identity, "num_subtasks": subtasks,
            "workspace": {"gid": "w1"}}


class AsanaServer:
    def __init__(self):
        self.calls, self.on_api, self.scope_override = [], None, None
        self.user, self.tasks = "user1", {
            "parent": task("parent", subtasks=1), "child": task("child", parent="parent"),
            "shared": task("shared"), "loose": task("loose")}
        self.projects = {"p1": ["parent", "shared"], "p2": ["shared"]}
        self.fail = None

    def request(self, url, *, origin, token=None, fields=None, deadline=None):
        self.calls.append({"url": url, "origin": origin, "fields": fields, "token": token})
        parsed, query = urlsplit(url), parse_qs(urlsplit(url).query)
        if parsed.path == "/-/oauth_token":
            return json.dumps({"access_token": "synthetic-asana-access", "refresh_token":
                "synthetic-asana-refresh", "token_type": "bearer", "expires_in": 3600}).encode()
        if parsed.path == "/-/token_info":
            return json.dumps({"active": True,
                               "scope": self.scope_override or " ".join(SCOPES)}).encode()
        if parsed.path == "/api/1.0/users/me":
            return json.dumps({"data": {"gid": self.user}}).encode()
        if self.fail:
            raise self.fail
        if self.on_api:
            self.on_api()
        path = parsed.path.removeprefix("/api/1.0")
        if path == "/projects/p1":
            value = {"data": {"gid": "p1", "workspace": {"gid": "w1"}, "team": {"gid": "t1"}}}
        elif path == "/workspaces":
            value = {"data": [{"gid": "w1", "name": "Synthetic work", "is_organization": True}]}
        elif path == "/organizations/w1/teams":
            value = {"data": [{"gid": "t1", "name": "Synthetic team"}]}
        elif path == "/teams/t1":
            value = {"data": {"gid": "t1", "organization": {"gid": "w1"}}}
        elif path == "/workspaces/w1":
            value = {"data": {"gid": "w1", "is_organization": True}}
        elif path in {"/projects", "/teams/t1/projects"}:
            value = {"data": [{"gid": identity, "name": "Synthetic " + identity}
                               for identity in self.projects]}
        elif path == "/tasks":
            ids = self.projects.get(query.get("project", [None])[0], ["loose"])
            offset = int(query.get("offset", ["0"])[0])
            size = int(query["limit"][0])
            value = {"data": [{"gid": identity} for identity in ids[offset:offset + size]],
                     "next_page": {"offset": str(offset + size), "uri": "https://evil.invalid"}
                     if offset + size < len(ids) else None}
        elif path.endswith("/subtasks"):
            value = {"data": [{"gid": "child"}] if path.split("/")[-2] == "parent" else []}
        elif path.endswith("/stories"):
            value = {"data": [{"gid": "c1", "resource_subtype": "comment_added", "text":
                                "Retained exact comment"}]}
        else:
            identity = path.split("/")[-1]
            value = {"data": self.tasks[identity]}
        return json.dumps(value).encode()


@pytest.fixture
def journey(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    vault, server = MemoryVault(), AsanaServer()
    manager = AsanaConnection(instance.store, vault=vault, http=server)
    manager.configure({"client_id": "synthetic-client", "client_secret": "synthetic-client-secret"})
    return instance, manager, vault, server


def connect(manager, *, identity=None):
    request = manager.begin(name="Synthetic Asana", redirect_uri=REDIRECT, confirmed=True,
                            identity=identity)
    fields = parse_qs(urlsplit(request["authorization_uri"]).query)
    query = urlencode({"state": fields["state"][0], "code": "synthetic-code"}).encode()
    return request, manager.complete(query, redirect_uri=REDIRECT), query


def source(manager, identity, *, scope="project", name="Selected"):
    return manager.select_source(identity, name=name, scope=scope, workspace="w1",
        team="t1" if scope == "team" else None, project="p1" if scope == "project" else None,
        confirmed=True)["source_id"]


def run(instance, manager, selected, key):
    jobs = ProductivityJobs(instance.store, asana=manager)
    instance.scheduler._productivity_manager_factory = lambda _store: jobs
    queued = jobs.queue(selected, request_key=key)
    result = instance.scheduler.run_one(job_id=queued["job"]["id"])
    return result, read_json(instance.store,
                            f"state/productivity-providers/asana-runs/{queued['job']['id']}.json")


def test_pkce_exact_read_scopes_external_tokens_replay_and_two_identities(journey):
    instance, manager, vault, server = journey
    request, first, callback = connect(manager)
    params = parse_qs(urlsplit(request["authorization_uri"]).query)
    assert params["scope"] == [" ".join(SCOPES)] and params["code_challenge_method"] == ["S256"]
    assert not any(scope.endswith(":write") for scope in SCOPES)
    token_request = server.calls[0]["fields"]
    assert len(token_request["code_verifier"]) >= 43
    with pytest.raises(ProductivityError):
        manager.complete(callback, redirect_uri=REDIRECT)
    selected = source(manager, first["identity_id"])
    _, second, _callback = connect(manager)
    assert second["identity_id"] != first["identity_id"]
    manager.disconnect(first["identity_id"], expected_revision=1, confirmed=True)
    assert manager.record(second["identity_id"])["status"] == "authorized"
    with pytest.raises(ProductivityError, match="authorization_required"):
        manager.resolve(first["identity_id"], "task_read")
    assert manager.host.policy(selected)["mode"] == "manual"
    assert all(b"synthetic-asana-" not in path.read_bytes()
               and b"productivity_asana_grant_" not in path.read_bytes()
               for path in instance.root.rglob("*") if path.is_file())
    assert vault.values != {}


@pytest.mark.parametrize("scope", ["project", "team", "workspace", "organization"])
def test_all_source_scopes_real_scheduler_subtasks_comments_and_exact_originals(journey, scope):
    instance, manager, _vault, _server = journey
    _, connected, _query = connect(manager)
    selected = source(manager, connected["identity_id"], scope=scope)
    result, receipt = run(instance, manager, selected, "full-source")
    assert result["status"] == "succeeded", result
    assert receipt["status"] == "completed" and receipt["network_used"] is False
    rows = ProductivityIntake(instance.store).records(selected)
    assert {row["item"]["remote_id"] for row in rows} == (
        {"parent", "shared", "child", "loose"} if scope in {"workspace", "organization"}
        else {"parent", "shared", "child"})
    assert all(row["availability"] == "in_completed_snapshot" for row in rows)
    row = next(row for row in rows if row["item"]["remote_id"] == "child")
    assert row["item"]["provenance"]["parent_id"] == "parent"
    assert row["item"]["provenance"]["comments"] == ["Retained exact comment"]
    for digest in row["item"]["provenance"]["response_sha256"]:
        assert instance.store.original_bytes("sha256_" + digest)
    raw = instance.document_original(row["document_id"])["data"]
    assert json.loads(raw)["data"]["gid"] == "child"
    assert instance.validate_instance()["status"] == "valid"
    assert len(instance.store.list_canonical("objects")) == len(rows)
    result, _receipt = run(instance, manager, selected, "unchanged-source")
    assert result["status"] == "succeeded", result
    assert len(instance.store.versions_for_document(row["document_id"])) == 1


def test_unaccepted_scopes_and_changed_account_cannot_replace_previous_grant(journey):
    _instance, manager, vault, server = journey
    _, connected, _query = connect(manager)
    identity = connected["identity_id"]
    before, link = manager.record(identity), vault.read(manager.link(identity))
    server.scope_override = " ".join((*SCOPES, "tasks:write"))
    with pytest.raises(ProductivityError, match="scope_mismatch"):
        connect(manager, identity=identity)
    assert manager.record(identity) == before and vault.read(manager.link(identity)) == link
    server.scope_override, server.user = None, "wrong-user"
    with pytest.raises(ProductivityError, match="account_mismatch"):
        connect(manager, identity=identity)
    assert manager.record(identity) == before and vault.read(manager.link(identity)) == link


def test_bounded_continuation_only_completes_after_all_original_steps(journey):
    instance, manager, _vault, server = journey
    server.tasks = {str(index): task(str(index)) for index in range(30)}
    server.projects = {"p1": list(server.tasks)}
    _, connected, _query = connect(manager)
    selected = source(manager, connected["identity_id"])
    first, receipt = run(instance, manager, selected, "first-50-responses")
    assert first["status"] == "succeeded", first
    assert receipt["status"] == "continuation_available"
    assert ProductivityIntake(instance.store).checkpoint(selected) is None
    second, receipt = run(instance, manager, selected, "continuation")
    assert second["status"] == "succeeded" and receipt["status"] == "completed", second
    rows = ProductivityIntake(instance.store).records(selected)
    assert len(rows) == 30 and all(row["availability"] == "in_completed_snapshot" for row in rows)
    assert not any("evil.invalid" in row["url"] for row in server.calls)


def test_mid_response_source_disable_never_promotes_or_advances(journey):
    instance, manager, _vault, server = journey
    _, connected, _query = connect(manager)
    selected = source(manager, connected["identity_id"])
    server.on_api = lambda: manager.connectors.disable_source(connected["identity_id"], selected)
    result, _receipt = run(instance, manager, selected, "disabled-during-response")
    assert result["status"] == "manual_intervention"
    assert instance.store.list_canonical("documents") == []
    assert ProductivityIntake(instance.store).checkpoint(selected) is None


def test_rate_limit_is_retained_and_blocks_equivalent_request_until_cooldown(journey):
    instance, manager, _vault, server = journey
    _, connected, _query = connect(manager)
    selected = source(manager, connected["identity_id"])
    server.fail = ProductivityHttpError(429, 300)
    result, _receipt = run(instance, manager, selected, "rate-limited")
    assert result["status"] == "manual_intervention"
    calls = len(server.calls)
    server.fail = None
    result, _receipt = run(instance, manager, selected, "blocked-during-cooldown")
    assert result["status"] == "manual_intervention" and len(server.calls) == calls
    cooldown = read_json(instance.store, f"{PLAN_ROOT}/{selected}/cooldown.json")
    assert cooldown["status"] == "rate_limited"


def test_full_resync_removes_membership_without_fabricating_task_cancellation(journey):
    instance, manager, _vault, server = journey
    _, connected, _query = connect(manager)
    selected = source(manager, connected["identity_id"])
    result, _receipt = run(instance, manager, selected, "first")
    assert result["status"] == "succeeded"
    before = deepcopy(instance.store.list_canonical("objects"))
    server.projects = {"p1": []}
    reset_source(manager, selected, expected_policy_revision=1, confirmed=True)
    result, receipt = run(instance, manager, selected, "explicit-full-reset")
    assert result["status"] == "succeeded" and receipt["status"] == "completed"
    assert instance.store.list_canonical("objects") == before
    rows = ProductivityIntake(instance.store).records(selected)
    assert {row["availability"] for row in rows} == {"not_in_completed_snapshot"}


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
def test_governed_ui_catalogue_selection_comments_and_get_without_vault(
    journey, tmp_path, language
):
    import re

    instance, manager, vault, server = journey
    _, connected, _callback = connect(manager)
    identity = connected["identity_id"]
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json",
                     effective_port=18765)
    app.state.provelume._asana_manager = manager
    client = TestClient(app)
    before = (len(server.calls), vault.reads)
    response = client.get("/asana/connect?lang=" + language)
    assert response.status_code == 200 and (len(server.calls), vault.reads) == before
    assert "asana.lead" not in response.text and "synthetic-client-secret" not in response.text
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def control(action, **fields):
        return client.post("/asana/connect?lang=" + language,
            data={"csrf_token": token, "confirm": "yes", "action": action, **fields})

    assert client.post("/asana/connect", data={"csrf_token": "bad"}).status_code == 403
    response = control("catalogue", identity=identity)
    assert "notice=saved" in str(response.url) and "Synthetic work" in response.text
    response = control("catalogue", identity=identity, workspace="w1")
    assert "Synthetic p1" in response.text and "Synthetic team" in response.text
    response = control("select", identity=identity, workspace="w1", scope="project", project="p1",
                       name="Selected UI project")
    assert "notice=saved" in str(response.url)
    selected = manager.view()["sources"][0]["id"]
    jobs = ProductivityJobs(instance.store, asana=manager)
    app.state.provelume.scheduler._productivity_manager_factory = lambda _store: jobs
    response = control("read", source_id=selected, revision="1")
    assert "notice=saved" in str(response.url)
    obj = instance.store.list_canonical("objects")[0]
    before = (len(server.calls), vault.reads)
    response = client.get(f"/objects/{obj['id']}?lang={language}")
    assert response.status_code == 200 and "Retained exact comment" in response.text
    assert "objects.connector_comments" not in response.text
    assert 'id="connector-provenance"' in response.text
    assert (len(server.calls), vault.reads) == before
    assert client.get(f"/objects/{obj['id']}/edit?lang={language}").status_code == 403


def test_official_asana_profile_cannot_be_used_by_another_oauth_adapter(journey):
    from provelume.oauth_authorization import OAuthAdapterError, _adapter_contract

    class Wrong:
        adapter_key, adapter_version = "another-provider", "1.0.0"
        authorization_endpoint, token_endpoint = "https://example.invalid/auth", "https://example.invalid/token"
        authorization_consent_profile = "asana-scoped-pkce-v1"

    with pytest.raises(OAuthAdapterError):
        _adapter_contract(Wrong())


def test_task_changed_during_comment_acquisition_remains_unpromoted(journey):
    instance, manager, _vault, server = journey
    _, connected, _query = connect(manager)
    selected = source(manager, connected["identity_id"])

    def changed():
        if server.calls[-1]["url"].split("?", 1)[0].endswith("/stories"):
            server.tasks["parent"]["modified_at"] = "2026-11-07T12:00:00Z"

    server.on_api = changed
    result, receipt = run(instance, manager, selected, "changed-task")
    assert result["status"] == "manual_intervention" and receipt["error_code"] == "stale"
    assert ProductivityIntake(instance.store).checkpoint(selected) is None
    assert instance.store.list_canonical("objects") == []


def test_fresh_automatic_qualification_has_real_worker_refusal_and_offline_transfer(tmp_path):
    from provelume.asana_qualification import qualify_asana

    result = qualify_asana(tmp_path / "Synthetic Qualification")
    assert result["result"] == "PASS" and result["real_asana"] == "NOT_RUN"
    assert result["http_worker"] == "ENDPOINT_REFUSAL_PASS" and not result["network_used"]


def test_expiring_token_never_refreshes_inside_any_canonical_commit_guard(journey, monkeypatch):
    from contextlib import contextmanager

    from provelume.connectors import ConnectorManager

    instance, manager, vault, server = journey
    _, connected, _query = connect(manager)
    identity = connected["identity_id"]
    selected = source(manager, identity)
    original_guard = ConnectorManager.policy_commit_guard
    original_request = server.request
    entered, depth = [], 0

    @contextmanager
    def guard(self, *, purpose):
        nonlocal depth
        with original_guard(self, purpose=purpose):
            depth += 1
            entered.append(purpose)
            try:
                yield
            finally:
                depth -= 1

    def request(url, **options):
        assert depth == 0, "HTTP attempted while canonical policy lock is held"
        result = original_request(url, **options)
        if "/api/1.0/" in url and "/users/me" not in url:
            slot = vault.read(manager.link(identity))["name"]
            grant = vault.read(slot)
            vault.write(slot, {**grant, "expires_at": 0})
        return result

    monkeypatch.setattr(ConnectorManager, "policy_commit_guard", guard)
    monkeypatch.setattr(server, "request", request)
    result, receipt = run(instance, manager, selected, "expires-after-every-response")
    assert result["status"] == "succeeded" and receipt["status"] == "completed", result
    assert "productivity-intake" in entered and "asana-page-checkpoint" in entered
    assert sum("oauth_token" in row["url"] for row in server.calls) > 1


def test_failed_external_grant_publication_preserves_previous_authority(journey, monkeypatch):
    _instance, manager, vault, _server = journey
    _, connected, _query = connect(manager)
    identity = connected["identity_id"]
    before, old_reference = manager.record(identity), vault.read(manager.link(identity))
    old_grant, write = vault.read(old_reference["name"]), vault.write

    def fail_pointer(slot, value):
        if slot == manager.link(identity) and value != old_reference:
            raise OSError("synthetic external vault publication failure")
        write(slot, value)

    monkeypatch.setattr(vault, "write", fail_pointer)
    with pytest.raises(OSError):
        connect(manager, identity=identity)
    assert manager.record(identity) == before
    assert vault.read(manager.link(identity)) == old_reference
    assert vault.read(old_reference["name"]) == old_grant
    assert sum(key.startswith("productivity_asana_grant_") for key in vault.values) == 1


def test_read_worker_refuses_task_writes_before_opening_any_connection(monkeypatch):
    from provelume import productivity_http

    def forbidden():
        pytest.fail("read transport reached a network opener for a task write")

    monkeypatch.setattr(productivity_http, "build_opener", forbidden)
    with pytest.raises(ProductivityError, match="unsupported"):
        productivity_http.request_direct({"url": "https://app.asana.com/api/1.0/tasks/123",
            "origin": "https://app.asana.com", "fields": {"completed": True}})


def test_catalogue_uses_documented_nonpaginated_workspaces_operation(journey):
    _instance, manager, _vault, server = journey
    _, connected, _query = connect(manager)
    manager.catalogue(connected["identity_id"], confirmed=True)
    query = parse_qs(urlsplit(server.calls[-1]["url"]).query)
    assert set(query) == {"opt_fields"}


def test_catalogue_rate_limit_is_grant_scoped_and_new_consent_is_independent(journey):
    _instance, manager, _vault, server = journey
    _, connected, _query = connect(manager)
    identity = connected["identity_id"]
    server.fail = ProductivityHttpError(429, 300)
    with pytest.raises(ProductivityError, match="rate_limited"):
        manager.catalogue(identity, confirmed=True)
    count = len(server.calls)
    server.fail = None
    with pytest.raises(ProductivityError, match="rate_limited"):
        manager.catalogue(identity, confirmed=True)
    assert len(server.calls) == count
    connect(manager, identity=identity)
    manager.catalogue(identity, confirmed=True)
    assert manager.view()["identities"][0]["catalogue"]["workspaces"][0]["gid"] == "w1"


def test_repeated_remote_cursor_cannot_complete_or_silently_drop_tasks(journey, monkeypatch):
    instance, manager, _vault, server = journey
    _, connected, _query = connect(manager)
    selected = source(manager, connected["identity_id"])
    original = server.request

    def repeating(url, **options):
        if urlsplit(url).path == "/api/1.0/tasks":
            return json.dumps({"data": [], "next_page": {"offset": "repeated"}}).encode()
        return original(url, **options)

    monkeypatch.setattr(server, "request", repeating)
    result, receipt = run(instance, manager, selected, "cursor-loop")
    assert result["status"] == "manual_intervention" and receipt["error_code"] == "cursor_loop"
    assert ProductivityIntake(instance.store).checkpoint(selected) is None
    assert instance.store.list_canonical("objects") == []
