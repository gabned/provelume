"""Canonical Entitas storage and integrity; no application/review authority."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .atomic_commit import (
    AtomicCommitLimits,
    AtomicCommitProfile,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    recover_atomic_transactions,
)
from .knowledge_object_contract import (
    MAX_RECORD_BYTES,
    MAX_REFERENCES,
    OBJECT_CANONICAL_KINDS,
    KnowledgeObjectError,
    record_digest,
    validate_evidence,
    validate_object,
    validate_relation,
    validate_successor,
)
from .paths import native_path

MAX_STORED_REVISION_BYTES = MAX_RECORD_BYTES + 2048
MAX_OBJECT_RECORDS = 100_000
OBJECT_TRANSACTION_PROFILE = AtomicCommitProfile(
    key="knowledge-object",
    kind="knowledge-object.canonical",
    owner_id_pattern=r"objop_[0-9a-f]{32}\Z",
    limits=AtomicCommitLimits(
        max_entries=257,
        max_entry_bytes=MAX_STORED_REVISION_BYTES,
        max_candidate_bytes=8 * 1024 * 1024,
        max_preimage_bytes=2 * 1024 * 1024,
        max_journal_payload_bytes=10 * 1024 * 1024,
    ),
)


def _require(value, code="integrity"):
    if not value:
        raise KnowledgeObjectError(code)


def _bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def load_object_file(path: Path, kind: str) -> dict:
    """Bound original JSON bytes and reject duplicate keys before validation."""
    limit = MAX_STORED_REVISION_BYTES if kind.endswith("revisions") else MAX_RECORD_BYTES + 1
    with native_path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    _require(len(raw) <= limit, "limit")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result)
            result[key] = value
        return result

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise KnowledgeObjectError() from None
    _require(type(result) is dict)
    return result


def revision_record(record: dict, *, relation: bool = False) -> dict:
    (validate_relation if relation else validate_object)(record)
    return {
        "schema_version": 1,
        "id": ("relrev_" if relation else "objrev_") + record_digest(record),
        "record": deepcopy(record),
    }


def hierarchy_object(node: dict, instance_id: str, previous: dict | None = None) -> dict:
    """The existing hierarchy remains authoritative for identity/name/parent."""
    _require(node.get("kind") in {"project", "collection"})
    if previous is None:
        result = {
            "schema_version": 1,
            "id": node["id"],
            "instance_id": instance_id,
            "kind": node["kind"],
            "revision": 1,
            "previous_sha256": None,
            "title": node["name"],
            "aliases": [],
            "state": "active",
            "body": {"description": ""},
            "evidence_ids": [],
            "origin": {"kind": "manual", "proposal_id": None},
            "created_at": node["created_at"],
            "updated_at": node["updated_at"],
        }
    else:
        result = deepcopy(previous)
        result.update(
            title=node["name"],
            revision=previous["revision"] + 1,
            previous_sha256=record_digest(previous),
            updated_at=node["updated_at"],
        )
        validate_successor(previous, result)
    validate_object(result)
    return result


def promote_hierarchy(store) -> list[str]:
    """Only used inside an unpublished, verified migration stage."""
    instance_id = store.read_config()["instance"]["id"]
    promoted = []
    for node in store.list_canonical("hierarchy"):
        if node["kind"] not in {"project", "collection"}:
            continue
        value = hierarchy_object(node, instance_id)
        store._atomic_json(store.paths.canonical_dir("objects") / f"{value['id']}.json", value)
        wrapper = revision_record(value)
        store._atomic_json(
            store.paths.canonical_dir("object-revisions") / f"{wrapper['id']}.json", wrapper
        )
        promoted.append(value["id"])
    return sorted(promoted)


def _control_root(store):
    from .instance_lifecycle import InstanceLifecycleManager

    return InstanceLifecycleManager(store).control_root


def object_recovery_handler():
    return AtomicRecoveryHandler(profile=OBJECT_TRANSACTION_PROFILE)


def recover_objects_locked(store):
    return recover_atomic_transactions(
        store, _control_root(store), handlers=(object_recovery_handler(),)
    )


def _commit_locked(store, entries):
    commit = AtomicInstanceCommit(
        store,
        _control_root(store) / "transactions",
        profile=OBJECT_TRANSACTION_PROFILE,
        owner_id="objop_" + uuid4().hex,
    )
    for kind, value, immutable in entries:
        commit.add(f"knowledge/{kind}/{value['id']}.json", _bytes(value), immutable=immutable)
    commit.commit()


def write_hierarchy_object_locked(store, node):
    from .domain import as_record

    value = as_record(node)
    previous = store.read_canonical("objects", value["id"])
    _require(previous is not None or store.read_canonical("hierarchy", value["id"]) is None)
    obj = hierarchy_object(value, store.read_config()["instance"]["id"], previous)
    entries = [
        ("hierarchy", value, False),
        ("objects", obj, False),
        ("object-revisions", revision_record(obj), True),
    ]
    _validate_proposed(store, entries)
    _commit_locked(store, entries)


def _validate_proposed(store, entries):
    records = {
        k: {v["id"]: v for v in store.list_canonical(k)}
        for k in (*OBJECT_CANONICAL_KINDS, "hierarchy", "documents", "versions", "originals")
    }
    for selected, row, _immutable in entries:
        records[selected][row["id"]] = row
    errors, warnings = [], []
    object_findings(store, records, errors, warnings)
    _require(not errors)


def persist_object_locked(store, value, *, expected_sha256, evidence=(), relation=False):
    """Internal primitive; callers own consent, permissions, selector resolution and the lock."""
    _require(store.read_config().get("schema_version") == 3, "schema")
    (validate_relation if relation else validate_object)(value)
    _require(value["instance_id"] == store.read_config()["instance"]["id"])
    kind = "object-relations" if relation else "objects"
    previous = store.read_canonical(kind, value["id"])
    if previous is None:
        _require(expected_sha256 is None and value["revision"] == 1, "conflict")
    else:
        _require(expected_sha256 == record_digest(previous), "conflict")
        validate_successor(previous, value, relation=relation)
    # Hierarchy-defined fields have one writer, through the existing hierarchy API.
    if not relation and value["kind"] in {"project", "collection"}:
        node = store.read_canonical("hierarchy", value["id"])
        _require(
            node is not None
            and node["name"] == value["title"]
            and node["created_at"] == value["created_at"]
        )
    if relation:
        for ref in (value["source"], value["target"]):
            head = store.read_canonical("objects", ref["id"])
            _require(
                head is not None
                and head["revision"] == ref["revision"]
                and record_digest(head) == ref["sha256"],
                "conflict",
            )
    entries = []
    for index, ev in enumerate(evidence):
        _require(index < MAX_REFERENCES, "limit")
        validate_evidence(ev)
        _require(ev["instance_id"] == value["instance_id"])
        version = store.read_canonical("versions", ev["version_id"])
        original = store.read_canonical("originals", ev["original_id"])
        _require(
            version is not None
            and original is not None
            and store.read_canonical("documents", ev["document_id"]) is not None
        )
        _require(
            version["document_id"] == ev["document_id"]
            and version["original_id"] == ev["original_id"]
            and version["content_hash"] == ev["original_sha256"]
            and original["sha256"] == ev["original_sha256"]
        )
        from .instance_backup import _file_identity
        from .paths import safe_instance_path

        _require(
            _file_identity(safe_instance_path(store.paths.root, original["storage_ref"]))
            == (original["size_bytes"], ev["original_sha256"])
        )
        entries.append(("object-evidence", ev, True))
    revision_kind = "object-relation-revisions" if relation else "object-revisions"
    entries.extend(
        [(kind, value, False), (revision_kind, revision_record(value, relation=relation), True)]
    )
    # Check closure against the complete proposed canonical view before journalling.
    _validate_proposed(store, entries)
    _commit_locked(store, entries)


def _chain(heads, revisions, *, relation, instance_id):
    validator = validate_relation if relation else validate_object
    indexed = {}
    for key, wrapper in revisions.items():
        _require(
            set(wrapper) == {"schema_version", "id", "record"}
            and type(wrapper["schema_version"]) is int
            and wrapper["schema_version"] == 1
        )
        record = wrapper["record"]
        validator(record)
        _require(
            record["instance_id"] == instance_id
            and wrapper == revision_record(record, relation=relation)
            and wrapper["id"] == key
        )
        digest = record_digest(record)
        _require(digest not in indexed)
        indexed[digest] = record
    used = set()
    for head in heads.values():
        validator(head)
        _require(head["instance_id"] == instance_id)
        current = head
        while True:
            digest = record_digest(current)
            _require(digest in indexed and indexed[digest] == current and digest not in used)
            used.add(digest)
            if current["revision"] == 1:
                break
            previous = indexed.get(current["previous_sha256"])
            _require(previous is not None)
            validate_successor(previous, current, relation=relation)
            current = previous
    _require(used == set(indexed))
    return indexed


def _acyclic(edges):
    graph = defaultdict(set)
    indegree = defaultdict(int)
    for source, target in edges:
        if target not in graph[source]:
            graph[source].add(target)
            indegree[target] += 1
            indegree.setdefault(source, 0)
    ready = deque(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        source = ready.popleft()
        visited += 1
        for target in graph[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    _require(visited == len(indegree), "cycle")


def object_findings(store, records, errors, warnings):
    """Inspect inert records and retained lineage, never migrate or certify truth."""
    selected = {k: records.get(k, {}) for k in OBJECT_CANONICAL_KINDS}
    if not any(selected.values()) and not any(
        v.get("kind") in ("project", "collection") for v in records.get("hierarchy", {}).values()
    ):
        return
    try:
        _require(sum(len(v) for v in selected.values()) <= MAX_OBJECT_RECORDS, "limit")
        instance_id = store.read_config()["instance"]["id"]
        objects = _chain(
            selected["objects"],
            selected["object-revisions"],
            relation=False,
            instance_id=instance_id,
        )
        relations = _chain(
            selected["object-relations"],
            selected["object-relation-revisions"],
            relation=True,
            instance_id=instance_id,
        )
        for ev in selected["object-evidence"].values():
            validate_evidence(ev)
            _require(ev["instance_id"] == instance_id)
            version = records.get("versions", {}).get(ev["version_id"])
            original = records.get("originals", {}).get(ev["original_id"])
            if version is None or original is None:
                warnings.append(
                    {
                        "code": "object_evidence_unavailable",
                        "message": "An exact retained evidence source is unavailable",
                    }
                )
            else:
                _require(
                    version.get("document_id") == ev["document_id"]
                    and version.get("original_id") == ev["original_id"]
                    and original.get("sha256") == ev["original_sha256"]
                )
        for row in [*objects.values(), *relations.values()]:
            _require(set(row["evidence_ids"]) <= set(selected["object-evidence"]))
        for node in records.get("hierarchy", {}).values():
            if node.get("kind") not in {"project", "collection"}:
                continue
            obj = selected["objects"].get(node["id"])
            _require(
                obj is not None
                and obj["kind"] == node["kind"]
                and obj["title"] == node["name"]
                and obj["created_at"] == node["created_at"]
            )
        for obj in selected["objects"].values():
            if obj["kind"] in {"project", "collection"}:
                _require(obj["id"] in records.get("hierarchy", {}))
        for relation in relations.values():
            endpoints = []
            for ref in (relation["source"], relation["target"]):
                endpoint = objects.get(ref["sha256"])
                _require(
                    endpoint is not None
                    and endpoint["id"] == ref["id"]
                    and endpoint["revision"] == ref["revision"]
                )
                endpoints.append(endpoint)
            if relation["relation_type"] == "fulfills":
                _require(all(v["kind"] in {"task", "outcome", "commitment"} for v in endpoints))
            if relation["relation_type"] == "scheduled_for":
                _require(endpoints[1]["kind"] == "calendar_event")
        for relation_type in ("part_of", "depends_on"):
            edges = [
                (r["source"]["id"], r["target"]["id"])
                for r in selected["object-relations"].values()
                if r["state"] == "active" and r["relation_type"] == relation_type
            ]
            if relation_type == "part_of":
                edges.extend(
                    (n["id"], n["parent_id"])
                    for n in records.get("hierarchy", {}).values()
                    if n.get("parent_id") in selected["objects"]
                )
            _acyclic(edges)
    except (KnowledgeObjectError, KeyError, TypeError, ValueError, RecursionError):
        errors.append(
            {
                "code": "knowledge_objects_invalid",
                "message": "Canonical object identities, history or references are invalid",
            }
        )
