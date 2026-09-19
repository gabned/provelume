"""Append-only annotation history and a prepare-only shared review provider."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import datetime

from .annotation_model import (
    DIGEST,
    MAX_RECORD_BYTES,
    MAX_REVISIONS,
    SOURCE_ID,
    AnnotationError,
    apply_operations,
    encoded,
    exact,
    fingerprint,
    invalid,
    text,
    validate_segments,
    validate_source,
)
from .annotation_sources import AnnotationSources, bounded_json, original_authority
from .paths import native_path
from .review_decisions import checked_path
from .review_effects import ABSENT, PreparedEffect, PreparedWrite


def validate_annotation_record(value: dict) -> dict:
    exact(
        value,
        {
            "schema_version",
            "id",
            "revision",
            "previous_sha256",
            "source",
            "segments",
            "action",
            "restores_revision",
            "request_id",
            "principal",
            "recorded_at",
        },
    )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["revision"]) is not int
        or not 1 <= value["revision"] <= MAX_REVISIONS
        or value["action"] not in {"save", "undo"}
        or value["principal"] not in {"local_browser", "local_cli"}
    ):
        invalid("Invalid annotation revision")
    previous = value["previous_sha256"]
    if previous != ABSENT and (not isinstance(previous, str) or DIGEST.fullmatch(previous) is None):
        invalid("Invalid history predecessor")
    if (value["revision"] == 1) != (previous == ABSENT):
        invalid("History predecessor does not match its revision")
    text(value["request_id"], 200)
    if not value["request_id"]:
        invalid("Missing request attribution")
    try:
        stamp = datetime.fromisoformat(value["recorded_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            invalid("Missing attribution timezone")
    except (ValueError, AttributeError, TypeError) as exc:
        raise AnnotationError("annotation_invalid", "Invalid attribution time") from exc
    restores = value["restores_revision"]
    if value["action"] == "save" and restores is not None:
        invalid("Save cannot claim an undo")
    if value["action"] == "undo" and (
        type(restores) is not int or not 0 <= restores < value["revision"] - 1
    ):
        invalid("Undo must restore an earlier retained state")
    validate_source(value["source"])
    validate_segments(value["segments"], value["source"]["segments"])
    if value["id"] != "annrev_" + fingerprint({k: v for k, v in value.items() if k != "id"}):
        invalid("Annotation history identity differs")
    if len(encoded(value)) > MAX_RECORD_BYTES:
        invalid("Annotation history exceeds its byte limit")
    return value


class AnnotationStore:
    def __init__(self, store):
        self.store = store
        self.sources = AnnotationSources(store)

    @staticmethod
    def relative(subject: str, revision: int) -> str:
        if not isinstance(subject, str) or SOURCE_ID.fullmatch(subject) is None:
            invalid("Invalid annotation subject")
        if type(revision) is not int or not 1 <= revision <= MAX_REVISIONS:
            invalid("Annotation history is full")
        return f"state/review/annotations/{subject}/{revision:06d}.json"

    def history(self, subject: str) -> dict:
        self.relative(subject, 1)
        root = native_path(checked_path(self.store, f"state/review/annotations/{subject}"))
        if not root.exists():
            return {"records": [], "head": ABSENT, "count": 0}
        if not root.is_dir():
            invalid("Annotation history is not a directory")
        names = []
        for path in root.iterdir():
            if len(names) >= MAX_REVISIONS or re.fullmatch(r"[0-9]{6}\.json", path.name) is None:
                invalid("Annotation history is incomplete or exceeds its limit")
            names.append(path.name)
        if sorted(names) != [f"{i:06d}.json" for i in range(1, len(names) + 1)]:
            invalid("Annotation history contains a gap")
        records = []
        head = ABSENT
        source = None
        for index in range(1, len(names) + 1):
            path = native_path(checked_path(self.store, self.relative(subject, index)))
            record, raw = bounded_json(path)
            validate_annotation_record(record)
            if (
                record["revision"] != index
                or record["previous_sha256"] != head
                or record["source"]["id"] != subject
            ):
                invalid("Annotation history chain differs")
            if source is not None and record["source"] != source:
                invalid("History cannot silently inherit another result")
            source = record["source"]
            if record["action"] == "undo":
                target = record["restores_revision"]
                expected = source["segments"] if target == 0 else records[target - 1]["segments"]
                if record["segments"] != expected:
                    invalid("Undo does not restore its declared revision")
            records.append(record)
            head = hashlib.sha256(raw).hexdigest()
        return {"records": records, "head": head, "count": len(records)}

    def read(self, subject: str) -> dict:
        source = self.sources.get(subject)
        history = self.history(subject)
        records = history["records"]
        if records and records[-1]["source"] != source:
            raise AnnotationError("annotation_stale", "Result changed; annotations cannot transfer")
        return {
            "source": source,
            "head": history["head"],
            "revision": history["count"],
            "segments": deepcopy(records[-1]["segments"] if records else source["segments"]),
            "history": [
                {
                    k: row[k]
                    for k in (
                        "id",
                        "revision",
                        "action",
                        "principal",
                        "recorded_at",
                        "restores_revision",
                    )
                }
                for row in records
            ],
            "network_used": False,
            "mutated": False,
        }


class AnnotationProvider:
    domain = "annotations"
    actions = ("save", "undo")

    def __init__(self, store):
        self.annotations = AnnotationStore(store)

    def preview(self, subject: str, action: str, parameters: dict) -> dict:
        model = self.annotations.read(subject)
        source = model["source"]
        if model["revision"] >= MAX_REVISIONS:
            invalid("Retained annotation history has reached its closed limit")
        if action == "save":
            exact(parameters, {"operations"})
            segments = apply_operations(
                model["segments"], parameters["operations"], source["segments"]
            )
            restores = None
        elif action == "undo":
            exact(parameters, {"revision"})
            restores = parameters["revision"]
            if type(restores) is not int or not 0 <= restores < model["revision"]:
                invalid("Choose an earlier retained revision or original result")
            history = self.annotations.history(subject)
            if history["head"] != model["head"]:
                raise AnnotationError("annotation_stale", "Annotation history changed")
            segments = (
                source["segments"]
                if restores == 0
                else history["records"][restores - 1]["segments"]
            )
        else:
            invalid("Unsupported annotation action")
        if segments == model["segments"]:
            invalid("There are no annotation changes to save")
        snapshot = {
            "source": source,
            "head": model["head"],
            "revision": model["revision"],
            "segments": segments,
            "restores_revision": restores,
        }
        return {
            "input_revision": fingerprint({"source": source, "head": model["head"]}),
            "evidence": {
                "version": source["version"],
                "result": source["binding"],
                "revision": model["revision"],
                "head": model["head"],
            },
            "reason": "Attributed annotation on this exact retained OCR or transcript result",
            "confidence": None,
            "impact": {
                "segments_before": len(model["segments"]),
                "segments_after": len(segments),
                "original_changed": False,
                "engine_output_changed": False,
                "speaker_identity_verified": False,
            },
            "reversibility": "Append a new revision restoring a retained state",
            "snapshot": snapshot,
        }

    def allowed_paths(self, plan: dict, request_id: str) -> frozenset[str]:
        snapshot = plan["provider"]["snapshot"]
        validate_source(snapshot["source"])
        if (
            plan["domain"] != self.domain
            or plan["action"] not in self.actions
            or snapshot["source"]["id"] != plan["subject"]
        ):
            invalid("Annotation plan belongs to another subject")
        return frozenset({self.annotations.relative(plan["subject"], snapshot["revision"] + 1)})

    def prepare(
        self, plan: dict, *, request_id: str, principal: str, recorded_at: str
    ) -> PreparedEffect:
        paths = self.allowed_paths(plan, request_id)
        snapshot = plan["provider"]["snapshot"]
        record = {
            "schema_version": 1,
            "revision": snapshot["revision"] + 1,
            "previous_sha256": snapshot["head"],
            "source": snapshot["source"],
            "segments": snapshot["segments"],
            "action": plan["action"],
            "restores_revision": snapshot["restores_revision"],
            "request_id": request_id,
            "principal": principal,
            "recorded_at": recorded_at,
        }
        record["id"] = "annrev_" + fingerprint(record)
        validate_annotation_record(record)
        path = next(iter(paths))
        return PreparedEffect(
            self.domain,
            plan["action"],
            (PreparedWrite(path, ABSENT, encoded(record), immutable=True),),
            {
                "subject": plan["subject"],
                "revision": record["revision"],
                "annotation_id": record["id"],
                "history_ref": path,
                "speaker_identity_verified": False,
            },
            path,
            "Save attributed annotation history; preserve Original and engine output",
            "Undo appends a new revision with the exact selected earlier contents",
        )


def annotation_state_findings(store, *, deep: bool = True) -> list[str]:
    """ROOT integration hook: removed derived results do not remove retained human history."""
    findings = []
    try:
        root = native_path(checked_path(store, "state/review/annotations"))
        if not root.exists():
            return []
        if not root.is_dir():
            return ["annotation_state_not_directory"]
        reader = AnnotationStore(store)
        for index, path in enumerate(root.iterdir()):
            if index >= 1000:
                return [*findings, "annotation_state_limit_exceeded"]
            history = reader.history(path.name)
            if not history["records"]:
                continue
            source = history["records"][-1]["source"]
            if deep:
                version, _path = original_authority(store, source["version"]["id"])
                if version != source["version"]:
                    findings.append("annotation_original_binding_changed")
                try:
                    current = reader.sources.get(path.name)
                except AnnotationError as exc:
                    if exc.code != "annotation_unavailable":
                        findings.append("annotation_derived_evidence_invalid")
                else:
                    if current != source:
                        findings.append("annotation_derived_binding_changed")
    except (AnnotationError, OSError, ValueError, KeyError, TypeError):
        findings.append("annotation_history_invalid_or_unavailable")
    return findings
