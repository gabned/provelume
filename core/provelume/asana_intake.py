"""Resumable Asana full reads, one original API response per durable scheduler step."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from copy import deepcopy
from urllib.parse import urlencode

from .asana_connection import API, AsanaConnection, decode, gid
from .index_evidence import publish_once
from .instance_lifecycle import InstanceLifecycleManager
from .productivity_contract import ReadPage, fingerprint, require, validate_item
from .productivity_generations import ProductivityGenerations
from .productivity_intake import ProductivityIntake
from .review_decisions import checked_path, read_json
from .storage import utc_now

FIELDS = ("gid,name,notes,completed,due_at,due_on,modified_at,parent.gid,parent.name,"
          "assignee.gid,assignee.name,memberships.project.gid,memberships.project.name,"
          "permalink_url,num_subtasks,workspace.gid")
PLAN_ROOT = "state/productivity-providers/asana-plans"


def map_task(value, comments, selection, response_hashes):
    require(type(value) is dict and type(value.get("completed")) is bool, "response")
    due = value.get("due_at")
    if due is not None:
        due = {"kind": "instant", "value": due, "time_zone": "UTC"}
    elif value.get("due_on") is not None:
        due = {"kind": "date", "value": value["due_on"], "time_zone": None}
    containers = [selection["workspace"]]
    if selection.get("team"):
        containers.append(selection["team"])
    for membership in value.get("memberships", []):
        require(type(membership) is dict and type(membership.get("project")) is dict, "response")
        containers.append(gid(membership["project"].get("gid")))
    parent, assignee = value.get("parent"), value.get("assignee")
    require(parent is None or type(parent) is dict, "response")
    require(assignee is None or type(assignee) is dict, "response")
    result = {"remote_id": gid(value.get("gid")), "revision": value.get("modified_at"),
        "revision_kind": "version", "kind": "task", "title": value.get("name"),
        "description": value.get("notes", ""),
        "state": "completed" if value["completed"] else "open",
        "due": due, "starts": None, "ends": None,
        "provenance": {"container_ids": list(dict.fromkeys(containers)),
            "parent_id": gid(parent["gid"]) if parent else None,
            "assignees": [gid(assignee["gid"])] if assignee else [],
            "links": [value["permalink_url"]] if value.get("permalink_url") else [],
            "comments": comments, "uid": None, "recurrence_id": None, "recurrence": [],
            "response_sha256": response_hashes}}
    result["provenance"]["display_names"] = {
        "assignees": ({assignee["gid"]: assignee["name"]}
                      if assignee and assignee.get("name") else {}),
        "containers": {row["project"]["gid"]: row["project"]["name"] for row in value.get(
            "memberships", []) if row["project"].get("name")},
        "parent": parent.get("name") if parent else None}
    return validate_item(result)


class AsanaSteps:
    def __init__(self, connection, source_id, *, scheduled=False, deadline=None):
        self.connection, self.store, self.source_id = connection, connection.store, source_id
        self.scheduled, self.deadline = scheduled, deadline or time.monotonic() + 60
        identity, source, definition = connection.host._records(source_id)
        require(definition["provider"] == "asana", "unsupported")
        self.identity, self.source = identity["id"], source
        self.grant_revision = connection.record(self.identity)["revision"]
        self.selection = json.loads(source["external_id"])
        require(type(self.selection) is dict and set(self.selection)
                == {"scope", "workspace", "team", "project"}, "integrity")
        require(self.selection["scope"] in {"workspace", "organization", "team", "project"},
                "integrity")
        gid(self.selection["workspace"])
        if self.selection["team"] is not None:
            gid(self.selection["team"])
        if self.selection["project"] is not None:
            gid(self.selection["project"])
        self.authority = connection.host.authority(source_id, "task_read", scheduled=scheduled)
        connection.resolve(self.identity, "task_read")
        self.binding = self.current_binding()
        self.network_used = False

    def current_binding(self):
        return {"authority": self.connection.host.authority(
                    self.source_id, "task_read", scheduled=self.scheduled)["sha256"],
                "authorization": self.connection.authority.authorization_fingerprint(self.identity),
                "credential": self.connection.credential_epoch(self.identity),
                "reset": read_json(self.store, f"{PLAN_ROOT}/{self.source_id}/reset.json")}

    def recheck(self):
        require(self.current_binding() == self.binding, "stale")

    def initial(self):
        project = self.selection.get("project")
        phase = "validate" if project else (
            "validate_team" if self.selection["scope"] == "team" else "validate_workspace")
        return {"schema": "asana-read-plan/v1", "source_id": self.source_id,
                "binding": self.binding, "phase": phase,
                "projects": [project] if project else [], "project_index": 0,
                "project_offset": None, "root_offset": None, "queue": [], "seen": [],
                "own_done": self.selection["scope"] not in {"workspace", "organization"},
                "current": None, "responses": 0, "cursor_tokens": []}

    def load(self, cursor):
        if cursor is None:
            return self.initial()
        require(type(cursor) is str and len(cursor) == 64 and all(
            char in "0123456789abcdef" for char in cursor), "cursor")
        value = read_json(self.store, f"{PLAN_ROOT}/{self.source_id}/plans/{cursor}.json")
        require(value is not None and fingerprint(value, maximum=2 * 1024 * 1024) == cursor
                and value["source_id"] == self.source_id and value["binding"] == self.binding,
                "cursor_invalidated")
        return value

    @staticmethod
    def next_offset(data):
        page = data.get("next_page")
        if page is None:
            return None
        require(type(page) is dict and type(page.get("offset")) is str
                and 0 < len(page["offset"]) <= 2048, "response")
        # Server-provided next_page.uri is never requested or trusted.
        return page["offset"]

    def get(self, path, params=None):
        from .productivity_http import ProductivityHttp, ProductivityHttpError

        self.recheck()
        cooldown = read_json(self.store, f"{PLAN_ROOT}/{self.source_id}/cooldown.json")
        require(cooldown is None or cooldown["grant_revision"] != self.grant_revision
                or cooldown["not_before"] <= time.time(), "rate_limited")
        require(time.monotonic() < self.deadline, "deadline")
        credential = self.connection.resolve(self.identity, "task_read")
        self.network_used |= type(self.connection.http) is ProductivityHttp
        self.connection.network_used |= self.network_used
        try:
            raw = self.connection.http.request(
                API + path + ("?" + urlencode(params) if params else ""),
                origin="https://app.asana.com", token=credential.payload["access_token"],
                deadline=self.deadline)
        except ProductivityHttpError as error:
            if error.status == 429:
                not_before = time.time() + (error.retry_after or 60)
                self.store._atomic_json(checked_path(self.store,
                    f"{PLAN_ROOT}/{self.source_id}/cooldown.json"), {
                    "not_before": not_before,
                    "grant_revision": self.grant_revision,
                    "status": "rate_limited"})
                self.connection.record_rate_limit(self.identity, self.grant_revision,
                                                   error.retry_after)
            raise
        require(type(raw) is bytes and len(raw) <= 1024 * 1024, "limit")
        value = decode(raw)
        if type(value.get("data")) is list and (params or {}).get("limit"):
            require(len(value["data"]) <= params["limit"], "limit")
        next_offset = self.next_offset(value)
        if next_offset is not None:
            token = fingerprint([path, {key: val for key, val in (params or {}).items()
                                       if key != "offset"}, next_offset])
            require(next_offset != (params or {}).get("offset"), "cursor_loop")
            require(token not in self._active_plan["cursor_tokens"], "cursor_loop")
            self._active_plan["cursor_tokens"].append(token)
        self.recheck()
        require(time.monotonic() < self.deadline, "deadline")
        return raw, value

    @staticmethod
    def rows(data):
        rows = data.get("data")
        require(type(rows) is list and len(rows) <= 100, "response")
        require(all(type(row) is dict for row in rows), "response")
        return rows

    def enqueue(self, plan, values):
        for value in values:
            selected = gid(value.get("gid"))
            if selected not in plan["seen"] and selected not in plan["queue"]:
                plan["queue"].append(selected)
        require(len(plan["seen"]) + len(plan["queue"]) <= 5000, "limit")

    def finish_task(self, plan):
        current = plan["current"]
        mapped = map_task(current["value"], current["comments"], self.selection,
                          current["response_hashes"])
        original = base64.b64decode(current["original"], validate=True)
        plan["seen"].append(plan["queue"].pop(0))
        plan.update(current=None, phase="roots")
        return (mapped,), (original,)

    def step(self, cursor):
        from .productivity_contract import ProductivityError

        try:
            return self._step(cursor)
        except ProductivityError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            raise ProductivityError("response") from None

    def _step(self, cursor):
        plan = deepcopy(self.load(cursor))
        self._active_plan = plan
        phase = plan["phase"]
        if phase == "roots" and plan["queue"]:
            phase = plan["phase"] = "detail"
        items, originals = (), ()
        params = {"limit": 25, "opt_fields": "gid"}
        if phase == "validate":
            raw, data = self.get("/projects/" + gid(self.selection["project"]),
                                  {"opt_fields": "gid,name,workspace.gid,team.gid"})
            project = data.get("data", {})
            require(project.get("gid") == self.selection["project"]
                    and project.get("workspace", {}).get("gid") == self.selection["workspace"],
                    "selection")
            require(self.selection["team"] is None or project.get("team", {}).get("gid")
                    == self.selection["team"], "selection")
            plan["phase"] = "roots"
        elif phase == "validate_team":
            raw, data = self.get("/teams/" + gid(self.selection["team"]),
                                 {"opt_fields": "gid,name,organization.gid"})
            value = data.get("data", {})
            require(value.get("gid") == self.selection["team"]
                    and value.get("organization", {}).get("gid") == self.selection["workspace"],
                    "selection")
            plan["phase"] = "projects"
        elif phase == "validate_workspace":
            raw, data = self.get("/workspaces/" + gid(self.selection["workspace"]),
                                 {"opt_fields": "gid,name,is_organization"})
            value = data.get("data", {})
            require(value.get("gid") == self.selection["workspace"], "selection")
            require(self.selection["scope"] != "organization" or value.get("is_organization")
                    is True, "selection")
            plan["phase"] = "projects"
        elif phase == "projects":
            if plan["project_offset"]:
                params["offset"] = plan["project_offset"]
            if self.selection["scope"] == "team":
                path = "/teams/" + gid(self.selection["team"]) + "/projects"
            else:
                path = "/projects"
                params["workspace"] = gid(self.selection["workspace"])
            raw, data = self.get(path, params)
            for project in self.rows(data):
                selected = gid(project.get("gid"))
                require(selected not in plan["projects"], "cursor_invalidated")
                plan["projects"].append(selected)
            require(len(plan["projects"]) <= 5000, "limit")
            plan["project_offset"] = self.next_offset(data)
            if plan["project_offset"] is None:
                plan["phase"] = "roots"
        elif phase == "roots":
            if plan["project_index"] < len(plan["projects"]):
                params["project"] = plan["projects"][plan["project_index"]]
            else:
                require(not plan["own_done"], "integrity")
                params.update(workspace=self.selection["workspace"], assignee="me")
            if plan["root_offset"]:
                params["offset"] = plan["root_offset"]
            raw, data = self.get("/tasks", params)
            self.enqueue(plan, self.rows(data))
            plan["root_offset"] = self.next_offset(data)
            if plan["root_offset"] is None:
                if plan["project_index"] < len(plan["projects"]):
                    plan["project_index"] += 1
                else:
                    plan["own_done"] = True
        elif phase == "detail":
            identity = plan["queue"][0]
            raw, data = self.get("/tasks/" + gid(identity), {"opt_fields": FIELDS})
            value = data.get("data")
            require(type(value) is dict and value.get("gid") == identity, "response")
            require(value.get("workspace", {}).get("gid") == self.selection["workspace"],
                    "selection")
            plan["current"] = {"value": value, "original": base64.b64encode(raw).decode(),
                "comments": [], "response_hashes": [hashlib.sha256(raw).hexdigest()],
                "story_offset": None, "subtask_offset": None}
            plan["phase"] = "stories"
        elif phase == "stories":
            current = plan["current"]
            params["opt_fields"] = "gid,text,resource_subtype"
            if current["story_offset"]:
                params["offset"] = current["story_offset"]
            raw, data = self.get("/tasks/" + gid(plan["queue"][0]) + "/stories", params)
            for row in self.rows(data):
                if row.get("resource_subtype") == "comment_added":
                    require(type(row.get("text")) is str, "response")
                    current["comments"].append(row["text"])
            require(len(current["comments"]) <= 200, "limit")
            current["response_hashes"].append(hashlib.sha256(raw).hexdigest())
            current["story_offset"] = self.next_offset(data)
            if current["story_offset"] is None:
                if current["value"].get("num_subtasks", 0):
                    plan["phase"] = "subtasks"
                else:
                    plan["phase"] = "verify"
        elif phase == "subtasks":
            current = plan["current"]
            if current["subtask_offset"]:
                params["offset"] = current["subtask_offset"]
            raw, data = self.get("/tasks/" + gid(plan["queue"][0]) + "/subtasks", params)
            self.enqueue(plan, self.rows(data))
            current["response_hashes"].append(hashlib.sha256(raw).hexdigest())
            current["subtask_offset"] = self.next_offset(data)
            if current["subtask_offset"] is None:
                plan["phase"] = "verify"
        elif phase == "verify":
            current = plan["current"]
            raw, data = self.get("/tasks/" + gid(plan["queue"][0]), {"opt_fields": FIELDS})
            require(data.get("data") == current["value"], "stale")
            current["response_hashes"].append(hashlib.sha256(raw).hexdigest())
            current["response_hashes"] = list(dict.fromkeys(current["response_hashes"]))
            items, originals = self.finish_task(plan)
        else:
            require(False, "integrity")
        plan["responses"] += 1
        require(plan["responses"] <= 20000, "limit")
        done = (plan["phase"] == "roots" and not plan["queue"] and plan["own_done"]
                and plan["project_index"] >= len(plan["projects"]) and plan["root_offset"] is None)
        digest = fingerprint(plan, maximum=2 * 1024 * 1024)
        if not done:
            publish_once(self.store, f"{PLAN_ROOT}/{self.source_id}/plans/{digest}.json", plan)
        return ReadPage(items, originals=originals, response=raw,
                        next_cursor=None if done else digest, checkpoint=digest if done else None)


def execute_asana_job(store, job, *, connection=None, cancelled=lambda: False):
    connection = connection or AsanaConnection(store)
    source_id = job["scope"]["id"]
    scheduled = job.get("reason") in {"scheduled", "coalesced", "catch_up"}
    adapter = AsanaSteps(connection, source_id, scheduled=scheduled)
    generations = ProductivityGenerations(store, source_id)
    state = generations.prepare(adapter.binding, 1, allow_delta=False)
    intake = ProductivityIntake(store)
    counts, total = {"processed": 0, "skipped": 0, "errors": 0}, 0
    for _index in range(50):
        require(not cancelled(), "cancelled")
        require(time.monotonic() < adapter.deadline, "deadline")
        page = adapter.step(state["page_token"])
        total += len(page.response or b"")
        require(total <= 8 * 1024 * 1024, "limit")
        preview = connection.host.page_preview(source_id, "task_read", page,
            expected_authority=adapter.authority["sha256"], scheduled=scheduled)
        generations.check_page(state, preview)
        result = intake.import_page_locked(preview, cancelled=cancelled, recheck=adapter.recheck)
        counts["processed"] += sum(row["status"] == "imported" for row in result["results"])
        counts["skipped"] += sum(row["status"] == "unchanged" for row in result["results"])
        with connection.connectors.policy_commit_guard(purpose="asana-page-checkpoint"):
            adapter.recheck()
            require(not cancelled(), "cancelled")
            state = generations.publish_page(state, preview, result)
        if state["status"] == "completed":
            break
    return {"progress": counts, "status": state["status"], "network_used": adapter.network_used}


def reset_source(connection, source_id, *, expected_policy_revision, confirmed):
    require(confirmed is True, "consent_required")
    with InstanceLifecycleManager(connection.store)._hold(purpose="asana-reset"), \
            connection.connectors.policy_commit_guard(purpose="asana-reset"):
        _identity, _source, definition = connection.host._records(source_id)
        require(definition["provider"] == "asana", "unsupported")
        require(connection.host.policy(source_id)["revision"] == expected_policy_revision, "stale")
        relative = f"{PLAN_ROOT}/{source_id}/reset.json"
        previous = read_json(connection.store, relative)
        value = {"source_id": source_id, "revision": previous["revision"] + 1 if previous else 1,
                 "reset_at": utc_now()}
        connection.store._atomic_json(checked_path(connection.store, relative), value)
        return value
