"""Reviewed public Tududi 2.1.0 read shapes, dates and unsupported cases."""

import json
import re
from datetime import UTC, datetime
from importlib.resources import files
from zoneinfo import ZoneInfo

import tzdata.zoneinfo as shipped_zones

from .productivity_contract import ProductivityError, fingerprint, require, text, validate_item

VERSION = "2.1.0"
PUBLIC_COMMIT = "e03bc361bc7fa49a475fca9952b345822d1d5f11"
KEY = "concordia-tududi-readonly"


def uid(value):
    require(
        type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None, "response"
    )
    return value


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "response")
            result[key] = value
        return result

    try:
        result = json.loads(raw, object_pairs_hook=unique)
        require(type(result) in {dict, list}, "response")
        fingerprint(result, maximum=2 * 1024 * 1024)
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise ProductivityError("response") from None


def zone(name):
    text(name, 100)
    require(
        re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name)
        and all(part not in {".", ".."} for part in name.split("/")),
        "time_zone",
    )
    try:
        with files(shipped_zones).joinpath(*name.split("/")).open("rb") as stream:
            return ZoneInfo.from_file(stream, key=name)
    except (OSError, ValueError):
        raise ProductivityError("time_zone") from None


def due(value, time_zone):
    day, clock, timed = value.get("due_date"), value.get("due_time"), value.get("due_has_time")
    if day is None:
        require(clock is None, "response")
        return None
    text(day, 10)
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is not None, "response")
    require(type(timed) is bool, "response")
    if not timed:
        require(clock is None, "response")
        return {"kind": "date", "value": day, "time_zone": None}
    require(type(clock) is str and re.fullmatch(r"\d{2}:\d{2}", clock) is not None, "response")
    local = datetime.fromisoformat(day + "T" + clock)
    selected = zone(time_zone)
    first, second = local.replace(tzinfo=selected, fold=0), local.replace(tzinfo=selected, fold=1)
    # The API serializes only a local day/clock: an ambiguous fold cannot be guessed.
    require(
        first.utcoffset() == second.utcoffset()
        and first.astimezone(UTC).astimezone(selected).replace(tzinfo=None) == local,
        "time_zone",
    )
    return {"kind": "instant", "value": first.isoformat(), "time_zone": time_zone}


def map_task(value, *, comments, hashes, time_zone, endpoint):
    require(
        type(value) is dict and type(value.get("status")) is int and 0 <= value["status"] <= 6,
        "response",
    )
    statuses = ("not_started", "in_progress", "done", "archived", "waiting", "cancelled", "planned")
    status = statuses[value["status"]]
    project, parent, assignee = (
        value.get("Project"),
        value.get("parent_task"),
        value.get("AssignedTo"),
    )
    require(
        all(row is None or type(row) is dict for row in (project, parent, assignee)), "response"
    )
    assigned = value.get("assigned_to")
    if assignee is not None:
        require(uid(assignee.get("uid")) == assigned, "response")
    context = {
        "status": status,
        "start_date": value.get("start_date"),
        "start_time": value.get("start_time"),
        "time_zone": time_zone,
    }
    for key in ("start_date", "start_time"):
        if context[key] is not None:
            text(context[key], 80)
    recurrence = {
        key: val
        for key, val in value.items()
        if key.startswith("recurrence_") or key in {"completion_based", "recurring_parent_uid"}
    }
    revision = value.get("updated_at")
    text(revision, 100)
    result = {
        "remote_id": uid(value.get("uid")),
        "revision": revision,
        "revision_kind": "version",
        "kind": "task",
        "title": value.get("original_name") or value.get("name"),
        "description": value.get("note") or "",
        "state": "completed"
        if status == "done" or (status == "archived" and value.get("completed_at"))
        else "in_progress"
        if status == "in_progress"
        else "cancelled"
        if status == "cancelled"
        else "open",
        "due": due(value, time_zone),
        "starts": None,
        "ends": None,
        "provenance": {
            "container_ids": [uid(project["uid"])] if project else [],
            "parent_id": uid(parent["uid"]) if parent else None,
            "assignees": [uid(assigned)] if assigned else [],
            "links": [endpoint + "/task/" + uid(value["uid"])],
            "comments": comments,
            "uid": None,
            "recurrence_id": None,
            "recurrence": [json.dumps(recurrence, sort_keys=True)] if recurrence else [],
            "response_sha256": hashes,
            "task_context": context,
            "display_names": {
                "containers": {project["uid"]: project["name"]} if project else {},
                "assignees": {assignee["uid"]: assignee["name"]} if assignee else {},
                "parent": parent.get("name") if parent else None,
            },
        },
    }
    return validate_item(result)
