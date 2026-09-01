from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .paths import normalise_locator, safe_instance_path
from .storage import InstanceStore, utc_now

ATOMIC_COMMIT_SCHEMA_VERSION = 1

_PROFILE_KEY = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_JOURNAL_FILE = re.compile(r"(?:candidates|preimages)/[0-9]{4}\.bin\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_BASE_BYTES = 64 * 1024
_MANIFEST_BYTES_PER_ENTRY = 8 * 1024


def _manifest_byte_limit(max_entries: int) -> int:
    return _MANIFEST_BASE_BYTES + max_entries * _MANIFEST_BYTES_PER_ENTRY


class AtomicCommitError(RuntimeError):
    code = "atomic_commit_failed"
    safe_message = "The atomic Instance commit failed closed."

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class AtomicCommitIntegrityError(AtomicCommitError):
    code = "atomic_commit_integrity_failed"
    safe_message = "Existing Instance state rejected the atomic commit."


class AtomicCommitLimitError(AtomicCommitError):
    code = "atomic_commit_limit_exceeded"
    safe_message = "The atomic commit exceeded its closed limits."


class AtomicCommitRecoveryError(AtomicCommitError):
    code = "atomic_commit_recovery_failed"
    safe_message = "An interrupted atomic commit could not be recovered safely."


@dataclass(frozen=True, slots=True)
class AtomicCommitLimits:
    max_entries: int
    max_entry_bytes: int
    max_candidate_bytes: int
    max_preimage_bytes: int
    max_journal_payload_bytes: int

    def __post_init__(self) -> None:
        values = (
            self.max_entries,
            self.max_entry_bytes,
            self.max_candidate_bytes,
            self.max_preimage_bytes,
            self.max_journal_payload_bytes,
        )
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError("atomic commit limits must be positive integers")
        if self.max_candidate_bytes > self.max_journal_payload_bytes:
            raise ValueError("candidate limit exceeds the journal payload limit")
        if self.max_preimage_bytes > self.max_journal_payload_bytes:
            raise ValueError("preimage limit exceeds the journal payload limit")

    def as_dict(self) -> dict[str, int]:
        return {
            "max_entries": self.max_entries,
            "max_entry_bytes": self.max_entry_bytes,
            "max_candidate_bytes": self.max_candidate_bytes,
            "max_preimage_bytes": self.max_preimage_bytes,
            "max_journal_payload_bytes": self.max_journal_payload_bytes,
        }


@dataclass(frozen=True, slots=True)
class AtomicCommitProfile:
    key: str
    kind: str
    owner_id_pattern: str
    limits: AtomicCommitLimits

    def __post_init__(self) -> None:
        if _PROFILE_KEY.fullmatch(self.key) is None:
            raise ValueError("atomic commit profile key is invalid")
        if not self.kind or len(self.kind) > 120:
            raise ValueError("atomic commit profile kind is invalid")
        if self.limits.max_entries > 10_000:
            raise ValueError("atomic commit profile exceeds the journal entry namespace")
        try:
            pattern = re.compile(self.owner_id_pattern)
        except re.error as exc:
            raise ValueError("atomic commit owner pattern is invalid") from exc
        if pattern.fullmatch("") is not None:
            raise ValueError("atomic commit owner pattern cannot match an empty id")

    @property
    def transaction_pattern(self) -> re.Pattern[str]:
        return re.compile(rf"{re.escape(self.key)}-[0-9a-f]{{32}}\Z")

    def accepts_owner_id(self, owner_id: str) -> bool:
        return re.fullmatch(self.owner_id_pattern, owner_id) is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ATOMIC_COMMIT_SCHEMA_VERSION,
            "key": self.key,
            "kind": self.kind,
            "owner_id_pattern": self.owner_id_pattern,
            "limits": self.limits.as_dict(),
        }


MANUAL_WEB_TRANSACTION_PROFILE = AtomicCommitProfile(
    key="manual-web",
    kind="connector.web.acquire",
    owner_id_pattern=r"op_[0-9a-f]{32}\Z",
    limits=AtomicCommitLimits(
        max_entries=2048,
        max_entry_bytes=64 * 1024 * 1024,
        max_candidate_bytes=128 * 1024 * 1024,
        max_preimage_bytes=64 * 1024 * 1024,
        max_journal_payload_bytes=192 * 1024 * 1024,
    ),
)

EMAIL_INTAKE_TRANSACTION_PROFILE = AtomicCommitProfile(
    key="email-intake",
    kind="email.intake",
    owner_id_pattern=r"job_[0-9a-f]{32}\Z",
    limits=AtomicCommitLimits(
        max_entries=4096,
        max_entry_bytes=64 * 1024 * 1024,
        max_candidate_bytes=256 * 1024 * 1024,
        max_preimage_bytes=128 * 1024 * 1024,
        max_journal_payload_bytes=384 * 1024 * 1024,
    ),
)

GOOGLE_INTAKE_TRANSACTION_PROFILE = AtomicCommitProfile(
    key="google-intake",
    kind="google.intake",
    owner_id_pattern=r"job_[0-9a-f]{32}\Z",
    limits=AtomicCommitLimits(
        max_entries=4096,
        max_entry_bytes=256 * 1024 * 1024,
        max_candidate_bytes=512 * 1024 * 1024,
        max_preimage_bytes=128 * 1024 * 1024,
        max_journal_payload_bytes=768 * 1024 * 1024,
    ),
)

TRANSCRIPT_INTAKE_TRANSACTION_PROFILE = AtomicCommitProfile(
    key="transcript-intake",
    kind="transcript.intake",
    owner_id_pattern=r"job_[0-9a-f]{32}\Z",
    limits=AtomicCommitLimits(
        max_entries=2048,
        max_entry_bytes=64 * 1024 * 1024,
        max_candidate_bytes=192 * 1024 * 1024,
        max_preimage_bytes=64 * 1024 * 1024,
        max_journal_payload_bytes=256 * 1024 * 1024,
    ),
)

_ErrorType = type[Exception]
_Replace = Callable[[Path, Path], None]
_InterruptedHandler = Callable[[InstanceStore, str], None]


@dataclass(frozen=True, slots=True)
class AtomicRecoveryHandler:
    profile: AtomicCommitProfile
    on_prepared_rollback: _InterruptedHandler | None = None
    error_type: _ErrorType = AtomicCommitRecoveryError

    def __post_init__(self) -> None:
        if not isinstance(self.error_type, type) or not issubclass(
            self.error_type, Exception
        ):
            raise ValueError("atomic recovery error type must be an Exception")


class AtomicInstanceCommit:
    """Durably journal a bounded multi-file Instance commit before replacement."""

    def __init__(
        self,
        store: InstanceStore,
        stage_parent: Path,
        *,
        profile: AtomicCommitProfile,
        owner_id: str,
        error_type: _ErrorType = AtomicCommitError,
        integrity_error_type: _ErrorType = AtomicCommitIntegrityError,
        limit_error_type: _ErrorType = AtomicCommitLimitError,
        replace: _Replace = os.replace,
    ):
        for selected_error in (error_type, integrity_error_type, limit_error_type):
            if not isinstance(selected_error, type) or not issubclass(
                selected_error, Exception
            ):
                raise ValueError("atomic commit error types must be Exceptions")
        if not profile.accepts_owner_id(owner_id):
            raise integrity_error_type()
        self.store = store
        self.stage_parent = stage_parent
        self.profile = profile
        self.owner_id = owner_id
        self._error_type = error_type
        self._integrity_error_type = integrity_error_type
        self._limit_error_type = limit_error_type
        self._replace = replace
        self._writes: dict[str, tuple[bytes, bool]] = {}
        self._candidate_bytes = 0

    def add(self, relative: str, data: bytes, *, immutable: bool) -> None:
        target, selected = _instance_target(
            self.store,
            relative,
            error_type=self._integrity_error_type,
        )
        del target
        payload = bytes(data)
        current = self._writes.get(selected)
        candidate = (payload, immutable)
        if current is not None:
            if current != candidate:
                raise self._integrity_error_type()
            return
        limits = self.profile.limits
        if (
            len(self._writes) >= limits.max_entries
            or len(payload) > limits.max_entry_bytes
            or self._candidate_bytes + len(payload) > limits.max_candidate_bytes
            or self._candidate_bytes + len(payload) > limits.max_journal_payload_bytes
        ):
            raise self._limit_error_type()
        self._writes[selected] = candidate
        self._candidate_bytes += len(payload)

    def _prepare(self) -> tuple[Path, dict[str, Any]]:
        if not self._writes:
            raise self._integrity_error_type()
        if self.stage_parent.exists() and (
            not self.stage_parent.is_dir() or self.stage_parent.is_symlink()
        ):
            raise self._integrity_error_type()
        self.stage_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        transaction_id = f"{self.profile.key}-{uuid4().hex}"
        stage = self.stage_parent / transaction_id
        stage.mkdir(mode=0o700)
        try:
            entries: list[dict[str, Any]] = []
            candidate_bytes = 0
            preimage_bytes = 0
            for index, (relative, (data, immutable)) in enumerate(
                sorted(self._writes.items())
            ):
                target, _ = _instance_target(
                    self.store,
                    relative,
                    error_type=self._integrity_error_type,
                )
                before = _bounded_file_bytes(
                    target,
                    limit=self.profile.limits.max_entry_bytes,
                    missing_ok=True,
                    integrity_error_type=self._integrity_error_type,
                    limit_error_type=self._limit_error_type,
                )
                if before is not None and immutable and before != data:
                    raise self._integrity_error_type()
                if before == data:
                    continue
                next_candidate = candidate_bytes + len(data)
                next_preimage = preimage_bytes + (len(before) if before is not None else 0)
                if (
                    next_candidate > self.profile.limits.max_candidate_bytes
                    or next_preimage > self.profile.limits.max_preimage_bytes
                    or next_candidate + next_preimage
                    > self.profile.limits.max_journal_payload_bytes
                ):
                    raise self._limit_error_type()
                candidate_bytes = next_candidate
                preimage_bytes = next_preimage
                candidate_ref = f"candidates/{index:04d}.bin"
                self.store._atomic_bytes(stage / candidate_ref, data)
                preimage_ref = (
                    f"preimages/{index:04d}.bin" if before is not None else None
                )
                if before is not None and preimage_ref is not None:
                    self.store._atomic_bytes(stage / preimage_ref, before)
                entries.append(
                    {
                        "relative": relative,
                        "immutable": immutable,
                        "had_preimage": before is not None,
                        "preimage_ref": preimage_ref,
                        "preimage_sha256": (
                            hashlib.sha256(before).hexdigest()
                            if before is not None
                            else None
                        ),
                        "candidate_ref": candidate_ref,
                        "candidate_sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            if not entries:
                raise self._integrity_error_type()
            manifest = {
                "schema_version": ATOMIC_COMMIT_SCHEMA_VERSION,
                "transaction_id": transaction_id,
                "kind": self.profile.kind,
                "status": "prepared",
                # Schema 1 retains this field name for manual-web journal compatibility.
                "operation_id": self.owner_id,
                "prepared_at": utc_now(),
                "committed_at": None,
                "entries": entries,
            }
            manifest_bytes = (
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            if len(manifest_bytes) > _manifest_byte_limit(
                self.profile.limits.max_entries
            ):
                raise self._limit_error_type()
            self.store._atomic_bytes(stage / "manifest.json", manifest_bytes)
            _fsync_directory(stage)
            _fsync_directory(self.stage_parent)
            return stage, manifest
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    def commit(self) -> None:
        try:
            stage, manifest = self._prepare()
        except (self._integrity_error_type, self._limit_error_type, self._error_type):
            raise
        except Exception:
            raise self._error_type() from None
        try:
            for entry in manifest["entries"]:
                target, _ = _instance_target(
                    self.store,
                    str(entry["relative"]),
                    error_type=self._error_type,
                )
                before = _bounded_file_bytes(
                    target,
                    limit=self.profile.limits.max_entry_bytes,
                    missing_ok=True,
                    integrity_error_type=self._error_type,
                    limit_error_type=self._error_type,
                )
                expected_before = (
                    _journal_bytes(
                        stage,
                        str(entry["preimage_ref"]),
                        limit=self.profile.limits.max_entry_bytes,
                        error_type=self._error_type,
                    )
                    if entry["had_preimage"]
                    else None
                )
                if before != expected_before:
                    raise self._error_type()
                candidate = _journal_path(
                    stage,
                    str(entry["candidate_ref"]),
                    error_type=self._error_type,
                )
                candidate_digest, _ = _bounded_file_digest(
                    candidate,
                    limit=self.profile.limits.max_entry_bytes,
                    error_type=self._error_type,
                )
                if candidate_digest != entry["candidate_sha256"]:
                    raise self._error_type()
                target.parent.mkdir(parents=True, exist_ok=True)
                self._replace(candidate, target)
                _fsync_directory(target.parent)
            committed = {
                **manifest,
                "status": "committed",
                "committed_at": utc_now(),
            }
            committed_bytes = (
                json.dumps(committed, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            if len(committed_bytes) > _manifest_byte_limit(
                self.profile.limits.max_entries
            ):
                raise self._error_type()
            self.store._atomic_bytes(stage / "manifest.json", committed_bytes)
            _fsync_directory(stage)
        except Exception as exc:
            try:
                _rollback_prepared_transaction(
                    self.store,
                    stage,
                    manifest,
                    profile=self.profile,
                    error_type=self._error_type,
                )
                shutil.rmtree(stage)
                _fsync_directory(self.stage_parent)
            except Exception:
                raise self._error_type() from None
            if isinstance(
                exc,
                (self._integrity_error_type, self._limit_error_type, self._error_type),
            ):
                raise
            raise self._error_type() from None
        shutil.rmtree(stage, ignore_errors=True)
        # A durable committed marker makes later journal cleanup recoverable on open.
        with suppress(OSError):
            _fsync_directory(self.stage_parent)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _instance_target(
    store: InstanceStore,
    relative: str,
    *,
    error_type: _ErrorType,
) -> tuple[Path, str]:
    try:
        selected = normalise_locator(relative)
        if selected == ".":
            raise error_type()
        root = store.paths.root.resolve()
        lexical = root.joinpath(*PurePosixPath(selected).parts)
        current = root
        for part in PurePosixPath(selected).parts:
            current /= part
            if current.is_symlink():
                raise error_type()
        target = safe_instance_path(root, selected)
        if target != lexical:
            raise error_type()
    except (OSError, RuntimeError, ValueError):
        raise error_type() from None
    return target, selected


def _journal_path(stage: Path, relative: str, *, error_type: _ErrorType) -> Path:
    if _JOURNAL_FILE.fullmatch(relative) is None:
        raise error_type()
    try:
        path = safe_instance_path(stage, relative)
    except (OSError, RuntimeError, ValueError):
        raise error_type() from None
    current = stage
    for part in PurePosixPath(relative).parts:
        current /= part
        if current.is_symlink():
            raise error_type()
    return path


def _bounded_file_bytes(
    path: Path,
    *,
    limit: int,
    missing_ok: bool,
    integrity_error_type: _ErrorType,
    limit_error_type: _ErrorType,
) -> bytes | None:
    if not path.exists():
        if missing_ok:
            return None
        raise integrity_error_type()
    if not path.is_file() or path.is_symlink():
        raise integrity_error_type()
    try:
        before = path.stat()
        if before.st_size > limit:
            raise limit_error_type()
        data = path.read_bytes()
        after = path.stat()
    except (integrity_error_type, limit_error_type):
        raise
    except OSError:
        raise integrity_error_type() from None
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or len(data) != before.st_size:
        raise integrity_error_type()
    return data


def _bounded_file_digest(
    path: Path,
    *,
    limit: int,
    error_type: _ErrorType,
) -> tuple[str, int]:
    if not path.is_file() or path.is_symlink():
        raise error_type()
    try:
        before = path.stat()
        if before.st_size > limit:
            raise error_type()
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                size += len(block)
                if size > limit:
                    raise error_type()
                digest.update(block)
        after = path.stat()
    except error_type:
        raise
    except OSError:
        raise error_type() from None
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or size != before.st_size:
        raise error_type()
    return digest.hexdigest(), size


def _journal_bytes(
    stage: Path,
    relative: str,
    *,
    limit: int,
    error_type: _ErrorType,
) -> bytes:
    path = _journal_path(stage, relative, error_type=error_type)
    selected = _bounded_file_bytes(
        path,
        limit=limit,
        missing_ok=False,
        integrity_error_type=error_type,
        limit_error_type=error_type,
    )
    if selected is None:  # pragma: no cover - guarded by missing_ok=False
        raise error_type()
    return selected


def _load_transaction_manifest(
    stage: Path,
    *,
    max_entries: int,
    error_type: _ErrorType,
) -> dict[str, Any] | None:
    path = stage / "manifest.json"
    try:
        payload = _bounded_file_bytes(
            path,
            limit=_manifest_byte_limit(max_entries),
            missing_ok=True,
            integrity_error_type=error_type,
            limit_error_type=error_type,
        )
        if payload is None:
            return None
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise error_type() from None
    if not isinstance(value, dict):
        raise error_type()
    return value


def _validate_transaction_manifest(
    store: InstanceStore,
    stage: Path,
    manifest: dict[str, Any],
    *,
    profile: AtomicCommitProfile,
    error_type: _ErrorType,
) -> None:
    if set(manifest) != {
        "schema_version",
        "transaction_id",
        "kind",
        "status",
        "operation_id",
        "prepared_at",
        "committed_at",
        "entries",
    }:
        raise error_type()
    status = manifest.get("status")
    owner_id = manifest.get("operation_id")
    if (
        manifest.get("schema_version") != ATOMIC_COMMIT_SCHEMA_VERSION
        or manifest.get("transaction_id") != stage.name
        or profile.transaction_pattern.fullmatch(stage.name) is None
        or manifest.get("kind") != profile.kind
        or not isinstance(owner_id, str)
        or not profile.accepts_owner_id(owner_id)
        or status not in {"prepared", "committed"}
        or not isinstance(manifest.get("prepared_at"), str)
        or (status == "prepared" and manifest.get("committed_at") is not None)
        or (status == "committed" and not isinstance(manifest.get("committed_at"), str))
    ):
        raise error_type()
    entries = manifest.get("entries")
    if (
        not isinstance(entries, list)
        or not 1 <= len(entries) <= profile.limits.max_entries
    ):
        raise error_type()
    seen: set[str] = set()
    candidate_refs: set[str] = set()
    preimage_refs: set[str] = set()
    candidate_bytes = 0
    preimage_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "relative",
            "immutable",
            "had_preimage",
            "preimage_ref",
            "preimage_sha256",
            "candidate_ref",
            "candidate_sha256",
        }:
            raise error_type()
        relative = entry.get("relative")
        if not isinstance(relative, str):
            raise error_type()
        _, selected = _instance_target(store, relative, error_type=error_type)
        if selected != relative or relative in seen:
            raise error_type()
        seen.add(relative)
        candidate_ref = entry.get("candidate_ref")
        if (
            type(entry.get("immutable")) is not bool
            or type(entry.get("had_preimage")) is not bool
            or not isinstance(candidate_ref, str)
            or not candidate_ref.startswith("candidates/")
            or _JOURNAL_FILE.fullmatch(candidate_ref) is None
            or candidate_ref in candidate_refs
            or _SHA256.fullmatch(str(entry.get("candidate_sha256"))) is None
        ):
            raise error_type()
        candidate_refs.add(candidate_ref)
        if entry["had_preimage"]:
            preimage_ref = entry.get("preimage_ref")
            if (
                not isinstance(preimage_ref, str)
                or not preimage_ref.startswith("preimages/")
                or _JOURNAL_FILE.fullmatch(preimage_ref) is None
                or preimage_ref in preimage_refs
                or _SHA256.fullmatch(str(entry.get("preimage_sha256"))) is None
            ):
                raise error_type()
            preimage_refs.add(preimage_ref)
            preimage_path = _journal_path(stage, preimage_ref, error_type=error_type)
            digest, size = _bounded_file_digest(
                preimage_path,
                limit=profile.limits.max_entry_bytes,
                error_type=error_type,
            )
            if digest != entry["preimage_sha256"]:
                raise error_type()
            preimage_bytes += size
            if preimage_bytes > profile.limits.max_preimage_bytes:
                raise error_type()
        elif entry.get("preimage_ref") is not None or entry.get(
            "preimage_sha256"
        ) is not None:
            raise error_type()

        candidate_path = _journal_path(stage, candidate_ref, error_type=error_type)
        target, _ = _instance_target(store, relative, error_type=error_type)
        if candidate_path.exists():
            digest, size = _bounded_file_digest(
                candidate_path,
                limit=profile.limits.max_entry_bytes,
                error_type=error_type,
            )
            if digest != entry["candidate_sha256"]:
                raise error_type()
            candidate_bytes += size
        else:
            # os.replace moves a candidate into the live tree. A prepared journal
            # may therefore contain applied candidates, while a recovery callback
            # that failed after rollback may leave the live preimage (or no file)
            # and the journal for a safe retry. Both states are deterministic and
            # rollback is idempotent; committed journals accept only live candidates.
            if target.exists():
                digest, size = _bounded_file_digest(
                    target,
                    limit=profile.limits.max_entry_bytes,
                    error_type=error_type,
                )
                live_candidate = digest == entry["candidate_sha256"]
                live_preimage = bool(
                    status == "prepared"
                    and entry["had_preimage"]
                    and digest == entry["preimage_sha256"]
                )
                if not live_candidate and not live_preimage:
                    raise error_type()
                if live_candidate:
                    candidate_bytes += size
            elif status != "prepared" or entry["had_preimage"]:
                raise error_type()
        if candidate_bytes > profile.limits.max_candidate_bytes:
            raise error_type()
        if candidate_bytes + preimage_bytes > profile.limits.max_journal_payload_bytes:
            raise error_type()


def _rollback_prepared_transaction(
    store: InstanceStore,
    stage: Path,
    manifest: Mapping[str, Any],
    *,
    profile: AtomicCommitProfile,
    error_type: _ErrorType,
) -> None:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise error_type()
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise error_type()
        target, _ = _instance_target(
            store,
            str(entry["relative"]),
            error_type=error_type,
        )
        candidate = _journal_path(
            stage,
            str(entry["candidate_ref"]),
            error_type=error_type,
        )
        candidate_present = candidate.exists()
        if candidate_present:
            digest, _ = _bounded_file_digest(
                candidate,
                limit=profile.limits.max_entry_bytes,
                error_type=error_type,
            )
            if digest != entry["candidate_sha256"]:
                raise error_type()
        if entry["had_preimage"]:
            before = _journal_bytes(
                stage,
                str(entry["preimage_ref"]),
                limit=profile.limits.max_entry_bytes,
                error_type=error_type,
            )
            if hashlib.sha256(before).hexdigest() != entry["preimage_sha256"]:
                raise error_type()
            live_digest, _ = _bounded_file_digest(
                target,
                limit=profile.limits.max_entry_bytes,
                error_type=error_type,
            )
            if live_digest == entry["preimage_sha256"]:
                continue
            if live_digest != entry["candidate_sha256"]:
                if candidate_present:
                    # This entry was not applied. Preserve a concurrent live
                    # change that is unrelated to the transaction.
                    continue
                raise error_type()
            store._atomic_bytes(target, before)
            _fsync_directory(target.parent)
        else:
            existed = target.exists()
            if existed and (not target.is_file() or target.is_symlink()):
                raise error_type()
            if existed:
                digest, _ = _bounded_file_digest(
                    target,
                    limit=profile.limits.max_entry_bytes,
                    error_type=error_type,
                )
                if digest != entry["candidate_sha256"]:
                    if candidate_present:
                        # The candidate was not moved; preserve unrelated state.
                        continue
                    raise error_type()
            target.unlink(missing_ok=True)
            if existed:
                _fsync_directory(target.parent)


def recover_atomic_transactions(
    store: InstanceStore,
    control_root: Path,
    *,
    handlers: Sequence[AtomicRecoveryHandler],
) -> dict[str, Any] | None:
    """Recover all registered transaction profiles before Instance validation."""

    if not handlers:
        raise ValueError("at least one atomic recovery handler is required")
    registrations: dict[str, AtomicRecoveryHandler] = {}
    for handler in handlers:
        key = handler.profile.key
        if key in registrations:
            raise ValueError(f"duplicate atomic recovery profile: {key}")
        registrations[key] = handler
    root = control_root / "transactions"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise AtomicCommitRecoveryError()
    if not root.exists():
        return None
    stages: list[tuple[Path, AtomicRecoveryHandler]] = []
    try:
        for key, handler in registrations.items():
            for stage in root.glob(f"{key}-*"):
                stages.append((stage, handler))
    except OSError:
        raise AtomicCommitRecoveryError() from None
    stages.sort(key=lambda item: item[0].name)
    rolled_back = 0
    committed_cleanups = 0
    profiles: dict[str, dict[str, int]] = {}
    for stage, handler in stages:
        error_type = handler.error_type
        profile = handler.profile
        try:
            if not stage.is_dir() or stage.is_symlink():
                raise error_type()
            manifest = _load_transaction_manifest(
                stage,
                max_entries=profile.limits.max_entries,
                error_type=error_type,
            )
            if manifest is None:
                shutil.rmtree(stage)
                continue
            _validate_transaction_manifest(
                store,
                stage,
                manifest,
                profile=profile,
                error_type=error_type,
            )
            profile_report = profiles.setdefault(
                profile.key,
                {"rolled_back": 0, "committed_cleanups": 0},
            )
            if manifest["status"] == "prepared":
                _rollback_prepared_transaction(
                    store,
                    stage,
                    manifest,
                    profile=profile,
                    error_type=error_type,
                )
                if handler.on_prepared_rollback is not None:
                    handler.on_prepared_rollback(store, str(manifest["operation_id"]))
                rolled_back += 1
                profile_report["rolled_back"] += 1
            else:
                for entry in manifest["entries"]:
                    target, _ = _instance_target(
                        store,
                        str(entry["relative"]),
                        error_type=error_type,
                    )
                    digest, _ = _bounded_file_digest(
                        target,
                        limit=profile.limits.max_entry_bytes,
                        error_type=error_type,
                    )
                    if digest != entry["candidate_sha256"]:
                        raise error_type()
                committed_cleanups += 1
                profile_report["committed_cleanups"] += 1
            shutil.rmtree(stage)
        except error_type:
            raise
        except Exception:
            raise error_type() from None
    try:
        _fsync_directory(root)
    except OSError:
        raise AtomicCommitRecoveryError() from None
    if not rolled_back and not committed_cleanups:
        return None
    return {
        "schema_version": ATOMIC_COMMIT_SCHEMA_VERSION,
        "status": "recovered",
        "rolled_back": rolled_back,
        "committed_cleanups": committed_cleanups,
        "profiles": profiles,
    }


__all__ = [
    "ATOMIC_COMMIT_SCHEMA_VERSION",
    "EMAIL_INTAKE_TRANSACTION_PROFILE",
    "GOOGLE_INTAKE_TRANSACTION_PROFILE",
    "MANUAL_WEB_TRANSACTION_PROFILE",
    "AtomicCommitError",
    "AtomicCommitIntegrityError",
    "AtomicCommitLimitError",
    "AtomicCommitLimits",
    "AtomicCommitProfile",
    "AtomicCommitRecoveryError",
    "AtomicInstanceCommit",
    "AtomicRecoveryHandler",
    "recover_atomic_transactions",
]
