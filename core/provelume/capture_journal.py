"""Internal durable submission boundary; no transport, pairing or acquisition API."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .atomic_commit import (
    AtomicCommitLimits,
    AtomicCommitProfile,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    recover_atomic_transactions,
)
from .capture_requests import (
    capture_payload_fingerprint,
    capture_scope_key,
    validate_capture_metadata,
)
from .instance_lifecycle import InstanceLifecycleManager
from .storage import InstanceStore, utc_now

MAX_RECORD_BYTES = 36 * 1024 * 1024
MAX_JOURNAL_BYTES = 128 * 1024 * 1024
MAX_RECORDS = 128
_PATH = re.compile(r"state/capture/dev_[0-9a-f]{32}/capture_[0-9a-f]{64}\.json\Z")
PROFILE = AtomicCommitProfile(
    key="capture",
    kind="capture.submission",
    owner_id_pattern=r"capture_[0-9a-f]{64}\Z",
    limits=AtomicCommitLimits(1, MAX_RECORD_BYTES, MAX_RECORD_BYTES, 1, MAX_RECORD_BYTES),
)


class CaptureJournalError(ValueError):
    """Unavailable, corrupt, full or conflicting Capture state fails visibly."""


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise CaptureJournalError("duplicate Capture field")
        value[key] = item
    return value


def _safe(path: Path) -> None:
    for parent in (path, *path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise CaptureJournalError("unsafe Capture path")


def _read(path: Path, limit: int = MAX_RECORD_BYTES) -> bytes:
    _safe(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise CaptureJournalError("invalid Capture record size or kind")

    def identity(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns

    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise CaptureJournalError("Capture record changed")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if (
        len(data) > limit
        or identity(after) != identity(before)
        or identity(path.lstat()) != identity(before)
    ):
        raise CaptureJournalError("Capture record changed")
    return data


class CaptureJournal:
    def __init__(self, store: InstanceStore):
        self.store = store
        self.lifecycle = InstanceLifecycleManager(store)
        self.root = store.paths.state / "capture"

    def _instance_id(self):
        value = self.store.read_config().get("instance", {}).get("id")
        if not isinstance(value, str) or not value:
            raise CaptureJournalError("Capture Instance identity unavailable")
        return value

    def _validate(self, data: bytes, relative: str) -> dict:
        try:
            value = json.loads(data, object_pairs_hook=_unique)
            if set(value) != {"schema_version", "instance_id", "receipt", "payload_base64"}:
                raise ValueError()
            receipt = value["receipt"]
            if set(receipt) != {
                "id",
                "device_id",
                "metadata",
                "fingerprint",
                "received_at",
                "status",
            }:
                raise ValueError()
            metadata = receipt["metadata"]
            key = capture_scope_key(receipt["device_id"], metadata["client_submission_id"])
            expected = f"state/capture/{receipt['device_id']}/{key}.json"
            payload = base64.b64decode(value["payload_base64"], validate=True)
            timestamp = datetime.fromisoformat(receipt["received_at"])
            if (
                type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or value["instance_id"] != self._instance_id()
                or relative != expected
                or receipt["id"] != key
                or receipt["status"] != "committed"
                or timestamp.tzinfo is None
                or receipt["fingerprint"]
                != capture_payload_fingerprint(
                    payload, metadata, transport_channel=metadata["channel"]
                )
            ):
                raise ValueError()
            return value
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise CaptureJournalError("invalid Capture record") from exc

    def _inventory(self) -> dict[str, dict]:
        _safe(self.root)
        if not self.root.exists():
            return {}
        result = {}
        total = 0
        with os.scandir(self.root) as devices:
            for index, device in enumerate(devices):
                if index >= MAX_RECORDS or not re.fullmatch(r"dev_[0-9a-f]{32}", device.name):
                    raise CaptureJournalError("invalid or full Capture device inventory")
                _safe(Path(device.path))
                if not device.is_dir(follow_symlinks=False):
                    raise CaptureJournalError("invalid Capture device directory")
                with os.scandir(device.path) as records:
                    for record in records:
                        relative = f"state/capture/{device.name}/{record.name}"
                        if len(result) >= MAX_RECORDS or not _PATH.fullmatch(relative):
                            raise CaptureJournalError("invalid or full Capture inventory")
                        data = _read(
                            Path(record.path), min(MAX_RECORD_BYTES, MAX_JOURNAL_BYTES - total)
                        )
                        total += len(data)
                        result[relative] = self._validate(data, relative)
        return result

    def _read_ready(self):
        root = self.lifecycle.control_root / "transactions"
        _safe(root)
        if root.exists() and any(root.glob("capture-*")):
            raise CaptureJournalError("Capture recovery required before receipt lookup")

    def lookup(
        self, device_id: str, client_id: str, *, authorize: Callable[[str], None]
    ) -> dict | None:
        key = capture_scope_key(device_id, client_id)
        authorize(device_id)
        self._read_ready()
        relative = f"state/capture/{device_id}/{key}.json"
        record = self._inventory().get(relative)
        self._read_ready()
        return record["receipt"] if record else None

    def list_receipts(self, device_id: str, *, authorize: Callable[[str], None]) -> list[dict]:
        # Validate the device through the same identity primitive as lookup.
        capture_scope_key(device_id, "00000000-0000-4000-8000-000000000000")
        authorize(device_id)
        self._read_ready()
        values = self._inventory()
        self._read_ready()
        return [v["receipt"] for v in values.values() if v["receipt"]["device_id"] == device_id]

    def submit(
        self,
        device_id: str,
        payload: bytes,
        metadata: Any,
        *,
        transport_channel: str,
        authorize: Callable[[str], None],
        validate_payload: Callable[[bytes, dict], None],
    ) -> dict:
        # Freeze client input before calling domain guards or acquiring a lock.
        selected = validate_capture_metadata(metadata, transport_channel=transport_channel)
        fingerprint = capture_payload_fingerprint(
            payload, selected, transport_channel=transport_channel
        )
        key = capture_scope_key(device_id, selected["client_submission_id"])
        relative = f"state/capture/{device_id}/{key}.json"
        with self.lifecycle._hold(purpose="capture-submit"):
            authorize(device_id)
            validate_payload(payload, dict(selected))
            inventory = self._inventory()
            previous = inventory.get(relative)
            if previous is not None:
                receipt = previous["receipt"]
                if (
                    receipt["device_id"] != device_id
                    or receipt["metadata"] != selected
                    or base64.b64decode(previous["payload_base64"]) != payload
                    or receipt["fingerprint"] != fingerprint
                ):
                    raise CaptureJournalError("conflicting Capture identity reuse")
                return receipt
            if len(inventory) >= MAX_RECORDS:
                raise CaptureJournalError("Capture journal full")
            receipt = dict(
                id=key,
                device_id=device_id,
                metadata=selected,
                fingerprint=fingerprint,
                received_at=utc_now(),
                status="committed",
            )
            value = dict(
                schema_version=1,
                instance_id=self._instance_id(),
                receipt=receipt,
                payload_base64=base64.b64encode(payload).decode("ascii"),
            )
            data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
            if (
                len(data) + sum((self.store.paths.root / path).stat().st_size for path in inventory)
                > MAX_JOURNAL_BYTES
            ):
                raise CaptureJournalError("Capture journal byte budget exhausted")
            self._validate(data, relative)
            transaction = AtomicInstanceCommit(
                self.store,
                self.lifecycle.control_root / "transactions",
                profile=PROFILE,
                owner_id=key,
            )
            transaction.add(relative, data, immutable=True)
            transaction.commit()
            return receipt


def recover_capture_transactions_locked(store: InstanceStore):
    """Lifecycle caller owns the lock; domain allowlist precedes generic recovery."""
    journal = CaptureJournal(store)
    root = journal.lifecycle.control_root / "transactions"
    _safe(root)
    if not root.exists():
        return None
    for index, stage in enumerate(root.glob("capture-*")):
        if index >= MAX_RECORDS or not PROFILE.transaction_pattern.fullmatch(stage.name):
            raise CaptureJournalError("invalid Capture recovery inventory")
        _safe(stage)
        manifest_path = stage / "manifest.json"
        if not manifest_path.exists():
            continue  # Generic recovery removes a stage with no prepared manifest.
        manifest = json.loads(_read(manifest_path, 72 * 1024), object_pairs_hook=_unique)
        entries = manifest.get("entries")
        if not isinstance(entries, list) or len(entries) != 1:
            raise CaptureJournalError("invalid Capture recovery entries")
        entry = entries[0]
        relative = entry.get("relative")
        if (
            not isinstance(relative, str)
            or not _PATH.fullmatch(relative)
            or entry.get("immutable") is not True
            or entry.get("had_preimage") is not False
            or entry.get("candidate_ref") != "candidates/0000.bin"
        ):
            raise CaptureJournalError("Capture recovery outside domain allowlist")
        target = store.paths.root / relative
        candidate = stage / "candidates/0000.bin"
        for path in (candidate, target):
            if path.exists():
                record = journal._validate(_read(path), relative)
                if record["receipt"]["id"] != manifest.get("operation_id"):
                    raise CaptureJournalError("Capture recovery owner mismatch")
    return recover_atomic_transactions(
        store, journal.lifecycle.control_root, handlers=(AtomicRecoveryHandler(profile=PROFILE),)
    )
