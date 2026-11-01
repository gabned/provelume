"""Producer-owned, attempt-specific proof of the selected FTS contribution.

A publication is not a scheduler receipt. Applicability requires that exact
producer's terminal success and the still-current Original, selection and row.
"""

import hashlib
import json
import re
import sqlite3
from datetime import datetime

from .action_center_model import digest, json_bytes
from .maintenance_local_files import (
    MaintenanceTargetError,
    prepare_local_directory,
    write_local_bytes,
)
from .ocr_selection import selected_text, selection_path
from .review_decisions import checked_path, read_bytes, read_json
from .review_effects import ReviewUnavailable
from .scheduler_model import MAX_RETRY_ATTEMPTS
from .storage import utc_now

ROOTS = {"processing": "state/processing/index-evidence",
         "maintenance": "state/maintenance/index-evidence"}
INPUT_FIELDS = {"schema_version", "producer", "job_id", "attempt", "instance_id",
                "source_id", "version", "selection", "authorization", "plan_sha256",
                "row_sha256"}
PUBLICATION_FIELDS = {"schema_version", "producer", "job_id", "attempt", "input_ref",
                      "input_sha256", "row_sha256", "selection_revision", "mode",
                      "actor", "recorded_at", "parent_binding"}


def validate_publication(value, producer, job_id, attempt):
    if (not isinstance(value, dict) or set(value) != PUBLICATION_FIELDS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["producer"] != producer or value["job_id"] != job_id
            or type(value["attempt"]) is not int or value["attempt"] != attempt
            or not 1 <= attempt <= MAX_RETRY_ATTEMPTS
            or value["mode"] not in {"direct_after_commit", "reconciled_current_state"}
            or re.fullmatch(r"(?:posix\.file-id\.v1:[0-9a-f]{32}|"
                            r"win32\.file-id\.v1:[0-9a-f]{48})",
                            str(value["parent_binding"])) is None):
        raise ReviewUnavailable("Index publication has an invalid closed identity")
    for key in ("input_sha256", "row_sha256", "selection_revision"):
        if re.fullmatch(r"[0-9a-f]{64}", str(value[key])) is None:
            raise ReviewUnavailable("Index publication digest is invalid")
    if value["mode"] == "reconciled_current_state":
        if value["actor"] is not None or value["recorded_at"] is not None:
            raise ReviewUnavailable("Reconciliation cannot invent the original actor or time")
    elif (value["actor"] != job_id or not isinstance(value["recorded_at"], str)
          or datetime.fromisoformat(value["recorded_at"]).tzinfo is None):
        raise ReviewUnavailable("Direct publication has no producer or aware observation time")
    return value


def publish_once(store, relative, value):
    """Pinned parent, private staging, fsync and no-overwrite publication."""
    data = json_bytes(value)
    if len(data) > 8 * 1024 * 1024:
        raise ReviewUnavailable("Index evidence exceeds its bound")
    path = checked_path(store, relative)
    with prepare_local_directory(path.parent, create=True) as opened:
        _path, binding = opened
        existing = read_bytes(store, relative)
        if existing is not None:
            if existing != data:
                raise ReviewUnavailable("Conflicting immutable index evidence")
        else:
            try:
                write_local_bytes(path, data)
            except MaintenanceTargetError as exc:
                if exc.code != "output_exists" or read_bytes(store, relative) != data:
                    raise
        if read_bytes(store, relative) != data:
            raise ReviewUnavailable("Published index evidence cannot be read back")
        return binding


def _row(store, document, version, text):
    return [document["id"], version["id"], document["source_id"], document["media_type"],
            version["acquired_at"], document["title"], text]


def row_matches(store, row):
    path = checked_path(store, "indexes/search.sqlite3")
    if not path.is_file():
        return False
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT document_id, version_id, source_id, media_type, acquired_at, title, "
                "content FROM search WHERE document_id = ?", (row[0],)).fetchall()
        return rows == [tuple(row)]
    except sqlite3.Error:
        return False


def finalize_ocr_index(store, job, request, selection, text):
    """Called under the existing scheduler lifecycle ownership, before success."""
    from .index import refresh_search_index
    from .ocr_jobs import OcrJobManager
    from .ocr_sources import SourceOcrReview

    authorization = SourceOcrReview(store).revalidate(request["source_authorization"])
    binding = authorization["version"]
    version, document, _original, _path = OcrJobManager(store)._version_source(
        binding["version_id"])
    if document["current_version_id"] != version["id"]:
        raise ReviewUnavailable("Index publication needs the current Source Version")
    if type(job["attempt"]) is not int or not 1 <= job["attempt"] <= MAX_RETRY_ATTEMPTS:
        raise ReviewUnavailable("Index publication has an invalid scheduler attempt")
    row = _row(store, document, version, text)
    snapshot = {"schema_version": 1, "producer": "processing", "job_id": job["id"],
                "attempt": job["attempt"], "instance_id": store.read_config()["instance"]["id"],
                "source_id": document["source_id"], "version": binding,
                "selection": selection, "authorization": authorization,
                "plan_sha256": digest(request), "row_sha256": digest(row)}
    directory = f"{ROOTS['processing']}/{job['id']}"
    snapshot_ref = f"{directory}/input_{digest(snapshot)}.json"
    # Freeze final selection/input before exposing the new active contribution.
    publish_once(store, snapshot_ref, snapshot)
    existing = selected_text(store, version["id"])
    if existing is not None and existing[0] != selection:
        raise ReviewUnavailable("Text selection changed; review the dependent plan again")
    target = checked_path(store, selection_path(version["id"]))
    with prepare_local_directory(target.parent, create=True):
        write_local_bytes(target, json_bytes(selection), replace=True)
    selected = selected_text(store, version["id"])
    if selected != (selection, text):
        raise ReviewUnavailable("Final selection differs from its durable input")
    already_current = row_matches(store, row)
    if not already_current:
        refresh_search_index(store, [document["id"]], recover_missing_derived=False,
                             allow_full_rebuild=False)
    if not row_matches(store, row):
        raise ReviewUnavailable("The exact selected text is not present in FTS")
    SourceOcrReview(store).revalidate(authorization)
    OcrJobManager(store)._version_source(version["id"])
    reference = f"{directory}/publication_a{job['attempt']}.json"
    existing_publication = read_json(store, reference)
    immutable = {"schema_version": 1, "producer": "processing", "job_id": job["id"],
                 "attempt": job["attempt"], "input_ref": snapshot_ref,
                 "input_sha256": hashlib.sha256(json_bytes(snapshot)).hexdigest(),
                 "row_sha256": digest(row), "selection_revision": selection["revision"]}
    if existing_publication is not None:
        validate_publication(existing_publication, "processing", job["id"], job["attempt"])
        if (set(existing_publication) != PUBLICATION_FIELDS
                or any(existing_publication[k] != v for k, v in immutable.items())):
            raise ReviewUnavailable("Another publication already owns this attempt")
        with prepare_local_directory(checked_path(store, directory)) as opened:
            if opened[1] != existing_publication["parent_binding"]:
                raise ReviewUnavailable("Producer publication root changed")
        return existing_publication
    with prepare_local_directory(checked_path(store, directory)) as opened:
        publication = {**immutable,
                       "mode": "reconciled_current_state" if already_current
                       else "direct_after_commit",
                       "actor": None if already_current else job["id"],
                       "recorded_at": None if already_current else utc_now(),
                       "parent_binding": opened[1]}
        validate_publication(publication, "processing", job["id"], job["attempt"])
        publish_once(store, reference, publication)
    return publication


def resolve_ocr_contribution(store, job_id):
    """No directory search, favorable attempt selection, repair or write on read."""
    from .ocr_jobs import OcrJobManager
    from .ocr_sources import SourceOcrReview
    from .scheduler import SchedulerCoordinator, _receipt_matches_terminal_job

    scheduler = SchedulerCoordinator(store)
    job = scheduler.journal.get_job(job_id)
    if job is None or job["status"] != "succeeded":
        raise ReviewUnavailable("Producer has no terminal scheduler success")
    receipt = scheduler.journal.get_receipt("receipt_" + job_id.removeprefix("job_"))
    if receipt is None or not _receipt_matches_terminal_job(receipt, job):
        raise ReviewUnavailable("Producer receipt differs from its current terminal job")
    directory = f"{ROOTS['processing']}/{job_id}"
    publication = read_json(store, f"{directory}/publication_a{job['attempt']}.json")
    validate_publication(publication, "processing", job_id, job["attempt"])
    if (publication is None or set(publication) != PUBLICATION_FIELDS
            or publication["schema_version"] != 1 or publication["producer"] != "processing"
            or publication["job_id"] != job_id or publication["attempt"] != job["attempt"]
            or publication["mode"] not in {"direct_after_commit", "reconciled_current_state"}
            or (publication["mode"] == "reconciled_current_state"
                and (publication["actor"] is not None or publication["recorded_at"] is not None))):
        raise ReviewUnavailable("Index publication is missing or unsupported")
    reference = publication["input_ref"]
    if not reference.startswith(directory + "/input_") or not reference.endswith(".json"):
        raise ReviewUnavailable("Index publication references another producer input")
    raw = read_bytes(store, reference)
    if raw is None or hashlib.sha256(raw).hexdigest() != publication["input_sha256"]:
        raise ReviewUnavailable("Index input snapshot is missing or changed")
    snapshot = json.loads(raw)
    if (set(snapshot) != INPUT_FIELDS or reference != f"{directory}/input_{digest(snapshot)}.json"
            or snapshot["job_id"] != job_id or snapshot["attempt"] != job["attempt"]
            or snapshot["instance_id"] != store.read_config()["instance"]["id"]):
        raise ReviewUnavailable("Index input has another identity")
    manager = OcrJobManager(store)
    request = manager._request_for_job(job)
    if digest(request) != snapshot["plan_sha256"]:
        raise ReviewUnavailable("Producer plan changed after indexing")
    authorization = SourceOcrReview(store).revalidate(snapshot["authorization"])
    version, document, _original, _path = manager._version_source(
        authorization["version"]["version_id"])
    chosen = selected_text(store, version["id"])
    if chosen is None or chosen[0] != snapshot["selection"]:
        raise ReviewUnavailable("Current text selection differs from the indexed input")
    row = _row(store, document, version, chosen[1])
    if (digest(row) != snapshot["row_sha256"] or digest(row) != publication["row_sha256"]
            or chosen[0]["revision"] != publication["selection_revision"]
            or not row_matches(store, row)):
        raise ReviewUnavailable("The selected current contribution is no longer applicable")
    with prepare_local_directory(checked_path(store, directory)) as opened:
        if opened[1] != publication["parent_binding"]:
            raise ReviewUnavailable("Index evidence was restored into another physical root")
    return {"publication": publication, "snapshot": snapshot, "receipt_id": receipt["id"],
            "profile": chosen[0]["profile"], "row_sha256": digest(row)}


def index_evidence_state_findings(store):
    """Validate retained producer bytes without upgrading historical applicability."""
    findings = []
    for producer, relative in ROOTS.items():
        try:
            root = checked_path(store, relative)
            if not root.exists():
                continue
            if not root.is_dir():
                raise ReviewUnavailable("Producer evidence root is not a directory")
            for directory in root.iterdir():
                checked_path(store, directory.relative_to(store.paths.root).as_posix())
                if not directory.is_dir():
                    raise ReviewUnavailable("Unsupported producer evidence entry")
                if directory.name == "admissions" and producer == "processing":
                    for path in directory.iterdir():
                        if re.fullmatch(r"[0-9a-f]{64}\.json", path.name) is None:
                            raise ReviewUnavailable("Unsupported OCR admission evidence")
                        value = read_json(store, path.relative_to(store.paths.root).as_posix())
                        if (set(value) != {"schema_version", "scheduler_key", "authorization"}
                                or value["schema_version"] != 1
                                or value["scheduler_key"] != path.stem):
                            raise ReviewUnavailable("OCR admission evidence is invalid")
                    continue
                if re.fullmatch(r"job_[0-9a-f]{32}", directory.name) is None:
                    raise ReviewUnavailable("Unknown index evidence producer identity")
                for count, path in enumerate(directory.iterdir(), 1):
                    if count > 2 * MAX_RETRY_ATTEMPTS:
                        raise ReviewUnavailable("Producer evidence exceeds scheduler attempts")
                    name = path.relative_to(store.paths.root).as_posix()
                    value = read_json(store, name)
                    if isinstance(value, dict) and "schema" in value:
                        from .producer_index_evidence import validate_packet

                        validate_packet(store, name, value)
                        continue
                    if re.fullmatch(r"input_[0-9a-f]{64}\.json", path.name):
                        if (set(value) != INPUT_FIELDS or value["schema_version"] != 1
                                or value["producer"] != producer
                                or value["job_id"] != directory.name
                                or type(value["attempt"]) is not int
                                or not 1 <= value["attempt"] <= MAX_RETRY_ATTEMPTS
                                or path.name != f"input_{digest(value)}.json"):
                            raise ReviewUnavailable("Index input evidence is invalid")
                    elif re.fullmatch(r"publication_a[1-8]\.json", path.name):
                        validate_publication(value, producer, directory.name,
                                             int(path.stem.removeprefix("publication_a")))
                        if (set(value) != PUBLICATION_FIELDS or value["schema_version"] != 1
                                or value["producer"] != producer
                                or value["job_id"] != directory.name
                                or path.name != f"publication_a{value['attempt']}.json"
                                or value["mode"] not in {
                                    "direct_after_commit", "reconciled_current_state"}
                                or (value["mode"] == "reconciled_current_state"
                                    and (value["actor"] is not None
                                         or value["recorded_at"] is not None))):
                            raise ReviewUnavailable("Index publication evidence is invalid")
                        raw = read_bytes(store, value["input_ref"])
                        if (raw is None or hashlib.sha256(raw).hexdigest()
                                != value["input_sha256"]
                                or not value["input_ref"].startswith(
                                    f"{relative}/{directory.name}/input_")):
                            raise ReviewUnavailable("Index publication input is missing or changed")
                    else:
                        raise ReviewUnavailable("Unknown index producer evidence file")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            findings.append({"code": "index_evidence_invalid", "path": relative,
                             "message": str(exc)})
    try:
        from .ocr_selection import FIELDS, SELECTION_ROOT

        root = checked_path(store, SELECTION_ROOT)
        if root.exists():
            if not root.is_dir():
                raise ReviewUnavailable("OCR selections root is invalid")
            for path in root.iterdir():
                if re.fullmatch(r"ver_[0-9a-f]{32}\.json", path.name) is None:
                    raise ReviewUnavailable("Unknown OCR selection file")
                value = read_json(store, path.relative_to(store.paths.root).as_posix())
                if (set(value) != FIELDS or value["version_id"] != path.stem
                        or value["schema_version"] != 1
                        or value["revision"] != digest({k: v for k, v in value.items()
                                                         if k != "revision"})):
                    raise ReviewUnavailable("Retained OCR text selection is invalid")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        findings.append({"code": "index_evidence_invalid", "path": SELECTION_ROOT,
                         "message": str(exc)})
    return findings
