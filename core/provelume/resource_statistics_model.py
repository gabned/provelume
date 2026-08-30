from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .scheduler_model import SchedulerError, instant_text

RESOURCE_STATISTICS_SCHEMA_VERSION = 1
MAX_RESOURCE_FILES = 1_000_000
MAX_RESOURCE_SNAPSHOTS = 100_000

RESOURCE_CATEGORIES = (
    "configuration",
    "canonical_originals",
    "canonical_records",
    "derived_assets",
    "operational_state",
    "managed_inbox",
    "other",
)
CAPACITY_STATES = ("ok", "warning", "critical")
THRESHOLD_CODES = (
    "minimum_free_bytes_warning",
    "minimum_free_bytes_critical",
    "maximum_instance_bytes_warning",
    "maximum_instance_bytes_critical",
)
THRESHOLD_FIELDS = (
    "minimum_free_bytes_warning",
    "minimum_free_bytes_critical",
    "maximum_instance_bytes_warning",
    "maximum_instance_bytes_critical",
)

_INSTANCE_ID = re.compile(r"inst_[0-9a-f]{32}\Z")
_JOB_ID = re.compile(r"job_([0-9a-f]{32})\Z")
_SNAPSHOT_ID = re.compile(r"resource_([0-9a-f]{32})\Z")


class ResourceStatisticsError(ValueError):
    pass


class ResourceStatisticsStateError(ResourceStatisticsError):
    pass


class ResourceStatisticsChangedError(ResourceStatisticsError):
    pass


class ResourceStatisticsIOError(ResourceStatisticsError):
    pass


class ResourceStatisticsLimitError(ResourceStatisticsError):
    pass


def _integer(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = 2**63 - 1,
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ResourceStatisticsStateError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return value


def _signed_integer(value: Any, label: str) -> int:
    return _integer(value, label, minimum=-(2**63 - 1), maximum=2**63 - 1)


def _instant(value: Any, label: str) -> str:
    try:
        return instant_text(value)
    except SchedulerError as exc:
        raise ResourceStatisticsStateError(f"{label} is invalid") from exc


def _instance_id(value: Any) -> str:
    if not isinstance(value, str) or _INSTANCE_ID.fullmatch(value) is None:
        raise ResourceStatisticsStateError("resource statistics Instance ID is invalid")
    return value


def _job_id(value: Any) -> str:
    if not isinstance(value, str) or _JOB_ID.fullmatch(value) is None:
        raise ResourceStatisticsStateError("resource statistics job ID is invalid")
    return value


def resource_snapshot_identifier(value: Any) -> bool:
    return isinstance(value, str) and _SNAPSHOT_ID.fullmatch(value) is not None


def empty_category_totals() -> dict[str, dict[str, int]]:
    return {
        category: {"file_count": 0, "byte_count": 0}
        for category in RESOURCE_CATEGORIES
    }


def normalise_threshold_limits(value: Any) -> dict[str, int | None]:
    if not isinstance(value, Mapping) or set(value) != set(THRESHOLD_FIELDS):
        raise ResourceStatisticsStateError(
            "resource threshold fields are incomplete or unsupported"
        )
    selected: dict[str, int | None] = {}
    for field in THRESHOLD_FIELDS:
        candidate = value.get(field)
        selected[field] = (
            None
            if candidate is None
            else _integer(candidate, field, minimum=0, maximum=2**63 - 1)
        )
    free_warning = selected["minimum_free_bytes_warning"]
    free_critical = selected["minimum_free_bytes_critical"]
    if (
        free_warning is not None
        and free_critical is not None
        and free_critical > free_warning
    ):
        raise ResourceStatisticsStateError(
            "critical minimum-free threshold cannot exceed warning"
        )
    bytes_warning = selected["maximum_instance_bytes_warning"]
    bytes_critical = selected["maximum_instance_bytes_critical"]
    if (
        bytes_warning is not None
        and bytes_critical is not None
        and bytes_critical < bytes_warning
    ):
        raise ResourceStatisticsStateError(
            "critical maximum-Instance threshold cannot precede warning"
        )
    return selected


def validate_threshold_settings(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "instance_id",
        "revision",
        "updated_at",
        "limits",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ResourceStatisticsStateError(
            "resource threshold settings are incomplete or unsupported"
        )
    if value.get("schema_version") != RESOURCE_STATISTICS_SCHEMA_VERSION:
        raise ResourceStatisticsStateError(
            "resource threshold schema version is unsupported"
        )
    return {
        "schema_version": RESOURCE_STATISTICS_SCHEMA_VERSION,
        "instance_id": _instance_id(value.get("instance_id")),
        "revision": _integer(value.get("revision"), "threshold revision", minimum=1),
        "updated_at": _instant(value.get("updated_at"), "threshold update time"),
        "limits": normalise_threshold_limits(value.get("limits")),
    }


def default_threshold_settings(instance_id: str) -> dict[str, Any]:
    return {
        "schema_version": RESOURCE_STATISTICS_SCHEMA_VERSION,
        "instance_id": _instance_id(instance_id),
        "revision": 0,
        "updated_at": None,
        "limits": {field: None for field in THRESHOLD_FIELDS},
    }


def normalise_category_totals(value: Any) -> dict[str, dict[str, int]]:
    if not isinstance(value, Mapping) or set(value) != set(RESOURCE_CATEGORIES):
        raise ResourceStatisticsStateError(
            "resource categories are incomplete or unsupported"
        )
    selected: dict[str, dict[str, int]] = {}
    for category in RESOURCE_CATEGORIES:
        totals = value.get(category)
        if not isinstance(totals, Mapping) or set(totals) != {
            "file_count",
            "byte_count",
        }:
            raise ResourceStatisticsStateError(
                "resource category totals are incomplete or unsupported"
            )
        selected[category] = {
            "file_count": _integer(
                totals.get("file_count"), f"{category} file count"
            ),
            "byte_count": _integer(
                totals.get("byte_count"), f"{category} byte count"
            ),
        }
    return selected


def _normalise_capacity(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {
        "total_bytes",
        "used_bytes",
        "free_bytes",
        "reserved_bytes",
    }:
        raise ResourceStatisticsStateError(
            "resource capacity fields are incomplete or unsupported"
        )
    selected = {
        key: _integer(value.get(key), f"capacity {key}")
        for key in ("total_bytes", "used_bytes", "free_bytes", "reserved_bytes")
    }
    if selected["total_bytes"] != (
        selected["used_bytes"]
        + selected["free_bytes"]
        + selected["reserved_bytes"]
    ):
        raise ResourceStatisticsStateError("resource capacity totals are inconsistent")
    return selected


def _normalise_threshold_evaluation(value: Any) -> dict[str, Any]:
    expected = {"settings_revision", "limits", "state", "codes"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ResourceStatisticsStateError(
            "resource threshold evaluation is incomplete or unsupported"
        )
    revision = _integer(
        value.get("settings_revision"),
        "threshold settings revision",
        minimum=0,
    )
    limits = normalise_threshold_limits(value.get("limits"))
    if revision == 0 and any(limit is not None for limit in limits.values()):
        raise ResourceStatisticsStateError(
            "default resource thresholds cannot contain configured limits"
        )
    state = value.get("state")
    codes = value.get("codes")
    if state not in CAPACITY_STATES:
        raise ResourceStatisticsStateError("resource capacity state is invalid")
    if (
        not isinstance(codes, list)
        or any(code not in THRESHOLD_CODES for code in codes)
        or codes != [code for code in THRESHOLD_CODES if code in set(codes)]
    ):
        raise ResourceStatisticsStateError("resource threshold codes are invalid")
    expected_state = (
        "critical"
        if any(code.endswith("_critical") for code in codes)
        else "warning"
        if codes
        else "ok"
    )
    if state != expected_state:
        raise ResourceStatisticsStateError(
            "resource threshold state and codes disagree"
        )
    return {
        "settings_revision": revision,
        "limits": limits,
        "state": str(state),
        "codes": list(codes),
    }


def _normalise_delta(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    expected = {
        "elapsed_seconds",
        "clock_reversed",
        "file_count",
        "byte_count",
        "free_bytes",
        "categories",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ResourceStatisticsStateError(
            "resource trend delta is incomplete or unsupported"
        )
    raw_categories = value.get("categories")
    if not isinstance(raw_categories, Mapping) or set(raw_categories) != set(
        RESOURCE_CATEGORIES
    ):
        raise ResourceStatisticsStateError(
            "resource trend category deltas are incomplete or unsupported"
        )
    categories: dict[str, dict[str, int]] = {}
    for category in RESOURCE_CATEGORIES:
        totals = raw_categories.get(category)
        if not isinstance(totals, Mapping) or set(totals) != {
            "file_count",
            "byte_count",
        }:
            raise ResourceStatisticsStateError(
                "resource trend category delta fields are invalid"
            )
        categories[category] = {
            "file_count": _signed_integer(
                totals.get("file_count"), f"{category} file delta"
            ),
            "byte_count": _signed_integer(
                totals.get("byte_count"), f"{category} byte delta"
            ),
        }
    if type(value.get("clock_reversed")) is not bool:
        raise ResourceStatisticsStateError("resource trend clock state is invalid")
    return {
        "elapsed_seconds": _integer(
            value.get("elapsed_seconds"), "resource trend elapsed seconds"
        ),
        "clock_reversed": bool(value["clock_reversed"]),
        "file_count": _signed_integer(value.get("file_count"), "file count delta"),
        "byte_count": _signed_integer(value.get("byte_count"), "byte count delta"),
        "free_bytes": _signed_integer(value.get("free_bytes"), "free byte delta"),
        "categories": categories,
    }


def validate_resource_snapshot(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "id",
        "instance_id",
        "job_id",
        "sequence",
        "observed_at",
        "previous_snapshot_id",
        "file_count",
        "byte_count",
        "categories",
        "capacity",
        "thresholds",
        "delta",
        "network_used",
        "canonical_mutation",
        "automatic_deletion",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ResourceStatisticsStateError(
            "resource snapshot fields are incomplete or unsupported"
        )
    snapshot_id = value.get("id")
    job_id = _job_id(value.get("job_id"))
    if (
        value.get("schema_version") != RESOURCE_STATISTICS_SCHEMA_VERSION
        or not resource_snapshot_identifier(snapshot_id)
        or snapshot_id != f"resource_{job_id.removeprefix('job_')}"
    ):
        raise ResourceStatisticsStateError("resource snapshot identity is invalid")
    sequence = _integer(value.get("sequence"), "resource snapshot sequence", minimum=1)
    previous_id = value.get("previous_snapshot_id")
    if previous_id is not None and not resource_snapshot_identifier(previous_id):
        raise ResourceStatisticsStateError(
            "resource previous snapshot reference is invalid"
        )
    categories = normalise_category_totals(value.get("categories"))
    file_count = _integer(
        value.get("file_count"),
        "resource file count",
        maximum=MAX_RESOURCE_FILES,
    )
    byte_count = _integer(value.get("byte_count"), "resource byte count")
    if file_count != sum(item["file_count"] for item in categories.values()):
        raise ResourceStatisticsStateError(
            "resource file count does not match category totals"
        )
    if byte_count != sum(item["byte_count"] for item in categories.values()):
        raise ResourceStatisticsStateError(
            "resource byte count does not match category totals"
        )
    delta = _normalise_delta(value.get("delta"))
    if (sequence == 1) != (previous_id is None and delta is None):
        raise ResourceStatisticsStateError(
            "resource snapshot sequence and previous reference disagree"
        )
    if sequence > 1 and (previous_id is None or delta is None):
        raise ResourceStatisticsStateError(
            "resource trend evidence is missing from a later snapshot"
        )
    if any(type(value.get(field)) is not bool or value.get(field) for field in (
        "network_used",
        "canonical_mutation",
        "automatic_deletion",
    )):
        raise ResourceStatisticsStateError(
            "resource snapshot safety flags are invalid"
        )
    return {
        "schema_version": RESOURCE_STATISTICS_SCHEMA_VERSION,
        "id": str(snapshot_id),
        "instance_id": _instance_id(value.get("instance_id")),
        "job_id": job_id,
        "sequence": sequence,
        "observed_at": _instant(value.get("observed_at"), "resource observation time"),
        "previous_snapshot_id": previous_id,
        "file_count": file_count,
        "byte_count": byte_count,
        "categories": categories,
        "capacity": _normalise_capacity(value.get("capacity")),
        "thresholds": _normalise_threshold_evaluation(value.get("thresholds")),
        "delta": delta,
        "network_used": False,
        "canonical_mutation": False,
        "automatic_deletion": False,
    }


__all__ = [
    "CAPACITY_STATES",
    "MAX_RESOURCE_FILES",
    "MAX_RESOURCE_SNAPSHOTS",
    "RESOURCE_CATEGORIES",
    "RESOURCE_STATISTICS_SCHEMA_VERSION",
    "THRESHOLD_CODES",
    "THRESHOLD_FIELDS",
    "ResourceStatisticsChangedError",
    "ResourceStatisticsError",
    "ResourceStatisticsIOError",
    "ResourceStatisticsLimitError",
    "ResourceStatisticsStateError",
    "default_threshold_settings",
    "empty_category_totals",
    "normalise_category_totals",
    "normalise_threshold_limits",
    "resource_snapshot_identifier",
    "validate_resource_snapshot",
    "validate_threshold_settings",
]
