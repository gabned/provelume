"""Read existing exact OCR/ASR/subtitle results without ensuring or deriving state."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .annotation_model import (
    MAX_RECORD_BYTES,
    MAX_SEGMENTS,
    MAX_TEXT,
    SOURCE_ID,
    AnnotationError,
    fingerprint,
    invalid,
    source_segment,
    validate_source,
)
from .paths import native_path
from .representations import validate_representation_bundle
from .review_decisions import checked_path
from .storage import InstanceStore

MAX_SOURCE_FILES = 1000
MAX_OUTPUT_BYTES = 64 * 1024 * 1024


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            invalid("Duplicate JSON field")
        value[key] = item
    return value


def bounded_json(path: Path, maximum: int = MAX_RECORD_BYTES) -> tuple[dict, bytes]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise AnnotationError("annotation_unavailable", "Evidence is absent or exceeds its limit")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        invalid("Evidence changed beyond its byte limit")
    try:
        result = json.loads(raw, object_pairs_hook=_unique)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AnnotationError("annotation_invalid", "Invalid evidence JSON") from exc
    if not isinstance(result, dict):
        invalid("Evidence must be an object")
    return result, raw


def verified_file(
    store: InstanceStore, reference: str, digest: str, size: int | None, maximum: int
) -> Path:
    path = native_path(checked_path(store, reference))
    if path.is_symlink() or not path.is_file():
        raise AnnotationError("annotation_unavailable", "Bound evidence is unavailable")
    actual_size = path.stat().st_size
    if actual_size > maximum or (size is not None and actual_size != size):
        invalid("Bound evidence size differs or exceeds its limit")
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                invalid("Bound evidence grew beyond its limit")
            h.update(chunk)
    if h.hexdigest() != digest or total != actual_size:
        invalid("Bound evidence checksum changed")
    return path


def original_authority(store: InstanceStore, version_id: str) -> tuple[dict, Path]:
    import re

    if not isinstance(version_id, str) or re.fullmatch(r"ver_[0-9a-f]{32}", version_id) is None:
        invalid("Invalid Version identity")
    relative = (
        (store.paths.canonical_dir("versions") / (version_id + ".json"))
        .relative_to(store.paths.root)
        .as_posix()
    )
    version, _ = bounded_json(native_path(checked_path(store, relative)))
    original_id = version.get("original_id")
    if (
        not isinstance(original_id, str)
        or re.fullmatch(r"sha256_[0-9a-f]{64}", original_id) is None
    ):
        invalid("Invalid Original identity")
    relative = (
        (store.paths.canonical_dir("originals") / (original_id + ".json"))
        .relative_to(store.paths.root)
        .as_posix()
    )
    original, _ = bounded_json(native_path(checked_path(store, relative)))
    if (
        version.get("id") != version_id
        or original.get("id") != original_id
        or original.get("sha256") != original_id[7:]
        or version.get("content_hash") != original["sha256"]
        or version.get("size_bytes") != original.get("size_bytes")
    ):
        invalid("Version and Original disagree")
    path = verified_file(
        store,
        original["storage_ref"],
        original["sha256"],
        original["size_bytes"],
        512 * 1024 * 1024,
    )
    return {
        "id": version_id,
        "original_id": original_id,
        "original_sha256": original["sha256"],
        "original_size_bytes": original["size_bytes"],
    }, path


def media_description(path: Path, kind: str) -> dict:
    with path.open("rb") as stream:
        head = stream.read(32)
    media = None
    selected = "unavailable"
    if kind == "ocr":
        for signature, mime in (
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"\xff\xd8\xff", "image/jpeg"),
            (b"II*\0", "image/tiff"),
            (b"MM\0*", "image/tiff"),
        ):
            if head.startswith(signature):
                selected, media = "image", mime
        if head.startswith(b"%PDF-"):
            selected, media = "pdf", "application/pdf"
    elif kind in {"audio", "video"}:
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            selected, media = "audio", "audio/wav"
        elif head[:4] == b"fLaC":
            selected, media = "audio", "audio/flac"
        elif head[:4] == b"OggS":
            selected, media = "audio", "audio/ogg"
        elif head[:3] == b"ID3" or head[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
            selected, media = "audio", "audio/mpeg"
        elif head[4:8] == b"ftyp":
            selected, media = kind, "video/mp4" if kind == "video" else "audio/mp4"
        elif kind == "video" and head.startswith(b"\x1aE\xdf\xa3"):
            selected, media = "video", "video/webm"
    return {"kind": selected, "media_type": media, "available": media is not None}


class AnnotationSources:
    def __init__(self, store: InstanceStore):
        self.store = store

    def _path(self, reference: str) -> Path:
        return native_path(checked_path(self.store, reference))

    def get(self, subject: str) -> dict:
        if not isinstance(subject, str) or SOURCE_ID.fullmatch(subject) is None:
            invalid("Invalid annotation subject")
        if subject.startswith("repr_"):
            value = self._representation(subject)
        else:
            value = self._legacy(subject)
        return validate_source(value)

    def list(self, *, limit: int = 100, version_id: str | None = None) -> dict:
        if version_id is not None and (
            not isinstance(version_id, str) or re.fullmatch(r"ver_[0-9a-f]{32}", version_id) is None
        ):
            invalid("Invalid editor Version filter")
        if type(limit) is not int or not 1 <= limit <= 500:
            invalid("Invalid editor list limit")
        items = []
        complete = True
        inspected = 0
        roots = [
            ("native", self._path("state/derived/representations")),
            (
                "legacy",
                self._path(
                    self.store.paths.derived_artifacts.relative_to(self.store.paths.root).as_posix()
                ),
            ),
        ]
        for family, root in roots:
            if inspected >= MAX_SOURCE_FILES:
                complete = False
                break
            if not root.exists():
                continue
            if not root.is_dir():
                invalid("Editor evidence inventory is not a directory")
            for path in root.iterdir():
                inspected += 1
                if inspected > MAX_SOURCE_FILES:
                    complete = False
                    break
                subject = path.name if family == "native" else path.stem
                if SOURCE_ID.fullmatch(subject) is None:
                    continue
                try:
                    relative = (
                        f"state/derived/representations/{subject}/bundle.json"
                        if family == "native"
                        else (
                            self.store.paths.derived_artifacts.relative_to(
                                self.store.paths.root
                            ).as_posix()
                            + "/"
                            + path.name
                        )
                    )
                    record, _ = bounded_json(self._path(relative))
                    if family == "native":
                        names = {
                            output["storage_ref"].rsplit("/", 1)[-1] for output in record["outputs"]
                        }
                        kind = (
                            "audio"
                            if "audio.json" in names
                            else "video"
                            if "video.json" in names
                            else None
                        )
                        version = record["version"]["id"]
                    else:
                        kind = {"ocr_document_bundle": "ocr", "transcript_bundle": "subtitle"}.get(
                            record.get("kind")
                        )
                        version = record["version_id"]
                    if kind is not None and (version_id is None or version == version_id):
                        items.append({"id": subject, "kind": kind, "version_id": version})
                except (AnnotationError, KeyError, TypeError, OSError, ValueError):
                    complete = False
        items.sort(key=lambda row: (row["kind"], row["id"]))
        return {
            "items": items[:limit],
            "complete": complete and len(items) <= limit,
            "count_relation": "exact" if complete else "at_least",
            "mutated": False,
            "network_used": False,
        }

    def _representation(self, subject: str) -> dict:
        root = f"state/derived/representations/{subject}/"
        bundle, raw = bounded_json(self._path(root + "bundle.json"))
        validate_representation_bundle(bundle)
        if bundle["representation_id"] != subject or bundle["lifecycle"]["state"] != "active":
            invalid("Representation identity or lifecycle changed")
        version, original_path = original_authority(self.store, bundle["version"]["id"])
        if version != bundle["version"]:
            invalid("Representation Original changed")
        outputs = {}
        total = 0
        for output in bundle["outputs"]:
            reference = output["storage_ref"]
            if (
                not reference.startswith(root + "outputs/")
                or "/" in reference[len(root + "outputs/") :]
            ):
                invalid("Output is outside the exact representation")
            total += output["size_bytes"]
            if total > MAX_OUTPUT_BYTES:
                invalid("Editor output verification limit exceeded")
            outputs[reference.rsplit("/", 1)[-1]] = verified_file(
                self.store, reference, output["sha256"], output["size_bytes"], MAX_OUTPUT_BYTES
            )
        kind = "audio" if "audio.json" in outputs else "video" if "video.json" in outputs else None
        if kind is None:
            raise AnnotationError("annotation_unavailable", "No supported anchored transcript")
        record, _ = bounded_json(outputs[kind + ".json"])
        if kind == "audio":
            from .audio_profiles import validate_audio_record

            validate_audio_record(record)
        else:
            from .video_profiles import validate_video_record

            validate_video_record(record)
        if (
            record["version_id"] != version["id"]
            or record["original_sha256"] != version["original_sha256"]
        ):
            invalid("Transcript source identity differs")
        transcript = record["transcript"]
        if transcript["state"] != "available":
            raise AnnotationError("annotation_unavailable", "Transcript is unavailable")
        anchor_targets = [a["target"] for a in bundle["anchors"] if a["kind"] == "time"]
        segments = []
        for row in transcript["segments"]:
            target = {"start_ms": row["start_ms"], "end_ms": row["end_ms"]}
            if target not in anchor_targets:
                invalid("Transcript segment has no authentic representation time anchor")
            segments.append(
                source_segment(
                    row["id"], row["text"], [{"kind": "time", **target}], row["confidence"]
                )
            )
        return {
            "schema_version": 1,
            "id": subject,
            "kind": kind,
            "version": version,
            "binding": {
                "result_sha256": hashlib.sha256(raw).hexdigest(),
                "recipe_sha256": bundle["recipe"]["fingerprint"],
                "implementation_sha256": fingerprint(
                    {
                        "implementation": bundle["implementation"],
                        "engine": transcript["engine"],
                        "model": transcript["model"],
                    }
                ),
            },
            "segments": segments,
            "media": media_description(original_path, kind),
        }

    def _legacy(self, subject: str) -> dict:
        artifact_path = self._path(
            (self.store.paths.derived_artifacts / (subject + ".json"))
            .relative_to(self.store.paths.root)
            .as_posix()
        )
        artifact, _ = bounded_json(artifact_path)
        if artifact.get("id") != subject or artifact.get("kind") not in {
            "ocr_document_bundle",
            "transcript_bundle",
        }:
            invalid("Unsupported derived source")
        reference = artifact["storage_ref"]
        prefix = (
            "state/derived/ocr-bundles/"
            if artifact["kind"] == "ocr_document_bundle"
            else ("state/derived/transcripts/")
        )
        if not reference.startswith(prefix) or not reference.endswith("/manifest.json"):
            invalid("Derived source is outside its owner namespace")
        manifest_path = verified_file(
            self.store, reference, artifact["checksum"], None, MAX_RECORD_BYTES
        )
        manifest, raw = bounded_json(manifest_path)
        version, original_path = original_authority(self.store, artifact["version_id"])
        if manifest["version_id"] != version["id"]:
            invalid("Derived Version binding differs")
        kind = "ocr" if artifact["kind"] == "ocr_document_bundle" else "subtitle"
        rows = []
        total_text = 0
        if kind == "ocr":
            if manifest["original"] != {
                "id": version["original_id"],
                "sha256": version["original_sha256"],
            }:
                invalid("OCR Original binding differs")
            pages = manifest["pages"]
            if not isinstance(pages, list) or not 1 <= len(pages) <= 200:
                invalid("OCR page limit exceeded")
            for page in pages:
                page_ref = page["result_ref"]
                if not page_ref.startswith(reference.rsplit("/", 1)[0] + "/pages/"):
                    invalid("OCR page lies outside the selected result")
                path = verified_file(
                    self.store, page_ref, page["result_sha256"], None, MAX_RECORD_BYTES
                )
                result = bounded_json(path)[0]["result"]
                identity = result["source_page"]
                if (
                    identity["version_id"] != version["id"]
                    or identity["original_sha256"] != version["original_sha256"]
                    or identity["page_number"] != page["page_number"]
                    or identity != page["source_page"]
                ):
                    invalid("OCR source page binding differs")
                spans = result["spans"] or [
                    {"text": result["text"], "box": None, "confidence": None}
                ]
                for index, span in enumerate(spans):
                    total_text += len(span["text"])
                    if total_text > MAX_TEXT:
                        invalid("Editor text limit exceeded")
                    anchor: dict[str, Any] = {"kind": "page", "page": page["page_number"]}
                    box = span["box"]
                    if box is not None:
                        if box["coordinate_space"] != "source-pixels":
                            invalid("Unknown OCR coordinates")
                        anchor.update(
                            kind="region",
                            x=box["left"],
                            y=box["top"],
                            width=box["width"],
                            height=box["height"],
                            page_width=box["page_width"],
                            page_height=box["page_height"],
                        )
                    rows.append(
                        source_segment(
                            f"{page['page_number']}:{index}",
                            span["text"],
                            [anchor],
                            span["confidence"],
                        )
                    )
                    if len(rows) > MAX_SEGMENTS:
                        invalid("Editor segment limit exceeded")
            recipe = manifest["settings_sha256"]
            implementation = fingerprint(
                {"adapter": manifest["adapter"], "renderer": manifest["renderer"]}
            )
        else:
            if (
                manifest["original_id"] != version["original_id"]
                or manifest["original_sha256"] != version["original_sha256"]
            ):
                invalid("Subtitle Original binding differs")
            cue_output = manifest["representations"]["cues"]
            if cue_output["storage_ref"] != reference.rsplit("/", 1)[0] + "/cues.json":
                invalid("Subtitle cues lie outside the selected result")
            path = verified_file(
                self.store,
                cue_output["storage_ref"],
                cue_output["sha256"],
                cue_output["size_bytes"],
                MAX_RECORD_BYTES,
            )
            cues = bounded_json(path)[0]
            if cues["revision_id"] != manifest["revision_id"] or cues["complete"] is not True:
                invalid("Incomplete or mismatched subtitle cues")
            if not isinstance(cues["cues"], list) or len(cues["cues"]) > MAX_SEGMENTS:
                invalid("Editor segment limit exceeded")
            rows = [
                source_segment(
                    row["id"],
                    row["text"],
                    [{"kind": "time", "start_ms": row["start_ms"], "end_ms": row["end_ms"]}],
                    speaker=row["speaker_label"],
                )
                for row in cues["cues"]
            ]
            recipe = manifest["parser"]["settings_sha256"]
            implementation = fingerprint(manifest["parser"])
        return {
            "schema_version": 1,
            "id": subject,
            "kind": kind,
            "version": version,
            "binding": {
                "result_sha256": hashlib.sha256(raw).hexdigest(),
                "recipe_sha256": recipe,
                "implementation_sha256": implementation,
            },
            "segments": rows,
            "media": media_description(original_path, kind),
        }

    def media(self, subject: str) -> tuple[Path, str]:
        source = self.get(subject)
        if not source["media"]["available"]:
            raise AnnotationError("annotation_unavailable", "Media was not attested")
        _version, path = original_authority(self.store, source["version"]["id"])
        return path, source["media"]["media_type"]
