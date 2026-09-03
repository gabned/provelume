from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from .paths import safe_instance_path
from .storage import InstanceStore, utc_now

REPRESENTATION_SCHEMA_VERSION = 1
REPRESENTATION_SCHEMA_TYPE = "provelume.representation-bundle"
REPRESENTATION_READ_MODEL_VERSION = 1
SUPPORT_REGISTRY_VERSION = 1


class SupportOperation(StrEnum):
    PRESERVE = "preserve"
    INSPECT = "inspect"
    EXTRACT = "extract"
    PREVIEW = "preview"
    LOCAL_ENRICH = "local_enrich"
    AI_ENRICH = "ai_enrich"


class DeclaredSupportState(StrEnum):
    SUPPORTED = "supported"
    OPTIONAL = "optional"
    UNSUPPORTED = "unsupported"


class EffectiveSupportState(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SupportReason(StrEnum):
    COMPONENT_MISSING = "component_missing"
    DISABLED_BY_CONFIGURATION = "disabled_by_configuration"
    INVALID_CONTRACT = "invalid_contract"
    NOT_APPLICABLE = "not_applicable"
    NOT_DECLARED = "not_declared"
    NOT_IMPLEMENTED = "not_implemented"
    OUTPUT_DEPENDENT = "output_dependent"
    PROFILE_LIMITED = "profile_limited"
    UNSUPPORTED_PLATFORM = "unsupported_platform"


class RepresentationLifecycle(StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    REMOVED = "removed"


class AnchorKind(StrEnum):
    PAGE = "page"
    TIME = "time"
    REGION = "region"
    SLIDE = "slide"
    SHEET = "sheet"
    CELL = "cell"
    MEMBER = "member"
    SYMBOL = "symbol"


SUPPORT_OPERATIONS = tuple(item.value for item in SupportOperation)
DECLARED_SUPPORT_STATES = tuple(item.value for item in DeclaredSupportState)
EFFECTIVE_SUPPORT_STATES = tuple(item.value for item in EffectiveSupportState)
SUPPORT_REASON_CODES = tuple(item.value for item in SupportReason)
REPRESENTATION_LIFECYCLE_STATES = tuple(item.value for item in RepresentationLifecycle)
ANCHOR_KINDS = tuple(item.value for item in AnchorKind)
RESERVED_ANCHOR_KINDS = ("slide", "sheet", "cell", "member", "symbol")
CORRECTION_KINDS = ("replace", "suppress", "restore", "relabel")

MAX_REPRESENTATION_OUTPUTS = 1_000
MAX_REPRESENTATION_ANCHORS = 100_000
MAX_REPRESENTATION_CORRECTIONS = 10_000
MAX_REPRESENTATION_WARNINGS = 1_000
MAX_REPRESENTATION_PATH_CHARS = 240
MAX_REPRESENTATION_SEGMENT_CHARS = 120
MAX_REPRESENTATION_FILE_BYTES = 16 * 1024 * 1024 * 1024
MAX_REPRESENTATION_TOTAL_BYTES = 512 * 1024 * 1024 * 1024
MAX_REPRESENTATION_EXPANSION_RATIO = 1_000

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,199}\Z")
_REPRESENTATION_ID = re.compile(r"repr_[0-9a-f]{64}\Z")
_OUTPUT_ID = re.compile(r"rout_[0-9a-f]{64}\Z")
_ANCHOR_ID = re.compile(r"ranc_[0-9a-f]{64}\Z")
_CORRECTION_ID = re.compile(r"rcor_[0-9a-f]{64}\Z")
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}\Z")
_WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
_WINDOWS_RESERVED = {
    "aux",
    "clock$",
    "con",
    "conin$",
    "conout$",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class RepresentationContractError(ValueError):
    """Closed, content-free failure for a representation contract violation."""

    def __init__(self, code: str, message: str):
        if code not in {
            "representation_invalid",
            "representation_identity_mismatch",
            "representation_path_unsafe",
            "representation_collision",
            "representation_limit_exceeded",
            "representation_original_mismatch",
            "representation_output_mismatch",
            "representation_not_found",
        }:
            raise ValueError("representation error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint(value: Any) -> str:
    try:
        return _sha256(canonical_json_bytes(value))
    except (TypeError, ValueError) as exc:
        raise RepresentationContractError(
            "representation_invalid", "representation value is not canonical JSON"
        ) from exc


def recipe_fingerprint(recipe_id: str, recipe_version: str, settings: Mapping[str, Any]) -> str:
    return _fingerprint({"id": recipe_id, "version": recipe_version, "settings": dict(settings)})


def output_fingerprint(outputs: Sequence[Mapping[str, Any]]) -> str:
    return _fingerprint(
        [
            {key: output[key] for key in ("id", "media_type", "sha256", "size_bytes")}
            for output in outputs
        ]
    )


def representation_id(
    *,
    version_id: str,
    original_sha256: str,
    recipe_sha256: str,
    output_sha256: str,
) -> str:
    return "repr_" + _fingerprint(
        {
            "version_id": version_id,
            "original_sha256": original_sha256,
            "recipe_fingerprint": recipe_sha256,
            "output_fingerprint": output_sha256,
        }
    )


def _expect_object(value: Any, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RepresentationContractError(
            "representation_invalid", f"{name} fields are incomplete or unsupported"
        )
    return dict(value)


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise RepresentationContractError("representation_invalid", f"{name} is invalid")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RepresentationContractError("representation_invalid", f"{name} is invalid")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RepresentationContractError("representation_invalid", f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RepresentationContractError("representation_invalid", f"{name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RepresentationContractError("representation_invalid", f"{name} is invalid")
    return parsed


def _positive_integer(value: Any, name: str, ceiling: int) -> int:
    if type(value) is not int or value < 1 or value > ceiling:
        raise RepresentationContractError(
            "representation_limit_exceeded", f"{name} is outside its closed limit"
        )
    return value


def _nonnegative_integer(value: Any, name: str, ceiling: int) -> int:
    if type(value) is not int or value < 0 or value > ceiling:
        raise RepresentationContractError(
            "representation_limit_exceeded", f"{name} is outside its closed limit"
        )
    return value


def _portable_relative_path(
    value: Any,
    *,
    max_path_chars: int = MAX_REPRESENTATION_PATH_CHARS,
    max_segment_chars: int = MAX_REPRESENTATION_SEGMENT_CHARS,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise RepresentationContractError(
            "representation_path_unsafe", "representation output path is unsafe"
        )
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
        or len(value) > max_path_chars
    ):
        raise RepresentationContractError(
            "representation_path_unsafe", "representation output path is unsafe"
        )
    for segment in pure.parts:
        if (
            len(segment) > max_segment_chars
            or segment.endswith((" ", "."))
            or any(ord(character) < 32 for character in segment)
            or any(character in _WINDOWS_FORBIDDEN for character in segment)
            or segment.split(".", 1)[0].casefold() in _WINDOWS_RESERVED
        ):
            raise RepresentationContractError(
                "representation_path_unsafe", "representation output path is not portable"
            )
    return value


def _validate_path_set(paths: Sequence[str]) -> None:
    if list(paths) != sorted(paths) or len(paths) != len(set(paths)):
        raise RepresentationContractError(
            "representation_collision", "representation output paths must be unique and sorted"
        )
    folded = [path.casefold() for path in paths]
    if len(folded) != len(set(folded)):
        raise RepresentationContractError(
            "representation_collision", "representation output paths collide by case"
        )
    nodes: dict[str, tuple[str, str]] = {}
    for path in paths:
        parts = PurePosixPath(path).parts
        for index in range(1, len(parts) + 1):
            node = "/".join(parts[:index])
            kind = "file" if index == len(parts) else "directory"
            previous = nodes.get(node.casefold())
            if previous is not None and previous != (node, kind):
                raise RepresentationContractError(
                    "representation_collision",
                    "representation paths collide by file or directory identity",
                )
            nodes[node.casefold()] = (node, kind)


def _validate_limits(value: Any) -> dict[str, int]:
    limits = _expect_object(
        value,
        "limits",
        {
            "max_outputs",
            "max_anchors",
            "max_corrections",
            "max_warnings",
            "max_path_chars",
            "max_segment_chars",
            "max_file_bytes",
            "max_total_bytes",
            "max_expansion_ratio",
        },
    )
    ceilings = {
        "max_outputs": MAX_REPRESENTATION_OUTPUTS,
        "max_anchors": MAX_REPRESENTATION_ANCHORS,
        "max_corrections": MAX_REPRESENTATION_CORRECTIONS,
        "max_warnings": MAX_REPRESENTATION_WARNINGS,
        "max_path_chars": MAX_REPRESENTATION_PATH_CHARS,
        "max_segment_chars": MAX_REPRESENTATION_SEGMENT_CHARS,
        "max_file_bytes": MAX_REPRESENTATION_FILE_BYTES,
        "max_total_bytes": MAX_REPRESENTATION_TOTAL_BYTES,
        "max_expansion_ratio": MAX_REPRESENTATION_EXPANSION_RATIO,
    }
    result = {
        name: _positive_integer(limits[name], name, ceiling) for name, ceiling in ceilings.items()
    }
    return result


def default_representation_limits() -> dict[str, int]:
    return {
        "max_outputs": MAX_REPRESENTATION_OUTPUTS,
        "max_anchors": MAX_REPRESENTATION_ANCHORS,
        "max_corrections": MAX_REPRESENTATION_CORRECTIONS,
        "max_warnings": MAX_REPRESENTATION_WARNINGS,
        "max_path_chars": MAX_REPRESENTATION_PATH_CHARS,
        "max_segment_chars": MAX_REPRESENTATION_SEGMENT_CHARS,
        "max_file_bytes": MAX_REPRESENTATION_FILE_BYTES,
        "max_total_bytes": MAX_REPRESENTATION_TOTAL_BYTES,
        "max_expansion_ratio": MAX_REPRESENTATION_EXPANSION_RATIO,
    }


def validate_representation_bundle(value: Any) -> dict[str, Any]:
    bundle = _expect_object(
        value,
        "representation bundle",
        {
            "schema_version",
            "schema_type",
            "representation_id",
            "version",
            "recipe",
            "output_fingerprint",
            "outputs",
            "implementation",
            "warnings",
            "lifecycle",
            "availability",
            "provenance",
            "corrections",
            "anchors",
            "limits",
            "invariants",
        },
    )
    if (
        bundle["schema_version"] != REPRESENTATION_SCHEMA_VERSION
        or bundle["schema_type"] != REPRESENTATION_SCHEMA_TYPE
        or not isinstance(bundle["representation_id"], str)
        or _REPRESENTATION_ID.fullmatch(bundle["representation_id"]) is None
    ):
        raise RepresentationContractError(
            "representation_invalid", "representation schema identity is invalid"
        )

    version = _expect_object(
        bundle["version"],
        "version",
        {"id", "original_id", "original_sha256", "original_size_bytes"},
    )
    _identifier(version["id"], "version id")
    _identifier(version["original_id"], "original id")
    _digest(version["original_sha256"], "original sha256")
    _nonnegative_integer(
        version["original_size_bytes"], "original size", MAX_REPRESENTATION_FILE_BYTES
    )

    recipe = _expect_object(
        bundle["recipe"], "recipe", {"id", "version", "settings", "fingerprint"}
    )
    _identifier(recipe["id"], "recipe id")
    _identifier(recipe["version"], "recipe version")
    if not isinstance(recipe["settings"], Mapping):
        raise RepresentationContractError(
            "representation_invalid", "recipe settings must be an object"
        )
    expected_recipe = recipe_fingerprint(recipe["id"], recipe["version"], recipe["settings"])
    if recipe["fingerprint"] != expected_recipe:
        raise RepresentationContractError(
            "representation_identity_mismatch", "recipe fingerprint does not match"
        )

    limits = _validate_limits(bundle["limits"])
    outputs_value = bundle["outputs"]
    if (
        not isinstance(outputs_value, list)
        or not outputs_value
        or len(outputs_value) > limits["max_outputs"]
    ):
        raise RepresentationContractError(
            "representation_limit_exceeded", "representation output count is invalid"
        )
    outputs: list[dict[str, Any]] = []
    total_size = 0
    for value_output in outputs_value:
        output = _expect_object(
            value_output,
            "output",
            {"id", "media_type", "storage_ref", "sha256", "size_bytes"},
        )
        if not isinstance(output["id"], str) or _OUTPUT_ID.fullmatch(output["id"]) is None:
            raise RepresentationContractError(
                "representation_invalid", "representation output id is invalid"
            )
        if (
            not isinstance(output["media_type"], str)
            or _MEDIA_TYPE.fullmatch(output["media_type"]) is None
        ):
            raise RepresentationContractError(
                "representation_invalid", "output media type is invalid"
            )
        _portable_relative_path(
            output["storage_ref"],
            max_path_chars=limits["max_path_chars"],
            max_segment_chars=limits["max_segment_chars"],
        )
        _digest(output["sha256"], "output sha256")
        size = _nonnegative_integer(output["size_bytes"], "output size", limits["max_file_bytes"])
        total_size += size
        outputs.append(output)
    if total_size > limits["max_total_bytes"]:
        raise RepresentationContractError(
            "representation_limit_exceeded", "representation total size exceeds its limit"
        )
    if total_size > max(1, int(version["original_size_bytes"])) * limits["max_expansion_ratio"]:
        raise RepresentationContractError(
            "representation_limit_exceeded", "representation expansion exceeds its limit"
        )
    paths = [str(output["storage_ref"]) for output in outputs]
    _validate_path_set(paths)
    if len({output["id"] for output in outputs}) != len(outputs):
        raise RepresentationContractError(
            "representation_collision", "representation output ids collide"
        )
    expected_output = output_fingerprint(outputs)
    if bundle["output_fingerprint"] != expected_output:
        raise RepresentationContractError(
            "representation_identity_mismatch", "output fingerprint does not match"
        )
    expected_id = representation_id(
        version_id=version["id"],
        original_sha256=version["original_sha256"],
        recipe_sha256=expected_recipe,
        output_sha256=expected_output,
    )
    if bundle["representation_id"] != expected_id:
        raise RepresentationContractError(
            "representation_identity_mismatch", "representation id does not match"
        )

    implementation = _expect_object(
        bundle["implementation"],
        "implementation",
        {"component", "component_version", "adapter", "adapter_version", "settings"},
    )
    for key in ("component", "component_version", "adapter", "adapter_version"):
        _identifier(implementation[key], f"implementation {key}")
    if not isinstance(implementation["settings"], Mapping):
        raise RepresentationContractError(
            "representation_invalid", "implementation settings must be an object"
        )

    warnings = bundle["warnings"]
    if (
        not isinstance(warnings, list)
        or len(warnings) > limits["max_warnings"]
        or warnings != sorted(set(warnings))
        or any(
            not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None for item in warnings
        )
    ):
        raise RepresentationContractError(
            "representation_invalid", "warning codes must be closed, unique and sorted"
        )

    lifecycle = _expect_object(
        bundle["lifecycle"], "lifecycle", {"state", "created_at", "removed_at"}
    )
    if lifecycle["state"] not in REPRESENTATION_LIFECYCLE_STATES:
        raise RepresentationContractError(
            "representation_invalid", "representation lifecycle state is invalid"
        )
    created_at = _timestamp(lifecycle["created_at"], "representation creation time")
    if lifecycle["state"] == "removed":
        removed_at = _timestamp(lifecycle["removed_at"], "representation removal time")
        if removed_at < created_at:
            raise RepresentationContractError(
                "representation_invalid", "representation removal precedes creation"
            )
    elif lifecycle["removed_at"] is not None:
        raise RepresentationContractError(
            "representation_invalid", "active representation cannot have a removal time"
        )

    availability = _expect_object(
        bundle["availability"], "availability", {"state", "reason", "missing_component"}
    )
    if availability["state"] not in EFFECTIVE_SUPPORT_STATES:
        raise RepresentationContractError(
            "representation_invalid", "representation availability state is invalid"
        )
    if availability["state"] == "available":
        if availability["reason"] is not None or availability["missing_component"] is not None:
            raise RepresentationContractError(
                "representation_invalid", "available representation cannot report a blocker"
            )
    else:
        if availability["reason"] not in SUPPORT_REASON_CODES:
            raise RepresentationContractError(
                "representation_invalid", "representation availability reason is invalid"
            )
        if availability["missing_component"] is not None:
            _identifier(availability["missing_component"], "missing component")

    provenance = _expect_object(
        bundle["provenance"],
        "provenance",
        {"derived_from_version_id", "previous_representation_ids", "parent_representation_ids"},
    )
    if provenance["derived_from_version_id"] != version["id"]:
        raise RepresentationContractError(
            "representation_identity_mismatch", "provenance version does not match"
        )
    for key in ("previous_representation_ids", "parent_representation_ids"):
        values = provenance[key]
        if (
            not isinstance(values, list)
            or values != sorted(set(values))
            or any(
                not isinstance(item, str) or _REPRESENTATION_ID.fullmatch(item) is None
                for item in values
            )
            or bundle["representation_id"] in values
        ):
            raise RepresentationContractError("representation_invalid", f"{key} is invalid")

    anchors_value = bundle["anchors"]
    if not isinstance(anchors_value, list) or len(anchors_value) > limits["max_anchors"]:
        raise RepresentationContractError(
            "representation_limit_exceeded", "representation anchor count is invalid"
        )
    anchor_ids: set[str] = set()
    for value_anchor in anchors_value:
        anchor = _expect_object(
            value_anchor,
            "anchor",
            {"id", "kind", "version_id", "representation_id", "target"},
        )
        if (
            not isinstance(anchor["id"], str)
            or _ANCHOR_ID.fullmatch(anchor["id"]) is None
            or anchor["id"] in anchor_ids
            or anchor["kind"] not in ANCHOR_KINDS
            or anchor["version_id"] != version["id"]
            or anchor["representation_id"] != bundle["representation_id"]
            or not isinstance(anchor["target"], Mapping)
            or not anchor["target"]
        ):
            raise RepresentationContractError(
                "representation_invalid", "representation anchor is invalid"
            )
        if anchor["kind"] in RESERVED_ANCHOR_KINDS and dict(anchor["target"]) != {"reserved": True}:
            raise RepresentationContractError(
                "representation_invalid", "reserved anchor must remain explicitly reserved"
            )
        if anchor["kind"] == "page" and (
            set(anchor["target"]) != {"page"}
            or type(anchor["target"].get("page")) is not int
            or anchor["target"]["page"] < 1
        ):
            raise RepresentationContractError(
                "representation_invalid", "page anchor target is invalid"
            )
        if anchor["kind"] == "time" and (
            set(anchor["target"]) != {"start_ms", "end_ms"}
            or type(anchor["target"].get("start_ms")) is not int
            or type(anchor["target"].get("end_ms")) is not int
            or anchor["target"]["start_ms"] < 0
            or anchor["target"]["end_ms"] < anchor["target"]["start_ms"]
        ):
            raise RepresentationContractError(
                "representation_invalid", "time anchor target is invalid"
            )
        if anchor["kind"] == "region" and (
            set(anchor["target"]) != {"page", "x", "y", "width", "height"}
            or any(
                isinstance(anchor["target"].get(key), bool)
                or not isinstance(anchor["target"].get(key), (int, float))
                for key in ("x", "y", "width", "height")
            )
            or type(anchor["target"].get("page")) is not int
            or anchor["target"]["page"] < 1
            or anchor["target"]["x"] < 0
            or anchor["target"]["y"] < 0
            or anchor["target"]["width"] <= 0
            or anchor["target"]["height"] <= 0
        ):
            raise RepresentationContractError(
                "representation_invalid", "region anchor target is invalid"
            )
        anchor_ids.add(anchor["id"])

    corrections_value = bundle["corrections"]
    if (
        not isinstance(corrections_value, list)
        or len(corrections_value) > limits["max_corrections"]
    ):
        raise RepresentationContractError(
            "representation_limit_exceeded", "representation correction count is invalid"
        )
    correction_ids: set[str] = set()
    for value_correction in corrections_value:
        correction = _expect_object(
            value_correction,
            "correction",
            {"id", "kind", "anchor_id", "before_sha256", "after_sha256", "reversible"},
        )
        if (
            not isinstance(correction["id"], str)
            or _CORRECTION_ID.fullmatch(correction["id"]) is None
            or correction["id"] in correction_ids
            or correction["kind"] not in CORRECTION_KINDS
            or correction["anchor_id"] not in anchor_ids
            or correction["reversible"] is not True
        ):
            raise RepresentationContractError(
                "representation_invalid", "representation correction is invalid"
            )
        _digest(correction["before_sha256"], "correction before sha256")
        _digest(correction["after_sha256"], "correction after sha256")
        correction_ids.add(correction["id"])

    invariants = _expect_object(
        bundle["invariants"],
        "invariants",
        {
            "derived",
            "attributable",
            "removable",
            "rebuildable",
            "original_immutable",
            "canonical_records_immutable",
            "provider_data_immutable",
            "network_used",
            "ai_used",
        },
    )
    expected_invariants = {
        "derived": True,
        "attributable": True,
        "removable": True,
        "rebuildable": True,
        "original_immutable": True,
        "canonical_records_immutable": True,
        "provider_data_immutable": True,
        "network_used": False,
        "ai_used": False,
    }
    if invariants != expected_invariants:
        raise RepresentationContractError(
            "representation_invalid", "representation invariants are invalid"
        )
    return bundle


def build_representation_bundle(
    *,
    version: Mapping[str, Any],
    recipe_id: str,
    recipe_version: str,
    recipe_settings: Mapping[str, Any],
    outputs: Sequence[Mapping[str, Any]],
    implementation: Mapping[str, Any],
    warnings: Sequence[str] = (),
    anchor_targets: Sequence[Mapping[str, Any]] = (),
    corrections: Sequence[Mapping[str, Any]] = (),
    previous_representation_ids: Sequence[str] = (),
    parent_representation_ids: Sequence[str] = (),
    availability_state: str = "available",
    availability_reason: str | None = None,
    missing_component: str | None = None,
    created_at: str,
) -> dict[str, Any]:
    recipe_sha256 = recipe_fingerprint(recipe_id, recipe_version, recipe_settings)
    selected_outputs = sorted(
        (dict(output) for output in outputs), key=lambda item: item["storage_ref"]
    )
    output_sha256 = output_fingerprint(selected_outputs)
    selected_id = representation_id(
        version_id=str(version["id"]),
        original_sha256=str(version["original_sha256"]),
        recipe_sha256=recipe_sha256,
        output_sha256=output_sha256,
    )
    anchors: list[dict[str, Any]] = []
    for ordinal, target_value in enumerate(anchor_targets):
        target = dict(target_value)
        kind = str(target.pop("kind"))
        identity = _fingerprint(
            {
                "representation_id": selected_id,
                "ordinal": ordinal,
                "kind": kind,
                "target": target,
            }
        )
        anchors.append(
            {
                "id": f"ranc_{identity}",
                "kind": kind,
                "version_id": str(version["id"]),
                "representation_id": selected_id,
                "target": target,
            }
        )
    selected_corrections: list[dict[str, Any]] = []
    for ordinal, correction_value in enumerate(corrections):
        correction = dict(correction_value)
        correction["id"] = "rcor_" + _fingerprint(
            {"representation_id": selected_id, "ordinal": ordinal, **correction}
        )
        selected_corrections.append(correction)
    bundle = {
        "schema_version": REPRESENTATION_SCHEMA_VERSION,
        "schema_type": REPRESENTATION_SCHEMA_TYPE,
        "representation_id": selected_id,
        "version": dict(version),
        "recipe": {
            "id": recipe_id,
            "version": recipe_version,
            "settings": dict(recipe_settings),
            "fingerprint": recipe_sha256,
        },
        "output_fingerprint": output_sha256,
        "outputs": selected_outputs,
        "implementation": dict(implementation),
        "warnings": sorted(set(warnings)),
        "lifecycle": {"state": "active", "created_at": created_at, "removed_at": None},
        "availability": {
            "state": availability_state,
            "reason": availability_reason,
            "missing_component": missing_component,
        },
        "provenance": {
            "derived_from_version_id": str(version["id"]),
            "previous_representation_ids": sorted(set(previous_representation_ids)),
            "parent_representation_ids": sorted(set(parent_representation_ids)),
        },
        "corrections": selected_corrections,
        "anchors": anchors,
        "limits": default_representation_limits(),
        "invariants": {
            "derived": True,
            "attributable": True,
            "removable": True,
            "rebuildable": True,
            "original_immutable": True,
            "canonical_records_immutable": True,
            "provider_data_immutable": True,
            "network_used": False,
            "ai_used": False,
        },
    }
    return validate_representation_bundle(bundle)


def _resource_json(name: str) -> dict[str, Any]:
    value = json.loads(files("provelume").joinpath(name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RepresentationContractError("representation_invalid", f"{name} is invalid")
    return value


def _validate_removal_receipt(value: Any) -> dict[str, Any]:
    receipt = _expect_object(
        value,
        "representation removal receipt",
        {
            "schema_version",
            "kind",
            "representation_id",
            "bundle_fingerprint",
            "bundle",
            "removed_outputs",
            "original_mutated",
            "canonical_records_mutated",
            "provider_data_mutated",
        },
    )
    selected_id = receipt["representation_id"]
    if (
        receipt["schema_version"] != 1
        or receipt["kind"] != "representation-removal-receipt"
        or not isinstance(selected_id, str)
        or _REPRESENTATION_ID.fullmatch(selected_id) is None
        or receipt["original_mutated"] is not False
        or receipt["canonical_records_mutated"] is not False
        or receipt["provider_data_mutated"] is not False
    ):
        raise RepresentationContractError(
            "representation_invalid", "representation removal receipt identity is invalid"
        )
    _digest(receipt["bundle_fingerprint"], "removed bundle fingerprint")
    removed = validate_representation_bundle(receipt["bundle"])
    if removed["representation_id"] != selected_id or removed["lifecycle"]["state"] != "removed":
        raise RepresentationContractError(
            "representation_identity_mismatch", "removed representation identity does not match"
        )
    active = {
        **removed,
        "lifecycle": {**removed["lifecycle"], "state": "active", "removed_at": None},
    }
    validate_representation_bundle(active)
    if _fingerprint(active) != receipt["bundle_fingerprint"]:
        raise RepresentationContractError(
            "representation_identity_mismatch", "removed bundle fingerprint does not match"
        )
    expected_outputs = [
        {key: output[key] for key in ("id", "storage_ref", "sha256", "size_bytes")}
        for output in removed["outputs"]
    ]
    if receipt["removed_outputs"] != expected_outputs:
        raise RepresentationContractError(
            "representation_identity_mismatch", "removed output evidence does not match"
        )
    return receipt


class SupportRegistry:
    """Resolve declared and effective support without network access or mutation."""

    def __init__(self, store: InstanceStore):
        self.store = store

    def _ocr_state(self) -> tuple[str, str | None, str | None]:
        from .ocr_contract import ocr_capability_report
        from .ocr_jobs import OcrJobManager

        try:
            manager = OcrJobManager(self.store)
            settings = manager.configured_settings()
            if settings.mode == "disabled":
                capability = ocr_capability_report(settings)
            else:
                with tempfile.TemporaryDirectory(prefix="provelume-ocr-capability-") as directory:
                    temporary_root = Path(directory)
                    if os.name == "posix":
                        os.chmod(temporary_root, 0o700)
                    renderer = manager.renderer_factory(settings, temporary_root)
                    renderer_capability = renderer.capability()
                    adapter = manager.adapter_factory(settings, renderer_capability, temporary_root)
                    capability = ocr_capability_report(settings, adapter, renderer)
        except (OSError, ValueError):
            return "unavailable", "component_missing", "local-ocr-runtime"
        state = str(capability.get("state", "adapter-unavailable"))
        if state == "ready":
            return "available", None, None
        if state == "disabled":
            return "unavailable", "disabled_by_configuration", None
        missing = {
            "adapter-unavailable": "local-ocr-adapter",
            "engine-unavailable": "tesseract-cli",
            "renderer-unavailable": "pypdfium2",
            "language-pack-missing": "tesseract-language-pack",
            "version-incompatible": "local-ocr-runtime",
        }.get(state, "local-ocr-runtime")
        reason = "unsupported_platform" if state == "version-incompatible" else "component_missing"
        return "unavailable", reason, missing

    @staticmethod
    def _photo_state() -> tuple[str, str | None, str | None]:
        from .photo_profiles import PillowPhotoDecoder

        capability = PillowPhotoDecoder().capability()
        if capability.get("state") == "ready":
            return "available", None, None
        reason = (
            "unsupported_platform"
            if capability.get("state") == "incompatible"
            else "component_missing"
        )
        return "unavailable", reason, "codec.pillow"

    def read(self, *, profile_id: str | None = None) -> dict[str, Any]:
        source = _resource_json("representation-support-registry.json")
        if (
            set(source)
            != {
                "schema_version",
                "registry_id",
                "operations",
                "reason_codes",
                "profiles",
            }
            or source.get("schema_version") != SUPPORT_REGISTRY_VERSION
            or source.get("registry_id") != "provelume.representation-support.v1"
            or source.get("operations") != list(SUPPORT_OPERATIONS)
            or source.get("reason_codes") != list(SUPPORT_REASON_CODES)
            or not isinstance(source.get("profiles"), list)
        ):
            raise RepresentationContractError(
                "representation_invalid", "support registry identity is invalid"
            )
        ocr_state: tuple[str, str | None, str | None] | None = None
        photo_state: tuple[str, str | None, str | None] | None = None
        records: list[dict[str, Any]] = []
        profile_ids: set[str] = set()
        for profile in source["profiles"]:
            if (
                not isinstance(profile, Mapping)
                or set(profile) != {"id", "version", "label", "operations"}
                or not isinstance(profile.get("operations"), Mapping)
            ):
                raise RepresentationContractError(
                    "representation_invalid", "support registry profile is invalid"
                )
            selected_profile = _identifier(profile.get("id"), "support profile id")
            _identifier(profile.get("version"), "support profile version")
            if (
                selected_profile in profile_ids
                or not isinstance(profile.get("label"), str)
                or not profile["label"]
                or set(profile["operations"]) != set(SUPPORT_OPERATIONS)
            ):
                raise RepresentationContractError(
                    "representation_invalid", "support registry profile identity is invalid"
                )
            profile_ids.add(selected_profile)
            include_profile = profile_id is None or selected_profile == profile_id
            for operation in SUPPORT_OPERATIONS:
                specification = profile["operations"].get(operation)
                if (
                    not isinstance(specification, Mapping)
                    or not {
                        "declared",
                        "effective",
                        "implementation",
                        "limits",
                        "reason",
                        "missing_component",
                    }.issubset(specification)
                    or set(specification)
                    - {
                        "declared",
                        "effective",
                        "implementation",
                        "limits",
                        "reason",
                        "missing_component",
                        "component_check",
                    }
                ):
                    raise RepresentationContractError(
                        "representation_invalid", "support registry operation is missing"
                    )
                declared = specification.get("declared")
                effective = specification.get("effective")
                reason = specification.get("reason")
                missing_component = specification.get("missing_component")
                implementation = specification.get("implementation")
                limits = specification.get("limits")
                if (
                    declared not in DECLARED_SUPPORT_STATES
                    or effective not in EFFECTIVE_SUPPORT_STATES
                    or not isinstance(limits, Mapping)
                ):
                    raise RepresentationContractError(
                        "representation_invalid", "support registry state is invalid"
                    )
                if implementation is not None:
                    implementation = _expect_object(
                        implementation,
                        "support implementation",
                        {"component", "adapter", "version"},
                    )
                    for key in ("component", "adapter", "version"):
                        _identifier(implementation[key], f"support implementation {key}")
                if missing_component is not None:
                    _identifier(missing_component, "support missing component")
                component_check = specification.get("component_check")
                if component_check not in {None, "ocr", "photo"}:
                    raise RepresentationContractError(
                        "representation_invalid", "support component check is invalid"
                    )
                if component_check == "ocr":
                    if ocr_state is None:
                        ocr_state = self._ocr_state()
                    effective, reason, missing_component = ocr_state
                if component_check == "photo":
                    if photo_state is None:
                        photo_state = self._photo_state()
                    effective, reason, missing_component = photo_state
                if operation == "ai_enrich":
                    if declared != "unsupported" or implementation is not None:
                        raise RepresentationContractError(
                            "representation_invalid", "AI enrich must remain unsupported"
                        )
                    effective, reason, missing_component = "unavailable", "not_implemented", None
                if effective in {"degraded", "unavailable"}:
                    if reason not in SUPPORT_REASON_CODES:
                        raise RepresentationContractError(
                            "representation_invalid",
                            "support reason is outside the closed registry",
                        )
                elif reason is not None or missing_component is not None:
                    raise RepresentationContractError(
                        "representation_invalid", "available support cannot report a blocker"
                    )
                if include_profile:
                    records.append(
                        {
                            "profile_id": selected_profile,
                            "profile_version": profile.get("version"),
                            "operation": operation,
                            "declared_state": declared,
                            "effective_state": effective,
                            "implementation": implementation,
                            "limits": dict(limits),
                            "reason": reason,
                            "missing_component": missing_component,
                            "network_required": False,
                            "ai_used": False,
                        }
                    )
        return {
            "schema_version": SUPPORT_REGISTRY_VERSION,
            "registry_id": "provelume.representation-support.v1",
            "operations": list(SUPPORT_OPERATIONS),
            "reason_codes": list(SUPPORT_REASON_CODES),
            "records": records,
            "network_used": False,
            "mutated": False,
        }


class RepresentationBundleManager:
    """Materialize, remove, rebuild and inspect universal derived bundles."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "derived" / "representations"
        self.history = store.paths.state / "derived" / "representation-history"

    def _version(self, version_id: str) -> dict[str, Any]:
        version = self.store.read_canonical("versions", version_id)
        if version is None:
            raise RepresentationContractError(
                "representation_not_found", "DocumentVersion was not found"
            )
        original = self.store.read_canonical("originals", str(version["original_id"]))
        if original is None:
            raise RepresentationContractError(
                "representation_original_mismatch", "Original identity is unavailable"
            )
        data = self.store.original_bytes(str(original["id"]))
        digest = _sha256(data)
        if (
            digest != original.get("sha256")
            or digest != version.get("content_hash")
            or len(data) != original.get("size_bytes")
            or len(data) != version.get("size_bytes")
        ):
            raise RepresentationContractError(
                "representation_original_mismatch", "Original identity verification failed"
            )
        return {
            "id": str(version["id"]),
            "original_id": str(original["id"]),
            "original_sha256": digest,
            "original_size_bytes": len(data),
        }

    def _authority_matches(self, bundle: Mapping[str, Any]) -> bool:
        try:
            authority = self._version(str(bundle["version"]["id"]))
        except (KeyError, OSError, TypeError, ValueError):
            return False
        return authority == bundle["version"]

    @staticmethod
    def _output_name(value: str) -> str:
        selected = _portable_relative_path(value)
        if len(PurePosixPath(selected).parts) != 1:
            raise RepresentationContractError(
                "representation_path_unsafe", "representation output name must be one segment"
            )
        return selected

    def materialize(
        self,
        version_id: str,
        *,
        recipe_id: str,
        recipe_version: str,
        recipe_settings: Mapping[str, Any],
        output_payloads: Mapping[str, tuple[str, bytes]],
        implementation: Mapping[str, Any],
        warnings: Sequence[str] = (),
        anchor_targets: Sequence[Mapping[str, Any]] = (),
        corrections: Sequence[Mapping[str, Any]] = (),
        previous_representation_ids: Sequence[str] = (),
        parent_representation_ids: Sequence[str] = (),
        availability_state: str = "available",
        availability_reason: str | None = None,
        missing_component: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        version = self._version(version_id)
        if not output_payloads:
            raise RepresentationContractError(
                "representation_invalid", "representation needs at least one output"
            )
        names = sorted(self._output_name(name) for name in output_payloads)
        _validate_path_set(names)
        outputs: list[dict[str, Any]] = []
        payloads: dict[str, bytes] = {}
        for name in names:
            media_type, payload = output_payloads[name]
            if not isinstance(payload, bytes):
                raise RepresentationContractError(
                    "representation_invalid", "representation output payload must be bytes"
                )
            digest = _sha256(payload)
            output_id = "rout_" + _fingerprint(
                {
                    "name": name,
                    "media_type": media_type,
                    "sha256": digest,
                    "size_bytes": len(payload),
                }
            )
            outputs.append(
                {
                    "id": output_id,
                    "media_type": media_type,
                    "storage_ref": "PENDING",
                    "sha256": digest,
                    "size_bytes": len(payload),
                }
            )
            payloads[name] = payload

        preliminary_recipe = recipe_fingerprint(recipe_id, recipe_version, recipe_settings)
        provisional = [
            {**output, "storage_ref": f"outputs/{name}"}
            for output, name in zip(outputs, names, strict=True)
        ]
        provisional_output = output_fingerprint(provisional)
        selected_id = representation_id(
            version_id=version_id,
            original_sha256=version["original_sha256"],
            recipe_sha256=preliminary_recipe,
            output_sha256=provisional_output,
        )
        final_outputs = [
            {
                **output,
                "storage_ref": (f"state/derived/representations/{selected_id}/outputs/{name}"),
            }
            for output, name in zip(outputs, names, strict=True)
        ]
        # Compute the fixed identifier before publishing the final storage paths.
        final_output_sha256 = output_fingerprint(final_outputs)
        selected_id = representation_id(
            version_id=version_id,
            original_sha256=version["original_sha256"],
            recipe_sha256=preliminary_recipe,
            output_sha256=final_output_sha256,
        )
        final_outputs = [
            {
                **output,
                "storage_ref": (f"state/derived/representations/{selected_id}/outputs/{name}"),
            }
            for output, name in zip(outputs, names, strict=True)
        ]
        bundle = build_representation_bundle(
            version=version,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            recipe_settings=recipe_settings,
            outputs=final_outputs,
            implementation=implementation,
            warnings=warnings,
            anchor_targets=anchor_targets,
            corrections=corrections,
            previous_representation_ids=previous_representation_ids,
            parent_representation_ids=parent_representation_ids,
            availability_state=availability_state,
            availability_reason=availability_reason,
            missing_component=missing_component,
            created_at=created_at or utc_now(),
        )
        # Storage paths do not participate recursively in the output fingerprint.
        selected_id = str(bundle["representation_id"])
        expected_prefix = f"state/derived/representations/{selected_id}/outputs/"
        if any(
            not str(item["storage_ref"]).startswith(expected_prefix) for item in bundle["outputs"]
        ):
            raise RepresentationContractError(
                "representation_identity_mismatch",
                "representation storage identity did not converge",
            )
        self._install(bundle, payloads)
        return self.get(selected_id, deep=True) or bundle

    def _install(self, bundle: Mapping[str, Any], payloads: Mapping[str, bytes]) -> None:
        selected = validate_representation_bundle(bundle)
        selected_id = str(selected["representation_id"])
        final = self.root / selected_id
        if final.exists():
            existing = self.get(selected_id, deep=True)
            if existing == selected:
                return
            raise RepresentationContractError(
                "representation_collision", "representation identity already has different bytes"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".representation-", dir=self.root))
        try:
            (staging / "outputs").mkdir()
            for output in selected["outputs"]:
                name = PurePosixPath(str(output["storage_ref"])).name
                payload = payloads.get(name)
                if (
                    payload is None
                    or _sha256(payload) != output["sha256"]
                    or len(payload) != output["size_bytes"]
                ):
                    raise RepresentationContractError(
                        "representation_output_mismatch", "representation output bytes do not match"
                    )
                (staging / "outputs" / name).write_bytes(payload)
            (staging / "bundle.json").write_bytes(canonical_json_bytes(selected))
            os.replace(staging, final)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def get(self, selected_id: str, *, deep: bool = True) -> dict[str, Any] | None:
        if _REPRESENTATION_ID.fullmatch(selected_id) is None:
            return None
        path = self.root / selected_id / "bundle.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            bundle = validate_representation_bundle(value)
        except (OSError, json.JSONDecodeError, RepresentationContractError):
            return None
        if bundle["representation_id"] != selected_id:
            return None
        if not self._authority_matches(bundle):
            return None
        expected_prefix = f"state/derived/representations/{selected_id}/outputs/"
        if any(
            not str(output["storage_ref"]).startswith(expected_prefix)
            or len(PurePosixPath(str(output["storage_ref"])).parts)
            != len(PurePosixPath(expected_prefix).parts) + 1
            for output in bundle["outputs"]
        ):
            return None
        if deep:
            for output in bundle["outputs"]:
                try:
                    target = safe_instance_path(self.store.paths.root, output["storage_ref"])
                    payload = target.read_bytes()
                except (OSError, ValueError):
                    return None
                if _sha256(payload) != output["sha256"] or len(payload) != output["size_bytes"]:
                    return None
        return bundle

    def list(
        self,
        *,
        version_id: str | None = None,
        recipe_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        result: list[dict[str, Any]] = []
        if not self.root.exists():
            return result
        for path in sorted(self.root.glob("repr_*/bundle.json")):
            bundle = self.get(path.parent.name, deep=True)
            if (
                bundle is None
                or (version_id is not None and bundle["version"]["id"] != version_id)
                or (recipe_id is not None and bundle["recipe"]["id"] != recipe_id)
            ):
                continue
            result.append(bundle)
            if len(result) >= min(limit, 500):
                break
        return result

    def remove(self, selected_id: str, *, removed_at: str | None = None) -> dict[str, Any]:
        bundle = self.get(selected_id, deep=True)
        if bundle is None:
            raise RepresentationContractError(
                "representation_not_found", "representation was not found"
            )
        history_bundle = {
            **bundle,
            "lifecycle": {
                **bundle["lifecycle"],
                "state": "removed",
                "removed_at": removed_at or utc_now(),
            },
        }
        validate_representation_bundle(history_bundle)
        self.history.mkdir(parents=True, exist_ok=True)
        receipt = {
            "schema_version": 1,
            "kind": "representation-removal-receipt",
            "representation_id": selected_id,
            "bundle_fingerprint": _fingerprint(bundle),
            "bundle": history_bundle,
            "removed_outputs": [
                {key: output[key] for key in ("id", "storage_ref", "sha256", "size_bytes")}
                for output in bundle["outputs"]
            ],
            "original_mutated": False,
            "canonical_records_mutated": False,
            "provider_data_mutated": False,
        }
        _validate_removal_receipt(receipt)
        target = self.history / f"{selected_id}.json"
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=self.history)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(canonical_json_bytes(receipt))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        shutil.rmtree(self.root / selected_id)
        return receipt

    def rebuild(self, selected_id: str, output_payloads: Mapping[str, bytes]) -> dict[str, Any]:
        receipt_path = self.history / f"{selected_id}.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt = _validate_removal_receipt(receipt)
            removed = receipt["bundle"]
        except (OSError, json.JSONDecodeError, RepresentationContractError) as exc:
            raise RepresentationContractError(
                "representation_not_found", "representation removal history was not found"
            ) from exc
        if not self._authority_matches(removed):
            raise RepresentationContractError(
                "representation_original_mismatch",
                "removed representation authority no longer matches",
            )
        active = {
            **removed,
            "lifecycle": {
                **removed["lifecycle"],
                "state": "active",
                "removed_at": None,
            },
        }
        payloads = {self._output_name(name): value for name, value in output_payloads.items()}
        self._install(active, payloads)
        result = self.get(selected_id, deep=True)
        if result is None or _fingerprint(result) != receipt["bundle_fingerprint"]:
            shutil.rmtree(self.root / selected_id, ignore_errors=True)
            raise RepresentationContractError(
                "representation_output_mismatch", "rebuilt representation is not equivalent"
            )
        return result


class RepresentationReadModel:
    """One immutable semantic projection for service, CLI, API and Browser."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.bundles = RepresentationBundleManager(store)
        self.support = SupportRegistry(store)

    def compatibility(self) -> list[dict[str, Any]]:
        source = _resource_json("lectio-representation-compatibility.json")
        profiles = source.get("profiles")
        if source.get("schema_version") != 1 or not isinstance(profiles, list):
            raise RepresentationContractError(
                "representation_invalid", "Lectio compatibility fixture is invalid"
            )
        counts = {
            "document-extraction": sum(
                item.get("kind") == "extracted_text" for item in self.store.list_derived_artifacts()
            ),
            "local-ocr": len(
                list((self.store.paths.state / "derived" / "ocr-bundles").glob("**/manifest.json"))
            ),
            "email-intake": len(self.store.list_canonical("email-messages")),
            "google-readonly": len(self.store.list_canonical("google-gmail-observations"))
            + len(self.store.list_canonical("google-drive-revisions")),
            "transcript-srt": sum(
                item.get("profile") == "srt-v1"
                for item in self.store.list_canonical("transcript-revisions")
            ),
            "transcript-webvtt": sum(
                item.get("profile") == "webvtt-v1"
                for item in self.store.list_canonical("transcript-revisions")
            ),
            "cross-source-findings": len(
                list((self.store.paths.state / "qualification" / "findings").glob("*.json"))
            ),
        }
        result = []
        for profile in profiles:
            selected = dict(profile)
            selected["records_visible"] = counts.get(str(selected["compatibility_id"]), 0)
            selected["source_byte_unchanged"] = True
            selected["migration_performed"] = False
            result.append(selected)
        return result

    def read(
        self,
        *,
        profile_id: str | None = None,
        version_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "schema_version": REPRESENTATION_READ_MODEL_VERSION,
            "model_id": "provelume.representation-read-model.v1",
            "support": self.support.read(profile_id=profile_id),
            "representations": self.bundles.list(version_id=version_id, limit=limit),
            "compatibility": self.compatibility(),
            "reserved_anchor_kinds": list(RESERVED_ANCHOR_KINDS),
            "network_used": False,
            "mutated": False,
        }

    def get(self, selected_id: str) -> dict[str, Any] | None:
        bundle = self.bundles.get(selected_id, deep=True)
        if bundle is None:
            return None
        return {
            "schema_version": REPRESENTATION_READ_MODEL_VERSION,
            "model_id": "provelume.representation-read-model.v1",
            "representation": bundle,
            "network_used": False,
            "mutated": False,
        }


def representation_state_findings(store: InstanceStore) -> list[dict[str, str]]:
    manager = RepresentationBundleManager(store)
    findings: list[dict[str, str]] = []
    if manager.root.exists():
        for path in sorted(manager.root.iterdir()):
            relative = path.relative_to(store.paths.root).as_posix()
            if (
                path.is_symlink()
                or not path.is_dir()
                or _REPRESENTATION_ID.fullmatch(path.name) is None
            ):
                findings.append(
                    {
                        "code": "representation_state_invalid",
                        "message": "Representation state contains an invalid entry",
                        "path": relative,
                    }
                )
                continue
            if manager.get(path.name, deep=True) is None:
                findings.append(
                    {
                        "code": "representation_state_invalid",
                        "message": "Representation bundle or output failed validation",
                        "path": relative,
                    }
                )
    if manager.history.exists():
        for path in sorted(manager.history.iterdir()):
            relative = path.relative_to(store.paths.root).as_posix()
            try:
                if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                    raise RepresentationContractError(
                        "representation_invalid", "representation history entry is invalid"
                    )
                receipt = _validate_removal_receipt(json.loads(path.read_text(encoding="utf-8")))
                if (
                    path.name != f"{receipt['representation_id']}.json"
                    or not manager._authority_matches(receipt["bundle"])
                ):
                    raise RepresentationContractError(
                        "representation_identity_mismatch",
                        "representation history filename does not match",
                    )
            except (OSError, json.JSONDecodeError, RepresentationContractError):
                findings.append(
                    {
                        "code": "representation_history_invalid",
                        "message": "Representation removal history failed validation",
                        "path": relative,
                    }
                )
    return findings


__all__ = [
    "ANCHOR_KINDS",
    "AnchorKind",
    "DeclaredSupportState",
    "EffectiveSupportState",
    "REPRESENTATION_SCHEMA_VERSION",
    "RESERVED_ANCHOR_KINDS",
    "SUPPORT_OPERATIONS",
    "SUPPORT_REASON_CODES",
    "RepresentationBundleManager",
    "RepresentationContractError",
    "RepresentationLifecycle",
    "RepresentationReadModel",
    "SupportOperation",
    "SupportReason",
    "SupportRegistry",
    "build_representation_bundle",
    "canonical_json_bytes",
    "output_fingerprint",
    "recipe_fingerprint",
    "representation_id",
    "representation_state_findings",
    "validate_representation_bundle",
]
