from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any

from . import __version__

BUILD_INFO_SCHEMA_VERSION = 1
SOURCE_REPOSITORY = "gabned/provelume"
SEMANTIC_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
OFFICIAL_CHANNELS = {"preview", "stable"}
IDENTITY_STATUSES = {
    "official_metadata_present",
    "development_build",
    "identity_unavailable",
}
EXPECTED_FIELDS = {
    "schema_version",
    "version",
    "source_repository",
    "tag",
    "commit",
    "channel",
    "source_date_epoch",
    "source_date_utc",
    "official",
}


class BuildInfoError(ValueError):
    """Raised when embedded build metadata violates the public contract."""


def _verification_boundary() -> dict[str, Any]:
    return {
        "status": "not_performed",
        "installation_integrity": "not_verified",
        "artifact_provenance": "not_verified_locally",
        "signature": "not_verified",
        "network_used": False,
    }


def _timestamp(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise BuildInfoError("source_date_epoch must be a non-negative integer or null")
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def create_build_info(
    *,
    version: str,
    commit: str | None,
    tag: str | None,
    channel: str,
    source_date_epoch: int | None,
    official: bool,
) -> dict[str, Any]:
    if not SEMANTIC_VERSION.fullmatch(version):
        raise BuildInfoError("version must be semantic X.Y.Z")
    if commit is not None and not COMMIT_SHA.fullmatch(commit):
        raise BuildInfoError("commit must be a lowercase 40-character SHA-1 or null")
    if not isinstance(official, bool):
        raise BuildInfoError("official must be a boolean")
    source_date_utc = _timestamp(source_date_epoch)

    if official:
        if tag != f"v{version}":
            raise BuildInfoError("official build tag must match the package version")
        if commit is None:
            raise BuildInfoError("official build metadata requires a commit")
        if channel not in OFFICIAL_CHANNELS:
            raise BuildInfoError("official build channel must be preview or stable")
        if source_date_epoch is None:
            raise BuildInfoError("official build metadata requires a source timestamp")
    else:
        if tag is not None:
            raise BuildInfoError("development build metadata must not declare a release tag")
        if channel != "development":
            raise BuildInfoError("non-official build channel must be development")

    return {
        "schema_version": BUILD_INFO_SCHEMA_VERSION,
        "version": version,
        "source_repository": SOURCE_REPOSITORY,
        "tag": tag,
        "commit": commit,
        "channel": channel,
        "source_date_epoch": source_date_epoch,
        "source_date_utc": source_date_utc,
        "official": official,
    }


def parse_build_info(value: Any, *, package_version: str = __version__) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuildInfoError("build metadata must be a JSON object")
    fields = set(value)
    missing = EXPECTED_FIELDS - fields
    unknown = fields - EXPECTED_FIELDS
    if missing:
        raise BuildInfoError(f"build metadata is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise BuildInfoError(f"build metadata has unknown fields: {', '.join(sorted(unknown))}")
    if value["schema_version"] != BUILD_INFO_SCHEMA_VERSION:
        raise BuildInfoError("unsupported build metadata schema version")
    if value["source_repository"] != SOURCE_REPOSITORY:
        raise BuildInfoError("build metadata source repository is not canonical")

    normalized = create_build_info(
        version=value["version"],
        commit=value["commit"],
        tag=value["tag"],
        channel=value["channel"],
        source_date_epoch=value["source_date_epoch"],
        official=value["official"],
    )
    if normalized["source_date_utc"] != value["source_date_utc"]:
        raise BuildInfoError("source_date_utc does not match source_date_epoch")
    if normalized["version"] != package_version:
        raise BuildInfoError(
            f"embedded version {normalized['version']} does not match package {package_version}"
        )

    return {
        **normalized,
        "identity_status": (
            "official_metadata_present" if normalized["official"] else "development_build"
        ),
        "metadata_present": True,
        "metadata_error": None,
        "verification": _verification_boundary(),
    }


def unavailable_build_info(error: str) -> dict[str, Any]:
    return {
        "schema_version": BUILD_INFO_SCHEMA_VERSION,
        "version": __version__,
        "source_repository": None,
        "tag": None,
        "commit": None,
        "channel": None,
        "source_date_epoch": None,
        "source_date_utc": None,
        "official": False,
        "identity_status": "identity_unavailable",
        "metadata_present": False,
        "metadata_error": error,
        "verification": _verification_boundary(),
    }


@lru_cache(maxsize=1)
def current_build_info() -> dict[str, Any]:
    try:
        path = files("provelume").joinpath("build_info.json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        result = parse_build_info(raw)
    except (BuildInfoError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result = unavailable_build_info(str(exc) or exc.__class__.__name__)
    if result["identity_status"] not in IDENTITY_STATUSES:
        return unavailable_build_info("invalid computed identity status")
    return result
