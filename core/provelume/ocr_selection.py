"""Checksum-bound, explicit complete OCR selection shared by reading and FTS."""

import hashlib
import json

from .action_center_model import digest
from .ocr_contract import OCR_ARTIFACT_KIND, reliable_text_metrics
from .ocr_sources import settings
from .review_decisions import read_bytes, read_json
from .review_effects import ReviewUnavailable
from .review_routing_model import identifier

MAX_TEXT_BYTES = 8 * 1024 * 1024
SELECTION_ROOT = "state/processing/ocr-selections"
FIELDS = {"schema_version", "version_id", "document_id", "original_id", "original_sha256",
          "artifact", "profile", "text_sha256", "acceptance", "revision"}


def selection_path(version_id):
    identifier(version_id, "version")
    return f"{SELECTION_ROOT}/{version_id}.json"


def _verified_bytes(store, relative, expected, *, maximum=MAX_TEXT_BYTES):
    raw = read_bytes(store, relative, maximum=maximum)
    if raw is None or hashlib.sha256(raw).hexdigest() != expected:
        raise ReviewUnavailable("Selected text evidence is missing or changed")
    return raw


def _seal(value):
    return {**value, "revision": digest(value)}


def _base(store, version_id, artifact, profile, text, acceptance=None):
    version = store.read_canonical("versions", version_id)
    if version is None:
        raise ReviewUnavailable("Selected Version is unavailable")
    if artifact is not None:
        artifact = {k: v for k, v in artifact.items() if k != "created_at"}
    return _seal({"schema_version": 1, "version_id": version_id,
                  "document_id": version["document_id"], "original_id": version["original_id"],
                  "original_sha256": version["content_hash"], "artifact": artifact,
                  "profile": profile, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                  "acceptance": acceptance})


def limited_selection(store, version_id, profile, artifact=None, *, acceptance=None):
    if profile == "limited-metadata" and artifact is None:
        return _base(store, version_id, None, profile, "", acceptance), ""
    if profile == "ocr-accepted" and artifact is not None:
        # The final receipt id is filled by the review transaction at commit.
        return bundle_selection(store, version_id, artifact,
                                 acceptance=acceptance or "PENDING_EXPLICIT_REVIEW")
    raise ReviewUnavailable("Review either metadata-only or one complete uncertain OCR bundle")


def embedded_selection(store, version_id, *, optional=False):
    artifacts = [a for a in store.list_derived_artifacts()
                 if a.get("version_id") == version_id and a.get("kind") == "extracted_text"]
    if not artifacts or (len(artifacts) == 1 and artifacts[0].get("generator") != "pypdf"):
        if optional:
            return None
        raise ReviewUnavailable("Reliable embedded PDF text is absent")
    if len(artifacts) != 1:
        raise ReviewUnavailable("Reliable embedded PDF text is absent or ambiguous")
    artifact = artifacts[0]
    text = _verified_bytes(store, artifact["storage_ref"], artifact["checksum"]).decode("utf-8")
    characters, ratio = reliable_text_metrics(text, generator="pypdf")
    thresholds = settings(store).automatic
    if characters < thresholds.min_reliable_characters or ratio < thresholds.min_printable_ratio:
        if optional:
            return None
        raise ReviewUnavailable("Embedded PDF text does not meet the accepted reliability limits")
    return _base(store, version_id, artifact, "embedded", text), text


def bundle_selection(store, version_id, artifact, *, acceptance=None):
    """Verify the exact complete bundle; never pick a newest or partial bundle."""
    if (artifact.get("kind") != OCR_ARTIFACT_KIND or artifact.get("version_id") != version_id
            or artifact.get("generator") != "provelume.local_ocr"):
        raise ReviewUnavailable("Select one exact local OCR bundle")
    if not isinstance(artifact.get("id"), str):
        raise ReviewUnavailable("OCR artifact identity is missing")
    current = read_json(store, f"state/derived/artifacts/{artifact['id']}.json")
    if current is None or ({k: v for k, v in current.items() if k != "created_at"}
                           != {k: v for k, v in artifact.items() if k != "created_at"}):
        raise ReviewUnavailable("Selected OCR artifact metadata is missing or changed")
    from .annotation_store import AnnotationStore

    if AnnotationStore(store).history(artifact["id"])["count"]:
        raise ReviewUnavailable("Annotated OCR requires a supported annotation index profile")
    raw = _verified_bytes(store, artifact["storage_ref"], artifact["checksum"])
    manifest = json.loads(raw)
    from .ocr_jobs import OcrJobManager

    manager = OcrJobManager(store)
    job = manager.scheduler.journal.get_job(manifest["job"]["id"])
    if job is None:
        raise ReviewUnavailable("OCR bundle has no producer request")
    request = manager._request_for_job(job)
    version = store.read_canonical("versions", version_id)
    if (version is None or manifest["version_id"] != version_id
            or manifest["document_id"] != version["document_id"]
            or manifest["original"] != {"id": version["original_id"],
                                        "sha256": version["content_hash"]}
            or request["version_id"] != version_id
            or manifest["derivation_key"] != request["derivation_key"]
            or manifest["settings_sha256"] != request["settings_sha256"]
            or manifest["settings"] != request["settings"]
            or request["pages"] != list(range(1, len(request["page_plan"]) + 1))
            or [p["page_number"] for p in manifest["pages"]] != request["pages"]):
        raise ReviewUnavailable("Selected OCR does not cover the complete bound PDF")
    parts, total, uncertain = [], 0, False
    parent = artifact["storage_ref"].rsplit("/", 1)[0]
    for page in manifest["pages"]:
        number = page["page_number"]
        if (page["text_ref"] != f"{parent}/pages/{number:06d}.txt"
                or page["result_ref"] != f"{parent}/pages/{number:06d}.json"):
            raise ReviewUnavailable("OCR page evidence escapes its selected bundle")
        data = _verified_bytes(store, page["text_ref"], page["text_sha256"])
        record = json.loads(_verified_bytes(store, page["result_ref"], page["result_sha256"]))
        text = data.decode("utf-8")
        if (record["result"]["text"] != text
                or record["result"]["source_page"] != page["source_page"]):
            raise ReviewUnavailable("OCR page observations and text disagree")
        total += len(data)
        if total > MAX_TEXT_BYTES:
            raise ReviewUnavailable("Selected OCR text exceeds its complete-text bound")
        uncertain |= page["text_status"] != "machine-unverified" or bool(page["warning_count"])
        parts.append(text)
    text = "\n\n".join(parts)
    if not text.strip():
        raise ReviewUnavailable("Empty OCR is not evidence of searchable completion")
    if uncertain and acceptance is None:
        raise ReviewUnavailable("Uncertain OCR needs this Version's explicit acceptance")
    return _base(store, version_id, artifact,
                 "ocr-accepted" if acceptance else "ocr-complete", text, acceptance), text


def selected_text(store, version_id):
    value = read_json(store, selection_path(version_id))
    if value is None:
        return None
    if (set(value) != FIELDS or type(value["schema_version"]) is not int
            or value["schema_version"] != 1 or value["version_id"] != version_id
            or value["revision"] != digest({k: v for k, v in value.items() if k != "revision"})):
        raise ReviewUnavailable("Explicit text selection is invalid")
    version = store.read_canonical("versions", version_id)
    if version is None or any(value[k] != version[v] for k, v in (
        ("document_id", "document_id"), ("original_id", "original_id"),
        ("original_sha256", "content_hash"),
    )):
        raise ReviewUnavailable("Explicit selection has another Original or Version")
    if value["profile"] == "embedded":
        actual, text = embedded_selection(store, version_id)
    elif value["profile"] in {"ocr-complete", "ocr-accepted"}:
        actual, text = bundle_selection(store, version_id, value["artifact"],
                                        acceptance=value["acceptance"])
    elif value["profile"] == "limited-metadata" and value["acceptance"] is not None:
        actual, text = _base(store, version_id, None, "limited-metadata", "",
                             value["acceptance"]), ""
    else:
        raise ReviewUnavailable("Unsupported selected text profile")
    if actual != value:
        raise ReviewUnavailable("Selected text identity changed")
    if value["acceptance"] is not None:
        from .ocr_sources import SourceOcrReview
        from .review_routing import _Inputs

        history, _ = SourceOcrReview(store).history_record(value["acceptance"], _Inputs(store))
        if (history["action"] != "limited_result"
                or history["execution"]["selection"] != value):
            raise ReviewUnavailable("Limited text selection has no matching explicit acceptance")
    return value, text
