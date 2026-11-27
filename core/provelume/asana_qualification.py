"""Fresh synthetic Asana qualification on installed services; no real account."""

import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .asana_connection import SCOPES, AsanaConnection
from .productivity_contract import ProductivityError, require
from .productivity_http import ProductivityHttp
from .productivity_intake import ProductivityIntake
from .productivity_jobs import ProductivityJobs
from .service import ProvelumeInstance


class _SyntheticVault:
    def __init__(self):
        self.values = {}

    def read(self, slot):
        return deepcopy(self.values.get(slot))

    def write(self, slot, value):
        self.values[slot] = deepcopy(value)

    def delete(self, slot):
        self.values.pop(slot, None)


class _SyntheticAsana:
    def __init__(self):
        self.calls = 0

    def request(self, url, **_options):
        self.calls += 1
        path = urlsplit(url).path
        if path == "/-/oauth_token":
            value = {"access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                     "expires_in": 3600, "token_type": "bearer"}
        elif path == "/-/token_info":
            value = {"active": True, "scope": " ".join(SCOPES)}
        elif path == "/api/1.0/users/me":
            value = {"data": {"gid": "synthetic-user"}}
        elif path == "/api/1.0/projects/synthetic-project":
            value = {"data": {"gid": "synthetic-project", "workspace": {"gid": "synthetic-space"}}}
        elif path == "/api/1.0/tasks":
            value = {"data": [{"gid": "synthetic-task"}]}
        elif path == "/api/1.0/tasks/synthetic-task":
            value = {"data": {"gid": "synthetic-task", "name": "Synthetic Asana task",
                "notes": "Synthetic complete source notes", "completed": False,
                "due_on": "2026-11-07", "due_at": None, "modified_at": "2026-11-07T10:00:00Z",
                "parent": None, "assignee": {"gid": "synthetic-user", "name": "Synthetic user"},
                "memberships": [{"project": {"gid": "synthetic-project", "name": "Synthetic"}}],
                "permalink_url": "https://app.asana.com/0/synthetic-project/synthetic-task",
                "num_subtasks": 0, "workspace": {"gid": "synthetic-space"}}}
        elif path == "/api/1.0/tasks/synthetic-task/stories":
            value = {"data": [{"gid": "synthetic-story", "resource_subtype": "comment_added",
                               "text": "Synthetic retained comment"}]}
        else:
            raise ProductivityError("unsupported")
        return json.dumps(value).encode()


def seed_asana(instance):
    """Synthetic qualification seam only; preserve the selected Instance network policy."""
    config = instance.store.read_config()
    enabled = deepcopy(config)
    enabled["network"]["external_access"] = True
    instance.store.write_config(enabled)
    try:
        return _seed_asana_enabled(instance)
    finally:
        instance.store.write_config(config)


def _seed_asana_enabled(instance):
    vault, provider = _SyntheticVault(), _SyntheticAsana()
    manager = AsanaConnection(instance.store, vault=vault, http=provider)
    manager.configure({"client_id": "synthetic-client", "client_secret": "synthetic-client-secret"})
    redirect = "http://127.0.0.1:18765/asana/oauth/callback"
    request = manager.begin(name="Synthetic Asana", redirect_uri=redirect, confirmed=True)
    state = parse_qs(urlsplit(request["authorization_uri"]).query)["state"][0]
    connected = manager.complete(urlencode({"state": state, "code": "synthetic-code"}).encode(),
                                  redirect_uri=redirect)
    source = manager.select_source(connected["identity_id"], name="Synthetic project tasks",
        scope="project", workspace="synthetic-space", project="synthetic-project",
        confirmed=True)["source_id"]
    jobs = ProductivityJobs(instance.store, asana=manager)
    instance.scheduler._productivity_manager_factory = lambda _store: jobs
    for key in ("initial", "replay"):
        job = jobs.queue(source, request_key=key)["job"]
        result = instance.scheduler.run_one(job_id=job["id"])
        require(result is not None and result["status"] == "succeeded", "qualification")
    return manager, provider, source


def qualify_asana(root, *, exercise_http_worker=True):
    from .build_info import current_build_info

    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    instance = ProvelumeInstance.initialise(root / "Synthetic Space")
    _manager, provider, source = seed_asana(instance)
    row = ProductivityIntake(instance.store).records(source)[0]
    require(row["availability"] == "in_completed_snapshot"
            and row["item"]["provenance"]["comments"] == ["Synthetic retained comment"]
            and len(instance.store.versions_for_document(row["document_id"])) == 1,
            "qualification")
    require(json.loads(instance.document_original(row["document_id"])["data"])["data"]["gid"]
            == "synthetic-task", "qualification")
    obj = instance.store.list_canonical("objects")[0]
    require(obj["body"]["due_date"] == "2026-11-07" and obj["body"]["due_at"] is None,
            "qualification")
    calls = provider.calls
    require(instance.object_services().get(obj["id"])["provider_snapshot"]["current"],
            "qualification")
    archive = root / "Synthetic Portable.zip"
    instance.export_portable(archive, derived_state="rebuild")
    restored = ProvelumeInstance.initialise(root / "Restored Space")
    restored.import_portable(archive)
    require(restored.object_services().get(obj["id"])["provider_snapshot"]["item"] == row["item"]
            and provider.calls == calls, "qualification")
    worker = "NOT_RUN"
    if exercise_http_worker:
        try:
            ProductivityHttp().request("http://example.invalid/refused", origin="https://app.asana.com")
        except ProductivityError as error:
            require(error.code == "endpoint", "qualification")
            worker = "ENDPOINT_REFUSAL_PASS"
        else:
            require(False, "qualification")
    return {"schema": "provelume-asana-qualification/v1", "result": "PASS",
            "build": current_build_info(), "execution_adapter": "synthetic",
            "network_used": False, "pkce_read_scopes": "PASS", "exact_originals": "PASS",
            "comments_assignees_date_only": "PASS", "replay": "PASS", "offline": "PASS",
            "portable_rebuild": "PASS", "http_worker": worker, "real_asana": "NOT_RUN",
            "object_id": obj["id"], "windows_11_pro_25h2_manual":
            "DEFERRED_BY_MAINTAINER / NOT_RUN"}
