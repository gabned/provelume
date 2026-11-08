"""Read-consented connector snapshots in Entitas; never a forged manual edit."""

from __future__ import annotations

from datetime import datetime
from importlib.resources import files
from zoneinfo import ZoneInfo

import tzdata.zoneinfo as shipped_zones

from .knowledge_object_contract import record_digest, validate_object
from .knowledge_object_services import KnowledgeObjectServices
from .knowledge_object_store import persist_object_locked
from .productivity_connectors import ROOT
from .productivity_contract import fingerprint, require, validate_item
from .productivity_intake import _identifier
from .review_decisions import read_json
from .storage import utc_now


def project_connector_object(store, source_id, document_id, version_id, item):
    """Caller owns lifecycle + Source policy guards and exact read authority."""
    validate_item(item)
    services = KnowledgeObjectServices(store)
    evidence = services.evidence_for_version(version_id)
    identity = _identifier("obj", "productivity:" + source_id + ":" + item["remote_id"])
    previous = store.read_canonical("objects", identity)
    origin = {
        "kind": "connector",
        "proposal_id": None,
        "source_id": source_id,
        "document_id": document_id,
        "remote_id_sha256": fingerprint(item["remote_id"]),
    }
    require(previous is None or previous["origin"] == origin, "integrity")
    description = item["description"]
    body = {"description": description if len(description) <= 16000 else ""}
    if len(description) > 16000:
        body["description_from_source"] = True
    if item["kind"] == "task":
        due = item["due"]
        body.update(
            due_at=due["value"] if due and due["kind"] == "instant" else None,
            due_date=due["value"] if due and due["kind"] == "date" else None,
        )
    elif item["starts"] is None or item["starts"]["kind"] == "date":
        body.update(
            starts_at=None,
            ends_at=None,
            time_zone=None,
            starts_on=item["starts"]["value"] if item["starts"] else None,
            ends_on=item["ends"]["value"] if item["ends"] else None,
        )
    else:
        zone = item["starts"]["time_zone"]
        with files(shipped_zones).joinpath(*zone.split("/")).open("rb") as stream:
            time_zone = ZoneInfo.from_file(stream, key=zone)
        body.update(
            time_zone=zone,
            starts_at=datetime.fromisoformat(item["starts"]["value"].replace("Z", "+00:00"))
            .astimezone(time_zone)
            .isoformat(),
            ends_at=datetime.fromisoformat(item["ends"]["value"].replace("Z", "+00:00"))
            .astimezone(time_zone)
            .isoformat(),
        )
    selected = {
        "title": item["title"] or "Calendar event",
        "state": item["state"],
        "body": body,
        "evidence_ids": [evidence["id"]],
    }
    if previous and all(previous[key] == value for key, value in selected.items()):
        return False
    stamp = utc_now()
    value = {
        "schema_version": 1,
        "id": identity,
        "instance_id": store.read_config()["instance"]["id"],
        "kind": item["kind"],
        "revision": previous["revision"] + 1 if previous else 1,
        "previous_sha256": record_digest(previous) if previous else None,
        "aliases": [],
        "origin": origin,
        "created_at": previous["created_at"] if previous else stamp,
        "updated_at": stamp,
        **selected,
    }
    validate_object(value)
    persist_object_locked(
        store,
        value,
        expected_sha256=record_digest(previous) if previous else None,
        evidence=[evidence],
    )
    return True


def connector_object_snapshot(store, value):
    """Resolve the exact attributed snapshot, including a long description, offline."""
    origin = value["origin"]
    evidence = store.read_canonical("object-evidence", value["evidence_ids"][0])
    require(evidence is not None and evidence["document_id"] == origin["document_id"], "integrity")
    record = read_json(
        store,
        f"{ROOT}/{origin['source_id']}/observations/"
        f"{origin['document_id']}/{evidence['version_id']}.json",
    )
    require(
        record is not None
        and record["item_sha256"] == fingerprint(record["item"])
        and record["original_sha256"] == evidence["original_sha256"]
        and fingerprint(record["item"]["remote_id"]) == origin["remote_id_sha256"],
        "integrity",
    )
    validate_item(record["item"])
    checkpoint = read_json(store, f"{ROOT}/{origin['source_id']}/sync.json")
    current = False
    if checkpoint and checkpoint.get("schema") == "productivity-generation/v1":
        from .productivity_generations import ProductivityGenerations

        current = ProductivityGenerations(store, origin["source_id"]).contains(
            origin["document_id"], evidence["version_id"]
        )
    elif checkpoint:
        current = (
            checkpoint.get("active_versions", {}).get(origin["document_id"])
            == evidence["version_id"]
        )
    return {"item": record["item"], "current": current, "source_id": origin["source_id"]}
