"""Read-only projections of the existing intake, scheduler and text services.

Unknown counts are None. A saved schedule is never evidence of a running worker,
and an input count is never a count of unfinished Documents.
"""

from .index_evidence import row_matches
from .library_projection_model import LibraryProjectionError
from .ocr_contract import OcrUnavailableError
from .ocr_sources import SourceOcrReview
from .producer_index_evidence import describe_contribution
from .review_effects import ReviewError


def runtime_state(app):
    if getattr(app.state, "scheduler_runtime_stopping", False):
        return "stopping"
    if not getattr(app.state, "scheduler_runtime_active", False):
        return "stopped"
    if getattr(app.state, "scheduler_runtime_error", None):
        return "attention"
    return "active"


def source_journey(instance, source, *, runtime="stopped"):
    """Return independent configuration, observation and completion dimensions."""
    result = {
        "source": source, "runtime": runtime, "role": "folder", "mode": "keep",
        "files_present": None, "files_observed_at": None, "to_complete": None,
        "counts_state": "unknown", "ocr_enabled": None, "ocr_state": "unknown",
        "ocr_error": None,
        "automation": "unknown", "next_due_at": None, "last_job": None,
        "exit_supported": False,
    }
    try:
        policy = instance.scheduler.journal.get_policy(source["policy_id"])
        if policy is not None:
            result["automation"] = (
                "manual" if policy["schedule"]["mode"] == "manual" else "automatic")
            result["next_due_at"] = policy["next_due_at"]
        observer = source["observer"]
        result["files_present"] = observer.get("file_count")
        result["files_observed_at"] = observer.get("last_observed_at")
        result["counts_state"] = "observed" if result["files_observed_at"] else "unknown"
        if observer.get("last_scheduler_job_id"):
            result["last_job"] = instance.scheduler.journal.get_job(
                observer["last_scheduler_job_id"])
        consent = SourceOcrReview(instance.store).policy(source["id"])
        result["ocr_enabled"] = bool(consent and consent["enabled"])
        capability = instance.ocr_capability()
        result["ocr_state"] = ("ready" if capability["available"] else "disabled"
                               if capability["state"] == "disabled" else "unavailable")
        result["ocr_error"] = capability.get("error")
        # Status resolves exact inputs and immutable exit outcomes with the S06
        # bounds. It does not infer an exit from a missing path or repair state.
        if source["source_class"] == "local":
            status = instance.inbox_transit.status(source["id"])
            result.update({key: status[key] for key in
                           ("role", "mode", "files_present", "exit_supported")})
            result["files_observed_at"] = None  # Current bounded status read.
            result["counts_state"] = "current"
            documents = {d["locator"]: d for d in instance.store.list_canonical("documents")
                         if d["source_id"] == source["id"]}
            pending = 0
            for item in status["files"]:
                document = documents.get(item["locator"])
                if document is None:
                    pending += 1
                    continue
                entry, row = describe_contribution(
                    instance.store, document["id"], document["current_version_id"])
                if (entry["original_sha256"] != item["sha256"] or row is None
                        or entry["profile"] in {"unavailable", "limited-unapproved"}
                        or not row_matches(instance.store, row)):
                    pending += 1
            result["to_complete"] = pending
    except (ReviewError, OcrUnavailableError, OSError, ValueError, KeyError):
        # Retain configured/observed dimensions already read, but never display a
        # fabricated zero after a partial/unavailable completion calculation.
        result["to_complete"] = None
        result["counts_state"] = "attention"
    return result


def document_journey(instance, document, content):
    """Text availability and materialized Library are separate from retention."""
    result = {"text": "unavailable", "library": "unavailable", "library_paths": []}
    if content is not None and content.get("markdown") is not None:
        result["text"] = "available"
    try:
        entry, row = describe_contribution(
            instance.store, document["id"], document["current_version"]["id"])
        profile = entry["profile"]
        result["text"] = ("unavailable" if profile == "unavailable" else "limited"
                          if profile.startswith("limited") else "ocr"
                          if profile.startswith("ocr") else "native")
        result["indexed"] = row is not None and row_matches(instance.store, row)
    except (ReviewError, OSError, ValueError, KeyError):
        result["indexed"] = None
    # Included in a projection policy does not mean a view was materialized.
    try:
        library = instance.library_status()
        result["library"] = library["status"]
        if library["status"] == "ready":
            selected = library["primary_paths"].get(document["id"])
            result["library_paths"] = [selected] if selected else []
            if not selected:
                result["library"] = "not_generated"
    except (LibraryProjectionError, OSError, ValueError, KeyError):
        pass
    return result
