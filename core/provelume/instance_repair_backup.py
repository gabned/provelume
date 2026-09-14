"""Bounded recovery capsule for a single repair write set, never a full backup."""

from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path
from typing import Any

from .instance_repair_model import (
    MAX_REPAIR_ARCHIVE_BYTES,
    MAX_REPAIR_FILE_BYTES,
    REPAIR_BACKUP_SCOPE,
    InstanceRepairError,
    binding_revision,
    digest,
    encoded,
    validate_binding,
)


def safe_path(path: Path, *, missing: bool = False) -> Path:
    """Reject links/reparse points in every existing component, including controls."""
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise InstanceRepairError("missing_path") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise InstanceRepairError("unsafe_path")
    return path


def read_regular(path: Path, *, limit: int = MAX_REPAIR_FILE_BYTES) -> bytes:
    safe_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise InstanceRepairError("unsupported_file")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    after = path.stat()
    if len(data) > limit or (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise InstanceRepairError("snapshot_changed")
    return data


def sync_directory(path: Path) -> None:
    if os.name == "nt":
        return  # Windows does not expose directory fsync through this API.
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def payload_paths(binding: dict[str, Any]) -> dict[str, str]:
    return {
        "affected.bin": binding["relative_path"],
        **{f"context/{index}.bin": row["path"] for index, row in enumerate(binding["context"])},
    }


def create_capsule(
    path: Path, binding: dict[str, Any], payloads: dict[str, bytes]
) -> dict[str, Any]:
    validate_binding(binding)
    expected = set(payload_paths(binding)) | {"validation.json"}
    if set(payloads) != expected:
        raise InstanceRepairError("invalid_backup_payload")
    manifest = {
        "schema_version": 1,
        "kind": "provelume-state-repair-backup",
        "scope": REPAIR_BACKUP_SCOPE,
        "binding": binding,
        "input_revision": binding_revision(binding),
        "entries": [
            {"name": name, "size": len(data), "sha256": digest(data)}
            for name, data in sorted(payloads.items())
        ],
    }
    safe_path(path, missing=True)
    with path.open("xb") as handle:
        with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", encoded(manifest))
            for name, data in sorted(payloads.items()):
                archive.writestr(name, data)
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(path.parent)
    return verify_capsule(path)[0]


def verify_capsule(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    raw = read_regular(path, limit=MAX_REPAIR_ARCHIVE_BYTES)
    try:
        import io

        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != 8 or len(set(name.casefold() for name in names)) != len(names):
                raise InstanceRepairError("invalid_backup_inventory")
            if (
                any(
                    item.flag_bits & 1
                    or item.is_dir()
                    or item.file_size > MAX_REPAIR_FILE_BYTES
                    or stat.S_IFMT(item.external_attr >> 16) not in {0, stat.S_IFREG}
                    for item in infos
                )
                or sum(item.file_size for item in infos) > MAX_REPAIR_ARCHIVE_BYTES
            ):
                raise InstanceRepairError("invalid_backup_inventory")
            manifest = json.loads(archive.read("manifest.json"))
            if (
                not isinstance(manifest, dict)
                or set(manifest)
                != {"schema_version", "kind", "scope", "binding", "input_revision", "entries"}
                or manifest["schema_version"] != 1
                or manifest["kind"] != "provelume-state-repair-backup"
                or manifest["scope"] != REPAIR_BACKUP_SCOPE
            ):
                raise InstanceRepairError("invalid_backup_manifest")
            binding = validate_binding(manifest["binding"])
            if manifest["input_revision"] != binding_revision(binding):
                raise InstanceRepairError("invalid_backup_manifest")
            expected = set(payload_paths(binding)) | {"validation.json"}
            entries = manifest["entries"]
            if (
                not isinstance(entries, list)
                or len(entries) != 7
                or {row.get("name") for row in entries if isinstance(row, dict)} != expected
                or set(names) != expected | {"manifest.json"}
            ):
                raise InstanceRepairError("invalid_backup_inventory")
            payloads = {}
            for row in entries:
                if set(row) != {"name", "size", "sha256"} or type(row["size"]) is not int:
                    raise InstanceRepairError("invalid_backup_inventory")
                data = archive.read(row["name"])
                if len(data) != row["size"] or digest(data) != row["sha256"]:
                    raise InstanceRepairError("backup_hash_mismatch")
                payloads[row["name"]] = data
            for name, row in zip(
                ["affected.bin", *(f"context/{i}.bin" for i in range(5))],
                [*binding["affected_files"], *binding["context"]],
                strict=True,
            ):
                if digest(payloads[name]) != row["sha256"] or len(payloads[name]) != row["size"]:
                    raise InstanceRepairError("backup_context_mismatch")
            if payloads["validation.json"] != encoded(binding["validation_report"]):
                raise InstanceRepairError("backup_context_mismatch")
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, InstanceRepairError):
            raise
        raise InstanceRepairError("unreadable_backup") from exc
    return {"archive_sha256": digest(raw), "manifest": manifest}, payloads
