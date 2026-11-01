"""Separate maintenance/processing adapters for complete index generations."""

import hashlib
import json
import re
from datetime import datetime

from .action_center_model import digest, json_bytes
from .index_evidence import ROOTS, publish_once, row_matches
from .maintenance_local_files import prepare_local_directory
from .ocr_selection import _verified_bytes, selected_text
from .review_decisions import checked_path, read_bytes, read_json
from .review_effects import ReviewUnavailable
from .review_routing_model import identifier
from .scheduler_model import MAX_RETRY_ATTEMPTS
from .storage import utc_now

INPUT_SCHEMA = "concordia-index-inputs/v1"
PUBLICATION_SCHEMA = "concordia-index-publication/v1"
INPUT_FIELDS = {"schema", "instance_id", "producer", "job_id", "attempt", "plan_revision",
                "contributions"}
PUBLICATION_FIELDS = {"schema", "producer", "job_id", "attempt", "input_ref", "input_sha256",
                      "contributions_sha256", "mode", "actor", "recorded_at", "parent_binding"}


def describe_contribution(store, document_id, version_id):
    from .index import _email_message_for_version, verified_email_text_artifact
    from .ocr_contract import reliable_text_metrics
    from .ocr_jobs import OcrJobManager
    from .ocr_sources import SourceOcrReview, settings

    version, document, original, _path = OcrJobManager(store)._version_source(version_id)
    if document["id"] != document_id or document["current_version_id"] != version_id:
        raise ReviewUnavailable("Index input no longer selects its current Version")
    selection = selected_text(store, version_id)
    if _email_message_for_version(store, version_id) is not None:
        email = verified_email_text_artifact(store, version_id)
        if email is None:
            selection, text, profile = None, None, "unavailable"
        else:
            selection, text, profile = email[0], email[1], "passive-email"
    elif selection is not None:
        selection, text = selection
        profile = selection["profile"]
    else:
        artifacts = [row for row in store.list_derived_artifacts()
                     if row.get("version_id") == version_id and row.get("kind") == "extracted_text"]
        if len(artifacts) > 1:
            raise ReviewUnavailable("Index input has ambiguous extracted text")
        selection = artifacts[0] if artifacts else None
        text = (None if selection is None else _verified_bytes(
            store, selection["storage_ref"], selection["checksum"]).decode("utf-8"))
        if text is not None:
            # Verify the stored bytes first, then mirror read_derived_text's
            # universal-newline projection used by the existing FTS writer.
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        profile = "unavailable" if selection is None else "native"
        if version["media_type"] == "application/pdf" and selection is not None:
            characters, ratio = reliable_text_metrics(text, generator=selection["generator"])
            threshold = settings(store).automatic
            if (characters < threshold.min_reliable_characters
                    or ratio < threshold.min_printable_ratio):
                profile = "limited-unapproved"
    row = (None if text is None else [document_id, version_id, document["source_id"],
                                     document["media_type"], version["acquired_at"],
                                     document["title"], text])
    source = read_bytes(store, f"knowledge/sources/{document['source_id']}.json")
    if source is None:
        raise ReviewUnavailable("Index Source identity is missing")
    result = {"document_id": document_id, "version_id": version_id,
              "source_id": document["source_id"],
              "source_sha256": hashlib.sha256(source).hexdigest(),
              "source_policy_revision": digest(
                  SourceOcrReview(store).policy(document["source_id"])),
              "original_id": original["id"], "original_sha256": original["sha256"],
              "original_size_bytes": original["size_bytes"], "profile": profile,
              "selection": selection, "row_sha256": None if row is None else digest(row)}
    return result, row


def prepare_index_inputs(store, job, producer, versions, plan_revision):
    if producer not in ROOTS or not 1 <= job["attempt"] <= MAX_RETRY_ATTEMPTS:
        raise ReviewUnavailable("Unsupported index evidence producer or attempt")
    entries = [describe_contribution(store, document, version)[0]
               for document, version in sorted(versions.items())]
    packet = {"schema": INPUT_SCHEMA, "instance_id": store.read_config()["instance"]["id"],
              "producer": producer, "job_id": job["id"], "attempt": job["attempt"],
              "plan_revision": plan_revision, "contributions": entries}
    relative = f"{ROOTS[producer]}/{job['id']}/input_{digest(packet)}.json"
    publish_once(store, relative, packet)
    return relative, packet


def publish_index_inputs(store, job, producer, prepared, *, reconciled=False):
    relative, packet = prepared
    for entry in packet["contributions"]:
        current, row = describe_contribution(store, entry["document_id"], entry["version_id"])
        if current != entry or (row is not None and not row_matches(store, row)):
            raise ReviewUnavailable("Index contribution changed before final proof publication")
    directory = f"{ROOTS[producer]}/{job['id']}"
    reference = f"{directory}/publication_a{job['attempt']}.json"
    immutable = {"schema": PUBLICATION_SCHEMA, "producer": producer, "job_id": job["id"],
                 "attempt": job["attempt"], "input_ref": relative,
                 "input_sha256": hashlib.sha256(json_bytes(packet)).hexdigest(),
                 "contributions_sha256": digest(packet["contributions"])}
    with prepare_local_directory(checked_path(store, directory)) as opened:
        previous = read_json(store, reference)
        if previous is not None:
            validate_packet(store, reference, previous)
            if (any(previous[k] != v for k, v in immutable.items())
                    or previous["parent_binding"] != opened[1]):
                raise ReviewUnavailable("Conflicting producer attempt publication")
            return previous
        value = {**immutable, "mode": "reconciled_current_state" if reconciled
                 else "direct_after_commit", "actor": None if reconciled else job["id"],
                 "recorded_at": None if reconciled else utc_now(), "parent_binding": opened[1]}
        publish_once(store, reference, value)
        validate_packet(store, reference, value)
        return value


def validate_packet(store, relative, value):
    if not isinstance(value, dict) or value.get("schema") not in {INPUT_SCHEMA, PUBLICATION_SCHEMA}:
        raise ReviewUnavailable("Unsupported producer index evidence schema")
    fields = INPUT_FIELDS if value["schema"] == INPUT_SCHEMA else PUBLICATION_FIELDS
    if (set(value) != fields or value["producer"] not in ROOTS
            or re.fullmatch(r"job_[0-9a-f]{32}", str(value["job_id"])) is None
            or type(value["attempt"]) is not int
            or not 1 <= value["attempt"] <= MAX_RETRY_ATTEMPTS):
        raise ReviewUnavailable("Invalid producer evidence fields")
    directory = f"{ROOTS[value['producer']]}/{value['job_id']}"
    if value["schema"] == INPUT_SCHEMA:
        if relative != f"{directory}/input_{digest(value)}.json":
            raise ReviewUnavailable("Producer input content-address differs")
        if not isinstance(value["contributions"], list):
            raise ReviewUnavailable("Producer input contributions are invalid")
        if (re.fullmatch(r"inst_[0-9a-f]{32}", str(value["instance_id"])) is None
                or re.fullmatch(r"[0-9a-f]{64}", str(value["plan_revision"])) is None):
            raise ReviewUnavailable("Producer input plan revision is invalid")
        seen = set()
        entry_fields = {"document_id", "version_id", "source_id", "source_sha256",
                        "source_policy_revision", "original_id", "original_sha256",
                        "original_size_bytes", "profile", "selection", "row_sha256"}
        for entry in value["contributions"]:
            if not isinstance(entry, dict) or set(entry) != entry_fields:
                raise ReviewUnavailable("Unsupported per-Version contribution schema")
            for key, kind in (("document_id", "document"), ("version_id", "version"),
                              ("source_id", "source"), ("original_id", "original")):
                identifier(entry[key], kind)
            for key in ("source_sha256", "source_policy_revision", "original_sha256"):
                if re.fullmatch(r"[0-9a-f]{64}", str(entry[key])) is None:
                    raise ReviewUnavailable("Producer contribution digest is invalid")
            if (type(entry["original_size_bytes"]) is not int or entry["original_size_bytes"] < 0
                    or entry["profile"] not in {"embedded", "ocr-complete", "ocr-accepted",
                                               "limited-metadata", "passive-email", "native",
                                               "unavailable", "limited-unapproved"}
                    or (entry["row_sha256"] is None) != (entry["profile"] == "unavailable")
                    or (entry["row_sha256"] is not None and re.fullmatch(
                        r"[0-9a-f]{64}", str(entry["row_sha256"])) is None)):
                raise ReviewUnavailable("Producer contribution profile is invalid")
            if entry["document_id"] in seen:
                raise ReviewUnavailable("Duplicate producer contribution")
            seen.add(entry["document_id"])
        return value
    if (relative != f"{directory}/publication_a{value['attempt']}.json"
            or value["mode"] not in {"direct_after_commit", "reconciled_current_state"}
            or (value["mode"] == "reconciled_current_state"
                and (value["actor"] is not None or value["recorded_at"] is not None))
            or (value["mode"] == "direct_after_commit"
                and (value["actor"] != value["job_id"] or not value["recorded_at"]))):
        raise ReviewUnavailable("Producer publication origin is invalid")
    if re.fullmatch(r"(?:posix\.file-id\.v1:[0-9a-f]{32}|win32\.file-id\.v1:[0-9a-f]{48})",
                    str(value["parent_binding"])) is None:
        raise ReviewUnavailable("Producer publication physical identity is invalid")
    if (value["mode"] == "direct_after_commit"
            and (not isinstance(value["recorded_at"], str)
                 or datetime.fromisoformat(value["recorded_at"]).tzinfo is None)):
        raise ReviewUnavailable("Producer publication timestamp is invalid")
    raw = read_bytes(store, value["input_ref"])
    if raw is None or hashlib.sha256(raw).hexdigest() != value["input_sha256"]:
        raise ReviewUnavailable("Producer input snapshot is unavailable or changed")
    packet = validate_packet(store, value["input_ref"], json.loads(raw))
    if (packet["producer"] != value["producer"] or packet["job_id"] != value["job_id"]
            or packet["attempt"] != value["attempt"]
            or digest(packet["contributions"]) != value["contributions_sha256"]):
        raise ReviewUnavailable("Producer publication selects another input")
    return value


def resolve_index_contribution(store, producer, job_id, document_id):
    from .scheduler import SchedulerCoordinator, _receipt_matches_terminal_job

    scheduler = SchedulerCoordinator(store)
    job = scheduler.journal.get_job(job_id)
    if job is None or job["status"] != "succeeded":
        raise ReviewUnavailable("Index producer has no terminal success")
    if job["job_kind"] == "ocr.execute" and producer == "processing":
        from .index_evidence import resolve_ocr_contribution

        result = resolve_ocr_contribution(store, job_id)
        if result["snapshot"]["version"]["document_id"] != document_id:
            raise ReviewUnavailable("OCR producer did not select this Document")
        return result
    if ((producer == "maintenance" and job["job_kind"] not in {
            "search.reindex", "search.reindex.incremental"})
            or (producer == "processing" and job["job_kind"] not in {
                "processing.execute", "source.refresh"})
            or producer not in ROOTS):
        raise ReviewUnavailable("Another producer owns this job")
    receipt = scheduler.journal.get_receipt("receipt_" + job_id.removeprefix("job_"))
    if receipt is None or not _receipt_matches_terminal_job(receipt, job):
        raise ReviewUnavailable("Index producer has no exact terminal receipt")
    relative = f"{ROOTS[producer]}/{job_id}/publication_a{job['attempt']}.json"
    publication = validate_packet(store, relative, read_json(store, relative))
    packet = read_json(store, publication["input_ref"])
    if packet["instance_id"] != store.read_config()["instance"]["id"]:
        raise ReviewUnavailable("Index evidence belongs to another Instance")
    if job["job_kind"] == "source.refresh":
        from .folder_sources import FolderSourceManager
        from .ingestion_runs import IngestionLedger

        observer = FolderSourceManager(store).observer(job["scope"]["id"])
        if observer["last_scheduler_job_id"] != job_id:
            raise ReviewUnavailable("Another folder refresh owns the current observation")
        run_id = observer["last_ingestion_run_id"]
        detail = IngestionLedger(store).run_detail(run_id) if run_id is not None else None
        if detail is None or detail["run"]["status"] != "completed":
            raise ReviewUnavailable("Folder contribution has no completed ingestion run")
        acquisitions = [read_json(store, f"knowledge/acquisitions/{i['acquisition_id']}.json")
                        for i in detail["items"] if i["acquisition_id"] is not None]
        if any(a is None or a["source_id"] != job["scope"]["id"] for a in acquisitions):
            raise ReviewUnavailable("Folder proof has an unavailable acquisition")
        versions = {a["document_id"]: a["version_id"] for a in acquisitions}
        plan_revision = digest({"run_id": run_id, "acquisitions": acquisitions})
    elif producer == "processing":
        from .processing_jobs import ProcessingJobs

        plan = job.get("execution_plan")
        ProcessingJobs(store)._current(plan)
        versions = plan["parameters"]["versions"]
        plan_revision = plan["plan_revision"]
    else:
        from .maintenance import MaintenanceManager

        run = MaintenanceManager(store).run_for_job(job_id)
        if run is None or run["status"] != "completed":
            raise ReviewUnavailable("Maintenance producer has no completed generation")
        versions, plan_revision = run["plan"]["documents"], run["plan_digest"]
    if (packet["plan_revision"] != plan_revision or versions != {
            e["document_id"]: e["version_id"] for e in packet["contributions"]}):
        raise ReviewUnavailable("Producer proof differs from its exact execution plan")
    entries = [e for e in packet["contributions"] if e["document_id"] == document_id]
    if len(entries) != 1:
        raise ReviewUnavailable("No exact per-Document index contribution")
    entry = entries[0]
    current, row = describe_contribution(store, document_id, entry["version_id"])
    if (entry != current or row is None or entry["profile"] in {"unavailable", "limited-unapproved"}
            or not row_matches(store, row)):
        raise ReviewUnavailable("The current per-Version contribution is not applicable")
    with prepare_local_directory(checked_path(store, f"{ROOTS[producer]}/{job_id}")) as opened:
        if opened[1] != publication["parent_binding"]:
            raise ReviewUnavailable("Index evidence has a restored or replaced physical root")
    return {"publication": publication, "snapshot": packet, "contribution": entry,
            "receipt_id": receipt["id"], "profile": entry["profile"],
            "row_sha256": entry["row_sha256"]}
