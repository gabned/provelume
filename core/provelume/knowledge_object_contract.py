"""Pure Entitas record validation. References and hashes confer no write authority."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any

MAX_RECORD_BYTES = 256 * 1024
MAX_REFERENCES = 128
OBJECT_CANONICAL_KINDS = (
    "objects", "object-evidence", "object-revisions", "object-relations",
    "object-relation-revisions",
)
OBJECT_KINDS = frozenset({
    "entity", "claim", "decision", "project", "collection", "task", "outcome",
    "calendar_event", "commitment",
})
RELATION_TYPES = frozenset({
    "relates_to", "about", "supports", "contradicts", "depends_on", "part_of",
    "fulfills", "scheduled_for",
})
STATES = {
    "entity": {"active", "retired"},
    "claim": {"asserted", "disputed", "retracted"},
    "decision": {"proposed", "decided", "superseded", "retracted"},
    "project": {"active", "archived"},
    "collection": {"active", "archived"},
    "task": {"open", "in_progress", "completed", "cancelled"},
    "outcome": {"proposed", "achieved", "abandoned"},
    "calendar_event": {"tentative", "confirmed", "cancelled"},
    "commitment": {"open", "fulfilled", "cancelled"},
}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_OBJECT_ID = re.compile(r"(?:obj|project|collection)_[0-9a-f]{32}\Z")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
    r"(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)\Z"
)
_ZONE = re.compile(r"[A-Za-z_+-]{1,64}(?:/[A-Za-z0-9_+-]{1,64}){0,3}\Z")


class KnowledgeObjectError(ValueError):
    """Content-free errors suitable for redacted operator diagnostics."""

    def __init__(self, code: str = "invalid"):
        self.code = code
        super().__init__("knowledge_object_" + code)


def _require(condition: bool, code: str = "invalid") -> None:
    if not condition:
        raise KnowledgeObjectError(code)


def _closed(value: Any, fields: set[str]) -> None:
    _require(type(value) is dict and set(value) == fields)


def _text(value: Any, maximum: int = 16000, *, empty: bool = False) -> str:
    _require(type(value) is str and len(value) <= maximum)
    _require(empty or bool(value.strip()))
    _require(not any(unicodedata.category(c) in {"Cc", "Cs"} and c not in "\n\t" for c in value))
    return value


def _match(value: Any, pattern: re.Pattern) -> None:
    _require(type(value) is str and pattern.fullmatch(value) is not None)


def _id(value: Any, prefix: str, width: int = 32) -> None:
    _match(value, re.compile(re.escape(prefix) + r"_[0-9a-f]{" + str(width) + r"}\Z"))


def _timestamp(value: Any) -> datetime:
    _match(value, _TIMESTAMP)
    _require(not value.endswith("-00:00"))  # RFC 3339 unknown local offset is not an instant.
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(parsed.utcoffset() is not None)
        return parsed
    except (ValueError, OverflowError):
        raise KnowledgeObjectError() from None


def canonical_bytes(value: Any) -> bytes:
    """Bound traversal before serialization; reject cycles, floats and foreign values."""
    pending = [(value, 0)]
    nodes = 0
    text_units = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(depth <= 12 and nodes <= 8192, "limit")
        if type(item) is dict:
            _require(len(item) <= 128 and all(type(k) is str for k in item), "limit")
            text_units += sum(len(k) for k in item)
            pending.extend((v, depth + 1) for v in item.values())
        elif type(item) is list:
            _require(len(item) <= MAX_REFERENCES, "limit")
            pending.extend((v, depth + 1) for v in item)
        elif type(item) is str:
            text_units += len(item)
            _text(item, MAX_RECORD_BYTES, empty=True)
        elif type(item) is int:
            _require(-(2**63) <= item < 2**63, "limit")
        else:
            _require(item is None or type(item) is bool)
        _require(text_units <= MAX_RECORD_BYTES, "limit")
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise KnowledgeObjectError() from None
    _require(len(raw) <= MAX_RECORD_BYTES, "limit")
    return raw


def record_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def parse_record(raw: bytes) -> dict:
    _require(type(raw) is bytes and len(raw) <= MAX_RECORD_BYTES, "limit")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result)
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise KnowledgeObjectError() from None
    _require(type(value) is dict)
    canonical_bytes(value)
    return value


def _revision(value: dict) -> None:
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _require(type(value["revision"]) is int and 1 <= value["revision"] <= 2**31 - 1)
    _id(value["instance_id"], "inst")
    if value["revision"] == 1:
        _require(value["previous_sha256"] is None)
    else:
        _match(value["previous_sha256"], _HASH)
    _require(_timestamp(value["created_at"]) <= _timestamp(value["updated_at"]))


def _references(values: Any) -> None:
    _require(type(values) is list and len(values) <= MAX_REFERENCES)
    for value in values:
        _id(value, "evd", 64)
    _require(len(set(values)) == len(values))


def validate_evidence(value: Any) -> dict:
    """Validate attribution syntax; services must independently resolve source bytes."""
    canonical_bytes(value)
    _closed(value, {"schema_version", "id", "instance_id", "document_id", "version_id",
                    "original_id", "original_sha256", "selector"})
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    for field, prefix in (("instance_id", "inst"), ("document_id", "doc"), ("version_id", "ver")):
        _id(value[field], prefix)
    _match(value["original_sha256"], _HASH)
    _require(value["original_id"] == "sha256_" + value["original_sha256"])
    selector = value["selector"]
    _require(type(selector) is dict)
    if selector.get("kind") == "original":
        _closed(selector, {"kind"})
    else:
        _closed(selector, {"kind", "representation_id", "output_id", "anchor_id", "quote_sha256"})
        _require(selector["kind"] == "text")
        for key, prefix in (("representation_id", "repr"), ("output_id", "rout"),
                            ("anchor_id", "ranc")):
            _id(selector[key], prefix, 64)
        _match(selector["quote_sha256"], _HASH)
    _require(value["id"] == "evd_" + record_digest({k: v for k, v in value.items() if k != "id"}))
    return value


def _body(kind: str, body: Any) -> None:
    fields = {"description"}
    if kind == "claim":
        fields = {"statement"}
    elif kind == "decision":
        fields = {"rationale"}
    elif kind in {"task", "commitment"}:
        fields.add("due_at")
    elif kind == "calendar_event":
        fields |= {"starts_at", "ends_at", "time_zone"}
    _closed(body, fields)
    for field in fields - {"due_at", "starts_at", "ends_at", "time_zone"}:
        _text(body[field], empty=kind not in {"claim", "decision"})
    if "due_at" in fields and body["due_at"] is not None:
        _timestamp(body["due_at"])
    if kind == "calendar_event":
        _require(_timestamp(body["starts_at"]) < _timestamp(body["ends_at"]))
        _match(body["time_zone"], _ZONE)


def validate_object(value: Any) -> dict:
    canonical_bytes(value)
    _closed(value, {"schema_version", "id", "instance_id", "kind", "revision", "previous_sha256",
                    "title", "aliases", "state", "body", "evidence_ids", "origin",
                    "created_at", "updated_at"})
    _revision(value)
    kind = value["kind"]
    _require(type(kind) is str and kind in OBJECT_KINDS)
    _match(value["id"], _OBJECT_ID)
    prefix = kind if kind in {"project", "collection"} else "obj"
    _require(value["id"].startswith(prefix + "_"))
    _require(type(value["state"]) is str and value["state"] in STATES[kind])
    _text(value["title"], 240)
    aliases = value["aliases"]
    _require(type(aliases) is list and len(aliases) <= 32)
    normalized = []
    for alias in aliases:
        normalized.append(unicodedata.normalize("NFC", _text(alias, 240).strip()).casefold())
    _require(len(set(normalized)) == len(normalized))
    _body(kind, value["body"])
    _references(value["evidence_ids"])
    _require(kind != "claim" or bool(value["evidence_ids"]))
    origin = value["origin"]
    _closed(origin, {"kind", "proposal_id"})
    _require(type(origin["kind"]) is str and origin["kind"] in {"manual", "reviewed_proposal"})
    if origin["kind"] == "manual":
        _require(origin["proposal_id"] is None)
    else:
        _id(origin["proposal_id"], "objprop", 64)
    return value


def validate_object_reference(value: Any) -> dict:
    _closed(value, {"id", "revision", "sha256"})
    _match(value["id"], _OBJECT_ID)
    _require(type(value["revision"]) is int and 1 <= value["revision"] <= 2**31 - 1)
    _match(value["sha256"], _HASH)
    return value


def validate_relation(value: Any) -> dict:
    canonical_bytes(value)
    _closed(value, {"schema_version", "id", "instance_id", "revision", "previous_sha256",
                    "relation_type", "source", "target", "state", "evidence_ids",
                    "created_at", "updated_at"})
    _revision(value)
    _id(value["id"], "rel")
    _require(type(value["relation_type"]) is str and value["relation_type"] in RELATION_TYPES)
    _require(type(value["state"]) is str and value["state"] in {"active", "retracted"})
    source = validate_object_reference(value["source"])
    target = validate_object_reference(value["target"])
    _require(source["id"] != target["id"])
    _references(value["evidence_ids"])
    return value


def validate_successor(previous: Any, current: Any, *, relation: bool = False) -> None:
    """Check immutable chain coordinates, without changing a record or granting review."""
    validator = validate_relation if relation else validate_object
    validator(previous)
    validator(current)
    keys = {"id", "instance_id", "created_at"} | (set() if relation else {"kind"})
    _require(all(previous[k] == current[k] for k in keys), "conflict")
    _require(current["revision"] == previous["revision"] + 1, "conflict")
    _require(current["previous_sha256"] == record_digest(previous), "conflict")
    _require(_timestamp(previous["updated_at"]) <= _timestamp(current["updated_at"]), "conflict")
