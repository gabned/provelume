"""Tududi bounded Source traversal with independent plans and exact response evidence."""

import hashlib
import json
import time
from copy import deepcopy
from urllib.parse import urlencode

from .instance_lifecycle import InstanceLifecycleManager
from .productivity_contract import ReadPage, fingerprint, require
from .productivity_generations import ProductivityGenerations
from .productivity_intake import ProductivityIntake
from .review_decisions import checked_path, read_json
from .tududi_connection import TududiConnection
from .tududi_contract import map_task, uid, zone

PLAN_ROOT = "state/productivity-providers/tududi-plans"


class TududiSteps:
    def __init__(self, connection, source_id, *, scheduled=False):
        self.connection, self.store, self.source_id = connection, connection.store, source_id
        identity, source, definition = connection.host._records(source_id)
        require(definition["provider"] == "tududi", "unsupported")
        self.identity, self.scheduled = identity["id"], scheduled
        self.selection = json.loads(source["external_id"])
        require(
            type(self.selection) is dict
            and set(self.selection) == {"scope", "uid"}
            and self.selection["scope"] in {"account", "project", "task"},
            "integrity",
        )
        require(
            (self.selection["uid"] is None) == (self.selection["scope"] == "account"), "integrity"
        )
        if self.selection["uid"] is not None:
            uid(self.selection["uid"])
        self.authority = connection.host.authority(source_id, "task_read", scheduled=scheduled)
        self.credential = connection.resolve(self.identity)
        self.binding, self.deadline = self.current_binding(), time.monotonic() + 60

    def current_binding(self):
        return {
            "authority": self.connection.host.authority(
                self.source_id, "task_read", scheduled=self.scheduled
            )["sha256"],
            "authorization": self.connection.authority(self.identity),
            "credential": self.connection.resolve(self.identity).revision_sha256,
            "reset": read_json(self.store, f"{PLAN_ROOT}/{self.source_id}/reset.json"),
        }

    def recheck(self):
        require(self.current_binding() == self.binding, "stale")

    def initial(self):
        scope = self.selection["scope"]
        return {
            "schema": "tududi-read-plan/v1",
            "source_id": self.source_id,
            "binding": self.binding,
            "phase": "profile",
            "after_profile": "validate_project"
            if scope == "project"
            else "detail"
            if scope == "task"
            else "roots",
            "time_zone": None,
            "offset": 0,
            "total": None,
            "root_ids": [],
            "verify_ids": [],
            "queue": [self.selection["uid"]] if scope == "task" else [],
            "seen": [],
            "current": None,
            "responses": 0,
            "roots_complete": scope == "task",
        }

    def load(self, cursor):
        if cursor is None:
            return self.initial()
        require(
            type(cursor) is str
            and len(cursor) == 64
            and all(char in "0123456789abcdef" for char in cursor),
            "cursor",
        )
        value = read_json(self.store, f"{PLAN_ROOT}/{self.source_id}/plans/{cursor}.json")
        require(
            value is not None
            and fingerprint(value, maximum=2 * 1024 * 1024) == cursor
            and value["source_id"] == self.source_id
            and value["binding"] == self.binding,
            "cursor_invalidated",
        )
        return value

    def enqueue(self, plan, values):
        for value in values:
            require(type(value) is dict, "response")
            selected = uid(value.get("uid"))
            require(
                plan["current"] is None or selected != plan["current"]["value"]["uid"], "response"
            )
            if selected not in plan["seen"] and selected not in plan["queue"]:
                plan["queue"].append(selected)
        require(len(set(plan["seen"] + plan["queue"])) <= 5000, "limit")

    def get(self, path):
        self.recheck()
        require(time.monotonic() < self.deadline, "deadline")
        raw, value = self.connection.get(self.identity, path, deadline=self.deadline)
        self.recheck()
        require(time.monotonic() < self.deadline, "deadline")
        return raw, value

    @staticmethod
    def comments(value):
        require(type(value) is dict and type(value.get("comments")) is list, "response")
        result, seen = [], set()
        for row in value["comments"]:
            require(type(row) is dict and type(row.get("replies", [])) is list, "response")
            for comment in [row, *row.get("replies", [])]:
                require(type(comment) is dict, "response")
                identity = uid(comment.get("uid"))
                require(
                    identity not in seen and (comment is row or not comment.get("replies")),
                    "response",
                )
                seen.add(identity)
                body = comment.get("body")
                require(type(body) is str, "response")
                # Deleted bodies remain empty tombstones; the exact response retains metadata.
                require(not comment.get("deleted_at") or not body, "response")
                result.append(body)
                require(len(result) <= 200, "limit")
        return result

    def step(self, cursor):
        plan = deepcopy(self.load(cursor))
        phase, selection = plan["phase"], self.selection
        item, original, done = None, None, False
        private_metadata = phase in {"profile", "verify_profile"}
        if private_metadata:
            raw, value = self.get("/profile")
            require(
                type(value) is dict
                and fingerprint(
                    [self.identity, self.credential.payload["endpoint"], uid(value.get("uid"))]
                )
                == self.connection.record(self.identity)["account_binding"],
                "account_mismatch",
            )
            time_zone = value.get("timezone")
            zone(time_zone)
            if phase == "profile":
                plan["time_zone"], plan["phase"] = time_zone, plan["after_profile"]
            else:
                require(plan["time_zone"] == time_zone, "time_zone")
                current = plan["current"]
                item = map_task(
                    current["value"],
                    comments=current["comments"],
                    hashes=current["hashes"],
                    time_zone=plan["time_zone"],
                    endpoint=self.credential.payload["endpoint"],
                )
                original = current["raw"].encode("utf-8")
                plan["seen"].append(item["remote_id"])
                plan["current"], plan["phase"] = None, "detail"
        elif phase == "validate_project":
            raw, value = self.get("/project/" + selection["uid"])
            require(type(value) is dict and uid(value.get("uid")) == selection["uid"], "selection")
            plan["phase"] = "roots"
        elif phase in {"roots", "verify_roots"}:
            params = {
                "type": "all",
                "status": "all",
                "limit": 25,
                "offset": plan["offset"],
                "order_by": "created_at:asc",
            }
            if selection["scope"] == "project":
                params["project_uid"] = selection["uid"]
            raw, value = self.get("/tasks?" + urlencode(params))
            require(
                type(value) is dict
                and type(value.get("tasks")) is list
                and len(value["tasks"]) <= 25,
                "response",
            )
            page = value.get("pagination")
            require(
                type(page) is dict
                and type(page.get("total")) is int
                and 0 <= page["total"] <= 5000
                and type(page.get("limit")) is int
                and type(page.get("offset")) is int
                and page.get("limit") == 25
                and page.get("offset") == plan["offset"]
                and type(page.get("hasMore")) is bool,
                "response",
            )
            if plan["total"] is None:
                plan["total"] = page["total"]
            require(page["total"] == plan["total"], "stale")
            target = "root_ids" if phase == "roots" else "verify_ids"
            ids = [uid(row.get("uid")) for row in value["tasks"] if type(row) is dict]
            require(
                len(ids) == len(value["tasks"])
                and len(set(ids)) == len(ids)
                and not set(ids).intersection(plan[target]),
                "cursor_loop",
            )
            plan[target].extend(ids)
            plan["offset"] += len(ids)
            require(
                page["hasMore"] == (plan["offset"] < plan["total"])
                and (bool(ids) or not page["hasMore"]),
                "response",
            )
            if phase == "roots":
                self.enqueue(plan, value["tasks"])
            if not page["hasMore"]:
                require(len(plan[target]) == plan["total"], "response")
                if phase == "verify_roots":
                    require(plan["root_ids"] == plan["verify_ids"], "stale")
                    done = True
                else:
                    plan["roots_complete"] = True
                    plan["phase"] = "detail"
        elif phase == "detail":
            require(plan["queue"], "integrity")
            selected = plan["queue"].pop(0)
            raw, value = self.get("/task/" + selected)
            require(type(value) is dict and uid(value.get("uid")) == selected, "response")
            if selection["scope"] == "project" and selected in plan["root_ids"]:
                require(
                    type(value.get("Project")) is dict
                    and value["Project"].get("uid") == selection["uid"],
                    "selection",
                )
            plan["current"] = {
                "value": value,
                "raw": raw.decode("utf-8"),
                "comments": [],
                "hashes": [hashlib.sha256(raw).hexdigest()],
            }
            plan["phase"] = "comments"
        elif phase == "comments":
            current = plan["current"]
            raw, value = self.get("/task/" + current["value"]["uid"] + "/comments")
            current["comments"] = self.comments(value)
            current["hashes"].append(hashlib.sha256(raw).hexdigest())
            plan["phase"] = "subtasks"
        elif phase == "subtasks":
            current = plan["current"]
            raw, value = self.get("/task/" + current["value"]["uid"] + "/subtasks")
            require(type(value) is list and len(value) <= 5000, "response")
            self.enqueue(plan, value)
            current["hashes"].append(hashlib.sha256(raw).hexdigest())
            plan["phase"] = "verify_task"
        elif phase == "verify_task":
            current = plan["current"]
            raw, value = self.get("/task/" + current["value"]["uid"])
            require(value == current["value"], "stale")
            current["hashes"].append(hashlib.sha256(raw).hexdigest())
            plan["phase"] = "verify_profile"
        else:
            require(False, "integrity")
        plan["responses"] += 1
        require(plan["responses"] <= 20000, "limit")
        if plan["phase"] == "detail" and not plan["queue"]:
            if selection["scope"] == "task":
                done = True
            else:
                plan["phase"], plan["offset"] = "verify_roots", 0
        digest = fingerprint(plan, maximum=2 * 1024 * 1024)
        self.last_response_size = len(raw)
        if not done:
            self.store._atomic_json(
                checked_path(self.store, f"{PLAN_ROOT}/{self.source_id}/plans/{digest}.json"), plan
            )
        return ReadPage(
            (item,) if item else (),
            originals=(original,) if item else (),
            # Account profile proves identity/zone, but unrelated profile settings
            # and possible provider secrets must never become task Originals.
            response=None if private_metadata else raw,
            next_cursor=None if done else digest,
            checkpoint=digest if done else None,
        )


def execute_tududi_job(store, job, *, connection=None, cancelled=lambda: False):
    connection = connection or TududiConnection(store)
    source_id = job["scope"]["id"]
    scheduled = job.get("reason") in {"scheduled", "coalesced", "catch_up"}
    adapter = TududiSteps(connection, source_id, scheduled=scheduled)
    generations, intake = ProductivityGenerations(store, source_id), ProductivityIntake(store)
    state = generations.prepare(adapter.binding, 1, allow_delta=False)
    counts, total = {"processed": 0, "skipped": 0, "errors": 0}, 0
    for _index in range(50):
        require(not cancelled(), "cancelled")
        page = adapter.step(state["page_token"])
        total += adapter.last_response_size
        require(total <= 8 * 1024 * 1024, "limit")
        preview = connection.host.page_preview(
            source_id,
            "task_read",
            page,
            expected_authority=adapter.authority["sha256"],
            scheduled=scheduled,
        )
        generations.check_page(state, preview)
        result = intake.import_page_locked(preview, cancelled=cancelled, recheck=adapter.recheck)
        counts["processed"] += sum(row["status"] == "imported" for row in result["results"])
        counts["skipped"] += sum(row["status"] == "unchanged" for row in result["results"])
        with connection.connectors.policy_commit_guard(purpose="tududi-page-checkpoint"):
            adapter.recheck()
            require(not cancelled(), "cancelled")
            state = generations.publish_page(state, preview, result)
        if state["status"] == "completed":
            break
    return {"progress": counts, "status": state["status"], "network_used": connection.network_used}


def reset_source(connection, source_id, *, expected_policy_revision, confirmed):
    require(confirmed is True, "consent_required")
    with (
        InstanceLifecycleManager(connection.store)._hold(purpose="tududi-reset"),
        connection.connectors.policy_commit_guard(purpose="tududi-reset"),
    ):
        identity, _source, definition = connection.host._records(source_id)
        require(definition["provider"] == "tududi", "unsupported")
        policy = connection.host.policy(source_id)
        require(policy is not None and policy["revision"] == expected_policy_revision, "stale")
        connection.store._atomic_json(
            checked_path(connection.store, f"{PLAN_ROOT}/{source_id}/reset.json"),
            {"epoch": __import__("uuid").uuid4().hex, "identity_id": identity["id"]},
        )
    return {"status": "reset"}
