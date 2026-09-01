from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

QUALIFICATION_SCHEMA_VERSION = 1
QUALIFICATION_ALGORITHM_ID = "provelume.cross-source-qualification"
QUALIFICATION_ALGORITHM_VERSION = "1.0.0"

QUALIFICATION_SOURCE_PROFILES = (
    "filesystem-document-v1",
    "ocr-document-bundle-v1",
    "local-email-v1",
    "gmail-synthetic-v1",
    "drive-synthetic-v1",
    "transcript-srt-v1",
    "transcript-webvtt-v1",
)

FINDING_TYPES = (
    "possible-exact-byte-duplicate",
    "possible-revision-relation",
    "observed-metadata-inconsistent",
    "checksum-provenance-incompatible",
    "timestamp-inconsistent",
    "language-format-discordant",
    "possible-same-event-document-content",
    "possible-participant-homonym",
    "representation-missing",
    "representation-obsolete",
    "representation-not-reconstructible",
    "representation-recipe-inconsistent",
    "qualification-required",
)

EPISTEMIC_STATES = (
    "deterministic-observation",
    "possible",
    "incompatible",
    "requires-human-review",
    "unqualified",
)

WORKFLOW_STATES = (
    "open",
    "acknowledged",
    "accepted",
    "rejected",
    "deferred",
    "superseded",
    "withdrawn",
    "reverted",
)

DECISION_ACTIONS = (
    "acknowledge",
    "accept",
    "reject",
    "defer",
    "declare-distinct",
    "add-relation",
    "correct-observation",
    "supersede",
    "withdraw",
    "revert",
)

DECISION_RESULT_STATES = {
    "acknowledge": "acknowledged",
    "accept": "accepted",
    "reject": "rejected",
    "defer": "deferred",
    "declare-distinct": "accepted",
    "add-relation": "accepted",
    "correct-observation": "accepted",
    "supersede": "superseded",
    "withdraw": "withdrawn",
    "revert": "reverted",
}

CORRECTION_FIELDS = (
    "format-observation",
    "language-observation",
    "timestamp-observation",
    "speaker-label-status",
    "participant-distinction",
    "relationship-note",
)

QUALIFICATION_ERROR_CODES = (
    "qualification_cancelled",
    "qualification_conflict",
    "qualification_input_changed",
    "qualification_internal_error",
    "qualification_invalid_decision",
    "qualification_invalid_source",
    "qualification_lease_expired",
    "qualification_limit_exceeded",
    "qualification_not_found",
    "qualification_output_limit_exceeded",
    "qualification_reference_stale",
    "qualification_retry_exhausted",
)

_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_FINDING_ID = re.compile(r"finding_[0-9a-f]{64}\Z")
_DECISION_ID = re.compile(r"decision_[0-9a-f]{64}\Z")
_ACTOR_ID = re.compile(r"[a-z][a-z0-9_.-]{1,79}\Z")
_SAFE_VALUE = re.compile(r"[\w .,:;()'\-/]{1,256}\Z", re.UNICODE)


class QualificationError(ValueError):
    def __init__(self, code: str, message: str):
        if code not in QUALIFICATION_ERROR_CODES:
            raise ValueError("qualification error code is outside the closed registry")
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class QualificationLimits:
    max_sources: int = 16
    max_objects: int = 10_000
    max_findings: int = 10_000
    max_candidate_relations: int = 50_000
    max_batch_size: int = 500
    max_job_seconds: int = 600
    max_temporary_bytes: int = 512 * 1024 * 1024
    max_evidence_bytes: int = 4096
    max_output_bytes: int = 32 * 1024 * 1024
    max_reason_characters: int = 1000
    lease_seconds: int = 120
    max_attempts: int = 3

    def __post_init__(self) -> None:
        ceilings = QualificationLimits.ceilings()
        for name, maximum in ceilings.items():
            value = getattr(self, name)
            if type(value) is not int or value < 1 or value > maximum:
                raise QualificationError(
                    "qualification_limit_exceeded",
                    f"qualification limit {name} is outside the closed boundary",
                )
        if self.max_sources < 2:
            raise QualificationError(
                "qualification_limit_exceeded",
                "cross-source qualification requires at least two Sources",
            )
        if self.max_batch_size > self.max_objects:
            raise QualificationError(
                "qualification_limit_exceeded",
                "qualification batch size cannot exceed the object limit",
            )

    @staticmethod
    def ceilings() -> dict[str, int]:
        return {
            "max_sources": 64,
            "max_objects": 100_000,
            "max_findings": 100_000,
            "max_candidate_relations": 500_000,
            "max_batch_size": 10_000,
            "max_job_seconds": 86_400,
            "max_temporary_bytes": 8 * 1024 * 1024 * 1024,
            "max_evidence_bytes": 64 * 1024,
            "max_output_bytes": 1024 * 1024 * 1024,
            "max_reason_characters": 4000,
            "lease_seconds": 3600,
            "max_attempts": 8,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> QualificationLimits:
        if value is None:
            return cls()
        expected = set(asdict(cls()))
        if set(value) != expected:
            raise QualificationError(
                "qualification_limit_exceeded",
                "qualification limits are incomplete or contain unknown fields",
            )
        return cls(**{name: value[name] for name in expected})

    def as_record(self) -> dict[str, int]:
        return asdict(self)


def normalise_source_ids(values: Any, limits: QualificationLimits) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise QualificationError(
            "qualification_invalid_source", "qualification Sources must be a sequence"
        )
    selected = tuple(sorted({str(value) for value in values}))
    if not 2 <= len(selected) <= limits.max_sources:
        raise QualificationError(
            "qualification_limit_exceeded",
            "qualification Source count is outside the effective limit",
        )
    if any(_SOURCE_ID.fullmatch(value) is None for value in selected):
        raise QualificationError(
            "qualification_invalid_source", "qualification Source identity is invalid"
        )
    return selected


def normalise_actor_id(value: Any) -> str:
    if not isinstance(value, str):
        raise QualificationError(
            "qualification_invalid_decision", "decision actor must be an opaque local identity"
        )
    selected = unicodedata.normalize("NFC", value.strip()).casefold()
    if _ACTOR_ID.fullmatch(selected) is None:
        raise QualificationError(
            "qualification_invalid_decision", "decision actor identity is invalid"
        )
    return selected


def sanitise_reason(value: Any, limits: QualificationLimits) -> str:
    if not isinstance(value, str):
        raise QualificationError("qualification_invalid_decision", "decision reason must be text")
    selected = unicodedata.normalize("NFC", value.strip())
    if not selected or len(selected) > limits.max_reason_characters:
        raise QualificationError(
            "qualification_invalid_decision", "decision reason is empty or too long"
        )
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in selected):
        raise QualificationError(
            "qualification_invalid_decision", "decision reason contains control characters"
        )
    lowered = selected.casefold()
    forbidden = ("<script", "javascript:", "data:", "file:", "http://", "https://")
    if selected.startswith(("=", "+", "-", "@")) or any(item in lowered for item in forbidden):
        raise QualificationError(
            "qualification_invalid_decision", "decision reason contains active-like content"
        )
    return selected


def normalise_decision_payload(action: str, value: Any) -> dict[str, Any]:
    if value is None:
        selected: dict[str, Any] = {}
    elif isinstance(value, Mapping):
        selected = dict(value)
    else:
        raise QualificationError(
            "qualification_invalid_decision", "decision payload must be an object"
        )
    allowed_by_action = {
        "acknowledge": set(),
        "accept": set(),
        "reject": set(),
        "defer": {"until"},
        "declare-distinct": {"object_ids"},
        "add-relation": {"relation_type", "object_ids"},
        "correct-observation": {"field", "value"},
        "supersede": {"supersedes_decision_id"},
        "withdraw": {"target_decision_id"},
        "revert": {"target_decision_id"},
    }
    if action not in allowed_by_action or set(selected) != allowed_by_action[action]:
        raise QualificationError(
            "qualification_invalid_decision",
            "decision payload does not match the selected action",
        )
    result: dict[str, Any] = {}
    if "until" in selected:
        until = selected["until"]
        if not isinstance(until, str) or len(until) > 80:
            raise QualificationError("qualification_invalid_decision", "defer timestamp is invalid")
        result["until"] = until
    if "object_ids" in selected:
        values = selected["object_ids"]
        if not isinstance(values, (list, tuple)) or not 2 <= len(values) <= 16:
            raise QualificationError(
                "qualification_invalid_decision", "decision object references are invalid"
            )
        object_ids = tuple(sorted({str(item) for item in values}))
        if len(object_ids) < 2 or any(len(item) > 160 or not item for item in object_ids):
            raise QualificationError(
                "qualification_invalid_decision", "decision object references are invalid"
            )
        result["object_ids"] = list(object_ids)
    if "relation_type" in selected:
        relation_type = selected["relation_type"]
        if relation_type not in {"related", "revision-of", "distinct-from"}:
            raise QualificationError(
                "qualification_invalid_decision", "decision relation type is unsupported"
            )
        result["relation_type"] = relation_type
    if "field" in selected:
        if selected["field"] not in CORRECTION_FIELDS:
            raise QualificationError(
                "qualification_invalid_decision", "correction field is unsupported"
            )
        replacement = selected["value"]
        if not isinstance(replacement, str):
            raise QualificationError(
                "qualification_invalid_decision", "correction value must be inert text"
            )
        replacement = unicodedata.normalize("NFC", replacement.strip())
        if _SAFE_VALUE.fullmatch(replacement) is None or replacement.startswith(
            ("=", "+", "-", "@")
        ):
            raise QualificationError(
                "qualification_invalid_decision", "correction value is unsafe or unsupported"
            )
        result.update({"field": selected["field"], "value": replacement})
    for key in ("supersedes_decision_id", "target_decision_id"):
        if key in selected:
            decision_id = selected[key]
            if not isinstance(decision_id, str) or _DECISION_ID.fullmatch(decision_id) is None:
                raise QualificationError(
                    "qualification_invalid_decision", "target decision identity is invalid"
                )
            result[key] = decision_id
    return result


def validate_finding_id(value: Any) -> str:
    if not isinstance(value, str) or _FINDING_ID.fullmatch(value) is None:
        raise QualificationError("qualification_not_found", "qualification finding was not found")
    return value


def qualification_matrix() -> dict[str, Any]:
    return {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "matrix_version": "2026-09-01.1",
        "claim_boundary": (
            "synthetic conformance is not authenticated real-provider qualification"
        ),
        "profiles": [
            {
                "id": "filesystem-document-v1",
                "deterministic_local_conformance": "qualified",
                "platform_preview": ["ubuntu-24.04-x86_64", "windows-2025-x86_64"],
                "authenticated_real_qualification": "not-applicable",
                "conditions": ["exact canonical and Original bindings", "no source mutation"],
            },
            {
                "id": "ocr-document-bundle-v1",
                "deterministic_local_conformance": "qualified",
                "platform_preview": ["ubuntu-24.04-x86_64"],
                "authenticated_real_qualification": "not-applicable",
                "conditions": [
                    "external Tesseract 5.x and eng",
                    "pypdfium2 5.13.0/PDFium 153.0.7999.0",
                    "Pillow 12.3.0",
                ],
            },
            {
                "id": "local-email-v1",
                "deterministic_local_conformance": "qualified",
                "platform_preview": [
                    "eml:ubuntu-24.04-x86_64",
                    "eml:windows-2025-x86_64",
                    "maildir:ubuntu-24.04-x86_64",
                ],
                "authenticated_real_qualification": "not-applicable",
                "conditions": ["CPython 3.12", "explicit Source", "bounded MIME profile"],
            },
            {
                "id": "gmail-synthetic-v1",
                "deterministic_local_conformance": "synthetic-qualified",
                "platform_preview": ["ubuntu-24.04-x86_64", "windows-2025-x86_64"],
                "authenticated_real_qualification": "unqualified",
                "conditions": ["no credentials", "no network", "read-only synthetic adapter"],
            },
            {
                "id": "drive-synthetic-v1",
                "deterministic_local_conformance": "synthetic-qualified",
                "platform_preview": ["ubuntu-24.04-x86_64", "windows-2025-x86_64"],
                "authenticated_real_qualification": "unqualified",
                "conditions": ["no credentials", "no network", "read-only synthetic adapter"],
            },
            {
                "id": "transcript-srt-v1",
                "deterministic_local_conformance": "qualified",
                "platform_preview": ["ubuntu-24.04-x86_64", "windows-2025-x86_64"],
                "authenticated_real_qualification": "not-applicable",
                "conditions": ["CPython 3.12", "strict UTF-8", "srt-v1"],
            },
            {
                "id": "transcript-webvtt-v1",
                "deterministic_local_conformance": "qualified",
                "platform_preview": ["ubuntu-24.04-x86_64", "windows-2025-x86_64"],
                "authenticated_real_qualification": "not-applicable",
                "conditions": ["CPython 3.12", "strict UTF-8", "webvtt-v1"],
            },
        ],
        "unqualified_combinations": [
            "real Gmail without permanent authorized exact-head smoke",
            "real Drive without permanent authorized exact-head smoke",
            "Maildir on Windows",
            "macOS, ARM, other Python versions and unlisted component combinations",
            "any automatic identity, semantic or provider-object merge",
        ],
    }


__all__ = [
    "CORRECTION_FIELDS",
    "DECISION_ACTIONS",
    "DECISION_RESULT_STATES",
    "EPISTEMIC_STATES",
    "FINDING_TYPES",
    "QUALIFICATION_ALGORITHM_ID",
    "QUALIFICATION_ALGORITHM_VERSION",
    "QUALIFICATION_ERROR_CODES",
    "QUALIFICATION_SCHEMA_VERSION",
    "QUALIFICATION_SOURCE_PROFILES",
    "QualificationError",
    "QualificationLimits",
    "WORKFLOW_STATES",
    "normalise_actor_id",
    "normalise_decision_payload",
    "normalise_source_ids",
    "qualification_matrix",
    "sanitise_reason",
    "validate_finding_id",
]
