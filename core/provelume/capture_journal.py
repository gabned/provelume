"""Internal durable submission boundary; no transport, pairing or acquisition API."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
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
from .maintenance_local_files import MaintenanceTargetError, _windows_open
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
        data = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    if (
        len(data) != before.st_size
        or identity(after) != identity(before)
        or identity(path.lstat()) != identity(before)
    ):
        raise CaptureJournalError("Capture record changed")
    return data


def _read_pinned_windows_record(path: Path, limit: int) -> bytes:
    # The inventory holds every ancestor against rename. This leaf handle rejects
    # reparse points and denies writes/delete for the duration of the fresh read.
    with os.fdopen(_windows_open(path, directory=False), "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise CaptureJournalError("invalid Capture record size or kind")
        # A small receipt must not allocate the 36 MiB maximum on every read.
        # The checked size bounds allocation; the extra byte and fresh identity
        # check still reject growth, truncation or replacement during the read.
        data = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
        if len(data) != before.st_size or (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise CaptureJournalError("Capture record changed")
        return data


@contextmanager
def _posix_inventory_handles(root: Path):
    # Descriptor-relative traversal refuses links at every component. POSIX open
    # directories can be renamed, so check every binding again before returning
    # an inventory. No ancestor or record validation survives this operation.
    with ExitStack() as stack:
        bindings, devices = [], {}
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

        def pin(name, parent=None):
            fd = os.open(name, flags, dir_fd=parent)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            bindings.append((parent, name, info.st_dev, info.st_ino))
            return fd

        root = root.absolute()
        root_fd = pin(root.anchor)
        for name in root.parts[1:]:
            root_fd = pin(name, root_fd)

        def pin_device(path):
            if path.parent != root or path.name in devices:
                raise CaptureJournalError("invalid Capture device directory")
            devices[path.name] = pin(path.name, root_fd)
            return devices[path.name]

        def read_record(path, limit):
            if path.parent.parent != root or path.parent.name not in devices:
                raise CaptureJournalError("invalid Capture record path")
            parent = devices[path.parent.name]
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=parent)

            def identity(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                    raise CaptureJournalError("invalid Capture record size or kind")
                data = stream.read(before.st_size + 1)
                after = os.fstat(fd)
                current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                if (len(data) != before.st_size or identity(before) != identity(after)
                        or identity(before) != identity(current)):
                    raise CaptureJournalError("Capture record changed")
                return data

        yield root_fd, pin_device, read_record
        for parent, name, device, inode in bindings:
            try:
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
                        device, inode):
                    raise CaptureJournalError("Capture directory changed during inventory")
            except OSError as exc:
                raise CaptureJournalError("Capture directory changed during inventory") from exc


@contextmanager
def _inventory_handles(root: Path):
    with ExitStack() as stack:
        try:
            if os.name == "nt":
                # Pin top-down once per operation, never cache authority across
                # inventories. Retained device handles are bounded by MAX_RECORDS.
                for parent in reversed((root, *root.parents)):
                    stack.callback(os.close, _windows_open(parent, directory=True))

                def pin_device(path):
                    stack.callback(os.close, _windows_open(path, directory=True))
                    return path

                yield root, pin_device, _read_pinned_windows_record
            else:
                with _posix_inventory_handles(root) as handles:
                    yield handles
        except (MaintenanceTargetError, OSError) as exc:
            raise CaptureJournalError("unsafe or unavailable Capture path") from exc


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

    def _validate(self, data: bytes, relative: str, *, instance_id: str | None = None) -> dict:
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
                or value["instance_id"]
                != (self._instance_id() if instance_id is None else instance_id)
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
        # Bind this inventory to one observed identity, rather than rereading
        # and deep-copying the full config for every retained receipt. This is
        # operation-local, with a fresh identity check before returning results.
        instance_id = self._instance_id()
        result = {}
        total = 0
        with _inventory_handles(self.root) as (scan_root, pin_device, read_record), os.scandir(
            scan_root
        ) as devices:
            for index, device in enumerate(devices):
                if index >= MAX_RECORDS or not re.fullmatch(r"dev_[0-9a-f]{32}", device.name):
                    raise CaptureJournalError("invalid or full Capture device inventory")
                device_path = self.root / device.name
                scan_device = pin_device(device_path)
                if not device.is_dir(follow_symlinks=False):
                    raise CaptureJournalError("invalid Capture device directory")
                with os.scandir(scan_device) as records:
                    for record in records:
                        relative = f"state/capture/{device.name}/{record.name}"
                        if len(result) >= MAX_RECORDS or not _PATH.fullmatch(relative):
                            raise CaptureJournalError("invalid or full Capture inventory")
                        data = read_record(
                            device_path / record.name,
                            min(MAX_RECORD_BYTES, MAX_JOURNAL_BYTES - total),
                        )
                        total += len(data)
                        result[relative] = self._validate(data, relative, instance_id=instance_id)
        if self._instance_id() != instance_id:
            raise CaptureJournalError("Capture Instance identity changed during inventory")
        return result

    def _read_ready(self):
        root = self.lifecycle.control_root / "transactions"
        _safe(root)
        if root.exists() and any(
            any(root.glob(pattern))
            for pattern in ("capture-*", "device-authority-*", "submission-quarantine-*")
        ):
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
        admission: Callable[[int], None] | None = None,
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
            if admission is not None:
                admission(len(data) * 2 + 72 * 1024)
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
        if stage.name.startswith("capture-acquisition-"):
            continue
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
    from .capture_adapter import recover_capture_acquisitions_locked

    recover_capture_acquisitions_locked(store)
    return recover_atomic_transactions(
        store, journal.lifecycle.control_root, handlers=(AtomicRecoveryHandler(profile=PROFILE),)
    )
