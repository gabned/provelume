"""Fresh Tududi automatic package path using a closed synthetic public API profile."""

import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .productivity_contract import ProductivityError, require
from .productivity_http import ProductivityHttp
from .productivity_intake import ProductivityIntake
from .productivity_jobs import ProductivityJobs
from .service import ProvelumeInstance
from .tududi_connection import TududiConnection


class SyntheticVault:
    def __init__(self):
        self.values, self.reads = {}, 0

    def read(self, slot):
        self.reads += 1
        return deepcopy(self.values.get(slot))

    def write(self, slot, value):
        self.values[slot] = deepcopy(value)

    def delete(self, slot):
        self.values.pop(slot, None)


def synthetic_task(identity, *, parent=None, timed=False):
    return {
        "uid": identity,
        "name": "Synthetic " + identity,
        "note": "Exact synthetic source note",
        "status": 0,
        "updated_at": "2026-11-07T10:00:00.000Z",
        "completed_at": None,
        "due_date": "2026-11-07",
        "due_time": "12:30" if timed else None,
        "due_has_time": timed,
        "start_date": "2026-11-06",
        "start_time": None,
        "recurrence_type": "none",
        "assigned_to": "person1",
        "AssignedTo": {"uid": "person1", "name": "Synthetic person"},
        "Project": {"uid": "project1", "name": "Synthetic project"},
        "parent_task": {"uid": parent, "name": "Synthetic parent"} if parent else None,
    }


class SyntheticTududi:
    def __init__(self):
        self.calls, self.before_response, self.failure = [], None, None
        self.user, self.time_zone = "user1", "Europe/Rome"
        self.tasks = {
            "parent": synthetic_task("parent"),
            "child": synthetic_task("child", parent="parent"),
            "timed": synthetic_task("timed", timed=True),
        }
        self.roots = ["parent", "timed"]

    def request(self, url, *, origin, token=None, fields=None, deadline=None):
        require(fields is None, "unsupported")
        self.calls.append({"url": url, "token": token, "origin": origin})
        path = urlsplit(url).path.removeprefix("/api/v1")
        query = parse_qs(urlsplit(url).query)
        if self.failure:
            raise self.failure
        if self.before_response:
            self.before_response()
        if path == "/profile":
            value = {"uid": self.user, "timezone": self.time_zone}
        elif path == "/projects":
            value = {"projects": [{"uid": "project1", "name": "Synthetic project"}]}
        elif path == "/project/project1":
            value = {"uid": "project1", "name": "Synthetic project"}
        elif path == "/tasks":
            offset, limit = int(query["offset"][0]), int(query["limit"][0])
            value = {
                "tasks": [{"uid": key} for key in self.roots[offset : offset + limit]],
                "pagination": {
                    "total": len(self.roots),
                    "limit": limit,
                    "offset": offset,
                    "hasMore": offset + limit < len(self.roots),
                },
            }
        elif path.endswith("/comments"):
            value = {
                "comments": [
                    {
                        "uid": "comment1",
                        "body": "Exact retained comment",
                        "replies": [
                            {"uid": "reply1", "body": "Exact retained reply", "replies": []}
                        ],
                    }
                ]
            }
        elif path.endswith("/subtasks"):
            value = [{"uid": "child"}] if path.split("/")[-2] == "parent" else []
        elif path.startswith("/task/"):
            value = self.tasks[path.removeprefix("/task/")]
        else:
            raise ProductivityError("unsupported")
        return json.dumps(value).encode()


def seed_tududi(instance):
    config = instance.store.read_config()
    enabled = deepcopy(config)
    enabled["network"]["external_access"] = True
    instance.store.write_config(enabled)
    try:
        vault, provider = SyntheticVault(), SyntheticTududi()
        manager = TududiConnection(instance.store, vault=vault, http=provider)
        identity = manager.connect(
            {
                "endpoint": "https://tududi.example.invalid",
                "token": "tt_synthetic_token",
                "server_version": "2.1.0",
            },
            name="Synthetic Tududi",
            confirmed=True,
        )["identity_id"]
        source = manager.select_source(
            identity,
            name="Synthetic Tududi project",
            scope="project",
            remote_id="project1",
            confirmed=True,
        )["source_id"]
        jobs = ProductivityJobs(instance.store, tududi=manager)
        instance.scheduler._productivity_manager_factory = lambda _store: jobs
        for key in ("initial", "replay"):
            job = jobs.queue(source, request_key=key)["job"]
            result = instance.scheduler.run_one(job_id=job["id"])
            require(result is not None and result["status"] == "succeeded", "qualification")
        return manager, provider, source
    finally:
        instance.store.write_config(config)


def qualify_tududi(root, *, exercise_http_worker=True):
    from .build_info import current_build_info

    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    instance = ProvelumeInstance.initialise(root / "Synthetic Space")
    _manager, provider, source = seed_tududi(instance)
    rows = ProductivityIntake(instance.store).records(source)
    require(
        len(rows) == 3 and all(row["availability"] == "in_completed_snapshot" for row in rows),
        "qualification",
    )
    row = next(row for row in rows if row["item"]["remote_id"] == "parent")
    require(
        row["item"]["provenance"]["comments"] == ["Exact retained comment", "Exact retained reply"]
        and len(instance.store.versions_for_document(row["document_id"])) == 1,
        "qualification",
    )
    require(
        json.loads(instance.document_original(row["document_id"])["data"])["uid"] == "parent",
        "qualification",
    )
    calls = len(provider.calls)
    archive = root / "Synthetic Portable.zip"
    instance.export_portable(archive, derived_state="rebuild")
    restored = ProvelumeInstance.initialise(root / "Restored Space")
    restored.import_portable(archive)
    task = next(
        obj
        for obj in instance.store.list_canonical("objects")
        if obj["title"] == "Synthetic parent"
    )
    require(
        restored.object_services().get(task["id"])["provider_snapshot"]["item"] == row["item"]
        and len(provider.calls) == calls,
        "qualification",
    )
    worker = "NOT_RUN"
    if exercise_http_worker:
        try:
            ProductivityHttp().request(
                "http://example.invalid/refused", origin="https://tududi.example.invalid"
            )
        except ProductivityError as error:
            require(error.code == "endpoint", "qualification")
            worker = "ENDPOINT_REFUSAL_PASS"
        else:
            require(False, "qualification")
    return {
        "schema": "provelume-tududi-qualification/v1",
        "result": "PASS",
        "build": current_build_info(),
        "execution_adapter": "synthetic",
        "network_used": False,
        "date_only_timed_comments_subtasks": "PASS",
        "exact_originals": "PASS",
        "replay": "PASS",
        "offline_portable": "PASS",
        "http_worker": worker,
        "real_tududi": "NOT_RUN",
        "server_version_verified": False,
        "token_scopes_verified": False,
        "object_id": task["id"],
        "windows_11_pro_25h2_manual": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
