"""Durable host-private locators; only opaque, immutable capabilities are public."""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .instance_backup import MAX_BACKUP_TOTAL_BYTES
from .maintenance_local_files import (
    MaintenanceTargetError,
    absolute_local_path,
    file_identity,
    open_local_file,
    open_local_lock,
    pinned_parent,
    stream_digest,
    write_local_bytes,
)
from .storage import InstanceStore, utc_now

MAX_TARGETS = 64
MAX_PRIVATE_BYTES = 256 * 1024
REF = re.compile(r"mt_[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def canonical_bytes(value) -> bytes:
    try:
        return (
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise MaintenanceTargetError("invalid_input") from exc


def revision(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def strict_json(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise MaintenanceTargetError("invalid_private_state")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise MaintenanceTargetError("invalid_private_state") from exc


class LocalTargetRegistry:
    def __init__(self, store: InstanceStore):
        self.store = store
        self.instance_id = store.read_config().get("instance", {}).get("id")
        if not isinstance(self.instance_id, str) or not re.fullmatch(
            r"inst_[0-9a-f]{32}", self.instance_id
        ):
            raise MaintenanceTargetError("instance_mismatch")
        self.control = store.paths.root.parent / ("." + store.paths.root.name + ".provelume")
        self.root = self.control / "maintenance-targets"
        self.path = self.root / "registry.json"

    def _ensure(self):
        for path in (self.control, self.root):
            with pinned_parent(path):
                path.mkdir(mode=0o700, exist_ok=True)

    @contextmanager
    def hold(self):
        from .instance_lifecycle import (
            InstanceLifecycleBusy,
            _acquire_os_lock,
            _release_os_lock,
        )

        self._ensure()
        lock = self.root / "registry.lock"
        with open_local_lock(lock) as descriptor:
            held = False
            try:
                _acquire_os_lock(descriptor)
                held = True
                yield
            except InstanceLifecycleBusy as exc:
                raise MaintenanceTargetError("busy") from exc
            finally:
                if held:
                    _release_os_lock(descriptor)

    def _load(self):
        if not self.path.exists() and not self.path.is_symlink():
            return {"schema_version": 1, "instance_id": self.instance_id, "targets": {}}
        with open_local_file(self.path) as handle:
            raw = handle.read(MAX_PRIVATE_BYTES + 1)
        if len(raw) > MAX_PRIVATE_BYTES:
            raise MaintenanceTargetError("invalid_private_state")
        value = strict_json(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "instance_id", "targets"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["instance_id"] != self.instance_id
            or not isinstance(value["targets"], dict)
            or len(value["targets"]) > MAX_TARGETS
        ):
            raise MaintenanceTargetError("invalid_private_state")
        for key, row in value["targets"].items():
            if (
                not REF.fullmatch(key)
                or not isinstance(row, dict)
                or set(row) != {"public", "locator", "identity"}
                or not isinstance(row["public"], dict)
                or not isinstance(row["locator"], str)
                or not isinstance(row["identity"], dict)
            ):
                raise MaintenanceTargetError("invalid_private_state")
            public = row["public"]
            purpose = public.get("purpose")
            fields = {"target_ref", "instance_id", "purpose", "created_at", "target_revision"}
            identity_fields = {"device", "inode"}
            if purpose == "backup_read":
                fields |= {"archive_sha256", "size_bytes"}
                identity_fields |= {"size_bytes", "mtime_ns", "ctime_ns"}
                if (
                    not isinstance(public.get("archive_sha256"), str)
                    or not SHA.fullmatch(public["archive_sha256"])
                    or type(public.get("size_bytes")) is not int
                    or not 0 <= public["size_bytes"] <= MAX_BACKUP_TOTAL_BYTES
                ):
                    raise MaintenanceTargetError("invalid_private_state")
            elif purpose != "diagnostic_write":
                raise MaintenanceTargetError("invalid_private_state")
            if (
                set(public) != fields
                or not isinstance(public["created_at"], str)
                or not re.fullmatch(r"[0-9T:.+Z-]{20,40}", public["created_at"])
                or set(row["identity"]) != identity_fields
                or any(type(n) is not int or n < 0 for n in row["identity"].values())
            ):
                raise MaintenanceTargetError("invalid_private_state")
            expected = {k: v for k, v in public.items() if k != "target_revision"}
            if (
                public.get("target_ref") != key
                or public.get("instance_id") != self.instance_id
                or public.get("target_revision")
                != revision(
                    {
                        **expected,
                        "private": {"locator": row["locator"], "identity": row["identity"]},
                    }
                )
            ):
                raise MaintenanceTargetError("invalid_private_state")
        return value

    def _save(self, state):
        raw = canonical_bytes(state)
        if len(raw) > MAX_PRIVATE_BYTES:
            raise MaintenanceTargetError("target_capacity")
        write_local_bytes(self.path, raw, replace=True)

    def status(self):
        """Pure bounded recovery inventory; never expose private locators or create state."""
        state = self._load()
        return {
            "instance_id": self.instance_id,
            "targets": [dict(row["public"]) for _, row in sorted(state["targets"].items())],
            "capacity": MAX_TARGETS,
        }

    def _register(self, path, purpose, identity, extra):
        with self.hold():
            state = self._load()
            if len(state["targets"]) >= MAX_TARGETS:
                raise MaintenanceTargetError("target_capacity")
            ref = "mt_" + uuid4().hex
            public = {
                "target_ref": ref,
                "instance_id": self.instance_id,
                "purpose": purpose,
                "created_at": utc_now(),
                **extra,
            }
            private = {"locator": str(path), "identity": identity}
            public["target_revision"] = revision({**public, "private": private})
            state["targets"][ref] = {"public": public, **private}
            self._save(state)
            return dict(public)

    def register_archive(self, path: Path | str):
        path = absolute_local_path(path)
        with open_local_file(path) as handle:
            identity = file_identity(handle)
            digest, size = stream_digest(handle, MAX_BACKUP_TOTAL_BYTES)
            if file_identity(handle) != identity:
                raise MaintenanceTargetError("target_stale")
        return self._register(
            path, "backup_read", identity, {"archive_sha256": digest, "size_bytes": size}
        )

    def register_output(self, path: Path | str):
        path = absolute_local_path(path)
        if path.is_relative_to(self.store.paths.root) or path.is_relative_to(self.control):
            raise MaintenanceTargetError("target_unsafe")
        with pinned_parent(path) as (_, parent):
            if path.exists() or path.is_symlink() or path.is_junction():
                raise MaintenanceTargetError("output_exists")
            info = path.parent.stat() if parent is None else os.fstat(parent)
            identity = {"device": info.st_dev, "inode": info.st_ino}
        return self._register(path, "diagnostic_write", identity, {})

    def resolve(self, target_ref: str, target_revision: str, purpose: str):
        if (
            not isinstance(target_ref, str)
            or not REF.fullmatch(target_ref)
            or not isinstance(target_revision, str)
            or not SHA.fullmatch(target_revision)
        ):
            raise MaintenanceTargetError("invalid_input")
        row = self._load()["targets"].get(target_ref)
        if row is None:
            raise MaintenanceTargetError("target_missing")
        public = row["public"]
        if public["target_revision"] != target_revision or public["purpose"] != purpose:
            raise MaintenanceTargetError("target_stale")
        return row

    @contextmanager
    def archive(self, target_ref: str, target_revision: str):
        # Lock order: caller lifecycle (if any), then locator registry, never scheduler here.
        with self.hold():
            row = self.resolve(target_ref, target_revision, "backup_read")
            with open_local_file(row["locator"]) as handle:
                if file_identity(handle) != row["identity"]:
                    raise MaintenanceTargetError("target_stale")
                before = stream_digest(handle, MAX_BACKUP_TOTAL_BYTES)
                if before != (row["public"]["archive_sha256"], row["public"]["size_bytes"]):
                    raise MaintenanceTargetError("target_stale")
                yield handle, dict(row["public"])
                if (
                    file_identity(handle) != row["identity"]
                    or stream_digest(handle, MAX_BACKUP_TOTAL_BYTES) != before
                ):
                    raise MaintenanceTargetError("target_stale")

    def write_output(self, target_ref: str, target_revision: str, data: bytes):
        with self.hold():
            row = self.resolve(target_ref, target_revision, "diagnostic_write")
            path = absolute_local_path(row["locator"])
            with pinned_parent(path) as (_, parent):
                info = path.parent.stat() if parent is None else os.fstat(parent)
                if row["identity"] != {"device": info.st_dev, "inode": info.st_ino}:
                    raise MaintenanceTargetError("target_stale")
                write_local_bytes(path, data)

    def revoke(self, target_ref: str, expected_revision: str):
        with self.hold():
            state = self._load()
            row = self.resolve(
                target_ref,
                expected_revision,
                state["targets"].get(target_ref, {}).get("public", {}).get("purpose", ""),
            )
            del state["targets"][target_ref]
            self._save(state)
            return {
                "target_ref": target_ref,
                "previous_revision": row["public"]["target_revision"],
                "instance_id": self.instance_id,
                "status": "revoked",
                "file_deleted": False,
            }
