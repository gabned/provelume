from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .transcript_contract import (
    TRANSCRIPT_PROFILE_EXTENSIONS,
    ObservedTranscriptBytes,
    TranscriptContractError,
    TranscriptLimits,
    TranscriptSourceConfig,
)


def _file_attributes(value: os.stat_result) -> int:
    return int(getattr(value, "st_file_attributes", 0))


def _reparse(value: os.stat_result) -> bool:
    return bool(_file_attributes(value) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _identity(value: os.stat_result) -> str:
    payload = {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "mode_type": stat.S_IFMT(value.st_mode),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class TranscriptCandidate:
    source_id: str
    locator_sha256: str
    filesystem_identity_sha256: str
    mtime_ns: int
    size_bytes: int
    path: Path = field(repr=False)

    def safe_record(self) -> dict[str, object]:
        return {
            "locator_sha256": self.locator_sha256,
            "filesystem_identity_sha256": self.filesystem_identity_sha256,
            "size_bytes": self.size_bytes,
        }

    def snapshot_record(self) -> dict[str, object]:
        """Private-metadata-free fields plus mtime only inside the snapshot digest."""

        return {**self.safe_record(), "mtime_ns": self.mtime_ns}


@dataclass(frozen=True, slots=True)
class TranscriptSnapshot:
    source_id: str
    profile: str
    selection_kind: str
    config_revision: int
    snapshot_sha256: str
    file_count: int
    total_bytes: int
    candidates: tuple[TranscriptCandidate, ...] = field(repr=False)

    def safe_record(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "profile": self.profile,
            "selection_kind": self.selection_kind,
            "config_revision": self.config_revision,
            "snapshot_sha256": self.snapshot_sha256,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "items": [candidate.safe_record() for candidate in self.candidates],
        }


class LocalTranscriptAdapter:
    """A bounded, non-recursive, read-only local transcript adapter."""

    def __init__(
        self,
        config: TranscriptSourceConfig,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self._monotonic = monotonic

    @staticmethod
    def _regular(value: os.stat_result) -> bool:
        return stat.S_ISREG(value.st_mode) and not _reparse(value)

    def _candidate(
        self, path: Path, locator_seed: str, limits: TranscriptLimits
    ) -> TranscriptCandidate:
        try:
            value = os.lstat(path)
        except FileNotFoundError as exc:
            raise TranscriptContractError(
                "transcript_source_missing", "transcript Source item is missing"
            ) from exc
        except OSError as exc:
            raise TranscriptContractError(
                "transcript_source_unsafe", "transcript Source item cannot be inspected"
            ) from exc
        if not self._regular(value) or stat.S_ISLNK(value.st_mode) or value.st_nlink != 1:
            raise TranscriptContractError(
                "transcript_input_non_regular",
                "transcript Source item is not an independent regular file",
            )
        if path.suffix.casefold() not in TRANSCRIPT_PROFILE_EXTENSIONS[self.config.profile]:
            raise TranscriptContractError(
                "transcript_profile_mismatch",
                "transcript Source item does not match the selected profile",
            )
        if value.st_size > limits.max_file_bytes:
            raise TranscriptContractError(
                "transcript_file_limit_exceeded", "transcript file limit was exceeded"
            )
        locator = hashlib.sha256(
            f"{self.config.source_id}\0{locator_seed}".encode()
        ).hexdigest()
        return TranscriptCandidate(
            source_id=self.config.source_id,
            locator_sha256=locator,
            filesystem_identity_sha256=_identity(value),
            mtime_ns=int(value.st_mtime_ns),
            size_bytes=int(value.st_size),
            path=path,
        )

    def snapshot(self, *, limits: TranscriptLimits) -> TranscriptSnapshot:
        if self.config.selection_kind == "file":
            candidates = [self._candidate(self.config.path, "selected-file", limits)]
        else:
            try:
                before = os.lstat(self.config.path)
                if (
                    not stat.S_ISDIR(before.st_mode)
                    or stat.S_ISLNK(before.st_mode)
                    or _reparse(before)
                ):
                    raise TranscriptContractError(
                        "transcript_source_unsafe", "transcript Source folder is unsafe"
                    )
                entries: list[os.DirEntry[str]] = []
                with os.scandir(self.config.path) as iterator:
                    for entry in iterator:
                        entries.append(entry)
                        if len(entries) > limits.max_enumerated_entries:
                            raise TranscriptContractError(
                                "transcript_enumeration_limit_exceeded",
                                "transcript enumeration limit was exceeded",
                            )
                candidates = []
                for entry in entries:
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise TranscriptContractError(
                            "transcript_source_unsafe",
                            "transcript Source entry cannot be inspected safely",
                        ) from exc
                    if (
                        entry.is_symlink()
                        or _reparse(entry_stat)
                        or not stat.S_ISREG(entry_stat.st_mode)
                    ):
                        raise TranscriptContractError(
                            "transcript_input_non_regular",
                            "transcript Source folder contains a non-regular entry",
                        )
                    candidates.append(self._candidate(Path(entry.path), entry.name, limits))
                after = os.lstat(self.config.path)
                if (
                    _identity(before) != _identity(after)
                    or before.st_mtime_ns != after.st_mtime_ns
                    or before.st_size != after.st_size
                ):
                    raise TranscriptContractError(
                        "transcript_input_changed",
                        "transcript Source folder changed during enumeration",
                    )
            except TranscriptContractError:
                raise
            except FileNotFoundError as exc:
                raise TranscriptContractError(
                    "transcript_source_missing", "transcript Source folder is missing"
                ) from exc
            except OSError as exc:
                raise TranscriptContractError(
                    "transcript_source_unsafe", "transcript Source folder cannot be read safely"
                ) from exc
        if not candidates:
            raise TranscriptContractError(
                "transcript_source_missing", "transcript Source selection contains no files"
            )
        if len(candidates) > limits.max_files_per_job:
            raise TranscriptContractError(
                "transcript_enumeration_limit_exceeded", "transcript file-count limit was exceeded"
            )
        selected = sorted(candidates, key=lambda candidate: candidate.locator_sha256)
        total_bytes = sum(candidate.size_bytes for candidate in selected)
        if total_bytes > limits.max_total_read_bytes or total_bytes > limits.max_temp_bytes_per_job:
            raise TranscriptContractError(
                "transcript_total_read_limit_exceeded",
                "transcript total read limit was exceeded",
            )
        snapshot_items = [candidate.snapshot_record() for candidate in selected]
        digest = hashlib.sha256(
            json.dumps(
                {
                    "source_id": self.config.source_id,
                    "profile": self.config.profile,
                    "selection_kind": self.config.selection_kind,
                    "config_revision": self.config.config_revision,
                    "items": snapshot_items,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return TranscriptSnapshot(
            source_id=self.config.source_id,
            profile=self.config.profile,
            selection_kind=self.config.selection_kind,
            config_revision=self.config.config_revision,
            snapshot_sha256=digest,
            file_count=len(selected),
            total_bytes=total_bytes,
            candidates=tuple(selected),
        )

    @staticmethod
    def _matches(candidate: TranscriptCandidate, value: os.stat_result) -> bool:
        return (
            stat.S_ISREG(value.st_mode)
            and not stat.S_ISLNK(value.st_mode)
            and not _reparse(value)
            and value.st_nlink == 1
            and _identity(value) == candidate.filesystem_identity_sha256
            and int(value.st_mtime_ns) == candidate.mtime_ns
            and int(value.st_size) == candidate.size_bytes
        )

    def assert_unchanged(self, candidate: TranscriptCandidate) -> None:
        try:
            current = os.lstat(candidate.path)
        except OSError as exc:
            raise TranscriptContractError(
                "transcript_input_changed", "transcript Source item changed during intake"
            ) from exc
        if not self._matches(candidate, current):
            raise TranscriptContractError(
                "transcript_input_changed", "transcript Source item changed during intake"
            )

    def read_exact(
        self,
        candidate: TranscriptCandidate,
        *,
        limits: TranscriptLimits,
        deadline: float,
    ) -> ObservedTranscriptBytes:
        self.assert_unchanged(candidate)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate.path, flags)
        except OSError as exc:
            raise TranscriptContractError(
                "transcript_input_changed", "transcript Source item could not be opened safely"
            ) from exc
        try:
            before = os.fstat(descriptor)
            if not self._matches(candidate, before):
                raise TranscriptContractError(
                    "transcript_input_changed", "transcript Source item changed before reading"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                if self._monotonic() > deadline:
                    raise TranscriptContractError(
                        "transcript_timeout", "transcript file read deadline was exceeded"
                    )
                chunk = os.read(descriptor, min(64 * 1024, limits.max_file_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limits.max_file_bytes:
                    raise TranscriptContractError(
                        "transcript_file_limit_exceeded", "transcript file limit was exceeded"
                    )
            after = os.fstat(descriptor)
            if not self._matches(candidate, after):
                raise TranscriptContractError(
                    "transcript_input_changed", "transcript Source item changed while reading"
                )
        finally:
            os.close(descriptor)
        self.assert_unchanged(candidate)
        data = b"".join(chunks)
        if len(data) != candidate.size_bytes:
            raise TranscriptContractError(
                "transcript_input_changed", "transcript Source item changed while reading"
            )
        return ObservedTranscriptBytes(
            source_id=candidate.source_id,
            locator_sha256=candidate.locator_sha256,
            filesystem_identity_sha256=candidate.filesystem_identity_sha256,
            mtime_ns=candidate.mtime_ns,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            data=data,
        )


__all__ = [
    "LocalTranscriptAdapter",
    "TranscriptCandidate",
    "TranscriptSnapshot",
]
