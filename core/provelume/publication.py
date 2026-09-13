"""Bounded, descriptive publication evidence. No network or package mutation on reads."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SOURCE_REPOSITORY = "gabned/provelume"
RECEIPT_NAME = "publication-receipt.json"
READY_NAME = "publication-ready.json"
MAX_RECEIPT_BYTES = 128 * 1024
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
MAX_ARTIFACTS = 256
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,254}\Z")


class PublicationError(ValueError):
    """A closed metadata failure; messages never contain local paths or response bodies."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise PublicationError("publication metadata fields are invalid")
    return value


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise PublicationError("publication timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise PublicationError("publication timestamp is invalid") from exc


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PublicationError("clock must have a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _identity(value: Mapping[str, Any]) -> None:
    if value.get("source_repository") != SOURCE_REPOSITORY:
        raise PublicationError("publication repository differs")
    version = value.get("version")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise PublicationError("publication version is invalid")
    if value.get("tag") != f"v{version}":
        raise PublicationError("publication tag differs")
    if not isinstance(value.get("commit"), str) or not _COMMIT.fullmatch(value["commit"]):
        raise PublicationError("publication commit is invalid")
    if value.get("channel") not in {"preview", "stable"}:
        raise PublicationError("publication channel is invalid")


def artifact_identity(value: Any) -> dict[str, Any]:
    row = _object(value, {"name", "sha256", "size_bytes"})
    if not isinstance(row["name"], str) or not _NAME.fullmatch(row["name"]):
        raise PublicationError("publication artifact name is invalid")
    if not isinstance(row["sha256"], str) or not _SHA.fullmatch(row["sha256"]):
        raise PublicationError("publication artifact digest is invalid")
    if type(row["size_bytes"]) is not int or not 0 < row["size_bytes"] <= MAX_PAYLOAD_BYTES:
        raise PublicationError("publication artifact size is invalid")
    return dict(row)


def decode_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_RECEIPT_BYTES:
        raise PublicationError("publication metadata exceeds its byte limit")

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise PublicationError("publication metadata has duplicate fields")
            result[key] = item
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PublicationError("publication metadata is not valid JSON") from exc
    if not isinstance(value, dict):
        raise PublicationError("publication metadata must be an object")
    return value


def parse_receipt(value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        value = decode_json(value)
    value = _object(
        value,
        {
            "schema_version",
            "source_repository",
            "version",
            "tag",
            "commit",
            "channel",
            "published_at",
            "observed_at",
            "release_id",
            "release_url",
            "manifest",
            "artifacts",
        },
    )
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise PublicationError("publication schema is unsupported")
    _identity(value)
    published = timestamp(value["published_at"])
    observed = timestamp(value["observed_at"])
    if observed < published:
        raise PublicationError("publication observation predates publication")
    try:
        published + timedelta(days=1)
    except OverflowError as exc:
        raise PublicationError("publication expiry is out of range") from exc
    if type(value["release_id"]) is not int or value["release_id"] <= 0:
        raise PublicationError("publication release identity is invalid")
    if (
        value["release_url"]
        != f"https://github.com/{SOURCE_REPOSITORY}/releases/tag/{value['tag']}"
    ):
        raise PublicationError("publication release URL differs")
    manifest = artifact_identity(value["manifest"])
    if manifest["name"] != "release-manifest.json":
        raise PublicationError("publication manifest name differs")
    rows = value["artifacts"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ARTIFACTS:
        raise PublicationError("publication artifact count is invalid")
    names: set[str] = set()
    for raw in rows:
        row = artifact_identity(raw)
        name = row["name"].casefold()
        if name in names or name == manifest["name"].casefold():
            raise PublicationError("publication artifact identities collide")
        names.add(name)
    return decode_json(canonical_bytes(value))


def parse_readiness(value: Any) -> dict[str, Any]:
    value = _object(
        value,
        {
            "schema_version",
            "status",
            "source_repository",
            "version",
            "tag",
            "commit",
            "channel",
            "release_id",
            "receipt",
            "manifest",
            "kit",
        },
    )
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise PublicationError("publication readiness schema is unsupported")
    if value["status"] != "installation_kit_ready":
        raise PublicationError("publication finalization is pending")
    _identity(value)
    if type(value["release_id"]) is not int or value["release_id"] <= 0:
        raise PublicationError("publication release identity is invalid")
    for field, name in (
        ("receipt", RECEIPT_NAME),
        ("manifest", "release-manifest.json"),
        ("kit", f"provelume-{value['version']}-installation-kit.zip"),
    ):
        if artifact_identity(value[field])["name"] != name:
            raise PublicationError("publication readiness artifact differs")
    return decode_json(canonical_bytes(value))


def validate_delivery(receipt: bytes, readiness: Any) -> dict[str, Any]:
    ready = parse_readiness(readiness)
    value = parse_receipt(receipt)
    if any(
        value[key] != ready[key]
        for key in (
            "source_repository",
            "version",
            "tag",
            "commit",
            "channel",
            "release_id",
            "manifest",
        )
    ):
        raise PublicationError("publication receipt differs from readiness")
    if ready["receipt"]["sha256"] != hashlib.sha256(receipt).hexdigest() or ready["receipt"][
        "size_bytes"
    ] != len(receipt):
        raise PublicationError("publication receipt digest differs from readiness")
    return value


def safe_path(path: Path) -> Path:
    """Reject link-like components before resolving, including an existing destination."""
    path = path.expanduser().absolute()
    for part in (*reversed(path.parents), path):
        if part.is_symlink() or part.is_junction():
            raise PublicationError("publication path is link-like")
        if part.exists() and getattr(part.stat(), "st_file_attributes", 0) & 0x400:
            raise PublicationError("publication path is a reparse point")
    return path


def read_metadata(path: Path) -> bytes:
    path = safe_path(path)
    with path.open("rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise PublicationError("publication metadata is not a regular file")
        raw = handle.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise PublicationError("publication metadata exceeds its byte limit")
    return raw


def file_identity(path: Path) -> dict[str, Any]:
    path = safe_path(path)
    if not path.is_file():
        raise PublicationError("publication payload is unavailable")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise PublicationError("publication payload is not a regular file")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            if size > MAX_PAYLOAD_BYTES:
                raise PublicationError("publication payload exceeds its byte limit")
            digest.update(chunk)
    return artifact_identity({"name": path.name, "sha256": digest.hexdigest(), "size_bytes": size})


def default_receipt_path(build: Mapping[str, Any]) -> Path:
    configured = os.environ.get("PROVELUME_PUBLICATION_RECEIPT")
    if configured:
        return Path(configured)
    version, commit = build.get("version"), build.get("commit")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise PublicationError("installed version is unavailable")
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise PublicationError("installed commit is unavailable")
    root = (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(sys.prefix) / "share" / "provelume"
    )
    return root / "publication" / f"{version}-{commit}" / RECEIPT_NAME


def _same_build(receipt: Mapping[str, Any], build: Mapping[str, Any]) -> bool:
    return build.get("official") is True and all(
        receipt[key] == build.get(key)
        for key in ("source_repository", "version", "tag", "commit", "channel")
    )


def write_once(path: Path, raw: bytes) -> None:
    """Atomic create, idempotent for identical bytes; never overwrite an existing identity."""
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path(path)
    if path.exists():
        if read_metadata(path) != raw:
            raise PublicationError("publication identity already has different bytes")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".publication-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if read_metadata(path) != raw:
                raise PublicationError("publication identity already has different bytes") from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def import_publication(
    receipt_path: Path,
    *,
    manifest_path: Path,
    payload_path: Path,
    destination: Path | None = None,
    build: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from .build_info import current_build_info

    build = dict(build) if build is not None else current_build_info()
    raw = read_metadata(receipt_path)
    receipt = parse_receipt(raw)
    if not _same_build(receipt, build):
        raise PublicationError("publication identity differs from installed build")
    manifest_raw = read_metadata(manifest_path)
    manifest = decode_json(manifest_raw)
    if file_identity(manifest_path) != receipt["manifest"]:
        raise PublicationError("publication manifest bytes differ")
    if any(
        manifest.get(key) != receipt[key]
        for key in (
            "source_repository",
            "version",
            "tag",
            "commit",
            "channel",
        )
    ):
        raise PublicationError("publication manifest identity differs")
    identity = file_identity(payload_path)
    if identity not in receipt["artifacts"]:
        raise PublicationError("publication payload bytes differ")
    manifest_rows = manifest.get("artifacts")
    if not isinstance(manifest_rows, list) or not any(
        isinstance(row, dict) and all(row.get(key) == identity[key] for key in identity)
        for row in manifest_rows
    ):
        raise PublicationError("publication payload is absent from the manifest")
    if not (
        identity["name"].endswith((".whl", ".tar.gz"))
        or identity["name"] == f"Provelume-Setup-{receipt['version']}-x64.exe"
    ):
        raise PublicationError("publication import requires a distribution payload")
    target = destination or default_receipt_path(build)
    write_once(target, raw)
    return {
        "schema_version": 1,
        "status": "imported",
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "published_at": receipt["published_at"],
        "network_used": False,
        "origin_authentication": "not_established",
    }


def current_publication(
    *,
    now: datetime | None = None,
    receipt_path: Path | str | None = None,
    build: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from .build_info import current_build_info

    build = dict(build) if build is not None else current_build_info()
    selected_now = now if now is not None else datetime.now(UTC)
    result = {
        "schema_version": 1,
        "status": "missing",
        "published_at": None,
        "expires_at": None,
        "computed_at": None,
        "new": False,
        "remaining_seconds": 0,
        "receipt_sha256": None,
        "source_repository": build.get("source_repository"),
        "version": build.get("version"),
        "tag": build.get("tag"),
        "commit": build.get("commit"),
        "origin_authentication": "not_established",
        "network_used": False,
    }
    try:
        result["computed_at"] = utc_text(selected_now)
        selected_now = timestamp(result["computed_at"])
    except (PublicationError, ValueError, OverflowError):
        result["status"] = "clock_unusable"
        return result
    if build.get("official") is not True:
        return result
    try:
        raw = read_metadata(
            Path(receipt_path) if receipt_path is not None else default_receipt_path(build)
        )
        receipt = parse_receipt(raw)
        if not _same_build(receipt, build):
            result["status"] = "identity_mismatch"
            return result
        published = timestamp(receipt["published_at"])
        expires = published + timedelta(days=1)
        result.update(
            status="available",
            published_at=utc_text(published),
            expires_at=utc_text(expires),
            receipt_sha256=hashlib.sha256(raw).hexdigest(),
        )
        if selected_now < timestamp(receipt["observed_at"]) or selected_now < published:
            result["status"] = "clock_unusable"
        else:
            result["new"] = selected_now < expires
            result["remaining_seconds"] = max(
                0, math.ceil((expires - selected_now).total_seconds())
            )
    except FileNotFoundError:
        pass
    except (OSError, PublicationError, ValueError, OverflowError):
        result["status"] = "invalid"
    return result
