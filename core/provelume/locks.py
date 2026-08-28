from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .storage import InstanceStore, utc_now

LOCK_SCHEMA_VERSION = 1
_LOCK_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,79}\Z")
_LOCK_TOKEN = re.compile(r"lock_[0-9a-f]{32}\Z")


class InstanceLockUnavailable(RuntimeError):
    pass


class InstanceLockOwnershipError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InstanceLockLease:
    schema_version: int
    name: str
    token: str
    purpose: str
    acquired_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class InstanceLockManager:
    """Small cross-platform lock registry for Instance-local exclusive work."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "locks"

    @staticmethod
    def _validate_name(name: str) -> str:
        selected = name.strip()
        if _LOCK_NAME.fullmatch(selected) is None:
            raise ValueError("invalid Instance lock name")
        return selected

    def _path(self, name: str) -> Path:
        return self.root / f"{self._validate_name(name)}.json"

    @staticmethod
    def _parse(value: Any, expected_name: str) -> InstanceLockLease | None:
        if not isinstance(value, dict):
            return None
        try:
            lease = InstanceLockLease(
                schema_version=int(value["schema_version"]),
                name=str(value["name"]),
                token=str(value["token"]),
                purpose=str(value["purpose"]),
                acquired_at=str(value["acquired_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if (
            lease.schema_version != LOCK_SCHEMA_VERSION
            or lease.name != expected_name
            or _LOCK_TOKEN.fullmatch(lease.token) is None
            or not lease.purpose.strip()
            or not lease.acquired_at.strip()
        ):
            return None
        return lease

    def inspect(self, name: str) -> dict[str, Any] | None:
        selected = self._validate_name(name)
        path = self._path(selected)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {
                "schema_version": LOCK_SCHEMA_VERSION,
                "name": selected,
                "held": True,
                "status": "unreadable",
                "purpose": None,
                "acquired_at": None,
            }
        lease = self._parse(value, selected)
        if lease is None:
            return {
                "schema_version": LOCK_SCHEMA_VERSION,
                "name": selected,
                "held": True,
                "status": "invalid",
                "purpose": None,
                "acquired_at": None,
            }
        return {
            "schema_version": LOCK_SCHEMA_VERSION,
            "name": selected,
            "held": True,
            "status": "held",
            "purpose": lease.purpose,
            "acquired_at": lease.acquired_at,
        }

    def acquire(self, name: str, *, purpose: str) -> InstanceLockLease:
        selected = self._validate_name(name)
        selected_purpose = purpose.strip()[:500]
        if not selected_purpose:
            raise ValueError("Instance lock purpose is required")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(selected)
        lease = InstanceLockLease(
            schema_version=LOCK_SCHEMA_VERSION,
            name=selected,
            token=f"lock_{uuid4().hex}",
            purpose=selected_purpose,
            acquired_at=utc_now(),
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise InstanceLockUnavailable(
                f"Instance lock is already held: {selected}"
            ) from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(lease.as_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return lease

    def release(self, lease: InstanceLockLease) -> None:
        path = self._path(lease.name)
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise InstanceLockOwnershipError(
                f"Instance lock cannot be released safely: {lease.name}"
            ) from exc
        current = self._parse(value, lease.name)
        if current is None or current.token != lease.token:
            raise InstanceLockOwnershipError(
                f"Instance lock ownership changed: {lease.name}"
            )
        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise InstanceLockOwnershipError(
                f"Instance lock disappeared before release: {lease.name}"
            ) from exc

    @contextmanager
    def hold(self, name: str, *, purpose: str) -> Iterator[InstanceLockLease]:
        lease = self.acquire(name, purpose=purpose)
        try:
            yield lease
        finally:
            self.release(lease)
