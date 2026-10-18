"""Explicit manual object/Relation services; no API, UI, AI or proposal authority."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from importlib.resources import files
from uuid import uuid4
from zoneinfo import ZoneInfo

import tzdata.zoneinfo as shipped_zones

from .instance_lifecycle import InstanceLifecycleManager
from .knowledge_object_contract import (
    MAX_REFERENCES,
    OBJECT_KINDS,
    KnowledgeObjectError,
    canonical_bytes,
    record_digest,
    validate_evidence,
    validate_object,
    validate_object_reference,
    validate_relation,
    validate_successor,
)
from .knowledge_object_evidence import (
    ObjectEvidenceResolver,
    current_instance_id,
    object_path,
    require,
)
from .knowledge_object_store import (
    MAX_OBJECT_RECORDS,
    persist_object_locked,
    revision_record,
)
from .representations import canonical_json_bytes
from .storage import utc_now

MAX_HISTORY_BYTES = 8 * 1024 * 1024
MAX_HISTORY_REVISIONS = 1024
_OBJECT = re.compile(r"(?:obj|project|collection)_[0-9a-f]{32}\Z")
_RELATION = re.compile(r"rel_[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OBJECT_CHANGES = {"title", "aliases", "state", "body", "evidence_ids"}
_RELATION_CHANGES = {"relation_type", "source", "target", "state", "evidence_ids"}
_WITHDRAWN = {"retired", "retracted", "superseded", "cancelled", "abandoned", "archived"}


def _calendar(value):
    if value["kind"] != "calendar_event":
        return
    try:
        name = value["body"]["time_zone"]
        # The shipped tzdata dependency is the portable authority, not the host TZ.
        with files(shipped_zones).joinpath(*name.split("/")).open("rb") as stream:
            zone = ZoneInfo.from_file(stream, key=name)
        for field in ("starts_at", "ends_at"):
            instant = datetime.fromisoformat(value["body"][field].replace("Z", "+00:00"))
            require(instant.astimezone(zone).utcoffset() == instant.utcoffset(), "time_zone")
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        raise KnowledgeObjectError("time_zone") from None


class KnowledgeObjectServices:
    """Trusted local host seam. Consent is per-call confirmation, never a saved grant."""

    def __init__(self, store):
        self.store = store

    def _identity(self, identity, relation=False):
        require(
            type(identity) is str and (_RELATION if relation else _OBJECT).fullmatch(identity),
            "invalid",
        )

    def _head(self, identity, relation=False):
        self._identity(identity, relation)
        instance_id = current_instance_id(self.store)
        value = self._read("object-relations" if relation else "objects", identity)
        if value is None:
            return None
        (validate_relation if relation else validate_object)(value)
        require(
            value["id"] == identity and value["instance_id"] == instance_id,
            "integrity",
        )
        return value

    def _read(self, kind, identity):
        try:
            object_path(self.store, f"knowledge/{kind}/{identity}.json")
            value = self.store.read_canonical(kind, identity)
            require(
                value is None or (type(value) is dict and value.get("id") == identity),
                "integrity",
            )
            return value
        except KnowledgeObjectError:
            raise
        except (OSError, ValueError):
            raise KnowledgeObjectError("integrity") from None

    def _history(self, value, relation=False):
        result, total, current = [], 0, value
        kind = "object-relation-revisions" if relation else "object-revisions"
        while True:
            require(len(result) < MAX_HISTORY_REVISIONS, "limit")
            wrapper = revision_record(current, relation=relation)
            retained = self._read(kind, wrapper["id"])
            require(
                type(retained) is dict
                and set(retained) == {"schema_version", "id", "record"}
                and type(retained["schema_version"]) is int
                and retained["schema_version"] == 1,
                "integrity",
            )
            require(
                retained == revision_record(retained["record"], relation=relation)
                and retained == wrapper,
                "integrity",
            )
            total += len(canonical_json_bytes(retained))
            require(total <= MAX_HISTORY_BYTES, "limit")
            result.append(deepcopy(current))
            if current["revision"] == 1:
                break
            previous = self._read(
                kind, ("relrev_" if relation else "objrev_") + current["previous_sha256"]
            )
            require(type(previous) is dict and "record" in previous, "integrity")
            validate_successor(previous["record"], current, relation=relation)
            current = previous["record"]
        return list(reversed(result)), total

    def _view(self, value, relation=False):
        resolver = ObjectEvidenceResolver(self.store)
        evidence = []
        for identity in value["evidence_ids"]:
            row = self._read("object-evidence", identity)
            evidence.append(
                resolver.status(row)
                if row is not None
                else {
                    "id": identity,
                    "status": "UNAVAILABLE",
                    "reason": "evidence_unavailable",
                    "truth": "NOT_VERIFIED",
                }
            )
        result = {
            "record": deepcopy(value),
            "sha256": record_digest(value),
            "evidence": evidence,
            "truth": "NOT_VERIFIED",
            "network_used": False,
            "mutated": False,
        }
        if relation:
            result["endpoints"] = []
            for ref in (value["source"], value["target"]):
                head = self._head(ref["id"])
                result["endpoints"].append(
                    {
                        "reference": deepcopy(ref),
                        "current": head is not None
                        and head["revision"] == ref["revision"]
                        and record_digest(head) == ref["sha256"],
                    }
                )
        return result

    def get(self, identity, *, relation=False):
        value = self._head(identity, relation)
        if value is None:
            return None
        self._history(value, relation)
        return self._view(value, relation)

    def history(self, identity, *, relation=False):
        value = self._head(identity, relation)
        require(value is not None, "not_found")
        return self._history(value, relation)[0]

    def list(self, *, relation=False, limit=50, after=None):
        require(type(limit) is int and 1 <= limit <= 100, "limit")
        current_instance_id(self.store)
        if after is not None:
            self._identity(after, relation)
        kind = "object-relations" if relation else "objects"
        directory = object_path(self.store, "knowledge/" + kind)
        names = []
        if directory.exists():
            for path in directory.iterdir():
                require(len(names) < MAX_OBJECT_RECORDS and path.suffix == ".json", "limit")
                self._identity(path.stem, relation)
                require(
                    path.is_file() and not path.is_symlink() and not path.is_junction(), "integrity"
                )
                names.append(path.stem)
        selected = sorted(n for n in names if after is None or n > after)
        items = []
        for identity in selected[:limit]:
            value = self._head(identity, relation)
            require(value is not None, "conflict")
            items.append(
                {
                    "id": identity,
                    "kind": "relation" if relation else value["kind"],
                    "title": None if relation else value["title"],
                    "state": value["state"],
                    "revision": value["revision"],
                    "sha256": record_digest(value),
                    "history": "NOT_CHECKED",
                    "truth": "NOT_VERIFIED",
                }
            )
        return {
            "items": items,
            "next": items[-1]["id"] if len(selected) > limit else None,
            "network_used": False,
            "mutated": False,
        }

    def evidence_for_version(self, version_id, *, selector=None):
        return ObjectEvidenceResolver(self.store).for_version(version_id, selector=selector)

    @staticmethod
    def _authority(consent):
        require(consent is True, "denied")

    def _evidence(self, value, provided, *, withdrawn=False):
        require(type(provided) in (list, tuple) and len(provided) <= MAX_REFERENCES, "limit")
        resolver, selected, new = ObjectEvidenceResolver(self.store), set(), []
        for row in provided:
            validate_evidence(row)
            require(row["id"] not in selected and row["id"] in value["evidence_ids"], "invalid")
            selected.add(row["id"])
            retained = self._read("object-evidence", row["id"])
            require(retained is None or retained == row, "integrity")
            if retained is None:
                new.append(deepcopy(row))
        incoming = {row["id"]: row for row in provided}
        for identity in value["evidence_ids"]:
            row = incoming.get(identity) or self._read("object-evidence", identity)
            require(row is not None, "evidence_unavailable")
            if withdrawn and identity not in incoming:
                # Withdrawal preserves attribution without certifying a missing source.
                validate_evidence(row)
            else:
                resolver.resolve(row)
        return new

    @staticmethod
    def _inputs(value, evidence):
        require(type(evidence) in (list, tuple) and len(evidence) <= MAX_REFERENCES, "limit")
        canonical_bytes({"value": value, "evidence": list(evidence)})
        for row in evidence:
            validate_evidence(row)

    def create(
        self, kind, title, body, *, state=None, aliases=(), evidence=(), consent=False,
        expected_instance_id=None,
    ):
        self._authority(consent)
        require(type(kind) is str and kind in OBJECT_KINDS, "invalid")
        require(kind not in {"project", "collection"}, "hierarchy_authority")
        require(type(aliases) in (list, tuple) and type(evidence) in (list, tuple), "invalid")
        self._inputs(
            {"title": title, "body": body, "state": state, "aliases": list(aliases)}, evidence
        )
        defaults = {
            "entity": "active",
            "claim": "asserted",
            "decision": "proposed",
            "task": "open",
            "outcome": "proposed",
            "calendar_event": "tentative",
            "commitment": "open",
        }
        now = utc_now()
        value = {
            "schema_version": 1,
            "id": "obj_" + uuid4().hex,
            "instance_id": current_instance_id(self.store),
            "kind": kind,
            "revision": 1,
            "previous_sha256": None,
            "title": title,
            "aliases": list(aliases),
            "state": defaults[kind] if state is None else state,
            "body": deepcopy(body),
            "evidence_ids": [row["id"] for row in evidence],
            "origin": {"kind": "manual", "proposal_id": None},
            "created_at": now,
            "updated_at": now,
        }
        return self._write(value, None, evidence, expected_instance_id=expected_instance_id)

    def update(
        self, identity, changes, *, expected_sha256, evidence=(), consent=False, relation=False,
        expected_instance_id=None,
    ):
        self._authority(consent)
        self._identity(identity, relation)
        require(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256), "conflict")
        allowed = _RELATION_CHANGES if relation else _OBJECT_CHANGES
        require(type(changes) is dict and changes and set(changes) <= allowed, "invalid")
        self._inputs(changes, evidence)
        current_instance_id(self.store)
        with InstanceLifecycleManager(self.store)._hold(purpose="manual-object-update"):
            previous = self._head(identity, relation)
            require(previous is not None, "not_found")
            require(record_digest(previous) == expected_sha256, "conflict")
            _history, history_bytes = self._history(previous, relation)
            if not relation and previous["kind"] in {"project", "collection"}:
                require(
                    changes.get("title", previous["title"]) == previous["title"],
                    "hierarchy_authority",
                )
            value = {
                **deepcopy(previous),
                **deepcopy(changes),
                "revision": previous["revision"] + 1,
                "previous_sha256": expected_sha256,
                "updated_at": utc_now(),
            }
            if not relation:
                value["origin"] = {"kind": "manual", "proposal_id": None}
            withdrawn = (
                set(changes) == {"state"}
                and type(changes["state"]) is str
                and changes["state"] in ({"retracted"} if relation else _WITHDRAWN)
            )
            return self._write_locked(
                value,
                expected_sha256,
                evidence,
                relation=relation,
                withdrawn=withdrawn,
                history_bytes=history_bytes,
                expected_instance_id=expected_instance_id,
            )

    def create_relation(
        self, relation_type, source, target, *, evidence=(), consent=False,
        expected_instance_id=None,
    ):
        self._authority(consent)
        validate_object_reference(source)
        validate_object_reference(target)
        require(type(evidence) in (list, tuple), "invalid")
        self._inputs({"relation_type": relation_type, "source": source, "target": target}, evidence)
        now = utc_now()
        value = {
            "schema_version": 1,
            "id": "rel_" + uuid4().hex,
            "instance_id": current_instance_id(self.store),
            "revision": 1,
            "previous_sha256": None,
            "relation_type": relation_type,
            "source": deepcopy(source),
            "target": deepcopy(target),
            "state": "active",
            "evidence_ids": [row["id"] for row in evidence],
            "created_at": now,
            "updated_at": now,
        }
        return self._write(
            value, None, evidence, relation=True, expected_instance_id=expected_instance_id,
        )

    def _write(self, value, expected, evidence, *, relation=False, expected_instance_id=None):
        with InstanceLifecycleManager(self.store)._hold(purpose="manual-object-create"):
            return self._write_locked(
                value, expected, evidence, relation=relation,
                expected_instance_id=expected_instance_id,
            )

    def _write_locked(
        self, value, expected, evidence, *, relation=False, withdrawn=False, history_bytes=0,
        expected_instance_id=None,
    ):
        require(
            expected_instance_id is None or expected_instance_id == current_instance_id(self.store),
            "conflict",
        )
        (validate_relation if relation else validate_object)(value)
        require(value["revision"] <= MAX_HISTORY_REVISIONS, "limit")
        require(
            history_bytes + len(canonical_json_bytes(revision_record(value, relation=relation)))
            <= MAX_HISTORY_BYTES,
            "limit",
        )
        if not relation:
            require(value["origin"] == {"kind": "manual", "proposal_id": None}, "denied")
            _calendar(value)
        new = self._evidence(value, evidence, withdrawn=withdrawn)
        persist_object_locked(
            self.store, value, expected_sha256=expected, evidence=new, relation=relation
        )
        return {**self._view(value, relation), "mutated": True}
