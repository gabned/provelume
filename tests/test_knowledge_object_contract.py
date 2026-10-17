"""Synthetic contract evidence, never canonical application or factual verification."""

import builtins
import json
import socket
import subprocess
from copy import deepcopy

import pytest

from provelume.knowledge_object_contract import (
    MAX_RECORD_BYTES,
    OBJECT_KINDS,
    RELATION_TYPES,
    KnowledgeObjectError,
    canonical_bytes,
    parse_record,
    record_digest,
    validate_evidence,
    validate_object,
    validate_relation,
    validate_successor,
)

INSTANCE = "inst_" + "1" * 32
TIME = "2026-10-17T12:00:00Z"


def evidence(**changes):
    row = {"schema_version": 1, "instance_id": INSTANCE, "document_id": "doc_" + "2" * 32,
           "version_id": "ver_" + "3" * 32, "original_id": "sha256_" + "4" * 64,
           "original_sha256": "4" * 64, "selector": {"kind": "original"}, **changes}
    return {**row, "id": "evd_" + record_digest(row)}


def object_record(kind="entity", **changes):
    body = {"description": "Synthetic knowledge"}
    state = "active"
    if kind == "claim":
        body, state = {"statement": "The synthetic sample is blue."}, "asserted"
    elif kind == "decision":
        body, state = {"rationale": "Use the synthetic blue sample."}, "decided"
    elif kind in {"task", "commitment"}:
        body, state = {**body, "due_at": None}, "open"
    elif kind == "outcome":
        state = "achieved"
    elif kind == "calendar_event":
        body = {**body, "starts_at": TIME, "ends_at": "2026-10-17T13:00:00Z",
                "time_zone": "Europe/Rome"}
        state = "confirmed"
    prefix = kind if kind in {"project", "collection"} else "obj"
    return {"schema_version": 1, "id": prefix + "_" + "5" * 32, "instance_id": INSTANCE,
            "kind": kind, "revision": 1, "previous_sha256": None, "title": "Synthetic",
            "aliases": ["Example", "Esempio"], "state": state, "body": body,
            "evidence_ids": [evidence()["id"]], "origin": {"kind": "manual", "proposal_id": None},
            "created_at": TIME, "updated_at": TIME, **changes}


def relation_record(**changes):
    source = object_record()
    target = object_record(id="obj_" + "6" * 32)
    return {"schema_version": 1, "id": "rel_" + "7" * 32, "instance_id": INSTANCE,
            "revision": 1, "previous_sha256": None, "relation_type": "relates_to",
            "source": {"id": source["id"], "revision": 1, "sha256": record_digest(source)},
            "target": {"id": target["id"], "revision": 1, "sha256": record_digest(target)},
            "state": "active", "evidence_ids": [], "created_at": TIME, "updated_at": TIME,
            **changes}


@pytest.mark.parametrize("kind", sorted(OBJECT_KINDS))
def test_all_object_types_round_trip_without_replacing_identity(kind):
    row = object_record(kind)
    assert validate_object(parse_record(canonical_bytes(row))) == row
    assert record_digest(dict(reversed(list(row.items())))) == record_digest(row)
    assert validate_object(row)["id"] == row["id"]


@pytest.mark.parametrize("relation_type", sorted(RELATION_TYPES))
def test_closed_versioned_relation_types(relation_type):
    row = relation_record(relation_type=relation_type)
    assert validate_relation(parse_record(canonical_bytes(row))) == row


def test_evidence_is_exact_version_bound_and_survives_document_evolution():
    old = evidence()
    current = evidence(version_id="ver_" + "9" * 32, original_id="sha256_" + "a" * 64,
                       original_sha256="a" * 64)
    assert validate_evidence(old) == old
    assert validate_evidence(current)["id"] != old["id"]
    assert object_record("claim")["evidence_ids"] == [old["id"]]
    changed = {**old, "version_id": current["version_id"]}
    with pytest.raises(KnowledgeObjectError):
        validate_evidence(changed)


def test_representation_evidence_binds_anchor_and_quote_without_embedding_content():
    selector = {"kind": "text", "representation_id": "repr_" + "a" * 64,
                "output_id": "rout_" + "b" * 64, "anchor_id": "ranc_" + "c" * 64,
                "quote_sha256": "d" * 64}
    row = evidence(selector=selector)
    assert validate_evidence(row) == row
    for key in selector:
        changed = deepcopy(row)
        changed["selector"][key] = "../private"
        with pytest.raises(KnowledgeObjectError):
            validate_evidence(changed)


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"schema_version": 2}, {"revision": True}, {"revision": 0},
    {"revision": 2}, {"previous_sha256": "a" * 64}, {"id": "../../secret"},
    {"id": "https://github.com/example"}, {"instance_id": "other"}, {"kind": []},
    {"kind": "document"}, {"kind": "project"}, {"state": []}, {"state": "verified"},
    {"title": ""}, {"title": "x" * 241}, {"title": "private\x00content"},
    {"title": "\ud800"}, {"aliases": ["EXAMPLE", "example"]},
    {"aliases": ["é", "e\u0301"]}, {"aliases": [None]}, {"aliases": ["a"] * 33},
    {"body": {"description": "a", "execute": "shell"}}, {"body": []},
    {"evidence_ids": ["evd_" + "a" * 64] * 2}, {"evidence_ids": ["../private"]},
    {"origin": {"kind": "automatic", "proposal_id": None}},
    {"origin": {"kind": "manual", "proposal_id": "objprop_" + "a" * 64}},
    {"created_at": "2026-10-18T12:00:00Z"}, {"updated_at": "2026-10-17T12:00:00"},
    {"updated_at": "2026-10-17T12:00:00-00:00"},
    {"updated_at": "2026-10-17T12:00:00+01:99"},
    {"updated_at": "2026-02-30T12:00:00Z"}, {"permission": "grant"},
])
def test_hostile_object_records_fail_closed_with_redacted_errors(changes):
    with pytest.raises(KnowledgeObjectError) as exc:
        validate_object({**object_record(), **changes})
    assert str(exc.value) in {"knowledge_object_invalid", "knowledge_object_limit"}


def test_claims_require_evidence_and_decisions_require_rationale():
    with pytest.raises(KnowledgeObjectError):
        validate_object(object_record("claim", evidence_ids=[]))
    with pytest.raises(KnowledgeObjectError):
        validate_object(object_record("decision", body={"rationale": ""}))


@pytest.mark.parametrize("body", [
    {"description": "", "starts_at": TIME, "ends_at": TIME, "time_zone": "UTC"},
    {"description": "", "starts_at": TIME, "ends_at": "yesterday", "time_zone": "UTC"},
    {"description": "", "starts_at": TIME, "ends_at": "2026-10-17T13:00:00Z",
     "time_zone": "../../zone"},
])
def test_calendar_instants_are_ordered_offset_aware_and_zone_is_inert(body):
    with pytest.raises(KnowledgeObjectError):
        validate_object(object_record("calendar_event", body=body))
    offset = {"description": "", "starts_at": "2026-10-25T02:30:00+02:00",
              "ends_at": "2026-10-25T02:30:00+01:00", "time_zone": "Europe/Rome"}
    assert validate_object(object_record("calendar_event", body=offset))


@pytest.mark.parametrize("relation", [False, True])
def test_revision_chains_preserve_history_and_detect_conflicts(relation):
    previous = relation_record() if relation else object_record()
    current = {**previous, "revision": 2, "previous_sha256": record_digest(previous),
               "updated_at": "2026-10-17T13:00:00Z"}
    validate_successor(previous, current, relation=relation)
    assert previous["revision"] == 1
    for field, bad in (("revision", 3), ("previous_sha256", "b" * 64),
                       ("instance_id", "inst_" + "9" * 32), ("created_at", current["updated_at"]),
                       ("updated_at", "2026-10-17T11:00:00Z")):
        with pytest.raises(KnowledgeObjectError):
            validate_successor(previous, {**current, field: bad}, relation=relation)


def test_relations_cannot_alias_self_or_grant_arbitrary_effects():
    row = relation_record()
    for changes in ({"target": row["source"]}, {"relation_type": "execute"},
                    {"target": {**row["target"], "path": "../private"}},
                    {"target": {**row["target"], "revision": True}}):
        with pytest.raises(KnowledgeObjectError):
            validate_relation({**row, **changes})


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'[]', b'{"a":NaN}',
                                b'{"a":1.5}', b'\xff', b'[' * 2000,
                                b' ' * (MAX_RECORD_BYTES + 1)])
def test_parser_rejects_duplicate_non_json_unbounded_or_non_record_data(raw):
    with pytest.raises(KnowledgeObjectError):
        parse_record(raw)


def test_direct_values_are_bounded_before_serialization():
    cycle = []
    cycle.append(cycle)
    for value in (cycle, {"a": "x" * MAX_RECORD_BYTES}, {"a": ["x" * 10000] * 128},
                  {"a": 2**64}, {"a": object()}):
        with pytest.raises(KnowledgeObjectError):
            canonical_bytes(value)


def test_validation_has_no_io_provider_or_execution_capability(monkeypatch):
    records = [object_record(kind) for kind in sorted(OBJECT_KINDS)]
    ev, rel = evidence(), relation_record()
    original = canonical_bytes(records[0])

    def denied(*args, **kwargs):
        pytest.fail("Pure contract attempted an external effect")

    monkeypatch.setattr(builtins, "open", denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    for row in records:
        assert validate_object(row) == row
    assert validate_evidence(ev) == ev
    assert validate_relation(rel) == rel
    assert json.loads(original) == parse_record(original)
