"""Exact-version processing requests in the existing durable scheduler only."""

import re
from pathlib import Path

from . import __version__
from .action_center_model import digest
from .maintenance_local_files import open_local_file
from .paths import safe_instance_path
from .processing_autonomy import OPERATIONS, ProcessingReview, scoped_inputs
from .review_authority import ReviewAuthority
from .review_effects import ReviewDenied, ReviewError, ReviewStale, ReviewUnavailable, sha256
from .review_integrity import CAPABILITIES
from .review_routing import _Inputs
from .review_routing_model import identifier
from .scheduler_model import SchedulerBusyError, SchedulerError

JOB_KIND = "processing.execute"
_FIELDS = {"schema_version", "kind", "instance_id", "scope", "parameters",
           "input_revision", "plan_revision"}
_PARAMETERS = {"version_id", "operation", "policy_receipt", "permit_receipt", "versions"}


def validate_plan(value):
    try:
        if (not isinstance(value, dict) or set(value) != _FIELDS
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["kind"] != JOB_KIND
                or not isinstance(value["instance_id"], str)
                or re.fullmatch(r"inst_[0-9a-f]{32}", value["instance_id"]) is None
                or not isinstance(value["scope"], dict)
                or set(value["scope"]) != {"kind", "id"}
                or value["scope"]["kind"] != "source"
                or not isinstance(value["parameters"], dict)
                or set(value["parameters"]) != _PARAMETERS):
            raise ValueError("plan fields")
        identifier(value["scope"]["id"], "source")
        parameters = value["parameters"]
        identifier(parameters["version_id"], "version")
        versions = parameters["versions"]
        if not isinstance(versions, dict) or not 1 <= len(versions) <= 500:
            raise ValueError("Version scope")
        for document_id, version_id in versions.items():
            identifier(document_id, "document")
            identifier(version_id, "version")
        if parameters["version_id"] not in versions.values():
            raise ValueError("selected Version is outside scope")
        if (not isinstance(parameters["operation"], str)
                or parameters["operation"] not in OPERATIONS):
            raise ValueError("unsupported operation")
        for field in ("policy_receipt", "permit_receipt"):
            selected = parameters[field]
            if selected is None and field == "permit_receipt":
                continue
            if (not isinstance(selected, str)
                    or re.fullmatch(r"review_[0-9a-f]{32}", selected) is None):
                raise ValueError("review identity")
        if (not isinstance(value["input_revision"], str)
                or re.fullmatch(r"[0-9a-f]{64}", value["input_revision"]) is None
                or value["plan_revision"] != digest(
                    {k: v for k, v in value.items() if k != "plan_revision"})):
            raise ValueError("plan digest")
    except (TypeError, KeyError, ValueError) as exc:
        raise SchedulerError("Processing execution plan is invalid") from exc
    return dict(value)


def with_permit(plan, receipt_id):
    result = {**plan, "parameters": {**plan["parameters"], "permit_receipt": receipt_id}}
    result["plan_revision"] = digest({k: v for k, v in result.items() if k != "plan_revision"})
    return result


def _text_inventory(store):
    relative = store.paths.derived_artifacts.relative_to(store.paths.root).as_posix()
    return _Inputs(store).inventory(relative, 5000)


def _text_artifact(inventory, version_id):
    matches = [row for row in inventory.values()
               if row.get("version_id") == version_id and row.get("kind") == "extracted_text"]
    if not matches:
        return None
    if len(matches) != 1:
        raise ReviewUnavailable("Extracted text identity is ambiguous")
    row = matches[0]
    if (set(row) != {"id", "version_id", "kind", "generator", "generator_version",
                     "storage_ref", "checksum", "created_at"}
            or not isinstance(row["id"], str)
            or re.fullmatch(r"derived_[0-9a-f]{32}", row["id"]) is None
            or row["storage_ref"] != f"state/derived/text/{row['id']}.txt"
            or not isinstance(row["checksum"], str)
            or re.fullmatch(r"[0-9a-f]{64}", row["checksum"]) is None):
        raise ReviewUnavailable("Extracted text has an invalid closed identity")
    return row


class ProcessingJobs:
    def __init__(self, store, *, coordinator=None, review=None):
        from .scheduler import SchedulerCoordinator

        self.store = store
        self.coordinator = coordinator or SchedulerCoordinator(store)
        self.journal = self.coordinator.journal
        self.review = review or ProcessingReview(store)

    def plan(self, source_id, version_id, operation, *, manual=False):
        inputs, policy, document, version, original = scoped_inputs(
            self.store, source_id, version_id, operation, review=self.review,
        )
        authority = ReviewAuthority(self.store, CAPABILITIES).resolve(
            "processing", source_id, "run",
        )
        if (authority["mode"] not in {"confirm-each", "controlled-automatic"}
                or (not manual and policy["mode"] != "controlled-automatic")):
            raise ReviewDenied("A current independent processing authorization is required")
        # Only existing managed filesystem Originals enter generic extractors.
        source = inputs.record(f"knowledge/sources/{source_id}.json")
        if source["kind"] != "filesystem":
            raise ReviewDenied("This Source retains its dedicated derivation controls")
        inputs.hashes["authority"] = authority["revision"]
        versions = {document["id"]: version_id}
        if operation in {"representation", "index"}:
            artifacts = _text_inventory(self.store)
            artifact = _text_artifact(artifacts, version_id)
            if artifact is None:
                raise ReviewUnavailable("Extract text before representation or indexing")
            inputs.hashes["derived-artifact"] = digest(artifact)
        if operation == "index":
            # FTS is one cache. Review every current Version of this Source and
            # update that exact set together, never silently widen to the Instance.
            from .retention_model import effective_dispositions
            from .review_routing import _document

            documents = inputs.inventory("knowledge/documents", 500)
            dispositions = effective_dispositions(self.store)
            versions, total = {}, 0
            for row in documents.values():
                if row["source_id"] != source_id:
                    continue
                disposition = dispositions[row["id"]]
                if (disposition["status"] != "active"
                        or disposition["library_visibility"] != "included"):
                    continue
                prefix = policy["path_prefix"]
                if (prefix and row["locator"] != prefix
                        and not row["locator"].startswith(prefix + "/")):
                    continue
                scoped, current, original = _document(inputs, row["id"])
                if type(original["size_bytes"]) is not int or original["size_bytes"] < 0:
                    raise ReviewUnavailable("A scoped Original has an invalid resource size")
                artifact = _text_artifact(artifacts, current["id"])
                if artifact is None:
                    raise ReviewUnavailable("Extract all reviewed Source Versions before indexing")
                total += original["size_bytes"]
                if total > policy["max_input_bytes"]:
                    raise ReviewDenied("Source index input exceeds its reviewed resource limit")
                inputs.hashes["derived:" + current["id"]] = digest(artifact)
                versions[scoped["id"]] = current["id"]
        result = {
            "schema_version": 1, "kind": JOB_KIND, "instance_id": self.journal.instance_id,
            "scope": {"kind": "source", "id": source_id},
            "parameters": {"version_id": version_id, "operation": operation,
                           "policy_receipt": policy["last_receipt"], "permit_receipt": None,
                           "versions": dict(sorted(versions.items()))},
            "input_revision": digest(inputs.hashes),
        }
        result["plan_revision"] = digest(result)
        return validate_plan(result)

    def _current(self, plan):
        validate_plan(plan)
        p = plan["parameters"]
        current = self.plan(plan["scope"]["id"], p["version_id"], p["operation"],
                            manual=p["permit_receipt"] is not None)
        if p["permit_receipt"] is not None:
            history, _ = self.review.history_record(p["permit_receipt"], _Inputs(self.store))
            if history["action"] != "run" or history["execution"] != current:
                raise ReviewStale("The exact processing confirmation is stale")
        if with_permit(current, p["permit_receipt"]) != plan:
            raise ReviewStale("Processing inputs or reviewed authority changed")
        return self.review.policy(plan["scope"]["id"])

    def _usage(self, policy):
        # Scheduler jobs, including failed/cancelled reservations, are the only
        # execution ledger. Retrying/restarting cannot reset a reviewed budget.
        return sum(
            job["job_kind"] == JOB_KIND
            and job.get("execution_plan", {}).get("parameters", {}).get("policy_receipt")
            == policy["last_receipt"]
            for job in self.journal._all_jobs()
        )

    def queue(self, source_id, version_id, operation, *, permit_receipt=None,
              expected_plan_revision=None):
        from .scheduler import retry_payload, schedule_payload

        with self.coordinator._hold_lifecycle("processing-enqueue"):
            plan = with_permit(self.plan(source_id, version_id, operation,
                                         manual=permit_receipt is not None), permit_receipt)
            if expected_plan_revision is not None and plan["plan_revision"] != (
                expected_plan_revision
            ):
                raise ReviewStale("Processing preview changed before enqueue")
            policy = self._current(plan)
            key = "processing:" + plan["plan_revision"]
            rows = [row for row in self.journal.list_policies()
                    if row["job_kind"] == JOB_KIND and row["scope"]["id"] == source_id]
            if len(rows) > 1 or (rows and (rows[0]["state"] != "disabled"
                                          or rows[0]["schedule"]["mode"] != "manual")):
                raise ReviewUnavailable("Processing has conflicting scheduler policies")
            if self._usage(policy) >= policy["max_jobs"]:
                # An exact replay may still return its existing reservation.
                existing = [j for j in self.journal._all_jobs()
                            if j["job_kind"] == JOB_KIND and j.get("execution_plan") == plan]
                if not existing:
                    raise ReviewDenied("Reviewed processing budget is exhausted")
            selected = rows[0] if rows else self.journal.create_policy(
                job_kind=JOB_KIND, scope=plan["scope"], state="disabled",
                schedule=schedule_payload(mode="manual", timezone="UTC"),
                retry=retry_payload(max_attempts=2, base_seconds=1),
            )
            return self.journal.run_now(selected["id"], request_key=key, execution_plan=plan)

    def control_state(self, plan):
        try:
            policy = self._current(plan)
            used = self._usage(policy)
            return {"resumable": used <= policy["max_jobs"],
                    "restartable": used < policy["max_jobs"],
                    "plan_revision": plan["plan_revision"], "execution_plan": plan}
        except (ReviewError, OSError, ValueError, TypeError, KeyError):
            return {"resumable": False, "restartable": False, "execution_plan": plan}

    def reconcile_automatic(self, *, limit=20):
        """Reconcile current policy/Version identities into the one existing queue.

        No cursor or second execution ledger is created. Repeating after restart
        returns the existing deterministic reservation for the same exact inputs.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ReviewError("Processing reconciliation limit must be between one and 100")
        result = {"queued": [], "blocked": 0, "complete": True}
        try:
            policies = self.review.policies()
        except (ReviewError, OSError, ValueError, KeyError, TypeError):
            return {**result, "blocked": 1, "complete": False}
        if not policies:
            return result
        inputs = _Inputs(self.store)
        try:
            documents = inputs.inventory("knowledge/documents", 500)
        except (ReviewError, OSError, ValueError, KeyError, TypeError):
            return {**result, "blocked": 1, "complete": False}
        for policy in policies:
            if policy["mode"] != "controlled-automatic":
                continue
            prefix = policy["path_prefix"]
            scoped_documents = [doc for doc in documents.values()
                                if doc["source_id"] == policy["id"] and (
                                    not prefix or doc["locator"] == prefix
                                    or doc["locator"].startswith(prefix + "/"))]
            for document in scoped_documents:
                if document["source_id"] != policy["id"]:
                    continue
                for operation in OPERATIONS:
                    if operation not in policy["operations"]:
                        continue
                    if operation == "index" and document != scoped_documents[0]:
                        continue
                    try:
                        queued = self.queue(policy["id"], document["current_version_id"], operation)
                    except (ReviewError, SchedulerError, SchedulerBusyError, OSError, ValueError,
                            KeyError, TypeError):
                        result["blocked"] += 1
                        continue
                    if queued["created"]:
                        result["queued"].append(queued["job"]["id"])
                    if len(result["queued"]) >= limit:
                        result["complete"] = False
                        return result
                    if queued["job"]["status"] != "succeeded":
                        # A prerequisite owns its existing reservation, including
                        # pause/failure. Do not enqueue dependent work ahead of it.
                        break
        return result

    def execute(self, job):
        """The scheduler owns lifecycle and its lease; every write is derived."""
        from .derived import materialize_extracted_text
        from .extractors import ExtractionError, extractor_for
        from .index import refresh_search_index
        from .representations import RepresentationBundleManager

        plan = job.get("execution_plan")
        policy = self._current(plan)
        if self._usage(policy) > policy["max_jobs"]:
            raise ReviewDenied("Reviewed processing budget is exhausted")
        p = plan["parameters"]
        _inputs, _policy, document, version, original = scoped_inputs(
            self.store, plan["scope"]["id"], p["version_id"], p["operation"], review=self.review,
        )
        self.coordinator._cooperative_boundary(job)
        path = safe_instance_path(self.store.paths.root, original["storage_ref"])
        with open_local_file(path) as stream:
            raw = stream.read(policy["max_input_bytes"] + 1)
        if len(raw) != original["size_bytes"] or sha256(raw) != original["sha256"]:
            raise ReviewUnavailable("Processing Original bytes differ from reviewed identity")
        text, artifact = None, None
        if p["operation"] == "extract":
            extractor = extractor_for(Path(document["locator"]))
            if extractor is None:
                raise ReviewDenied("No supported deterministic extractor")
            try:
                extraction = extractor.extract(raw)
            except ExtractionError as exc:
                raise ReviewUnavailable("The bounded local extraction failed") from exc
            if len(extraction.text.encode("utf-8")) > policy["max_input_bytes"]:
                raise ReviewDenied("Extracted text exceeds the reviewed processing resource limit")
        else:
            artifacts = _text_inventory(self.store)
            artifact = _text_artifact(artifacts, version["id"])
            if artifact is None:
                raise ReviewUnavailable("Current extracted text is missing")
            with open_local_file(safe_instance_path(self.store.paths.root,
                                                    artifact["storage_ref"])) as stream:
                text = stream.read(policy["max_input_bytes"] + 1)
            if len(text) > policy["max_input_bytes"] or sha256(text) != artifact["checksum"]:
                raise ReviewUnavailable("Processing text checksum or resource limit differs")
            text.decode("utf-8", errors="strict")
            if p["operation"] == "index":
                total = 0
                for version_id in p["versions"].values():
                    current = _text_artifact(artifacts, version_id)
                    if current is None:
                        raise ReviewUnavailable("A reviewed Source text is missing")
                    with open_local_file(safe_instance_path(
                        self.store.paths.root, current["storage_ref"],
                    )) as stream:
                        body = stream.read(policy["max_input_bytes"] + 1)
                    total += len(body)
                    if total > policy["max_input_bytes"] or sha256(body) != current["checksum"]:
                        raise ReviewUnavailable("Source text checksum or resource limit differs")
                    body.decode("utf-8", errors="strict")
        # Recheck host-owned inputs after potentially expensive reads/extraction.
        # Pending pause/cancel wins before the first derived write.
        self._current(plan)
        self.coordinator._cooperative_boundary(job, commit=True)
        if p["operation"] == "extract":
            materialize_extracted_text(self.store, version["id"], extraction)
        elif p["operation"] == "representation":
            RepresentationBundleManager(self.store)._materialize_locked(
                version["id"], recipe_id="provelume.local-text", recipe_version="1",
                recipe_settings={"artifact_sha256": artifact["checksum"], "normalization": "none"},
                output_payloads={"text.txt": ("text/plain", text)},
                implementation={"component": "provelume.core", "component_version": __version__,
                                "adapter": "local-text", "adapter_version": "1",
                                "settings": {"mode": "offline"}},
                anchor_targets=({"kind": "page", "page": 1},),
            )
        else:
            refresh_search_index(self.store, p["versions"], recover_missing_derived=False,
                                 allow_full_rebuild=False)
        return {"processed": 1, "skipped": 0, "errors": 0}
