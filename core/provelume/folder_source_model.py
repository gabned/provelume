from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .ingest import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_FILES

FOLDER_SOURCE_SCHEMA_VERSION = 1
SOURCE_CLASSES = ("local", "removable", "network")
SOURCE_LIFECYCLE_STATES = ("enabled", "paused")
SOURCE_AVAILABILITY_STATES = ("available", "missing", "attention")
SOURCE_PHASES = (
    "unobserved",
    "paused",
    "missing",
    "quiescing",
    "ready",
    "refreshing",
    "current",
    "attention",
)
SOURCE_ERROR_CODES = (
    "configuration_invalid",
    "input_io_error",
    "input_unreadable",
    "ingestion_failed",
    "ingestion_limit",
    "source_changed_during_refresh",
    "unsafe_path",
)

DEFAULT_QUIESCENCE_SECONDS = 5
DEFAULT_STABLE_OBSERVATIONS = 2
MAX_QUIESCENCE_SECONDS = 7 * 24 * 60 * 60
MAX_STABLE_OBSERVATIONS = 100
MAX_FOLDER_PATH_CHARS = 4096

_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_POLICY_ID = re.compile(r"policy_[0-9a-f]{32}\Z")
_RUN_ID = re.compile(r"run_[0-9a-f]{32}\Z")
_JOB_ID = re.compile(r"job_[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class FolderSourceError(ValueError):
    pass


class FolderSourceNotFound(FolderSourceError):
    pass


def _integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise FolderSourceError(f"{label} must be between {minimum} and {maximum}")
    return value


def _optional_identifier(value: Any, label: str, pattern: re.Pattern[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise FolderSourceError(f"invalid {label}")
    return value


def _optional_fingerprint(value: Any, label: str) -> str | None:
    return _optional_identifier(value, label, _SHA256)


def _optional_instant(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FolderSourceError(f"invalid {label}")
    try:
        selected = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FolderSourceError(f"invalid {label}") from exc
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise FolderSourceError(f"invalid {label}")
    return selected.astimezone(UTC).isoformat()


def normalise_folder_config(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "source_class",
        "lifecycle_state",
        "quiescence_seconds",
        "stable_observations",
        "max_file_bytes",
        "max_files",
        "policy_id",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise FolderSourceError("folder Source configuration fields are incomplete")
    source_class = value.get("source_class")
    lifecycle_state = value.get("lifecycle_state")
    if (
        value.get("schema_version") != FOLDER_SOURCE_SCHEMA_VERSION
        or source_class not in SOURCE_CLASSES
        or lifecycle_state not in SOURCE_LIFECYCLE_STATES
    ):
        raise FolderSourceError("folder Source configuration identity is invalid")
    return {
        "schema_version": FOLDER_SOURCE_SCHEMA_VERSION,
        "source_class": source_class,
        "lifecycle_state": lifecycle_state,
        "quiescence_seconds": _integer(
            value.get("quiescence_seconds"),
            "quiescence_seconds",
            minimum=0,
            maximum=MAX_QUIESCENCE_SECONDS,
        ),
        "stable_observations": _integer(
            value.get("stable_observations"),
            "stable_observations",
            minimum=1,
            maximum=MAX_STABLE_OBSERVATIONS,
        ),
        "max_file_bytes": _integer(
            value.get("max_file_bytes"),
            "max_file_bytes",
            minimum=1,
            maximum=2**63 - 1,
        ),
        "max_files": _integer(
            value.get("max_files"),
            "max_files",
            minimum=1,
            maximum=2**31 - 1,
        ),
        "policy_id": _optional_identifier(value.get("policy_id"), "policy ID", _POLICY_ID),
    }


def folder_config_payload(
    *,
    source_class: str,
    lifecycle_state: str,
    quiescence_seconds: int = DEFAULT_QUIESCENCE_SECONDS,
    stable_observations: int = DEFAULT_STABLE_OBSERVATIONS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    policy_id: str | None = None,
) -> dict[str, Any]:
    return normalise_folder_config(
        {
            "schema_version": FOLDER_SOURCE_SCHEMA_VERSION,
            "source_class": source_class,
            "lifecycle_state": lifecycle_state,
            "quiescence_seconds": quiescence_seconds,
            "stable_observations": stable_observations,
            "max_file_bytes": max_file_bytes,
            "max_files": max_files,
            "policy_id": policy_id,
        }
    )


def new_observer_record(source_id: str, *, lifecycle_state: str) -> dict[str, Any]:
    phase = "paused" if lifecycle_state == "paused" else "unobserved"
    return normalise_observer_record(
        {
            "schema_version": FOLDER_SOURCE_SCHEMA_VERSION,
            "source_id": source_id,
            "lifecycle_state": lifecycle_state,
            "availability": "missing",
            "phase": phase,
            "last_observed_at": None,
            "last_available_at": None,
            "last_missing_at": None,
            "pending_since": None,
            "pending_fingerprint": None,
            "ingested_fingerprint": None,
            "last_attempted_fingerprint": None,
            "change_sequence": 0,
            "stable_observations": 0,
            "file_count": 0,
            "total_bytes": 0,
            "clock_change_count": 0,
            "active_run_id": None,
            "last_ingestion_run_id": None,
            "last_scheduler_job_id": None,
            "last_error_code": None,
            "updated_at": None,
            "network_used": False,
            "automatic_deletion": False,
        }
    )


def normalise_observer_record(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "source_id",
        "lifecycle_state",
        "availability",
        "phase",
        "last_observed_at",
        "last_available_at",
        "last_missing_at",
        "pending_since",
        "pending_fingerprint",
        "ingested_fingerprint",
        "last_attempted_fingerprint",
        "change_sequence",
        "stable_observations",
        "file_count",
        "total_bytes",
        "clock_change_count",
        "active_run_id",
        "last_ingestion_run_id",
        "last_scheduler_job_id",
        "last_error_code",
        "updated_at",
        "network_used",
        "automatic_deletion",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise FolderSourceError("folder Source observer fields are incomplete")
    source_id = value.get("source_id")
    lifecycle_state = value.get("lifecycle_state")
    availability = value.get("availability")
    phase = value.get("phase")
    error_code = value.get("last_error_code")
    if (
        value.get("schema_version") != FOLDER_SOURCE_SCHEMA_VERSION
        or not isinstance(source_id, str)
        or _SOURCE_ID.fullmatch(source_id) is None
        or lifecycle_state not in SOURCE_LIFECYCLE_STATES
        or availability not in SOURCE_AVAILABILITY_STATES
        or phase not in SOURCE_PHASES
        or (error_code is not None and error_code not in SOURCE_ERROR_CODES)
        or type(value.get("network_used")) is not bool
        or value.get("automatic_deletion") is not False
    ):
        raise FolderSourceError("folder Source observer identity is invalid")
    if phase == "paused" and lifecycle_state != "paused":
        raise FolderSourceError("only a paused Source may have a paused observer")
    return {
        "schema_version": FOLDER_SOURCE_SCHEMA_VERSION,
        "source_id": source_id,
        "lifecycle_state": lifecycle_state,
        "availability": availability,
        "phase": phase,
        "last_observed_at": _optional_instant(value.get("last_observed_at"), "last observation"),
        "last_available_at": _optional_instant(value.get("last_available_at"), "last availability"),
        "last_missing_at": _optional_instant(value.get("last_missing_at"), "last missing time"),
        "pending_since": _optional_instant(value.get("pending_since"), "pending time"),
        "pending_fingerprint": _optional_fingerprint(
            value.get("pending_fingerprint"), "pending fingerprint"
        ),
        "ingested_fingerprint": _optional_fingerprint(
            value.get("ingested_fingerprint"), "ingested fingerprint"
        ),
        "last_attempted_fingerprint": _optional_fingerprint(
            value.get("last_attempted_fingerprint"), "last attempted fingerprint"
        ),
        "change_sequence": _integer(
            value.get("change_sequence"), "change_sequence", minimum=0, maximum=2**63 - 1
        ),
        "stable_observations": _integer(
            value.get("stable_observations"), "stable_observations", minimum=0, maximum=2**31 - 1
        ),
        "file_count": _integer(value.get("file_count"), "file_count", minimum=0, maximum=2**63 - 1),
        "total_bytes": _integer(
            value.get("total_bytes"), "total_bytes", minimum=0, maximum=2**63 - 1
        ),
        "clock_change_count": _integer(
            value.get("clock_change_count"), "clock_change_count", minimum=0, maximum=2**63 - 1
        ),
        "active_run_id": _optional_identifier(value.get("active_run_id"), "active run ID", _RUN_ID),
        "last_ingestion_run_id": _optional_identifier(
            value.get("last_ingestion_run_id"), "last ingestion run ID", _RUN_ID
        ),
        "last_scheduler_job_id": _optional_identifier(
            value.get("last_scheduler_job_id"), "last scheduler job ID", _JOB_ID
        ),
        "last_error_code": error_code,
        "updated_at": _optional_instant(value.get("updated_at"), "observer update time"),
        "network_used": value["network_used"],
        "automatic_deletion": False,
    }


__all__ = [
    "DEFAULT_QUIESCENCE_SECONDS",
    "DEFAULT_STABLE_OBSERVATIONS",
    "FOLDER_SOURCE_SCHEMA_VERSION",
    "FolderSourceError",
    "FolderSourceNotFound",
    "MAX_FOLDER_PATH_CHARS",
    "SOURCE_AVAILABILITY_STATES",
    "SOURCE_CLASSES",
    "SOURCE_ERROR_CODES",
    "SOURCE_LIFECYCLE_STATES",
    "SOURCE_PHASES",
    "folder_config_payload",
    "new_observer_record",
    "normalise_folder_config",
    "normalise_observer_record",
]
