"""Explicit Source OCR consent and exact Original backlog permits.

All decisions use the existing local review transaction and scheduler. Preparing
the optional OCR kit or changing global settings never creates Source consent.
"""

import re
from datetime import datetime

from .action_center_model import digest, json_bytes
from .ocr_contract import OcrSettings, settings_fingerprint
from .review_decisions import (
    assert_review_readable,
    receipt_identifier,
    validate_receipt,
)
from .review_effects import ABSENT, PreparedEffect, PreparedWrite, ReviewDenied, ReviewUnavailable
from .review_routing import _Inputs
from .review_routing_model import identifier

ROOT = "state/review/ocr_sources"
MAX_BACKLOG_VERSIONS = 1000
MAX_BACKLOG_BYTES = 25 * 1024 * 1024
POLICY_FIELDS = {
    "schema_version", "id", "revision", "enabled", "languages", "settings_sha256",
    "source_sha256", "enabled_at", "last_receipt", "principal", "updated_at",
}


def policy_path(source_id):
    identifier(source_id, "source")
    return f"{ROOT}/policies/{source_id}.json"


def settings(store):
    from .ocr_contract import ocr_settings_from_config

    return ocr_settings_from_config(store.read_config())


def validate_policy(value):
    if (not isinstance(value, dict) or set(value) != POLICY_FIELDS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["revision"]) is not int or not 1 <= value["revision"] <= 10000
            or type(value["enabled"]) is not bool
            or value["principal"] not in {"local_browser", "local_cli"}):
        raise ReviewUnavailable("Source OCR consent has an invalid schema")
    identifier(value["id"], "source")
    from .action_center_model import revision

    for key in ("settings_sha256", "source_sha256"):
        revision(value[key])
    if list(OcrSettings(languages=tuple(value["languages"])).languages) != value["languages"]:
        raise ReviewUnavailable("Source OCR languages are invalid")
    for key in ("enabled_at", "updated_at"):
        stamp = datetime.fromisoformat(value[key])
        if stamp.tzinfo is None:
            raise ReviewUnavailable("Source OCR consent needs an aware timestamp")


def version_input(inputs, source_id, version_id):
    """Direct selection avoids a 500-Document Instance inventory before filtering."""
    identifier(version_id, "version")
    version = inputs.record(f"knowledge/versions/{version_id}.json")
    identifier(version["document_id"], "document")
    identifier(version["original_id"], "original")
    document = inputs.record(f"knowledge/documents/{version['document_id']}.json")
    original = inputs.record(f"knowledge/originals/{version['original_id']}.json")
    from .retention_model import canonical_disposition_errors, disposition_id

    disposition = inputs.record(
        f"knowledge/dispositions/{disposition_id(document['id'])}.json", optional=True)
    if disposition is not None and (
        canonical_disposition_errors({disposition["id"]: disposition}, {document["id"]: document})
        or disposition["status"] != "active" or disposition["library_visibility"] != "included"
    ):
        raise ReviewDenied("Source OCR cannot override retention or library visibility")
    if (version["id"] != version_id or document["source_id"] != source_id
            or document["current_version_id"] != version_id
            or version["document_id"] != document["id"]
            or original["id"] != version["original_id"]
            or original["sha256"] != version["content_hash"]
            or original["size_bytes"] != version["size_bytes"]
            or type(original["size_bytes"]) is not int or original["size_bytes"] < 0
            or version["media_type"] != "application/pdf"):
        raise ReviewDenied("Select a current PDF Version belonging to this Source")
    return {"document_id": document["id"], "version_id": version_id,
            "original_id": original["id"], "sha256": original["sha256"],
            "size_bytes": original["size_bytes"]}


def source_pdf_choices(store, source_id):
    from .action_center_model import MAX_ITEMS
    from .review_decisions import checked_path

    identifier(source_id, "source")
    inputs, result = _Inputs(store), []
    directory = checked_path(store, "knowledge/documents")
    for count, path in enumerate(directory.iterdir(), 1):
        if count > MAX_ITEMS:
            raise ReviewUnavailable("Source choice catalogue exceeds its declared traversal bound")
        document = inputs.record(f"knowledge/documents/{path.name}")
        if document["source_id"] == source_id and document["media_type"] == "application/pdf":
            if len(result) >= MAX_BACKLOG_VERSIONS:
                raise ReviewUnavailable("Source PDF choices exceed the 1000-Version bound")
            result.append({"id": document["current_version_id"], "title": document["title"]})
    return sorted(result, key=lambda r: (r["title"], r["id"]))


class SourceOcrReview:
    domain = "ocr_sources"
    actions = ("save_policy", "revoke_policy", "backlog", "limited_result")

    def __init__(self, store):
        self.store = store
        self.instance_id = store.read_config()["instance"]["id"]

    def history_record(self, receipt_id, inputs):
        from .review_decisions import _RECEIPT

        if not isinstance(receipt_id, str) or _RECEIPT.fullmatch(receipt_id + ".json") is None:
            raise ReviewUnavailable("Invalid Source OCR receipt")
        receipt = inputs.record(f"state/review/receipts/{receipt_id}.json")
        validate_receipt(receipt, instance_id=self.instance_id)
        path = f"{ROOT}/history/{receipt['subject']}/{receipt_id}.json"
        row = inputs.record(path)
        if (receipt["domain"] != self.domain or receipt["history_ref"] != path
                or receipt["history_sha256"] != inputs.hashes[path]
                or set(row) != {"schema_version", "domain", "subject", "action", "before",
                                "after", "execution", "request_id", "principal", "recorded_at"}
                or row["schema_version"] != 1
                or row["action"] not in self.actions
                or any(row[k] != receipt[k] for k in
                       ("domain", "subject", "action", "request_id", "principal", "recorded_at"))
                or receipt["result"] != {"policy": row["after"], "execution": row["execution"]}):
            raise ReviewUnavailable("Source OCR history differs from its committed receipt")
        for item in (row["before"], row["after"]):
            if item is not None:
                validate_policy(item)
                if item["id"] != row["subject"]:
                    raise ReviewUnavailable("Source OCR history changes another Source")
        if row["action"] in {"backlog", "limited_result"}:
            if row["before"] != row["after"] or row["execution"] is None:
                raise ReviewUnavailable("A backlog permit cannot change Source consent")
        elif row["execution"] is not None or row["after"]["last_receipt"] != receipt_id:
            raise ReviewUnavailable("Source consent has another effect")
        return row, receipt

    def policy(self, source_id, inputs=None):
        assert_review_readable(self.store)
        inputs = inputs or _Inputs(self.store)
        result = inputs.record(policy_path(source_id), optional=True)
        current, seen = result, set()
        while current is not None:
            validate_policy(current)
            if current["last_receipt"] in seen or len(seen) >= 10000:
                raise ReviewUnavailable("Source OCR history is cyclic or exceeds its bound")
            seen.add(current["last_receipt"])
            row, _ = self.history_record(current["last_receipt"], inputs)
            previous = row["before"]
            if (row["subject"] != source_id or row["after"] != current
                    or row["action"] in {"backlog", "limited_result"}
                    or current["revision"] != (
                        1 if previous is None else previous["revision"] + 1)):
                raise ReviewUnavailable("Source OCR consent has unconfirmed history")
            current = previous
        assert_review_readable(self.store)
        return result

    def preview(self, subject, action, parameters):
        identifier(subject, "source")
        if action not in self.actions or not isinstance(parameters, dict):
            raise ReviewDenied("Unsupported Source OCR choice")
        inputs = _Inputs(self.store)
        source = inputs.record(f"knowledge/sources/{subject}.json")
        if source["id"] != subject or source["kind"] != "filesystem":
            raise ReviewDenied("Source OCR currently supports local filesystem Sources")
        before = self.policy(subject, inputs)
        configured = settings(self.store)
        inputs.hashes["ocr-settings"] = settings_fingerprint(configured)
        after, execution = before, None
        if action == "save_policy":
            if (set(parameters) != {"enabled", "languages"}
                    or type(parameters["enabled"]) is not bool):
                raise ReviewDenied("Review the exact Source consent and languages")
            selected = OcrSettings(languages=tuple(parameters["languages"]))
            if list(selected.languages) != parameters["languages"]:
                raise ReviewDenied("Select canonical OCR languages")
            if before is None and len(inputs.inventory(f"{ROOT}/policies", 128)) >= 128:
                raise ReviewUnavailable("Source OCR consent inventory is full")
            after = {"schema_version": 1, "id": subject,
                     "revision": 1 if before is None else before["revision"] + 1,
                     "enabled": parameters["enabled"], "languages": parameters["languages"],
                     "settings_sha256": settings_fingerprint(configured),
                     "source_sha256": inputs.hashes[f"knowledge/sources/{subject}.json"]}
        elif action == "revoke_policy":
            if parameters or before is None:
                raise ReviewDenied("No Source OCR consent to disable")
            after = {**before, "enabled": False, "revision": before["revision"] + 1}
        elif action == "backlog":
            ids = parameters.get("versions")
            if (set(parameters) != {"versions"} or not isinstance(ids, list)
                    or not 1 <= len(ids) <= MAX_BACKLOG_VERSIONS
                    or len(set(ids)) != len(ids)):
                raise ReviewDenied("Select between one and 1000 distinct PDF Versions")
            rows = [version_input(inputs, subject, version_id) for version_id in sorted(ids)]
            if sum(row["size_bytes"] for row in rows) > MAX_BACKLOG_BYTES:
                raise ReviewDenied("Selected Original bytes exceed the reviewed backlog budget")
            execution = {"source_id": subject, "versions": rows,
                         "settings_sha256": settings_fingerprint(configured),
                         "source_sha256": inputs.hashes[f"knowledge/sources/{subject}.json"]}
        else:
            from .ocr_selection import limited_selection, selection_path

            if set(parameters) != {"version_id", "profile", "artifact_id"}:
                raise ReviewDenied("Review one Version and its exact limited search profile")
            selected_version = parameters["version_id"]
            selected_binding = version_input(inputs, subject, selected_version)
            inputs.record(selection_path(selected_version), optional=True)
            artifact = None
            if parameters["artifact_id"] is not None:
                if re.fullmatch(r"derived_[0-9a-f]{32}", str(parameters["artifact_id"])) is None:
                    raise ReviewDenied("Invalid limited OCR artifact identity")
                artifact = inputs.record(
                    f"state/derived/artifacts/{parameters['artifact_id']}.json")
            selected, _ = limited_selection(self.store, selected_version,
                                             parameters["profile"], artifact)
            execution = {"selection": selected, "version": selected_binding,
                         "settings_sha256": settings_fingerprint(configured),
                         "source_sha256": inputs.hashes[f"knowledge/sources/{subject}.json"]}
            # Bind all selected page bytes in the preview as well as their declared hashes.
            if artifact is not None:
                manifest = inputs.record(artifact["storage_ref"])
                for page in manifest["pages"]:
                    inputs.record(page["result_ref"])
                    from .review_decisions import read_bytes

                    text = read_bytes(self.store, page["text_ref"])
                    if text is None:
                        raise ReviewUnavailable("Selected OCR page text is missing")
                    from .review_effects import sha256

                    inputs.hashes[page["text_ref"]] = sha256(text)
        return {"before": before, "after": after, "execution": execution,
                "inputs": inputs.hashes, "input_revision": digest(inputs.hashes),
                "evidence": {"source_id": subject, "source_name": source["name"],
                             "future_only": action != "backlog", "execution": execution,
                             "network_used": False, "originals_changed": False},
                "confidence": None, "reason": "source_ocr_" + action,
                "impact": "Local OCR and selected derived text only; no Inbox exit or AI consent.",
                "reversibility": "Disable future admission; preserved Originals remain unchanged."}

    def allowed_paths(self, plan, request_id):
        receipt = receipt_identifier(self.instance_id, request_id)
        result = {f"{ROOT}/history/{plan['subject']}/{receipt}.json"}
        if plan["action"] in {"save_policy", "revoke_policy"}:
            result.add(policy_path(plan["subject"]))
        if plan["action"] == "limited_result":
            from .ocr_selection import selection_path

            result.add(selection_path(plan["parameters"]["version_id"]))
        return frozenset(result)

    def prepare(self, plan, *, request_id, principal, recorded_at):
        if principal not in {"local_browser", "local_cli"}:
            raise ReviewDenied("Source OCR requires explicit local review")
        data = plan["provider"]
        receipt = receipt_identifier(self.instance_id, request_id)
        after, writes = data["after"], []
        if plan["action"] in {"save_policy", "revoke_policy"}:
            after = {**after, "last_receipt": receipt, "principal": principal,
                     "enabled_at": (recorded_at if plan["action"] == "save_policy"
                                    else data["before"]["enabled_at"]),
                     "updated_at": recorded_at}
            validate_policy(after)
            writes.append(PreparedWrite(policy_path(plan["subject"]),
                                        data["inputs"][policy_path(plan["subject"])],
                                        json_bytes(after)))
        execution = data["execution"]
        if plan["action"] == "limited_result":
            from .ocr_selection import _seal, selection_path

            selected = _seal({**{k: v for k, v in execution["selection"].items()
                                 if k != "revision"}, "acceptance": receipt})
            execution = {**execution, "selection": selected}
            relative = selection_path(selected["version_id"])
            writes.append(PreparedWrite(relative, data["inputs"][relative], json_bytes(selected)))
        path = f"{ROOT}/history/{plan['subject']}/{receipt}.json"
        row = {"schema_version": 1, "domain": self.domain, "subject": plan["subject"],
               "action": plan["action"], "before": data["before"], "after": after,
               "execution": execution, "request_id": request_id,
               "principal": principal, "recorded_at": recorded_at}
        result = {"policy": after, "execution": execution}
        writes.append(PreparedWrite(path, ABSENT, json_bytes(row), immutable=True))
        return PreparedEffect(self.domain, plan["action"], tuple(writes), result, path,
                              data["impact"], data["reversibility"])

    def authorization(self, source_id, version_id, *, permit=None, acquisition=None):
        from .review_authority import ReviewAuthority
        from .review_integrity import CAPABILITIES

        if isinstance(permit, dict):
            from .setup_trial_authority import SetupTrialAuthority

            return SetupTrialAuthority(self.store).ocr_authorization(
                source_id, version_id, permit, acquisition)

        inputs = _Inputs(self.store)
        binding = version_input(inputs, source_id, version_id)
        inputs.record(f"knowledge/sources/{source_id}.json")
        fingerprint = settings_fingerprint(settings(self.store))
        policy = self.policy(source_id, inputs)
        if permit is not None:
            row, _ = self.history_record(permit, inputs)
            execution = row["execution"]
            if (row["action"] not in {"backlog", "limited_result"}
                    or row["subject"] != source_id
                    or binding not in (execution["versions"] if row["action"] == "backlog"
                                       else [execution["version"]])
                    or execution["settings_sha256"] != fingerprint
                    or execution["source_sha256"] != inputs.hashes[
                        f"knowledge/sources/{source_id}.json"]):
                raise ReviewDenied("Historical OCR needs a fresh exact Original permit")
            consent = permit
        else:
            if (policy is None or not policy["enabled"]
                    or policy["settings_sha256"] != fingerprint
                    or policy["source_sha256"] != inputs.hashes[
                        f"knowledge/sources/{source_id}.json"]
                    or acquisition is None or acquisition["source_id"] != source_id
                    or acquisition["version_id"] != version_id
                    or acquisition["outcome"] == "unchanged"
                    or datetime.fromisoformat(acquisition["observed_at"])
                    < datetime.fromisoformat(policy["enabled_at"])):
                raise ReviewDenied("This acquisition has no current Source OCR consent")
            if re.fullmatch(r"acq_[0-9a-f]{32}", str(acquisition.get("id"))) is None:
                raise ReviewDenied("Invalid OCR acquisition identity")
            if inputs.record(f"knowledge/acquisitions/{acquisition['id']}.json") != acquisition:
                raise ReviewDenied("OCR admission needs the committed acquisition")
            consent = policy["last_receipt"]
        authority = ReviewAuthority(self.store, CAPABILITIES).resolve(
            self.domain, source_id, row["action"] if permit is not None else "save_policy")
        if authority["mode"] not in {"confirm-each", "controlled-automatic"}:
            raise ReviewDenied("Current local authority does not allow Source OCR")
        return {"source_id": source_id, "version": binding, "consent": consent,
                "permit": permit, "acquisition": acquisition,
                "settings_sha256": fingerprint,
                "source_sha256": inputs.hashes[f"knowledge/sources/{source_id}.json"],
                "languages": (policy["languages"] if policy and permit is None
                              else list(settings(self.store).languages))}

    def revalidate(self, authorization):
        expected = self.authorization(
            authorization["source_id"], authorization["version"]["version_id"],
            permit=authorization["permit"], acquisition=authorization["acquisition"])
        if expected != authorization:
            raise ReviewDenied("Source OCR consent or input changed; review it again")
        return expected


class SourceOcrFlow:
    """Admit exact requests into ocr.execute, including unavailable components.

    The scheduler owns pause, retry and terminal cancellation from admission.
    There is no second backlog dispatcher or OCR queue.
    """

    def __init__(self, store):
        self.store = store
        self.review = SourceOcrReview(store)

    def queue(self, source_id, version_id, *, permit=None, acquisition=None):
        from .ocr_jobs import OcrJobManager, _json_bytes
        from .scheduler_model import idempotency_digest

        authorization = self.review.authorization(source_id, version_id,
                                                   permit=permit, acquisition=acquisition)
        manager = OcrJobManager(self.store)
        manager._ensure_directories()
        request_key = "source-ocr:" + digest(authorization)
        # Scheduler policy revisions must not turn one cancelled Source permit
        # into a new reservation. The existing scheduler remains the sole ledger.
        for existing in manager.scheduler.journal._all_jobs():
            if (existing["job_kind"] == "ocr.execute" and existing["idempotency_key"]
                    == idempotency_digest("manual", existing["policy_id"],
                                          str(existing["policy_revision"]), request_key)):
                if manager._request_for_job(existing).get("source_authorization") != authorization:
                    raise ReviewUnavailable("Existing Source OCR request identity conflicts")
                return {"scheduled": True, "created": False, "job": existing}
        policy = manager._policy()
        key = idempotency_digest("manual", policy["id"], str(policy["revision"]), request_key)
        selected_settings = settings(self.store)
        if isinstance(permit, dict):
            from .setup_trial_authority import SetupTrialAuthority

            selected_settings = SetupTrialAuthority(self.store).settings(permit["id"])
        request = {"schema_version": 1, "scheduler_key": key, "operation": "source",
                   "version_id": version_id, "source_authorization": authorization,
                   "settings": selected_settings.as_record()}
        from .index_evidence import publish_once
        from .review_decisions import read_json

        relative = f"state/ocr/requests/{key}.json"
        previous = read_json(self.store, relative)
        if previous is None:
            # Same canonical bytes as the existing OCR request reader/writer.
            from .maintenance_local_files import prepare_local_directory, write_local_bytes
            from .review_decisions import checked_path

            path = checked_path(self.store, relative)
            with prepare_local_directory(path.parent, create=True):
                write_local_bytes(path, _json_bytes(request))
        elif previous.get("source_authorization") != authorization:
            raise ReviewUnavailable("Source OCR idempotency identity conflicts")
        # Retain the reviewed request as content-addressed producer evidence.
        publish_once(self.store, f"state/processing/index-evidence/admissions/{key}.json",
                     {"schema_version": 1, "scheduler_key": key,
                      "authorization": authorization})
        result = manager.scheduler.journal.run_now(policy["id"], request_key=request_key)
        return {"scheduled": True, **result}

    def admit(self, acquisition, *, trial_id=None):
        if trial_id is not None:
            from .setup_trial_authority import SetupTrialAuthority

            permit = SetupTrialAuthority(self.store).read(trial_id)
            return self.queue(acquisition["source_id"], acquisition["version_id"],
                              permit={"kind": "setup-trial", "id": trial_id,
                                      "sha256": digest(permit)}, acquisition=acquisition)
        policy = self.review.policy(acquisition["source_id"])
        if (policy is None or not policy["enabled"] or acquisition["outcome"] == "unchanged"
                or datetime.fromisoformat(acquisition["observed_at"])
                < datetime.fromisoformat(policy["enabled_at"])):
            return None
        version = self.store.read_canonical("versions", acquisition["version_id"])
        if version is None or version["media_type"] != "application/pdf":
            return None
        return self.queue(acquisition["source_id"], version["id"], acquisition=acquisition)

    def backlog(self, receipt_id):
        from .instance_lifecycle import InstanceLifecycleManager

        with InstanceLifecycleManager(self.store)._hold(purpose="source-ocr-backlog"):
            row, _ = self.review.history_record(receipt_id, _Inputs(self.store))
            if row["action"] not in {"backlog", "limited_result"}:
                raise ReviewDenied("Select a committed Original backlog permit")
            versions = (row["execution"]["versions"] if row["action"] == "backlog"
                        else [row["execution"]["version"]])
            # Validate the whole exact selection before admitting any job.
            for version in versions:
                self.review.authorization(row["subject"], version["version_id"], permit=receipt_id)
            return [self.queue(row["subject"], version["version_id"], permit=receipt_id)
                    for version in versions]
