"""Manual, private, disposable document excerpts bound to current evidence (S08)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from contextlib import suppress
from dataclasses import asdict
from itertools import islice

from .ai_context import (
    SYNTHESIS_TEMPLATES,
    OutputBytes,
    RedactionConfig,
    Selection,
    SourceSnapshot,
    TaskTemplate,
    VersionIdentity,
    _json,
    validate_candidate,
)
from .ai_contract import Scope, ScopeRef, digest
from .ai_job_contract import check, fingerprint
from .maintenance_local_files import (
    MaintenanceTargetError,
    open_local_file,
    pinned_parent,
    write_local_bytes,
)
from .representations import (
    canonical_json_bytes,
    safe_instance_path,
    validate_representation_bundle,
)

MAX_SOURCE = 1024 * 1024
MAX_TEXT = 2000
MAX_SEGMENTS = 16
MAX_RESULTS = 128
MAX_RESULT_BYTES = 32768


def validate_reference(value):
    check(type(value) is dict and set(value) == {
        "schema_version", "recipe", "association", "body_sha256", "route", "model", "execution",
    })
    check(type(value["schema_version"]) is int and value["schema_version"] == 1)
    for name in ("association", "body_sha256", "route"):
        fingerprint(value[name])
    check(type(value["model"]) is str and 0 < len(value["model"]) <= 512)
    check(value["execution"] in {"local", "external"})
    recipe = value["recipe"]
    check(type(recipe) is dict and set(recipe) == {
        "template", "template_revision", "redaction_revision", "selections",
    })
    check(type(recipe["template"]) is str and recipe["template"] in SYNTHESIS_TEMPLATES)
    fingerprint(recipe["template_revision"])
    fingerprint(recipe["redaction_revision"])
    check(type(recipe["selections"]) is list and 1 <= len(recipe["selections"]) <= MAX_SEGMENTS)
    selections = tuple(Selection.from_bytes(canonical_json_bytes(s)) for s in recipe["selections"])
    check(len({s.version for s in selections}) == 1)
    check(len({(s.representation_id, s.output_id) for s in selections}) == 1)
    return selections


class DocumentSynthesis:
    def __init__(self, setup):
        self.setup = setup
        self.instance = setup.instance
        self.policy_path = setup.path.with_name("ai-scope-policies.json")

    def policies(self):
        check(self.instance.store.read_config()["instance"]["id"] == self.setup.instance_id,
              "ai_wrong_instance")
        try:
            with open_local_file(self.policy_path) as stream:
                raw = stream.read(32769)
        except MaintenanceTargetError as exc:
            if exc.code != "target_missing":
                raise
            return {"schema_version": 1, "instance_id": self.setup.instance_id,
                    "revision": 0, "rules": []}
        check(len(raw) <= 32768)
        return self.validate_policies(json.loads(raw), self.setup.instance_id)

    @staticmethod
    def validate_policies(value, instance_id):
        check(type(value) is dict and set(value) == {
            "schema_version", "instance_id", "revision", "rules",
        })
        check(type(value["schema_version"]) is int and value["schema_version"] == 1)
        check(value["instance_id"] == instance_id, "ai_wrong_instance")
        check(type(value["revision"]) is int and value["revision"] >= 0)
        check(type(value["rules"]) is list and len(value["rules"]) <= 128)
        keys = []
        for row in value["rules"]:
            check(type(row) is dict and set(row) == {"kind", "id", "restriction"})
            scope = ScopeRef(Scope(row["kind"]), row["id"])
            check(row["restriction"] in {"deny", "local_only"})
            keys.append((scope.kind, scope.id))
        check(len(keys) == len(set(keys)))
        return value

    def restrict(self, document_id, kind, scope_id, restriction, revision):
        check(restriction in {"inherit", "deny", "local_only"})
        with self.setup.lock:
            def update():
                document = self.instance.get_document(document_id)
                check(document is not None)
                scopes, _ = self.setup.document_governance(document)
                scope = ScopeRef(Scope(kind), scope_id)
                check(scope in scopes)
                current = self.policies()
                check(current["revision"] == revision, "ai_setup_stale")
                rows = [r for r in current["rules"] if (r["kind"], r["id"]) != (kind, scope_id)]
                if restriction != "inherit":
                    rows.append(dict(kind=kind, id=scope_id, restriction=restriction))
                check(len(rows) <= 128, "ai_limit_exceeded")
                value = {**current, "revision": revision + 1, "rules": rows}
                write_local_bytes(self.policy_path, canonical_json_bytes(value), replace=True)
                self.setup.previews.clear()
            self.setup.jobs.change_authority(update)

    def source(self, document_id, representation_id, output_id):
        check(self.instance.store.read_config()["instance"]["id"] == self.setup.instance_id,
              "ai_wrong_instance")
        document = self.instance.get_document(document_id)
        check(document is not None and document["current_version"] is not None,
              "ai_context_mismatch")
        version = document["current_version"]
        original = self.instance.store.read_canonical("originals", version["original_id"])
        check(original is not None and original["size_bytes"] <= MAX_SOURCE, "ai_limit_exceeded")
        # The generic bundle reader hashes the whole Original. This profile first
        # bounds the actual bytes, including an externally grown Original, and
        # independently binds all canonical Version/Original fields.
        original_path = safe_instance_path(self.instance.root, original["storage_ref"])
        with open_local_file(original_path) as stream:
            original_bytes = stream.read(MAX_SOURCE + 1)
        check(len(original_bytes) <= MAX_SOURCE, "ai_limit_exceeded")
        check(len(original_bytes) == original["size_bytes"]
              and hashlib.sha256(original_bytes).hexdigest() == original["sha256"]
              and version["content_hash"] == original["sha256"], "ai_context_mismatch")
        bundle = self.bundle(representation_id)
        check(bundle["version"] == {
            "id": version["id"], "original_id": version["original_id"],
            "original_sha256": original["sha256"], "original_size_bytes": original["size_bytes"],
        }, "ai_context_mismatch")
        output = next((o for o in bundle["outputs"] if o["id"] == output_id), None)
        check(output is not None and output["media_type"] == "text/plain"
              and output["size_bytes"] <= MAX_SOURCE, "ai_context_mismatch")
        path = safe_instance_path(self.instance.root, output["storage_ref"])
        with open_local_file(path) as stream:
            raw = stream.read(MAX_SOURCE + 1)
        check(len(raw) <= MAX_SOURCE, "ai_limit_exceeded")
        identity = VersionIdentity(self.setup.instance_id, document_id, **{
            "version_id": bundle["version"]["id"],
            **{k: bundle["version"][k] for k in (
                "original_id", "original_sha256", "original_size_bytes",
            )},
        })
        return document, bundle, SourceSnapshot(
            identity, (canonical_json_bytes(bundle),),
            (OutputBytes(representation_id, output_id, raw),),
        )

    def bundle(self, representation_id):
        check(type(representation_id) is str
              and re.fullmatch(r"repr_[a-f0-9]{64}", representation_id), "ai_context_mismatch")
        path = self.instance.representations.bundles.root / representation_id / "bundle.json"
        with open_local_file(path) as stream:
            raw = stream.read(128 * 1024 + 1)
        bundle = validate_representation_bundle(_json(raw, 128 * 1024))
        check(bundle["representation_id"] == representation_id, "ai_context_mismatch")
        return bundle

    def choices(self, document_id):
        document = self.instance.get_document(document_id)
        check(document is not None and document["current_version"] is not None)
        choices = []
        paths = self.instance.representations.bundles.root.glob("repr_*/bundle.json")
        for index, path in enumerate(paths):
            check(index < 500, "ai_limit_exceeded")
            bundle = self.bundle(path.parent.name)
            if bundle["version"]["id"] != document["current_version"]["id"]:
                continue
            for output in bundle["outputs"]:
                if output["media_type"] == "text/plain" and output["size_bytes"] <= MAX_SOURCE:
                    choices.append((bundle["representation_id"], output["id"]))
        return document, sorted(choices)

    def association(self, document, source, recipe):
        # Bound inventory before the existing complete association collector reads it.
        for kind in ("acquisitions", "hierarchy", "classifications", "sources"):
            paths = self.instance.store.paths.canonical_dir(kind).glob("*.json")
            check(len(list(islice(paths, 513))) <= 512, "ai_limit_exceeded")
        governance = self.setup.document_governance(document)
        policies = self.policies()
        network = self.instance.store.read_config()["network"]["external_access"]
        check(type(network) is bool, "ai_missing_policy")
        association = digest({
            "source": {
                "version": asdict(source.version),
                "bundles": [hashlib.sha256(b).hexdigest() for b in source.bundles],
                "outputs": [(o.representation_id, o.output_id,
                             hashlib.sha256(o.data).hexdigest()) for o in source.outputs],
            }, "recipe": recipe,
            "governance": governance[1], "policies": policies,
            "configuration": self.setup.configuration(), "network": network,
            "current_template": TaskTemplate(recipe["template"], True).identity.revision,
            "current_redaction": digest(RedactionConfig().as_record()),
        })
        return association, governance, policies, network

    def preview(self, document_id, representation_id, output_id, task, language):
        check(task in {"summary", "key-points"} and language in {"en", "it"})
        with self.setup.lock:
            self.setup._expire()
            if len(self.setup.previews) >= 32:
                unused = [(row["created"], key) for key, row in self.setup.previews.items()
                          if "recipe" in row and not row["approved"]]
                if not unused:
                    for key, row in self.setup.previews.items():
                        if "recipe" in row and row["job"]:
                            job = self.setup.jobs.journal.get_job(row["job"])
                            if job is not None and job["status"] == "succeeded":
                                unused.append((row["created"], key))
                if unused:
                    del self.setup.previews[min(unused)[1]]
            check(len(self.setup.previews) < 32, "ai_preview_capacity")
            document, bundle, source = self.source(document_id, representation_id, output_id)
            text = source.outputs[0].data.decode("utf-8")
            selections, offset, size = [], 0, 0
            anchors = {a["target"]["page"]: a["id"] for a in bundle["anchors"]
                       if a["kind"] == "page"}
            # Whole paragraphs preserve conditions and negations; never truncate a
            # paragraph to fit. Offsets precede normalization/redaction and remain exact.
            for page, content in enumerate(text.split("\f"), 1):
                for match in re.finditer(r"[^\r\n]+(?:(?:\r\n|\r|\n)(?![\r\n])[^\r\n]+)*", content):
                    part = match.group()
                    length = len(part.encode("utf-8"))
                    if not part.strip() or page not in anchors:
                        continue
                    if size + length > MAX_TEXT or len(selections) >= MAX_SEGMENTS:
                        continue
                    selections.append(Selection(source.version, representation_id, digest(bundle),
                                                output_id, anchors[page],
                                                offset + match.start(), offset + match.end()))
                    size += length
                offset += len(content) + 1
            check(selections, "ai_limit_exceeded")
            template = TaskTemplate(f"{task}-{language}-v1", True)
            recipe = {"template": template.id, "template_revision": template.identity.revision,
                      "redaction_revision": digest(RedactionConfig().as_record()),
                      "selections": [s.as_record() for s in selections]}
            association, governance, policies, network = self.association(document, source, recipe)
            key = secrets.token_hex(32)
            configuration = self.setup.configuration()
            prepared = self.setup.prepare(
                key, source, tuple(selections), configuration=configuration,
                governance=governance, template=TaskTemplate(recipe["template"], True),
                scope_policy=policies, external_access=network,
            )
            self.setup.previews[key] = dict(
                created=time.monotonic(), configuration=configuration, source=source,
                selections=tuple(selections), prepared=prepared, approved=False, job=None,
                generation=self.setup.jobs._control()["generation"], recipe=recipe,
                association=association,
            )
            return key, prepared, document

    def revalidate(self, row):
        selection = row["selections"][0]
        document, _, source = self.source(selection.version.document_id,
                                         selection.representation_id, selection.output_id)
        association, _, _, _ = self.association(document, source, row["recipe"])
        check(source == row["source"] and association == row["association"], "ai_setup_stale")

    def path(self, job_id):
        check(type(job_id) is str and re.fullmatch(r"job_[0-9a-f]{32}", job_id), "ai_job_invalid")
        # Existing portable derived directory; no unchecked mkdir or payload in jobs.
        return self.instance.store.paths.derived_artifacts.parent / (
            "ai-synthesis-" + job_id + ".json"
        )

    def project(self, job, result):
        row = self.setup.previews.get(job["ai"]["request_ref"])
        if row is None or "recipe" not in row:
            return result
        self.revalidate(row)
        prepared = row["prepared"]
        if result["kind"] == "untrusted_text":
            raw = result["value"].encode("utf-8")
        else:
            check(result["kind"] == "context_check")
            value = result["value"]
            check(value["preview_fingerprint"] == prepared[0].fingerprint)
            check(value["template"] == prepared[0].manifest.template.as_record())
            raw = canonical_json_bytes({k: value[k]
                                        for k in ("schema_version", "status", "references")})
        candidate = validate_candidate(raw, prepared[0], row["source"], row["selections"],
                                       **prepared[2])
        body = {"schema_version": 1, "job_id": job["id"],
                "status": candidate.status, "references": list(candidate.references),
                "segments": [s.as_record() for s in prepared[0].segments],
                "coverage": prepared[0].manifest.coverage}
        raw_body = canonical_json_bytes(body)
        check(len(raw_body) <= MAX_RESULT_BYTES, "ai_limit_exceeded")
        path = self.path(job["id"])
        check(len(list(islice(path.parent.glob("ai-synthesis-job_*.json"), MAX_RESULTS + 1)))
              < MAX_RESULTS, "ai_limit_exceeded")
        route = job["ai"]["attempts"][-1]["route"]
        profile = next(p for p in prepared[3] if p.fingerprint == route)
        reference = dict(schema_version=1, recipe=row["recipe"], association=row["association"],
                         body_sha256=digest(body), route=route, model=profile.model,
                         execution="external" if job["control"]["network_used"] else "local")
        validate_reference(reference)
        write_local_bytes(path, raw_body)
        return {"kind": "derived_ref", "value": reference}

    def reference(self, job_id):
        job = self.setup.jobs.journal.get_job(job_id)
        check(job is not None and job["job_kind"] == "ai.execute"
              and job["ai"]["terminal"] == "succeeded", "ai_result_unavailable")
        result = job["ai"]["result"]
        check(result is not None and result["kind"] == "derived_ref", "ai_result_unavailable")
        selections = validate_reference(result["value"])
        check(selections[0].version.instance_id == self.setup.instance_id, "ai_wrong_instance")
        return job, result["value"], selections

    def read(self, job_id):
        # Return one validated snapshot: supported ingestion, policy changes,
        # discard and Instance replacement cannot commit halfway through this read.
        with self.setup.jobs._transaction(wait_seconds=2):
            return self._read_locked(job_id)

    def _read_locked(self, job_id):
        job, ref, selections = self.reference(job_id)
        first = selections[0]
        document, _, source = self.source(first.version.document_id, first.representation_id,
                                         first.output_id)
        association, governance, policies, network = self.association(
            document, source, ref["recipe"],
        )
        check(association == ref["association"], "ai_setup_stale")
        with open_local_file(self.path(job_id)) as stream:
            raw = stream.read(MAX_RESULT_BYTES + 1)
        check(len(raw) <= MAX_RESULT_BYTES, "ai_limit_exceeded")
        body = json.loads(raw)
        check(type(body) is dict and set(body) == {
            "schema_version", "job_id", "status", "references", "segments", "coverage",
        })
        check(digest(body) == ref["body_sha256"] and body["job_id"] == job_id,
              "ai_result_invalid")
        prepared = self.setup.prepare(
            "stored-result-read", source, selections,
            configuration=self.setup.configuration(), governance=governance,
            template=TaskTemplate(ref["recipe"]["template"], True),
            scope_policy=policies, external_access=network,
        )
        check(body["segments"] == [s.as_record() for s in prepared[0].segments]
              and body["coverage"] == prepared[0].manifest.coverage, "ai_result_invalid")
        validate_candidate(canonical_json_bytes({k: body[k]
                           for k in ("schema_version", "status", "references")}),
                           prepared[0], source, selections, **prepared[2])
        return body, ref, document, job

    def discard(self, job_id):
        with self.setup.jobs._transaction():
            self.reference(job_id)  # Stale source/policy does not prevent deletion.
            with pinned_parent(self.path(job_id)) as (path, parent):
                if os.name == "nt":
                    path.unlink(missing_ok=True)
                else:
                    with suppress(FileNotFoundError):
                        os.unlink(path.name, dir_fd=parent)

    def regenerate(self, job_id):
        _, reference, selections = self.reference(job_id)
        first = selections[0]
        task, language, _ = reference["recipe"]["template"].rsplit("-", 2)
        return self.preview(first.version.document_id, first.representation_id,
                            first.output_id, task, language)
