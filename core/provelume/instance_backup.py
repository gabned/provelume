from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .instance_schema import (
    CURRENT_INSTANCE_SCHEMA_VERSION,
    DERIVED_STATE_POLICY,
    LEGACY_INSTANCE_SCHEMA_VERSION,
)
from .instance_validation import inspect_instance
from .paths import normalise_locator, safe_instance_path
from .storage import CANONICAL_KINDS, InstanceStore, utc_now

BACKUP_SCHEMA_VERSION = 1
BACKUP_KIND = "provelume-instance-backup"
BACKUP_MANIFEST_NAME = "backup-manifest.json"
BACKUP_PAYLOAD_PREFIX = "payload/"
BACKUP_EXCLUDED_PREFIXES = (
    "indexes/",
    "library/",
    "state/locks/",
)
MAX_BACKUP_ENTRIES = 100_000
MAX_BACKUP_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_BACKUP_FILE_BYTES = 16 * 1024 * 1024 * 1024
MAX_BACKUP_TOTAL_BYTES = 512 * 1024 * 1024 * 1024


class BackupError(RuntimeError):
    pass


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def default_backup_directory(store: InstanceStore) -> Path:
    return store.paths.root.parent / f".{store.paths.root.name}.provelume" / "backups"


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _backup_destination(
    store: InstanceStore,
    destination: Path | str | None,
) -> tuple[str, Path]:
    backup_id = (
        "backup_"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        + "_"
        + uuid4().hex
    )
    if destination is None:
        selected = default_backup_directory(store) / f"{backup_id}.zip"
    else:
        requested = Path(destination).expanduser()
        if requested.exists() and requested.is_dir():
            selected = requested / f"{backup_id}.zip"
        elif requested.suffix.casefold() == ".zip":
            selected = requested
        else:
            selected = requested / f"{backup_id}.zip"
    selected = selected.resolve()
    if _is_inside(selected, store.paths.root):
        raise BackupError("backup archive must be stored outside the Instance root")
    if selected.exists():
        raise BackupError("backup destination already exists")
    return backup_id, selected


def _excluded(relative: str) -> bool:
    value = f"{relative.rstrip('/')}/" if not relative.endswith("/") else relative
    return any(value.startswith(prefix) for prefix in BACKUP_EXCLUDED_PREFIXES)


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _payload_files(store: InstanceStore) -> list[tuple[str, Path, int, str]]:
    result: list[tuple[str, Path, int, str]] = []
    for path in sorted(store.paths.root.rglob("*")):
        relative = path.relative_to(store.paths.root).as_posix()
        if _excluded(relative):
            continue
        if path.is_symlink():
            raise BackupError(
                f"Instance-internal symbolic link cannot be backed up: {relative}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise BackupError(f"Instance entry is not a regular file: {relative}")
        try:
            size, digest = _file_identity(path)
        except OSError as exc:
            raise BackupError(f"Instance file cannot be read: {relative}") from exc
        result.append((normalise_locator(relative), path, size, digest))
    return result


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info


def create_backup(
    store: InstanceStore,
    *,
    destination: Path | str | None = None,
    reason: str = "manual",
) -> dict[str, Any]:
    selected_reason = reason.strip()[:120]
    if not selected_reason:
        raise ValueError("backup reason is required")
    validation = inspect_instance(store.paths.root, deep=True)
    if validation["status"] != "valid":
        raise BackupError("Instance validation failed before backup")
    backup_id, archive = _backup_destination(store, destination)
    archive.parent.mkdir(parents=True, exist_ok=True)
    files = _payload_files(store)
    entries = [
        {
            "path": relative,
            "sha256": digest,
            "size_bytes": size,
        }
        for relative, _path, size, digest in files
    ]
    manifest = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "kind": BACKUP_KIND,
        "backup_id": backup_id,
        "created_at": utc_now(),
        "reason": selected_reason,
        "instance_id": validation["instance_id"],
        "instance_schema_version": validation["instance_schema_version"],
        "content_fingerprint": validation["content_fingerprint"],
        "derived_state": dict(DERIVED_STATE_POLICY),
        "excluded_prefixes": list(BACKUP_EXCLUDED_PREFIXES),
        "entries": entries,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive.name}.", suffix=".tmp", dir=archive.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as bundle:
            bundle.writestr(_zip_info(BACKUP_MANIFEST_NAME), manifest_bytes)
            for relative, source, _size, _digest in files:
                with source.open("rb") as source_handle, bundle.open(
                    _zip_info(f"{BACKUP_PAYLOAD_PREFIX}{relative}"),
                    mode="w",
                ) as target_handle:
                    while chunk := source_handle.read(1024 * 1024):
                        target_handle.write(chunk)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)

    verified = verify_backup(archive)
    if verified["status"] != "valid":
        archive.unlink(missing_ok=True)
        raise BackupError("new backup archive failed independent verification")
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "status": "completed",
        "backup_id": backup_id,
        "archive": str(archive),
        "archive_sha256": _archive_sha256(archive),
        "size_bytes": archive.stat().st_size,
        "instance_id": validation["instance_id"],
        "instance_schema_version": validation["instance_schema_version"],
        "content_fingerprint": validation["content_fingerprint"],
        "files": len(entries),
        "derived_state": dict(DERIVED_STATE_POLICY),
        "excluded_prefixes": list(BACKUP_EXCLUDED_PREFIXES),
    }


def _manifest_from_bundle(bundle: zipfile.ZipFile) -> dict[str, Any]:
    try:
        info = bundle.getinfo(BACKUP_MANIFEST_NAME)
    except KeyError as exc:
        raise BackupError("backup manifest is missing") from exc
    if info.file_size > MAX_BACKUP_MANIFEST_BYTES:
        raise BackupError("backup manifest exceeds the safety limit")
    try:
        value = json.loads(bundle.read(info))
    except (UnicodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise BackupError("backup manifest is unreadable") from exc
    if not isinstance(value, dict):
        raise BackupError("backup manifest must be a JSON object")
    return value


def _validated_entries(
    bundle: zipfile.ZipFile,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    if (
        manifest.get("schema_version") != BACKUP_SCHEMA_VERSION
        or manifest.get("kind") != BACKUP_KIND
        or not isinstance(manifest.get("backup_id"), str)
        or not str(manifest["backup_id"]).startswith("backup_")
        or not isinstance(manifest.get("created_at"), str)
        or not isinstance(manifest.get("reason"), str)
        or not isinstance(manifest.get("instance_id"), str)
        or manifest.get("instance_schema_version")
        not in {LEGACY_INSTANCE_SCHEMA_VERSION, CURRENT_INSTANCE_SCHEMA_VERSION}
        or manifest.get("derived_state") != DERIVED_STATE_POLICY
        or manifest.get("excluded_prefixes") != list(BACKUP_EXCLUDED_PREFIXES)
        or not isinstance(manifest.get("entries"), list)
    ):
        raise BackupError("backup manifest contract is invalid")

    infos = bundle.infolist()
    if len(infos) > MAX_BACKUP_ENTRIES + 1:
        raise BackupError("backup contains too many entries")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise BackupError("backup contains duplicate ZIP entry names")
    if any(info.flag_bits & 0x1 for info in infos):
        raise BackupError("encrypted backup entries are not supported")
    for info in infos:
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) == stat.S_IFLNK:
            raise BackupError("backup contains a symbolic link")

    rows: list[dict[str, Any]] = []
    paths: list[str] = []
    total = 0
    entries = manifest["entries"]
    if len(entries) > MAX_BACKUP_ENTRIES:
        raise BackupError("backup manifest contains too many entries")
    for row in entries:
        if not isinstance(row, dict):
            raise BackupError("backup entry descriptor is invalid")
        path = row.get("path")
        digest = row.get("sha256")
        size = row.get("size_bytes")
        try:
            normalized_path = normalise_locator(path) if isinstance(path, str) else None
        except ValueError as exc:
            raise BackupError("backup entry path is unsafe") from exc
        if (
            not isinstance(path, str)
            or normalized_path != path
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or type(size) is not int
            or size < 0
            or size > MAX_BACKUP_FILE_BYTES
            or _excluded(path)
        ):
            raise BackupError("backup entry descriptor is invalid")
        payload_name = f"{BACKUP_PAYLOAD_PREFIX}{path}"
        try:
            info = bundle.getinfo(payload_name)
        except KeyError as exc:
            raise BackupError(f"backup payload is missing: {path}") from exc
        if info.is_dir() or info.file_size != size:
            raise BackupError(f"backup payload size is invalid: {path}")
        total += size
        if total > MAX_BACKUP_TOTAL_BYTES:
            raise BackupError("backup expands beyond the total safety limit")
        paths.append(path)
        rows.append({"path": path, "sha256": digest, "size_bytes": size})
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise BackupError("backup paths must be unique and sorted")
    folded = [path.casefold() for path in paths]
    if len(folded) != len(set(folded)):
        raise BackupError("backup paths collide on case-insensitive filesystems")
    expected_names = {BACKUP_MANIFEST_NAME} | {
        f"{BACKUP_PAYLOAD_PREFIX}{path}" for path in paths
    }
    if set(names) != expected_names:
        raise BackupError("backup contains undeclared ZIP entries")
    return rows


def verify_backup(archive: Path | str) -> dict[str, Any]:
    selected = Path(archive).expanduser().resolve()
    try:
        with zipfile.ZipFile(selected, mode="r") as bundle:
            manifest = _manifest_from_bundle(bundle)
            entries = _validated_entries(bundle, manifest)
            for row in entries:
                digest = hashlib.sha256()
                size = 0
                with bundle.open(
                    f"{BACKUP_PAYLOAD_PREFIX}{row['path']}", mode="r"
                ) as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                if size != row["size_bytes"] or digest.hexdigest() != row["sha256"]:
                    raise BackupError(
                        f"backup payload hash is invalid: {row['path']}"
                    )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("backup archive cannot be read") from exc
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "status": "valid",
        "archive": str(selected),
        "archive_sha256": _archive_sha256(selected),
        "size_bytes": selected.stat().st_size,
        "backup_id": manifest["backup_id"],
        "instance_id": manifest["instance_id"],
        "instance_schema_version": manifest["instance_schema_version"],
        "content_fingerprint": manifest.get("content_fingerprint"),
        "files": len(entries),
        "derived_state": dict(DERIVED_STATE_POLICY),
        "excluded_prefixes": list(BACKUP_EXCLUDED_PREFIXES),
    }


def extract_backup(archive: Path | str, destination: Path | str) -> dict[str, Any]:
    selected = Path(archive).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=False)
    try:
        (target / "originals").mkdir()
        for kind in CANONICAL_KINDS:
            (target / "knowledge" / kind).mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(selected, mode="r") as bundle:
            manifest = _manifest_from_bundle(bundle)
            entries = _validated_entries(bundle, manifest)
            for row in entries:
                output = safe_instance_path(target, row["path"])
                output.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    output,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                digest = hashlib.sha256()
                size = 0
                with bundle.open(
                    f"{BACKUP_PAYLOAD_PREFIX}{row['path']}", mode="r"
                ) as source, os.fdopen(descriptor, "wb") as handle:
                    while chunk := source.read(1024 * 1024):
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                if size != row["size_bytes"] or digest.hexdigest() != row["sha256"]:
                    raise BackupError(
                        f"backup payload hash is invalid: {row['path']}"
                    )
    except Exception:
        import shutil

        shutil.rmtree(target, ignore_errors=True)
        raise
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "status": "extracted",
        "instance_id": manifest["instance_id"],
        "instance_schema_version": manifest["instance_schema_version"],
        "files": len(entries),
    }
