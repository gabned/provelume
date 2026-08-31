from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from .email_contract import (
    EMAIL_CONTRACT_SCHEMA_VERSION,
    ContainerSnapshot,
    EmailAdapterCapability,
    EmailContainerAdapter,
    EmailContractError,
    EmailLimits,
    EmailSourceConfig,
    FilesystemIdentity,
    MessageCandidate,
    ObservedMessageBytes,
    SourceProbe,
    email_adapter_capability,
)

_READ_CHUNK_BYTES = 1024 * 1024
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_PLATFORM = os.name == "nt"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _path_bytes(path: Path) -> bytes:
    return os.fsencode(os.fspath(path))


def _digest_parts(*parts: bytes) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def _file_attributes(value: os.stat_result) -> int:
    return int(getattr(value, "st_file_attributes", 0))


def _is_reparse(value: os.stat_result) -> bool:
    return bool(_file_attributes(value) & _REPARSE_POINT)


def _identity(value: os.stat_result) -> FilesystemIdentity:
    return FilesystemIdentity(
        device=int(value.st_dev),
        inode=int(value.st_ino),
        size_bytes=int(value.st_size),
        mtime_ns=int(value.st_mtime_ns),
        ctime_ns=int(value.st_ctime_ns),
        link_count=int(value.st_nlink),
        file_attributes=_file_attributes(value),
    )


def _assert_path_components_safe(path: Path) -> None:
    for component in [*reversed(path.parents), path]:
        try:
            value = os.lstat(component)
        except FileNotFoundError as exc:
            raise EmailContractError(
                "email_source_missing", "configured email Source is unavailable"
            ) from exc
        except PermissionError as exc:
            raise EmailContractError(
                "email_source_unsafe", "configured email Source is not safely readable"
            ) from exc
        if stat.S_ISLNK(value.st_mode) or _is_reparse(value):
            raise EmailContractError(
                "email_source_unsafe",
                "configured email Source contains a link or reparse point",
            )


def _regular_identity(path: Path) -> FilesystemIdentity:
    _assert_path_components_safe(path)
    try:
        value = os.lstat(path)
    except FileNotFoundError as exc:
        raise EmailContractError(
            "email_source_missing", "configured email input is unavailable"
        ) from exc
    if stat.S_ISLNK(value.st_mode) or _is_reparse(value):
        raise EmailContractError(
            "email_source_unsafe", "email input is a link or reparse point"
        )
    if not stat.S_ISREG(value.st_mode):
        raise EmailContractError(
            "email_input_non_regular", "email input is not a regular file"
        )
    if int(value.st_nlink) != 1:
        raise EmailContractError(
            "email_source_unsafe", "hard-linked email inputs are not supported"
        )
    return _identity(value)


def _directory_identity(path: Path) -> FilesystemIdentity:
    _assert_path_components_safe(path)
    value = os.lstat(path)
    if stat.S_ISLNK(value.st_mode) or _is_reparse(value) or not stat.S_ISDIR(
        value.st_mode
    ):
        raise EmailContractError(
            "email_source_unsafe", "email container directory is unsafe"
        )
    return _identity(value)


def _same_identity(left: FilesystemIdentity, right: FilesystemIdentity) -> bool:
    return left == right


def _same_open_identity(
    opened: FilesystemIdentity, path_identity: FilesystemIdentity
) -> bool:
    common_matches = (
        opened.device == path_identity.device
        and opened.inode == path_identity.inode
        and opened.size_bytes == path_identity.size_bytes
        and opened.mtime_ns == path_identity.mtime_ns
        and opened.link_count == path_identity.link_count
    )
    if _WINDOWS_PLATFORM:
        # CPython's path and handle stat implementations can expose different
        # precision or dummy values for Windows-only metadata.  The file index,
        # device, size, modification time and link count bind the open handle;
        # full path identities are still compared before and after the read.
        return common_matches
    return (
        common_matches
        and opened.ctime_ns == path_identity.ctime_ns
        and opened.file_attributes == path_identity.file_attributes
    )


class _BaseLocalEmailAdapter:
    def __init__(self, config: EmailSourceConfig):
        self.config = config

    def capability(
        self, *, limits: EmailLimits | None = None
    ) -> EmailAdapterCapability:
        return email_adapter_capability(
            self.config.mailbox_format,
            self.config.profile,
            limits=limits,
        )

    def _require_runtime(self, limits: EmailLimits) -> EmailAdapterCapability:
        capability = self.capability(limits=limits)
        if not capability.available:
            code = capability.reason or "email_runtime_unqualified"
            raise EmailContractError(code, "local email capability is unavailable")
        return capability

    def _require_enabled(self) -> None:
        if self.config.state == "disabled":
            raise EmailContractError(
                "email_source_disabled", "email Source is disabled"
            )
        if self.config.state == "paused":
            raise EmailContractError("email_source_paused", "email Source is paused")

    def _container_identity(self) -> str:
        return _digest_parts(
            self.config.source_id.encode("ascii"),
            self.config.mailbox_format.encode("ascii"),
            self.config.profile.encode("ascii"),
            _path_bytes(self.config.path),
        )

    @staticmethod
    def _candidate(
        *,
        config: EmailSourceConfig,
        container_identity: str,
        locator_sha256: str,
        filesystem: FilesystemIdentity,
    ) -> MessageCandidate:
        return MessageCandidate(
            source_id=config.source_id,
            mailbox_format=config.mailbox_format,
            profile=config.profile,
            container_identity_sha256=container_identity,
            snapshot_sha256="0" * 64,
            locator_sha256=locator_sha256,
            filesystem=filesystem,
        )

    def _snapshot_record(
        self,
        *,
        container_identity: str,
        container_rows: list[dict[str, object]],
        candidates: list[MessageCandidate],
        total_bytes: int,
    ) -> ContainerSnapshot:
        payload = {
            "source_id": self.config.source_id,
            "mailbox_format": self.config.mailbox_format,
            "profile": self.config.profile,
            "container_identity_sha256": container_identity,
            "container_rows": container_rows,
            "messages": [
                {
                    "locator_sha256": item.locator_sha256,
                    "filesystem": item.filesystem.as_record(),
                }
                for item in candidates
            ],
        }
        snapshot_sha256 = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        bound = tuple(
            replace(item, snapshot_sha256=snapshot_sha256) for item in candidates
        )
        return ContainerSnapshot(
            schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
            source_id=self.config.source_id,
            mailbox_format=self.config.mailbox_format,
            profile=self.config.profile,
            container_identity_sha256=container_identity,
            snapshot_sha256=snapshot_sha256,
            observed_at=_utc_now(),
            message_count=len(bound),
            total_bytes=total_bytes,
            candidates=bound,
        )

    def _validate_candidate(self, candidate: MessageCandidate) -> None:
        if (
            candidate.source_id != self.config.source_id
            or candidate.mailbox_format != self.config.mailbox_format
            or candidate.profile != self.config.profile
            or candidate.container_identity_sha256 != self._container_identity()
        ):
            raise EmailContractError(
                "email_internal_error", "email candidate binding is invalid"
            )

    @staticmethod
    def _read_path_exact(
        path: Path,
        expected: FilesystemIdentity,
        *,
        limits: EmailLimits,
    ) -> tuple[bytes, FilesystemIdentity]:
        before = _regular_identity(path)
        if not _same_identity(before, expected):
            raise EmailContractError(
                "email_input_changed", "email input changed before it was opened"
            )
        if before.size_bytes > limits.max_message_bytes:
            raise EmailContractError(
                "email_message_limit_exceeded", "email message byte limit was exceeded"
            )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        started = time.monotonic()
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as exc:
            raise EmailContractError(
                "email_input_changed", "email input disappeared before it was opened"
            ) from exc
        except OSError as exc:
            raise EmailContractError(
                "email_source_unsafe", "email input could not be opened safely"
            ) from exc
        data = bytearray()
        try:
            opened = _identity(os.fstat(descriptor))
            if not _same_open_identity(opened, expected):
                raise EmailContractError(
                    "email_input_changed", "email input changed while it was opened"
                )
            while True:
                if time.monotonic() - started > limits.max_seconds_per_message:
                    raise EmailContractError(
                        "email_timeout", "email message read deadline was exceeded"
                    )
                chunk = os.read(descriptor, _READ_CHUNK_BYTES)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limits.max_message_bytes:
                    raise EmailContractError(
                        "email_message_limit_exceeded",
                        "email message byte limit was exceeded",
                    )
            after = _identity(os.fstat(descriptor))
            if not _same_identity(after, opened) or len(data) != expected.size_bytes:
                raise EmailContractError(
                    "email_input_changed", "email input changed during the bounded read"
                )
        finally:
            os.close(descriptor)
        final = _regular_identity(path)
        if not _same_identity(final, expected):
            raise EmailContractError(
                "email_input_changed", "email input changed after the bounded read"
            )
        return bytes(data), final


class EmlFileAdapter(_BaseLocalEmailAdapter):
    """Read one explicitly configured regular EML file without byte translation."""

    def __init__(self, config: EmailSourceConfig):
        if config.mailbox_format != "eml" or config.profile != "eml-file-v1":
            raise EmailContractError(
                "email_profile_unsupported", "EML adapter profile is unsupported"
            )
        super().__init__(config)

    def probe(self) -> SourceProbe:
        capability = self.capability()
        if not capability.available:
            return SourceProbe(
                schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
                source_id=self.config.source_id,
                mailbox_format=self.config.mailbox_format,
                profile=self.config.profile,
                available=False,
                state=capability.state,
                reason=capability.reason,
                container_identity_sha256=None,
            )
        try:
            _regular_identity(self.config.path)
        except EmailContractError as exc:
            return SourceProbe(
                schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
                source_id=self.config.source_id,
                mailbox_format=self.config.mailbox_format,
                profile=self.config.profile,
                available=False,
                state=(
                    "source-missing"
                    if exc.code == "email_source_missing"
                    else "source-unsafe"
                ),
                reason=exc.code,
                container_identity_sha256=None,
            )
        return SourceProbe(
            schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
            source_id=self.config.source_id,
            mailbox_format=self.config.mailbox_format,
            profile=self.config.profile,
            available=True,
            state="ready",
            reason=None,
            container_identity_sha256=self._container_identity(),
        )

    def snapshot(self, *, limits: EmailLimits | None = None) -> ContainerSnapshot:
        selected = limits or EmailLimits()
        self._require_runtime(selected)
        self._require_enabled()
        identity = _regular_identity(self.config.path)
        if identity.size_bytes > selected.max_message_bytes:
            raise EmailContractError(
                "email_message_limit_exceeded", "email message byte limit was exceeded"
            )
        if identity.size_bytes > selected.max_total_read_bytes:
            raise EmailContractError(
                "email_total_read_limit_exceeded", "email run read limit was exceeded"
            )
        container_identity = self._container_identity()
        candidate = self._candidate(
            config=self.config,
            container_identity=container_identity,
            locator_sha256=_digest_parts(b"eml-file-v1", b"message"),
            filesystem=identity,
        )
        return self._snapshot_record(
            container_identity=container_identity,
            container_rows=[{"file": identity.as_record()}],
            candidates=[candidate],
            total_bytes=identity.size_bytes,
        )

    def read_exact(
        self,
        candidate: MessageCandidate,
        *,
        limits: EmailLimits | None = None,
    ) -> ObservedMessageBytes:
        selected = limits or EmailLimits()
        self._require_runtime(selected)
        self._require_enabled()
        self._validate_candidate(candidate)
        if candidate.locator_sha256 != _digest_parts(b"eml-file-v1", b"message"):
            raise EmailContractError(
                "email_internal_error", "EML candidate locator is invalid"
            )
        observed_at = _utc_now()
        data, final = self._read_path_exact(
            self.config.path, candidate.filesystem, limits=selected
        )
        return ObservedMessageBytes(
            source_id=self.config.source_id,
            mailbox_format=self.config.mailbox_format,
            profile=self.config.profile,
            container_identity_sha256=candidate.container_identity_sha256,
            snapshot_sha256=candidate.snapshot_sha256,
            locator_sha256=candidate.locator_sha256,
            filesystem=final,
            observed_at=observed_at,
            acquired_at=_utc_now(),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            data=data,
        )

    def recheck(
        self,
        snapshot: ContainerSnapshot,
        *,
        limits: EmailLimits | None = None,
    ) -> ContainerSnapshot:
        current = self.snapshot(limits=limits)
        if current.snapshot_sha256 != snapshot.snapshot_sha256:
            raise EmailContractError(
                "email_input_changed", "EML Source snapshot changed before promotion"
            )
        return current


class MaildirAdapter(_BaseLocalEmailAdapter):
    """Read a strict cur/new Maildir profile without using ``mailbox.Maildir``."""

    def __init__(self, config: EmailSourceConfig):
        if (
            config.mailbox_format != "maildir"
            or config.profile != "maildir-cur-new-v1"
        ):
            raise EmailContractError(
                "email_profile_unsupported", "Maildir adapter profile is unsupported"
            )
        super().__init__(config)

    def _layout(self) -> dict[str, FilesystemIdentity]:
        identities = {"root": _directory_identity(self.config.path)}
        for name in ("cur", "new", "tmp"):
            identities[name] = _directory_identity(self.config.path / name)
        return identities

    @staticmethod
    def _locator_digest(subdirectory: str, name: str) -> str:
        return _digest_parts(
            b"maildir-cur-new-v1",
            subdirectory.encode("ascii"),
            os.fsencode(name),
        )

    def _scan_locations(
        self,
    ) -> tuple[dict[str, FilesystemIdentity], list[tuple[str, Path, FilesystemIdentity]]]:
        layout = self._layout()
        rows: list[tuple[str, Path, FilesystemIdentity]] = []
        for subdirectory in ("cur", "new"):
            directory = self.config.path / subdirectory
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name)
            except OSError as exc:
                raise EmailContractError(
                    "email_source_unsafe", "Maildir could not be enumerated safely"
                ) from exc
            for entry in entries:
                path = directory / entry.name
                try:
                    value = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise EmailContractError(
                        "email_input_changed", "Maildir entry changed during enumeration"
                    ) from exc
                if stat.S_ISLNK(value.st_mode) or _is_reparse(value):
                    raise EmailContractError(
                        "email_source_unsafe",
                        "Maildir contains a link or reparse point",
                    )
                if not stat.S_ISREG(value.st_mode):
                    raise EmailContractError(
                        "email_input_non_regular",
                        "Maildir contains a non-regular message entry",
                    )
                if int(value.st_nlink) != 1:
                    raise EmailContractError(
                        "email_source_unsafe",
                        "hard-linked Maildir messages are not supported",
                    )
                rows.append(
                    (
                        self._locator_digest(subdirectory, entry.name),
                        path,
                        _identity(value),
                    )
                )
        rows.sort(key=lambda row: row[0])
        return layout, rows

    def probe(self) -> SourceProbe:
        capability = self.capability()
        if not capability.available:
            return SourceProbe(
                schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
                source_id=self.config.source_id,
                mailbox_format=self.config.mailbox_format,
                profile=self.config.profile,
                available=False,
                state=capability.state,
                reason=capability.reason,
                container_identity_sha256=None,
            )
        try:
            self._scan_locations()
        except EmailContractError as exc:
            return SourceProbe(
                schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
                source_id=self.config.source_id,
                mailbox_format=self.config.mailbox_format,
                profile=self.config.profile,
                available=False,
                state=(
                    "source-missing"
                    if exc.code == "email_source_missing"
                    else "source-unsafe"
                ),
                reason=exc.code,
                container_identity_sha256=None,
            )
        return SourceProbe(
            schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
            source_id=self.config.source_id,
            mailbox_format=self.config.mailbox_format,
            profile=self.config.profile,
            available=True,
            state="ready",
            reason=None,
            container_identity_sha256=self._container_identity(),
        )

    def snapshot(self, *, limits: EmailLimits | None = None) -> ContainerSnapshot:
        selected = limits or EmailLimits()
        self._require_runtime(selected)
        self._require_enabled()
        layout, locations = self._scan_locations()
        if len(locations) > selected.max_messages_per_run:
            raise EmailContractError(
                "email_container_limit_exceeded", "Maildir message limit was exceeded"
            )
        total_bytes = sum(item[2].size_bytes for item in locations)
        if total_bytes > selected.max_maildir_container_bytes:
            raise EmailContractError(
                "email_container_limit_exceeded", "Maildir byte limit was exceeded"
            )
        if total_bytes > selected.max_total_read_bytes:
            raise EmailContractError(
                "email_total_read_limit_exceeded", "email run read limit was exceeded"
            )
        if any(
            identity.size_bytes > selected.max_message_bytes
            for _locator, _path, identity in locations
        ):
            raise EmailContractError(
                "email_message_limit_exceeded", "Maildir message byte limit was exceeded"
            )
        container_identity = self._container_identity()
        candidates = [
            self._candidate(
                config=self.config,
                container_identity=container_identity,
                locator_sha256=locator,
                filesystem=identity,
            )
            for locator, _path, identity in locations
        ]
        return self._snapshot_record(
            container_identity=container_identity,
            container_rows=[
                {"name": name, "filesystem": identity.as_record()}
                for name, identity in sorted(layout.items())
                if name in {"cur", "new"}
            ],
            candidates=candidates,
            total_bytes=total_bytes,
        )

    def _resolve_candidate(self, candidate: MessageCandidate) -> Path:
        _layout, locations = self._scan_locations()
        match = next(
            (row for row in locations if row[0] == candidate.locator_sha256), None
        )
        if match is None:
            raise EmailContractError(
                "email_input_changed", "Maildir message is no longer available"
            )
        _locator, path, identity = match
        if not _same_identity(identity, candidate.filesystem):
            raise EmailContractError(
                "email_input_changed", "Maildir message identity changed"
            )
        return path

    def read_exact(
        self,
        candidate: MessageCandidate,
        *,
        limits: EmailLimits | None = None,
    ) -> ObservedMessageBytes:
        selected = limits or EmailLimits()
        self._require_runtime(selected)
        self._require_enabled()
        self._validate_candidate(candidate)
        observed_at = _utc_now()
        path = self._resolve_candidate(candidate)
        data, final = self._read_path_exact(path, candidate.filesystem, limits=selected)
        return ObservedMessageBytes(
            source_id=self.config.source_id,
            mailbox_format=self.config.mailbox_format,
            profile=self.config.profile,
            container_identity_sha256=candidate.container_identity_sha256,
            snapshot_sha256=candidate.snapshot_sha256,
            locator_sha256=candidate.locator_sha256,
            filesystem=final,
            observed_at=observed_at,
            acquired_at=_utc_now(),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            data=data,
        )

    def recheck(
        self,
        snapshot: ContainerSnapshot,
        *,
        limits: EmailLimits | None = None,
    ) -> ContainerSnapshot:
        current = self.snapshot(limits=limits)
        if current.snapshot_sha256 != snapshot.snapshot_sha256:
            raise EmailContractError(
                "email_input_changed", "Maildir snapshot changed before promotion"
            )
        return current


def adapter_for_profile(config: EmailSourceConfig) -> EmailContainerAdapter:
    if config.profile == "eml-file-v1" and config.mailbox_format == "eml":
        return EmlFileAdapter(config)
    if config.profile == "maildir-cur-new-v1" and config.mailbox_format == "maildir":
        return MaildirAdapter(config)
    raise EmailContractError(
        "email_profile_unsupported", "email Source profile is unsupported"
    )


__all__ = ["EmlFileAdapter", "MaildirAdapter", "adapter_for_profile"]
