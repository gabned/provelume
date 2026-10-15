"""Closed disposable assessments projected inside the existing governed AI job.

This producer never dispatches a provider or applies canonical classification.
The immutable terminal scheduler result anchors the private body hash. Real task
quality is NOT_EVALUATED; these records cannot qualify a model or grant authority.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from itertools import islice

from .ai_classification_targets import CurrentClassificationTargets, resolve_classification_targets
from .ai_context import (
    CLASSIFICATION_TEMPLATES,
    ClassificationTarget,
    RedactionPreview,
    Selection,
    VersionIdentity,
    _json,
    validate_candidate,
)
from .ai_contract import Scope, digest
from .ai_job_contract import check, fingerprint
from .ai_synthesis import MAX_RESULT_BYTES, MAX_RESULTS
from .maintenance_local_files import open_local_file, pinned_parent, write_local_bytes
from .representations import canonical_json_bytes
from .scheduler import _receipt_matches_terminal_job

_JOB = re.compile(r"job_[0-9a-f]{32}\Z")


def classification_request_ref(preview, targets):
    """The host must also revalidate targets in its live current callback."""
    check(type(preview) is RedactionPreview and type(targets) is CurrentClassificationTargets)
    return digest(["provelume.classification-proposal.v1", preview.fingerprint, targets.revision])


def validate_reference(value):
    """A scheduler reference proves attribution, never present authority/quality."""
    check(type(value) is dict and set(value) == {
        "schema_version", "recipe", "association", "body_sha256", "route", "model", "execution",
    }, "ai_result_invalid")
    check(type(value["schema_version"]) is int and value["schema_version"] == 1)
    for key in ("association", "body_sha256", "route"):
        fingerprint(value[key])
    check(type(value["model"]) is str and 0 < len(value["model"]) <= 512)
    check(type(value["execution"]) is str and value["execution"] in {"local", "external"})
    recipe = value["recipe"]
    check(type(recipe) is dict and set(recipe) == {
        "template", "template_revision", "redaction_revision", "selections",
        "allowlist", "target_revision",
    })
    check(type(recipe["template"]) is str and recipe["template"] in CLASSIFICATION_TEMPLATES)
    for key in ("template_revision", "redaction_revision", "target_revision"):
        fingerprint(recipe[key])
    check(type(recipe["allowlist"]) is list and 1 <= len(recipe["allowlist"]) <= 64)
    pairs = []
    for row in recipe["allowlist"]:
        check(type(row) is list and len(row) == 2)
        ClassificationTarget(row[0], row[1], "identity validation")
        pairs.append(tuple(row))
    check(len(set(pairs)) == len(pairs) and len({p[1] for p in pairs}) == len(pairs))
    check(type(recipe["selections"]) is list and 1 <= len(recipe["selections"]) <= 16)
    selections = tuple(Selection.from_bytes(canonical_json_bytes(s)) for s in recipe["selections"])
    check(len({s.version for s in selections}) == 1)
    check(len({(s.representation_id, s.output_id) for s in selections}) == 1)
    return selections


class DocumentClassification:
    """Reuse Synthesis's verified context/policy producer, journal and derived store."""

    def __init__(self, setup):
        self.setup = setup
        self.instance = setup.instance

    def path(self, job_id):
        check(type(job_id) is str and _JOB.fullmatch(job_id), "ai_job_invalid")
        return self.instance.store.paths.derived_artifacts.parent / (
            "ai-classification-" + job_id + ".json"
        )

    def project(self, job, result):
        # Called by AiJobs under the original lifecycle/journal transaction after
        # known call settlement, before terminal result/receipt publication.
        saved = self.setup.jobs.journal.get_job(job["id"])
        check(saved is not None and saved["status"] == job["status"] == "running"
              and saved["ai"]["terminal"] is None and job["ai"]["terminal"] is None
              and saved["lease"] == job["lease"]
              and saved["ai"]["binding"] == job["ai"]["binding"], "ai_result_invalid")
        ai = job["ai"]
        inputs, request, profile = self.setup.jobs._inputs(ai["request_ref"], ai["route"])
        check(inputs.plan.binding == ai["binding"]
              and canonical_json_bytes(request.as_record()) == canonical_json_bytes(ai["request"]),
              "ai_setup_stale")
        template = inputs.current["template"]
        check(template.id in CLASSIFICATION_TEMPLATES)
        allowlist = tuple((t.kind, t.id) for t in template.targets)
        targets = resolve_classification_targets(
            self.instance.store, inputs.source.version.document_id, allowlist,
        )
        language = template.id.removeprefix("classification-").removesuffix("-v1")
        check(targets.template(language) == template
              and classification_request_ref(inputs.preview, targets) == ai["request_ref"],
              "ai_setup_stale")
        check(any(s.kind == Scope.SOURCE and s.id == targets.source_id
                  for s in inputs.current["snapshot"].scopes), "ai_context_mismatch")
        first = inputs.selections[0]
        document, _, source = self.setup.synthesis.source(
            first.version.document_id, first.representation_id, first.output_id,
        )
        check(source == inputs.source, "ai_context_mismatch")
        if result["kind"] == "untrusted_text":
            check(type(result["value"]) is str)
            raw = result["value"].encode("utf-8")
        else:
            check(result["kind"] == "context_check")
            value = result["value"]
            check(type(value) is dict and set(value) == {
                "schema_version", "preview_fingerprint", "template", "status", "references",
                "target", "authority",
            })
            raw = canonical_json_bytes({k: value[k] for k in (
                "schema_version", "preview_fingerprint", "status", "references", "target",
            )})
        assessed = validate_candidate(raw, inputs.preview, source, inputs.selections,
                                      **inputs.current)
        if result["kind"] == "context_check":
            check(canonical_json_bytes(assessed.as_record())
                  == canonical_json_bytes(result["value"]), "ai_result_invalid")
        check(profile.fingerprint == ai["attempts"][-1]["route"], "ai_route_changed")
        recipe = {
            "template": template.id, "template_revision": template.identity.revision,
            "redaction_revision": digest(inputs.current["redaction"].as_record()),
            "selections": [s.as_record() for s in inputs.selections],
            "allowlist": [list(p) for p in allowlist], "target_revision": targets.revision,
        }
        association, _, _, _ = self.setup.synthesis.association(
            document, source, recipe, template=template,
        )
        targets.revalidate(self.instance.store)
        body = {
            "schema_version": 1, "job_id": job["id"], "source": source.version.as_record(),
            "assessment": assessed.as_record(), "target_revision": targets.revision,
            "segments": [s.as_record() for s in inputs.preview.segments],
            "coverage": inputs.preview.manifest.coverage,
            "policy_fingerprint": inputs.plan.policy_fingerprint,
            "classification_quality": "NOT_EVALUATED", "confidence": None,
            "automation_authorized": False, "canonical_mutation": False,
        }
        raw_body = canonical_json_bytes(body)
        check(len(raw_body) <= MAX_RESULT_BYTES, "ai_limit_exceeded")
        path = self.path(job["id"])
        check(len(list(islice(path.parent.glob("ai-classification-job_*.json"),
                              MAX_RESULTS + 1))) < MAX_RESULTS, "ai_limit_exceeded")
        reference = {
            "schema_version": 1, "recipe": recipe, "association": association,
            "body_sha256": digest(body), "route": profile.fingerprint, "model": profile.model,
            "execution": "external" if job["control"]["network_used"] else "local",
        }
        validate_reference(reference)
        result = {"kind": "classification_ref", "value": reference}
        check(len(json.dumps(result).encode()) <= MAX_RESULT_BYTES, "ai_limit_exceeded")
        write_local_bytes(path, raw_body)
        return result

    def reference(self, job_id):
        self.path(job_id)
        job = self.setup.jobs.journal.get_job(job_id)
        check(job is not None and job["job_kind"] == "ai.execute"
              and job["status"] == "succeeded" and job["ai"]["terminal"] == "succeeded",
              "ai_result_unavailable")
        receipt = self.setup.jobs.journal.get_receipt(
            "receipt_" + job_id.removeprefix("job_"))
        check(receipt is not None and _receipt_matches_terminal_job(receipt, job),
              "ai_result_invalid")
        result = job["ai"]["result"]
        check(result is not None and result["kind"] == "classification_ref",
              "ai_result_unavailable")
        selections = validate_reference(result["value"])
        check(selections[0].version.instance_id == self.setup.instance_id, "ai_wrong_instance")
        check(job["ai"]["request"]["template"] == {
            "schema_version": 1, "id": result["value"]["recipe"]["template"],
            "revision": result["value"]["recipe"]["template_revision"],
        }, "ai_result_invalid")
        check(result["value"]["route"] == job["ai"]["attempts"][-1]["route"],
              "ai_result_invalid")
        return job, result["value"], selections

    def read(self, job_id):
        with self.setup.jobs._transaction(wait_seconds=2):
            job, ref, selections = self.reference(job_id)
            first = selections[0]
            document, _, source = self.setup.synthesis.source(
                first.version.document_id, first.representation_id, first.output_id,
            )
            check(source.version == first.version, "ai_setup_stale")
            recipe = ref["recipe"]
            allowlist = tuple(tuple(p) for p in recipe["allowlist"])
            targets = resolve_classification_targets(
                self.instance.store, first.version.document_id, allowlist)
            check(targets.revision == recipe["target_revision"], "ai_setup_stale")
            language = recipe["template"].removeprefix("classification-").removesuffix("-v1")
            template = targets.template(language)
            check(template.identity.revision == recipe["template_revision"], "ai_setup_stale")
            association, _, _, _ = self.setup.synthesis.association(
                document, source, recipe, template=template)
            check(association == ref["association"], "ai_setup_stale")
            with open_local_file(self.path(job_id)) as stream:
                raw = stream.read(MAX_RESULT_BYTES + 1)
            body = _json(raw, MAX_RESULT_BYTES)
            check(type(body) is dict and set(body) == {
                "schema_version", "job_id", "source", "assessment", "target_revision", "segments",
                "coverage", "policy_fingerprint", "classification_quality", "confidence",
                "automation_authorized", "canonical_mutation",
            }, "ai_result_invalid")
            check(digest(body) == ref["body_sha256"] and body["job_id"] == job_id
                  and VersionIdentity(**body["source"]) == source.version
                  and body["target_revision"] == targets.revision, "ai_result_invalid")
            targets.revalidate(self.instance.store)
            return body, ref, document, job, targets

    def discard(self, job_id):
        # No source/policy/model/consent renewal, refund, queue write or regeneration.
        # The terminal job cannot enter the projector again; deletion frees its slot.
        with self.setup.jobs._transaction(wait_seconds=2):
            self.reference(job_id)
            with pinned_parent(self.path(job_id)) as (path, parent):
                if os.name == "nt":
                    path.unlink(missing_ok=True)
                else:
                    with suppress(FileNotFoundError):
                        os.unlink(path.name, dir_fd=parent)
