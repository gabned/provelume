"""Disposable receipt-bound drafts and explicit, atomic canonical object review.

The existing synthesis producer selects attributable excerpts. The local user
chooses the object type and typed fields; no inference or canonical write is
authorized by preparing, inspecting or discarding a draft.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict
from itertools import islice
from uuid import uuid4

from .action_center_model import bounded_json, digest, json_bytes
from .ai_contract import digest as ai_digest
from .ai_job_contract import receipt_snapshot
from .ai_synthesis import MAX_RESULT_BYTES, validate_reference
from .instance_lifecycle import InstanceLifecycleManager
from .knowledge_object_contract import (
    KnowledgeObjectError,
    record_digest,
    validate_evidence,
    validate_object,
    validate_relation,
)
from .knowledge_object_evidence import current_instance_id
from .knowledge_object_services import KnowledgeObjectServices, _calendar
from .knowledge_object_store import _bytes, prepare_object_locked, revision_record
from .maintenance_local_files import pinned_parent, write_local_bytes
from .review_decisions import (
    MAX_HISTORY,
    assert_review_readable,
    checked_path,
    decode_json,
    read_bytes,
    read_json,
    receipt_identifier,
    validate_receipt,
)
from .review_effects import (
    ABSENT,
    PreparedEffect,
    PreparedWrite,
    ReviewConflict,
    ReviewDenied,
    ReviewError,
    ReviewStale,
    ReviewUnavailable,
    sha256,
)
from .scheduler import _receipt_matches_terminal_job
from .scheduler_model import validate_job_record, validate_receipt_record
from .storage import utc_now

PROPOSALS = "state/derived/object-proposals"
HISTORY = "state/review/object-proposals"
MAX_PROPOSALS = 128
MAX_PROPOSAL_BYTES = 256 * 1024
_PROPOSAL = re.compile(r"objprop_[0-9a-f]{64}\Z")
_JOB = re.compile(r"job_[0-9a-f]{32}\Z")
_FIELDS = {
    "schema_version", "id", "instance_id", "job_id", "scheduler_receipt_id",
    "scheduler_receipt_sha256", "reference", "source", "evidence", "draft",
    "created_at", "request_id",
}


def _need(condition, message="Object proposal evidence is unavailable"):
    if not condition:
        raise ReviewUnavailable(message)


def proposal_identity(identity):
    if not isinstance(identity, str) or _PROPOSAL.fullmatch(identity) is None:
        raise ReviewError("Invalid object proposal identity")
    return identity


def _source_record(source, first, instance_id):
    _need(isinstance(source, dict)
          and set(source) == {"version", "source_id", "bundles", "outputs",
                              "governance_sha256", "policies_sha256"})
    _need(first.version.instance_id == instance_id and source["version"] == asdict(first.version))
    _need(isinstance(source["source_id"], str)
          and re.fullmatch(r"src_[0-9a-f]{32}", source["source_id"]))
    _need(isinstance(source["bundles"], list) and len(source["bundles"]) == 1
          and isinstance(source["outputs"], list) and len(source["outputs"]) == 1)
    output = source["outputs"][0]
    _need(isinstance(output, list) and len(output) == 3
          and output[:2] == [first.representation_id, first.output_id])
    for value in (source["bundles"][0], output[2], source["governance_sha256"],
                  source["policies_sha256"]):
        _need(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value))


def validate_proposal(value, identity, instance_id):
    proposal_identity(identity)
    _need(isinstance(value, dict) and set(value) == _FIELDS)
    _need(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _need(value["id"] == identity and value["instance_id"] == instance_id)
    _need(value["id"] == "objprop_" + digest({k: v for k, v in value.items() if k != "id"}))
    _need(isinstance(value["job_id"], str) and _JOB.fullmatch(value["job_id"]))
    selections = validate_reference(value["reference"])
    first = selections[0]
    _source_record(value["source"], first, instance_id)
    _need(value["evidence"]["version_id"] == first.version.version_id)
    _need(value["evidence"]["document_id"] == first.version.document_id)
    validate_evidence(value["evidence"])
    _need(value["evidence"]["instance_id"] == instance_id
          and value["evidence"]["selector"] == {"kind": "original"}
          and value["evidence"]["original_id"] == first.version.original_id
          and value["evidence"]["original_sha256"] == first.version.original_sha256)
    _need(value["scheduler_receipt_id"] == "receipt_" + value["job_id"][4:])
    _need(isinstance(value["scheduler_receipt_sha256"], str)
          and re.fullmatch(r"[0-9a-f]{64}", value["scheduler_receipt_sha256"]))
    bounded_json(value, maximum=MAX_PROPOSAL_BYTES)
    return value


def candidate(proposal, draft, recorded_at):
    """Closed typed fields; identity, provenance, evidence and time are host owned."""
    if not isinstance(draft, dict):
        raise ReviewError("A typed object draft is required")
    relation = draft.get("kind") == "relation"
    expected = (
        {"kind", "relation_type", "source", "target", "state"} if relation
        else {"kind", "title", "aliases", "state", "body"}
    )
    if set(draft) != expected or draft["kind"] in {"project", "collection"}:
        raise ReviewError("Unsupported or extra object draft fields")
    value = {
        "schema_version": 1,
        "id": ("rel_" if relation else "obj_") + proposal["id"][8:40],
        "instance_id": proposal["instance_id"],
        "revision": 1,
        "previous_sha256": None,
        **deepcopy({k: v for k, v in draft.items() if k != "kind" or not relation}),
        "evidence_ids": [proposal["evidence"]["id"]],
        "created_at": recorded_at,
        "updated_at": recorded_at,
    }
    if not relation:
        value["origin"] = {"kind": "reviewed_proposal", "proposal_id": proposal["id"]}
    try:
        (validate_relation if relation else validate_object)(value)
        if not relation:
            _calendar(value)
    except KnowledgeObjectError as exc:
        raise ReviewError("Invalid typed object draft: " + exc.code) from exc
    return value, relation


def history_record(store, identity):
    """Retained provenance is independent of disposable derived text and current heads."""
    proposal_identity(identity)
    assert_review_readable(store)
    relative = f"{HISTORY}/{identity}.json"
    raw = read_bytes(store, relative, maximum=MAX_PROPOSAL_BYTES)
    if raw is None:
        return None
    value = decode_json(raw)
    fields = {
        "schema_version", "proposal_id", "proposal_sha256", "instance_id", "job_id",
        "scheduler_receipt_id", "scheduler_receipt_sha256", "reference", "source",
        "evidence_id", "action", "edited", "original_draft_sha256", "reviewed_draft_sha256",
        "canonical", "receipt_id", "principal", "recorded_at",
    }
    _need(set(value) == fields and type(value["schema_version"]) is int
          and value["schema_version"] == 1)
    _need(value["proposal_id"] == identity
          and value["instance_id"] == current_instance_id(store))
    _need(value["action"] in {"apply", "reject"} and type(value["edited"]) is bool)
    _need(value["edited"] == (value["original_draft_sha256"] != value["reviewed_draft_sha256"]))
    selections = validate_reference(value["reference"])
    _source_record(value["source"], selections[0], value["instance_id"])
    for field in ("proposal_sha256", "scheduler_receipt_sha256", "original_draft_sha256",
                  "reviewed_draft_sha256"):
        _need(isinstance(value[field], str) and re.fullmatch(r"[0-9a-f]{64}", value[field]))
    _need(isinstance(value["job_id"], str) and _JOB.fullmatch(value["job_id"])
          and value["scheduler_receipt_id"] == "receipt_" + value["job_id"][4:])
    receipt = read_json(store, f"state/review/receipts/{value['receipt_id']}.json")
    _need(receipt is not None)
    validate_receipt(receipt, instance_id=value["instance_id"])
    _need(receipt["id"] == value["receipt_id"] and receipt["domain"] == "knowledge_objects"
          and receipt["subject"] == identity and receipt["action"] == value["action"]
          and receipt["history_ref"] == relative and receipt["history_sha256"] == sha256(raw)
          and receipt["principal"] == value["principal"]
          and receipt["recorded_at"] == value["recorded_at"]
          and receipt["result"] == {"proposal_id": identity, "canonical": value["canonical"]}
          and receipt["canonical_mutation"] == (value["action"] == "apply"))
    if value["action"] == "reject":
        _need(value["canonical"] is None)
    else:
        ref = value["canonical"]
        _need(isinstance(ref, dict) and set(ref) == {"id", "sha256", "relation"}
              and type(ref["relation"]) is bool)
        kind = "object-relation-revisions" if ref["relation"] else "object-revisions"
        prefix = "relrev_" if ref["relation"] else "objrev_"
        wrapper = read_json(store, f"knowledge/{kind}/{prefix}{ref['sha256']}.json")
        _need(isinstance(wrapper, dict) and set(wrapper) == {"schema_version", "id", "record"})
        record = wrapper["record"]
        _need(wrapper == revision_record(record, relation=ref["relation"]))
        _need(record["id"] == ref["id"] and record_digest(record) == ref["sha256"]
              and record["revision"] == 1 and record["instance_id"] == value["instance_id"]
              and record["created_at"] == record["updated_at"] == value["recorded_at"]
              and record["evidence_ids"] == [value["evidence_id"]])
        _need(record["id"] == ("rel_" if ref["relation"] else "obj_") + identity[8:40])
        if not ref["relation"]:
            _need(record["origin"] == {"kind": "reviewed_proposal", "proposal_id": identity})
    return value


class KnowledgeObjectReview:
    domain = "knowledge_objects"
    actions = ("apply", "reject")

    def __init__(self, instance):
        self.instance = instance
        self.store = instance.store
        self.services = KnowledgeObjectServices(self.store)
        self._locked = ContextVar("object_review_locked", default=False)

    def _synthesis(self):
        # This read-only setup binds no adapter and grants no inference session.
        from .ai_setup import AiSetup

        return AiSetup(self.instance, bind_execution=False).synthesis

    @contextmanager
    def secondary_lock(self, plan):
        with self.instance.ai_jobs.journal.hold():
            token = self._locked.set(True)
            try:
                yield
            finally:
                self._locked.reset(token)

    @contextmanager
    def _observe(self):
        if self._locked.get():
            yield
        else:
            # Optimistic read-only observation. The scheduler writer lock creates
            # directories/files even for an empty Instance, so GET must not take
            # it. Terminal receipts and source digests bind the proposal; final
            # confirmation owns lifecycle/journal and rereads every input.
            assert_review_readable(self.store)
            identity = current_instance_id(self.store)
            yield
            assert_review_readable(self.store)
            if current_instance_id(self.store) != identity:
                raise ReviewStale("Instance changed during proposal observation")

    def _receipt(self, job):
        relative = f"state/scheduler/receipts/receipt_{job['id'][4:]}.json"
        raw = read_bytes(self.store, relative)
        _need(raw is not None, "The original terminal AI receipt is missing")
        receipt = decode_json(raw)
        validate_job_record(job)
        validate_receipt_record(receipt)
        _need(_receipt_matches_terminal_job(receipt, job)
              and receipt.get("ai") == receipt_snapshot(job["ai"]),
              "The terminal AI receipt does not match its job")
        return receipt, sha256(raw)

    def _job(self, job_id):
        _need(isinstance(job_id, str) and _JOB.fullmatch(job_id))
        raw = read_bytes(self.store, f"state/scheduler/jobs/{job_id}.json")
        _need(raw is not None, "The original AI producer job is missing")
        job = decode_json(raw)
        validate_job_record(job)
        _need(job["id"] == job_id)
        return job

    def _source(self, synthesis, reference):
        first = validate_reference(reference)[0]
        for kind, identity in (("documents", first.version.document_id),
                               ("versions", first.version.version_id),
                               ("originals", first.version.original_id)):
            checked_path(self.store, f"knowledge/{kind}/{identity}.json")
        # The producer's governance reader has the same 512-record profile.
        # Bound and pin every inventory before asking it to assemble associations.
        for kind in ("acquisitions", "hierarchy", "classifications", "sources"):
            directory = checked_path(self.store, "knowledge/" + kind)
            paths = list(islice(directory.iterdir(), 513)) if directory.exists() else []
            _need(len(paths) <= 512, "Object producer association inventory exceeds its bound")
            for path in paths:
                checked_path(self.store, path.relative_to(self.store.paths.root).as_posix())
                _need(path.is_file())
        document, _, source = synthesis.source(
            first.version.document_id, first.representation_id, first.output_id,
        )
        _need(source.version == first.version)
        return {
            "version": asdict(source.version), "source_id": document["source_id"],
            "governance_sha256": synthesis.setup.document_governance(document)[1],
            "policies_sha256": digest(synthesis.policies()),
            "bundles": [sha256(b) for b in source.bundles],
            "outputs": [[o.representation_id, o.output_id, sha256(o.data)] for o in source.outputs],
        }

    def _proposal(self, identity):
        proposal_identity(identity)
        raw = read_bytes(self.store, f"{PROPOSALS}/{identity}.json", maximum=MAX_PROPOSAL_BYTES)
        _need(raw is not None, "Object proposal was discarded or is unavailable")
        return validate_proposal(decode_json(raw), identity, current_instance_id(self.store)), raw

    def _fresh(self, proposal):
        synthesis = self._synthesis()
        job, reference, _ = synthesis._reference_record(
            proposal["job_id"], self._job(proposal["job_id"]),
        )
        receipt, receipt_sha = self._receipt(job)
        _need(reference == proposal["reference"]
              and receipt["id"] == proposal["scheduler_receipt_id"]
              and receipt_sha == proposal["scheduler_receipt_sha256"])
        # Read historical result bytes without renewing or requiring inference authority.
        relative = synthesis.path(job["id"]).relative_to(self.store.paths.root).as_posix()
        raw = read_bytes(self.store, relative, maximum=MAX_RESULT_BYTES)
        _need(raw is not None, "The base AI excerpt has been discarded")
        body = decode_json(raw)
        _need(ai_digest(body) == reference["body_sha256"] and body.get("job_id") == job["id"])
        try:
            source = self._source(synthesis, reference)
        except (ValueError, OSError) as exc:
            raise ReviewStale("The exact proposal source is no longer available") from exc
        if source != proposal["source"]:
            raise ReviewStale("The exact proposal source changed; prepare a new proposal")
        self.services._evidence({"evidence_ids": [proposal["evidence"]["id"]]},
                                [proposal["evidence"]])

    def seed(self, job_id):
        with self._observe():
            synthesis = self._synthesis()
            body, reference, _, job = synthesis._read_locked(job_id, recorded_job=self._job(job_id))
            self._receipt(job)
            _need(body["status"] == "selected" and body["references"],
                  "An abstained AI result cannot prepare an object proposal")
            source = self._source(synthesis, reference)
            return {
                "job_id": job_id, "source": source,
                "producer_sha256": digest({"reference": reference, "source": source}),
                "text": "\n\n".join(body["segments"][i]["text"] for i in body["references"]),
            }

    def listing(self):
        with self._observe():
            assert_review_readable(self.store)
            directory = checked_path(self.store, PROPOSALS)
            if not directory.exists():
                return []
            _need(directory.is_dir())
            paths = list(islice(directory.iterdir(), MAX_PROPOSALS + 1))
            _need(len(paths) <= MAX_PROPOSALS, "Object draft inventory exceeds its bound")
            rows = []
            for path in sorted(paths):
                _need(path.suffix == ".json")
                proposal, _ = self._proposal(path.stem)
                rows.append({"proposal": proposal,
                             "history": history_record(self.store, path.stem)})
            assert_review_readable(self.store)
            return rows

    def prepare_proposal(self, job_id, draft, *, consent=False, expected_instance_id=None,
                         expected_producer_sha256=None):
        if consent is not True:
            raise ReviewDenied("Preparing an object draft requires explicit confirmation")
        if not isinstance(job_id, str) or _JOB.fullmatch(job_id) is None:
            raise ReviewError("Invalid AI result identity")
        draft = bounded_json(draft, maximum=MAX_PROPOSAL_BYTES)
        with InstanceLifecycleManager(self.store)._hold(
            purpose="object-proposal-prepare"
        ), self.secondary_lock({}):
            instance_id = current_instance_id(self.store)
            if expected_instance_id != instance_id:
                raise ReviewStale("Instance changed; open a new draft")
            assert_review_readable(self.store)
            synthesis = self._synthesis()
            body, reference, _, job = synthesis._read_locked(job_id, recorded_job=self._job(job_id))
            _need(body["status"] == "selected" and body["references"],
                  "An abstained AI result cannot prepare an object proposal")
            receipt, receipt_sha = self._receipt(job)
            source = self._source(synthesis, reference)
            if (expected_producer_sha256 is not None
                    and expected_producer_sha256 != digest({"reference": reference,
                                                           "source": source})):
                raise ReviewStale("The selected AI result changed; open a new draft")
            evidence = self.services.evidence_for_version(source["version"]["version_id"])
            value = {
                "schema_version": 1, "instance_id": instance_id, "job_id": job_id,
                "scheduler_receipt_id": receipt["id"], "scheduler_receipt_sha256": receipt_sha,
                "reference": deepcopy(reference), "source": source, "evidence": evidence,
                "draft": draft, "created_at": utc_now(), "request_id": uuid4().hex,
            }
            value["id"] = "objprop_" + digest(value)
            candidate(value, draft, value["created_at"])
            validate_proposal(value, value["id"], instance_id)
            directory = checked_path(self.store, PROPOSALS)
            _need(not directory.exists() or (directory.is_dir()
                  and len(list(islice(directory.iterdir(), MAX_PROPOSALS))) < MAX_PROPOSALS),
                  "Object draft limit reached")
            raw = json_bytes(value)
            _need(len(raw) <= MAX_PROPOSAL_BYTES)
            directory.mkdir(exist_ok=True)
            write_local_bytes(directory / (value["id"] + ".json"), raw)
            return deepcopy(value)

    def inspect(self, identity):
        with self._observe():
            assert_review_readable(self.store)
            proposal, _ = self._proposal(identity)
            self._fresh(proposal)
            return {"proposal": proposal, "history": history_record(self.store, identity),
                    "truth": "NOT_VERIFIED", "automatic_allowed": False}

    def discard(self, identity, *, consent=False, expected_instance_id=None):
        if consent is not True:
            raise ReviewDenied("Discarding an object draft requires explicit confirmation")
        proposal_identity(identity)
        with InstanceLifecycleManager(self.store)._hold(purpose="object-proposal-discard"):
            if current_instance_id(self.store) != expected_instance_id:
                raise ReviewStale("Instance changed; open a new draft")
            # No current source, inference consent or live result is needed to remove a draft.
            path = checked_path(self.store, f"{PROPOSALS}/{identity}.json")
            if path.exists():
                self._proposal(identity)
                with pinned_parent(path) as (target, parent):
                    if os.name == "nt":
                        target.unlink()
                    else:
                        os.unlink(target.name, dir_fd=parent)
            return {"proposal_id": identity, "discarded": True, "canonical_mutation": False}

    def preview(self, subject, action, parameters):
        if (action not in self.actions or not isinstance(parameters, dict)
                or set(parameters) != {"draft"}):
            raise ReviewError("Object review requires one explicit typed draft")
        with self._observe():
            proposal, raw = self._proposal(subject)
            if history_record(self.store, subject) is not None:
                raise ReviewConflict("This proposal already has a terminal domain decision")
            receipts = checked_path(self.store, "state/review/receipts")
            _need(not receipts.exists() or len(list(islice(
                receipts.iterdir(), MAX_HISTORY,
            ))) < MAX_HISTORY, "Retained review history has reached its bound")
            self._fresh(proposal)
            candidate(proposal, parameters["draft"], proposal["created_at"])
            if action == "apply":
                self._candidate_entries(proposal, parameters["draft"], proposal["created_at"])
            return {
                "input_revision": digest({"proposal": sha256(raw), "draft": parameters["draft"]}),
                "proposal": proposal, "proposal_sha256": sha256(raw),
                "evidence": {"version": proposal["source"]["version"],
                             "scheduler_receipt_id": proposal["scheduler_receipt_id"],
                             "edited": parameters["draft"] != proposal["draft"]},
                "reason": "A local user reviews an attributable excerpt and explicit typed fields",
                "confidence": None,
                "impact": ("Create one canonical record" if action == "apply"
                           else "Reject this draft"),
                "reversibility": ("Discard the draft independently; "
                                  "canonical edits retain revision history"),
            }

    def _entries(self, plan, recorded_at):
        if plan["action"] == "reject":
            return [], None
        return self._candidate_entries(plan["provider"]["proposal"],
                                       plan["parameters"]["draft"], recorded_at)

    def _candidate_entries(self, proposal, draft, recorded_at):
        value, relation = candidate(proposal, draft, recorded_at)
        try:
            evidence = self.services._evidence(value, [proposal["evidence"]])
            entries = prepare_object_locked(self.store, value, expected_sha256=None,
                                            evidence=evidence, relation=relation)
        except KnowledgeObjectError as exc:
            if exc.code == "conflict":
                raise ReviewStale("Canonical identity or relation endpoint changed") from exc
            raise ReviewUnavailable("The canonical object graph could not be validated") from exc
        return entries, {"id": value["id"], "sha256": record_digest(value), "relation": relation}

    def allowed_paths_at(self, plan, request_id, recorded_at):
        # Independently derive exact canonical revision paths using the coordinator's time.
        entries, _ = self._entries(plan, recorded_at)
        return frozenset({f"{HISTORY}/{proposal_identity(plan['subject'])}.json", *(
            f"knowledge/{kind}/{value['id']}.json" for kind, value, _ in entries
        )})

    def prepare(self, plan, *, request_id, principal, recorded_at):
        proposal = plan["provider"]["proposal"]
        entries, canonical = self._entries(plan, recorded_at)
        writes = tuple(PreparedWrite(f"knowledge/{kind}/{value['id']}.json", ABSENT,
                                     _bytes(value), immutable=immutable)
                       for kind, value, immutable in entries)
        relative = f"{HISTORY}/{proposal['id']}.json"
        draft = plan["parameters"]["draft"]
        history = {
            "schema_version": 1, "proposal_id": proposal["id"],
            "proposal_sha256": plan["provider"]["proposal_sha256"],
            **{key: deepcopy(proposal[key]) for key in (
                "instance_id", "job_id", "scheduler_receipt_id", "scheduler_receipt_sha256",
                "reference", "source",
            )},
            "evidence_id": proposal["evidence"]["id"], "action": plan["action"],
            "edited": draft != proposal["draft"],
            "original_draft_sha256": digest(proposal["draft"]),
            "reviewed_draft_sha256": digest(draft), "canonical": canonical,
            "receipt_id": receipt_identifier(proposal["instance_id"], request_id),
            "principal": principal, "recorded_at": recorded_at,
        }
        return PreparedEffect(
            self.domain, plan["action"],
            (*writes, PreparedWrite(relative, ABSENT, json_bytes(history), immutable=True)),
            {"proposal_id": proposal["id"], "canonical": canonical}, relative,
            plan["provider"]["impact"], plan["provider"]["reversibility"],
        )
