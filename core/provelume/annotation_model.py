"""Bounded, inert annotations; engine output and its authentic anchors stay immutable."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any

MAX_SEGMENTS = 1000
MAX_TEXT = 500_000
MAX_OPERATIONS = 100
MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_REVISIONS = 64
SOURCE_ID = re.compile(r"(?:repr_[0-9a-f]{64}|derived_[0-9a-f]{32})\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class AnnotationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def invalid(message: str = "Annotation evidence is invalid") -> None:
    raise AnnotationError("annotation_invalid", message)


def encoded(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def exact(value: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        invalid()
    return value


def text(value: Any, maximum: int = MAX_TEXT) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or any(ord(c) < 32 and c not in "\n\t\r" for c in value)
        or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        invalid("Annotation text exceeds its limit or contains invalid controls")
    return value


def validate_anchor(anchor: Any) -> dict[str, Any]:
    if not isinstance(anchor, dict):
        invalid()
    kind = anchor.get("kind")
    if kind == "page":
        exact(anchor, {"kind", "page"})
    elif kind == "region":
        exact(anchor, {"kind", "page", "x", "y", "width", "height", "page_width", "page_height"})
        for key in ("x", "y", "width", "height", "page_width", "page_height"):
            val = anchor[key]
            if type(val) not in (int, float) or not math.isfinite(val) or not 0 <= val <= 1_000_000:
                invalid("Invalid region")
        if (
            min(anchor[k] for k in ("width", "height", "page_width", "page_height")) <= 0
            or anchor["x"] + anchor["width"] > anchor["page_width"]
            or anchor["y"] + anchor["height"] > anchor["page_height"]
        ):
            invalid("Region lies outside its source page")
    elif kind == "time":
        exact(anchor, {"kind", "start_ms", "end_ms"})
        if (
            type(anchor["start_ms"]) is not int
            or type(anchor["end_ms"]) is not int
            or not 0 <= anchor["start_ms"] <= anchor["end_ms"] <= 86_400_000
        ):
            invalid("Invalid time anchor")
    else:
        invalid("Unsupported annotation anchor")
    if kind in {"page", "region"} and (
        type(anchor["page"]) is not int or not 1 <= anchor["page"] <= 1_000_000
    ):
        invalid("Invalid page")
    return anchor


def validate_segments(value: Any, source: list[dict[str, Any]] | None = None) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SEGMENTS:
        invalid("Annotation segment count is unavailable or exceeds the limit")
    ids: set[str] = set()
    origins = {s["id"]: s for s in source} if source is not None else None
    total = 0
    for row in value:
        exact(row, {"id", "text", "speaker_label", "confidence", "anchors", "lineage"})
        if not isinstance(row["id"], str) or not re.fullmatch(r"aseg_[0-9a-f]{64}", row["id"]):
            invalid("Invalid segment identity")
        if row["id"] in ids:
            invalid("Duplicate segment identity")
        ids.add(row["id"])
        total += len(text(row["text"]))
        if row["speaker_label"] is not None:
            text(row["speaker_label"], 200)
        confidence = row["confidence"]
        if confidence is not None and (
            type(confidence) not in (int, float)
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            invalid("Invalid confidence")
        if not isinstance(row["anchors"], list) or not 1 <= len(row["anchors"]) <= 1000:
            invalid("Missing or excessive anchors")
        for anchor in row["anchors"]:
            validate_anchor(anchor)
        if len({fingerprint(a) for a in row["anchors"]}) != len(row["anchors"]):
            invalid("Repeated anchor")
        lineage = row["lineage"]
        if (
            not isinstance(lineage, list)
            or not 1 <= len(lineage) <= MAX_SEGMENTS
            or any(not isinstance(item, str) for item in lineage)
            or len(set(lineage)) != len(lineage)
        ):
            invalid("Invalid source lineage")
        if origins is None:
            if lineage != [row["id"]]:
                invalid("Source segment cannot invent lineage")
        else:
            if any(item not in origins for item in lineage):
                invalid("Unknown source segment")
            anchors = {fingerprint(a) for item in lineage for a in origins[item]["anchors"]}
            if {fingerprint(a) for a in row["anchors"]} != anchors:
                invalid("Annotation anchors must remain exactly source bound")
            expected_confidence = origins[lineage[0]]["confidence"] if len(lineage) == 1 else None
            if row["confidence"] != expected_confidence:
                invalid("Annotations cannot manufacture confidence")
    if total > MAX_TEXT:
        invalid("Annotation text exceeds its aggregate limit")
    if origins is not None and {item for row in value for item in row["lineage"]} != set(origins):
        invalid("An annotation cannot discard source lineage")
    return value


def source_segment(key: str, value: str, anchors: list, confidence=None, speaker=None) -> dict:
    identity = "aseg_" + fingerprint({"key": key, "text": value, "anchors": anchors})
    return {
        "id": identity,
        "text": value,
        "speaker_label": speaker,
        "confidence": confidence,
        "anchors": anchors,
        "lineage": [identity],
    }


def validate_source(value: Any) -> dict:
    exact(value, {"schema_version", "id", "kind", "version", "binding", "segments", "media"})
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or not isinstance(value["id"], str)
        or SOURCE_ID.fullmatch(value["id"]) is None
        or value["kind"] not in {"ocr", "audio", "video", "subtitle"}
    ):
        invalid("Invalid annotation source")
    version = exact(
        value["version"], {"id", "original_id", "original_sha256", "original_size_bytes"}
    )
    if (
        not isinstance(version["id"], str)
        or re.fullmatch(r"ver_[0-9a-f]{32}", version["id"]) is None
        or not isinstance(version["original_sha256"], str)
        or DIGEST.fullmatch(version["original_sha256"]) is None
        or version["original_id"] != "sha256_" + version["original_sha256"]
        or type(version["original_size_bytes"]) is not int
        or not 0 <= version["original_size_bytes"] <= 512 * 1024 * 1024
    ):
        invalid("Invalid annotation Original binding")
    binding = exact(value["binding"], {"result_sha256", "recipe_sha256", "implementation_sha256"})
    if any(not isinstance(v, str) or DIGEST.fullmatch(v) is None for v in binding.values()):
        invalid("Invalid annotation result binding")
    media = exact(value["media"], {"kind", "media_type", "available"})
    if media["kind"] not in {"image", "pdf", "audio", "video", "unavailable"}:
        invalid("Invalid evidence media")
    allowed_media = {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/tiff",
        "application/pdf",
        "audio/wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/ogg",
        "audio/flac",
        "video/mp4",
        "video/webm",
        None,
    }
    if (
        media["media_type"] not in allowed_media
        or type(media["available"]) is not bool
        or media["available"] != (media["kind"] != "unavailable")
        or media["available"] != (media["media_type"] is not None)
    ):
        invalid("Invalid media availability")
    validate_segments(value["segments"])
    if len(encoded(value)) > MAX_RECORD_BYTES // 2:
        invalid("Annotation source exceeds the retained evidence limit")
    return value


def apply_operations(segments: list, operations: Any, source: list) -> list:
    """Client supplies text operations only; coordinates/times always come from evidence.

    Split parts share the authentic source anchor. No interpolated timing or region
    is labelled observed. Merge preserves the ordered union of original anchors.
    """
    result = deepcopy(validate_segments(segments, source))
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
        invalid("Invalid operation count")
    for op in operations:
        if not isinstance(op, dict) or op.get("kind") not in {"edit", "speaker", "merge", "split"}:
            invalid("Unsupported editor operation")
        kind = op["kind"]
        fields = {
            "kind",
            "segment",
            {"edit": "text", "speaker": "label", "merge": "next", "split": "offset"}[kind],
        }
        exact(op, fields)
        index = next((i for i, row in enumerate(result) if row["id"] == op["segment"]), None)
        if index is None:
            invalid("Editor segment changed")
        row = result[index]
        if kind == "edit":
            row["text"] = text(op["text"])
        elif kind == "speaker":
            row["speaker_label"] = None if op["label"] is None else text(op["label"], 200)
        elif kind == "split":
            offset = op["offset"]
            if type(offset) is not int or not 0 < offset < len(row["text"]):
                invalid("Split must be inside the selected text")
            children = []
            for ordinal, part in enumerate((row["text"][:offset], row["text"][offset:])):
                child = deepcopy(row)
                child["id"] = "aseg_" + fingerprint(
                    {"parent": row, "offset": offset, "part": ordinal}
                )
                child["text"] = part
                children.append(child)
            result[index : index + 1] = children
        else:
            if index + 1 >= len(result) or result[index + 1]["id"] != op["next"]:
                invalid("Only adjacent segments can merge")
            following = result[index + 1]
            joined = deepcopy(row)
            joined["id"] = "aseg_" + fingerprint({"left": row, "right": following})
            joined["text"] += "\n" + following["text"]
            joined["lineage"] = list(dict.fromkeys(row["lineage"] + following["lineage"]))
            joined["anchors"] = list(
                {fingerprint(a): a for a in (row["anchors"] + following["anchors"])}.values()
            )
            joined["confidence"] = row["confidence"] if len(joined["lineage"]) == 1 else None
            if row["speaker_label"] != following["speaker_label"]:
                joined["speaker_label"] = None
            result[index : index + 2] = [joined]
        validate_segments(result, source)
    return result
