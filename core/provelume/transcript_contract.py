from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

TRANSCRIPT_CONTRACT_SCHEMA_VERSION = 1
TRANSCRIPT_ADAPTER_PROTOCOL_VERSION = 1
TRANSCRIPT_PARSER_PROTOCOL_VERSION = 1
TRANSCRIPT_ADAPTER_ID = "provelume.local-transcript"
TRANSCRIPT_ADAPTER_VERSION = "1.0.0"
TRANSCRIPT_PARSER_ID = "provelume.bounded-transcript"
TRANSCRIPT_PARSER_VERSION = "1.0.0"
TRANSCRIPT_JOB_KIND = "transcript.intake"

TRANSCRIPT_FORMATS = ("srt", "webvtt")
TRANSCRIPT_PROFILES = ("srt-v1", "webvtt-v1")
TRANSCRIPT_SUPPORTED_PROFILES = TRANSCRIPT_PROFILES
TRANSCRIPT_PROFILE_FORMATS = MappingProxyType(
    {"srt-v1": "srt", "webvtt-v1": "webvtt"}
)
TRANSCRIPT_PROFILE_EXTENSIONS = MappingProxyType(
    {"srt-v1": (".srt",), "webvtt-v1": (".vtt",)}
)
TRANSCRIPT_SOURCE_STATES = ("enabled", "paused", "disabled")
TRANSCRIPT_SELECTION_KINDS = ("file", "folder")
TRANSCRIPT_SOURCE_SCHEDULE_MODES = ("manual", "interval")

TRANSCRIPT_ERROR_CODES = (
    "transcript_disabled",
    "transcript_source_disabled",
    "transcript_source_paused",
    "transcript_source_removed",
    "transcript_source_missing",
    "transcript_source_unsafe",
    "transcript_profile_unsupported",
    "transcript_profile_mismatch",
    "transcript_encoding_unsupported",
    "transcript_input_non_regular",
    "transcript_input_changed",
    "transcript_enumeration_limit_exceeded",
    "transcript_file_limit_exceeded",
    "transcript_total_read_limit_exceeded",
    "transcript_line_limit_exceeded",
    "transcript_cue_limit_exceeded",
    "transcript_text_limit_exceeded",
    "transcript_output_limit_exceeded",
    "transcript_timestamp_invalid",
    "transcript_duration_limit_exceeded",
    "transcript_cue_malformed",
    "transcript_active_block_unsupported",
    "transcript_timeout",
    "transcript_cancelled",
    "transcript_derived_invalid",
    "transcript_internal_error",
)

TRANSCRIPT_WARNING_CODES = (
    "utf8_bom_removed",
    "line_endings_normalised",
    "cue_identifier_duplicate",
    "cue_duplicate",
    "cue_overlap",
    "cue_out_of_order",
    "speaker_label_ambiguous",
    "speaker_label_absent",
    "webvtt_note_ignored",
)

MIB = 1024 * 1024
KIB = 1024

TRANSCRIPT_LIMIT_CEILINGS = {
    "max_file_bytes": 256 * MIB,
    "max_files_per_job": 10_000,
    "max_enumerated_entries": 50_000,
    "max_total_read_bytes": 4 * 1024 * MIB,
    "max_cues_per_file": 100_000,
    "max_line_characters": 1 * MIB,
    "max_cue_characters": 5 * MIB,
    "max_text_characters_per_file": 50_000_000,
    "max_cue_duration_ms": 7 * 24 * 60 * 60 * 1000,
    "max_timeline_ms": 365 * 24 * 60 * 60 * 1000,
    "max_warnings_per_file": 10_000,
    "max_errors_per_job": 10_000,
    "max_temp_bytes_per_job": 8 * 1024 * MIB,
    "max_derived_bytes_per_file": 256 * MIB,
    "max_seconds_per_file": 300,
    "max_seconds_per_job": 86_400,
}


class TranscriptContractError(ValueError):
    """A closed, content-free transcript contract failure."""

    def __init__(self, code: str, message: str):
        if code not in TRANSCRIPT_ERROR_CODES:
            raise ValueError("transcript error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def _bounded_integer(value: Any, name: str, *, ceiling: int) -> int:
    if type(value) is not int or value < 1 or value > ceiling:
        raise TranscriptContractError(
            "transcript_internal_error",
            f"{name} must be an integer between 1 and {ceiling}",
        )
    return value


@dataclass(frozen=True, slots=True)
class TranscriptLimits:
    max_file_bytes: int = 32 * MIB
    max_files_per_job: int = 500
    max_enumerated_entries: int = 2_000
    max_total_read_bytes: int = 256 * MIB
    max_cues_per_file: int = 10_000
    max_line_characters: int = 16 * KIB
    max_cue_characters: int = 64 * KIB
    max_text_characters_per_file: int = 2_000_000
    max_cue_duration_ms: int = 24 * 60 * 60 * 1000
    max_timeline_ms: int = 30 * 24 * 60 * 60 * 1000
    max_warnings_per_file: int = 500
    max_errors_per_job: int = 500
    max_temp_bytes_per_job: int = 512 * MIB
    max_derived_bytes_per_file: int = 32 * MIB
    max_seconds_per_file: int = 30
    max_seconds_per_job: int = 600

    def __post_init__(self) -> None:
        for name, ceiling in TRANSCRIPT_LIMIT_CEILINGS.items():
            _bounded_integer(getattr(self, name), name, ceiling=ceiling)
        if self.max_total_read_bytes < self.max_file_bytes:
            raise TranscriptContractError(
                "transcript_internal_error",
                "total read limit cannot be lower than the file limit",
            )
        if self.max_enumerated_entries < self.max_files_per_job:
            raise TranscriptContractError(
                "transcript_internal_error",
                "enumeration limit cannot be lower than the file-count limit",
            )
        if self.max_temp_bytes_per_job < self.max_file_bytes:
            raise TranscriptContractError(
                "transcript_internal_error",
                "temporary-byte limit cannot be lower than the file limit",
            )
        if self.max_seconds_per_job < self.max_seconds_per_file:
            raise TranscriptContractError(
                "transcript_internal_error",
                "job deadline cannot be lower than the file deadline",
            )

    @classmethod
    def from_mapping(cls, value: Any) -> TranscriptLimits:
        if not isinstance(value, Mapping) or set(value) != set(TRANSCRIPT_LIMIT_CEILINGS):
            raise TranscriptContractError(
                "transcript_internal_error",
                "transcript limit fields are incomplete or unsupported",
            )
        return cls(**{name: value[name] for name in TRANSCRIPT_LIMIT_CEILINGS})

    def as_record(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TranscriptSourceConfig:
    source_id: str
    connector_instance_id: str
    profile: Literal["srt-v1", "webvtt-v1"]
    selection_kind: Literal["file", "folder"]
    path: Path = field(repr=False)
    state: Literal["enabled", "paused", "disabled"] = "disabled"
    config_revision: int = 1
    adapter_id: str = TRANSCRIPT_ADAPTER_ID
    adapter_version: str = TRANSCRIPT_ADAPTER_VERSION
    schema_version: int = TRANSCRIPT_CONTRACT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class TranscriptCue:
    ordinal: int
    start_ms: int
    end_ms: int
    identifier: str | None = field(default=None, repr=False)
    text: str = field(default="", repr=False)
    speaker_label: str | None = field(default=None, repr=False)
    settings: str | None = field(default=None, repr=False)
    warning_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedTranscript:
    profile: str
    format: str
    original_sha256: str
    original_size_bytes: int
    encoding: str
    bom: str | None
    source_line_endings: str
    cues: tuple[TranscriptCue, ...]
    warning_codes: tuple[str, ...]
    text_character_count: int
    parser_id: str = TRANSCRIPT_PARSER_ID
    parser_version: str = TRANSCRIPT_PARSER_VERSION
    parser_protocol_version: int = TRANSCRIPT_PARSER_PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class ObservedTranscriptBytes:
    source_id: str
    locator_sha256: str
    filesystem_identity_sha256: str
    mtime_ns: int
    size_bytes: int
    sha256: str
    data: bytes = field(repr=False)


def profile_format(profile: str) -> str:
    try:
        return TRANSCRIPT_PROFILE_FORMATS[profile]
    except KeyError as exc:
        raise TranscriptContractError(
            "transcript_profile_unsupported",
            "transcript profile is unsupported",
        ) from exc


def settings_fingerprint(
    limits: TranscriptLimits,
    *,
    parser_id: str = TRANSCRIPT_PARSER_ID,
    parser_version: str = TRANSCRIPT_PARSER_VERSION,
    parser_protocol_version: int = TRANSCRIPT_PARSER_PROTOCOL_VERSION,
    adapter_id: str = TRANSCRIPT_ADAPTER_ID,
    adapter_version: str = TRANSCRIPT_ADAPTER_VERSION,
) -> str:
    payload = {
        "schema_version": TRANSCRIPT_CONTRACT_SCHEMA_VERSION,
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "parser_id": parser_id,
        "parser_version": parser_version,
        "parser_protocol_version": parser_protocol_version,
        "limits": limits.as_record(),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def capability_report() -> dict[str, Any]:
    return {
        "schema_version": TRANSCRIPT_CONTRACT_SCHEMA_VERSION,
        "available": True,
        "default_enabled": False,
        "profiles": [
            {
                "id": profile,
                "format": TRANSCRIPT_PROFILE_FORMATS[profile],
                "versioned": True,
                "parser": {
                    "id": TRANSCRIPT_PARSER_ID,
                    "version": TRANSCRIPT_PARSER_VERSION,
                    "protocol_version": TRANSCRIPT_PARSER_PROTOCOL_VERSION,
                    "replaceable": True,
                },
                "encoding": "utf-8-or-utf-8-bom",
                "conformance": "deterministic-synthetic",
            }
            for profile in TRANSCRIPT_PROFILES
        ],
        "selection_kinds": list(TRANSCRIPT_SELECTION_KINDS),
        "network_access": "none",
        "network_required": False,
        "runtime_downloads": False,
        "remote_fallback": False,
        "active_content_executed": False,
        "source_mutation": False,
        "limits": TranscriptLimits().as_record(),
        "authority": {
            "original": "exact_bytes",
            "text": "derived",
            "speaker_labels": "unverified_observations",
            "timestamps": "unverified_observations",
        },
        "qualification": {
            "kind": "permanent-synthetic-local-smoke",
            "real_provider": False,
            "cloud_platform": False,
        },
    }


__all__ = [
    "ObservedTranscriptBytes",
    "ParsedTranscript",
    "TRANSCRIPT_ADAPTER_ID",
    "TRANSCRIPT_ADAPTER_VERSION",
    "TRANSCRIPT_CONTRACT_SCHEMA_VERSION",
    "TRANSCRIPT_ERROR_CODES",
    "TRANSCRIPT_JOB_KIND",
    "TRANSCRIPT_PARSER_ID",
    "TRANSCRIPT_PARSER_VERSION",
    "TRANSCRIPT_PROFILE_EXTENSIONS",
    "TRANSCRIPT_PROFILE_FORMATS",
    "TRANSCRIPT_PROFILES",
    "TRANSCRIPT_SELECTION_KINDS",
    "TRANSCRIPT_SOURCE_SCHEDULE_MODES",
    "TRANSCRIPT_SOURCE_STATES",
    "TRANSCRIPT_SUPPORTED_PROFILES",
    "TRANSCRIPT_WARNING_CODES",
    "TranscriptContractError",
    "TranscriptCue",
    "TranscriptLimits",
    "TranscriptSourceConfig",
    "capability_report",
    "profile_format",
    "settings_fingerprint",
]
