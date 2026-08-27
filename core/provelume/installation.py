from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import json
import os
import posixpath
import re
import stat
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from email.parser import Parser
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

from .release_bundle import VerificationError, verify_bundle
from .release_wheel import (
    WINDOWS_RESERVED_NAMES,
    ReleaseWheelEvidence,
    WheelVerificationError,
    verify_release_wheel,
)

DISTRIBUTION_NAME = "provelume"
PACKAGE_NAME = "provelume"
MAX_FINDINGS = 200
MAX_PACKAGE_ENTRIES = 20_000
MAX_RECORD_ENTRIES = 20_000
MAX_RECORD_LINE_CHARS = 64 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_HASH_BYTES = 64 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
KNOWN_UNHASHED_METADATA = {"RECORD", "RECORD.jws", "RECORD.p7s"}
IGNORED_DISCOVERED_NAMES = {".DS_Store"}
GENERATED_BYTECODE_SUFFIXES = {".pyc", ".pyo"}
PEP_440_VERSION_PATTERN = re.compile(
    r"""
    v?
    (?:(?P<epoch>[0-9]+)!)?
    (?P<release>[0-9]+(?:\.[0-9]+)*)
    (?P<pre>
        [-_.]?
        (?P<pre_label>alpha|a|beta|b|preview|pre|c|rc)
        [-_.]?
        (?P<pre_number>[0-9]+)?
    )?
    (?P<post>
        (?:-(?P<post_number>[0-9]+))
        |
        (?:
            [-_.]?
            (?P<post_label>post|rev|r)
            [-_.]?
            (?P<post_label_number>[0-9]+)?
        )
    )?
    (?P<dev>
        [-_.]?
        dev
        [-_.]?
        (?P<dev_number>[0-9]+)?
    )?
    (?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?
    """,
    re.ASCII | re.IGNORECASE | re.VERBOSE,
)
HARD_FINDING_ISSUES = frozenset(
    {
        "missing_file",
        "modified_file",
        "unreadable_file",
        "unexpected_file",
        "unsafe_path",
        "unreadable_path",
        "scan_limit",
        "release_file_missing",
        "release_file_modified",
        "release_unexpected_file",
        "bundle_invalid",
        "wheel_invalid",
    }
)
METADATA_FINDING_ISSUES = frozenset(
    {"unhashed_record", "unsupported_hash", "invalid_record"}
)


@dataclass(frozen=True, slots=True)
class RecordEntry:
    path: str
    hash_mode: str | None
    hash_value: str | None
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class InstallationFinding:
    path: str
    issue: str
    detail: str
    expected_sha256: str | None = None
    actual_sha256: str | None = None


@dataclass(slots=True)
class _FindingLog:
    items: list[InstallationFinding] = field(default_factory=list)
    observed_issues: set[str] = field(default_factory=set)
    truncated: bool = False

    def add(self, finding: InstallationFinding) -> None:
        self.observed_issues.add(finding.issue)
        if len(self.items) < MAX_FINDINGS:
            self.items.append(finding)
            return
        self.truncated = True
        if finding.issue not in HARD_FINDING_ISSUES:
            return
        for index in range(len(self.items) - 1, -1, -1):
            if self.items[index].issue not in HARD_FINDING_ISSUES:
                self.items[index] = finding
                return


@dataclass(slots=True)
class _RecordIterationState:
    complete: bool = True


class _HashBudgetExceeded(RuntimeError):
    pass


def _presentation_text(value: str) -> str:
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _sha256_file(path: Path, *, max_bytes: int) -> str:
    if max_bytes < 0:
        raise ValueError("hash byte limit cannot be negative")
    digest = hashlib.sha256()
    bytes_read = 0
    with path.open("rb") as handle:
        while True:
            read_size = min(HASH_CHUNK_BYTES, max_bytes - bytes_read + 1)
            chunk = handle.read(read_size)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > max_bytes:
                raise _HashBudgetExceeded
            digest.update(chunk)
    return digest.hexdigest()


def _expected_sha256(value: str) -> str:
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("invalid urlsafe-base64 SHA-256 value")
    try:
        encoded = value + "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            encoded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("invalid urlsafe-base64 SHA-256 value") from exc
    if len(decoded) != hashlib.sha256().digest_size:
        raise ValueError("invalid SHA-256 digest length")
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise ValueError("noncanonical urlsafe-base64 SHA-256 value")
    return decoded.hex()


def _safe_record_parts(path_value: str) -> tuple[str, ...]:
    if not path_value or "\x00" in path_value:
        raise ValueError("empty or null-containing path")
    normalized = path_value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("absolute or traversal path")
    if any(
        ":" in part
        or part.endswith((" ", "."))
        or part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
        for part in path.parts
    ):
        raise ValueError("Windows-unsafe or drive-prefixed path")
    return tuple(path.parts)


def _is_relevant(parts: tuple[str, ...], package_name: str) -> bool:
    return _is_relevant_component(parts[0], package_name)


def _is_relevant_component(component: str, package_name: str) -> bool:
    first = component.casefold()
    normalized_package = package_name.casefold()
    return first == normalized_package or (
        first.startswith(f"{normalized_package}-") and first.endswith(".dist-info")
    )


def _is_distribution_metadata_component(component: str, package_name: str) -> bool:
    normalized = component.casefold()
    package = package_name.casefold()
    return _is_relevant_component(component, package_name) or (
        normalized == f"{package}.egg-info"
        or (normalized.startswith(f"{package}-") and normalized.endswith(".egg-info"))
    )


def _looks_relevant_record_path(path_value: str, package_name: str) -> bool:
    normalized = path_value.replace("\\", "/")
    lexical = posixpath.normpath(normalized)
    for candidate in (normalized, lexical):
        components = [
            component
            for component in candidate.split("/")
            if component not in {"", "."}
        ]
        if components and _is_relevant_component(components[0], package_name):
            return True
    return False


def _is_known_unhashed_metadata(parts: tuple[str, ...]) -> bool:
    return (
        len(parts) == 2
        and parts[-1] in KNOWN_UNHASHED_METADATA
        and parts[0].casefold().endswith(".dist-info")
    )


def _is_generated_bytecode(parts: tuple[str, ...]) -> bool:
    return (
        len(parts) >= 2
        and parts[-2] == "__pycache__"
        and PurePosixPath(parts[-1]).suffix in GENERATED_BYTECODE_SUFFIXES
    )


def _inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink() or path.is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _has_link_like_component(root: Path, target: Path) -> bool:
    try:
        relative = target.relative_to(root)
    except ValueError:
        return True
    current = root
    for component in relative.parts:
        current /= component
        if _is_link_like(current):
            return True
    return False


def _distribution_metadata_root(
    distribution: metadata.Distribution,
    site_root: Path,
) -> Path:
    raw_metadata_root = getattr(distribution, "_path", None)
    if raw_metadata_root is None:
        raise ValueError("distribution metadata path is unavailable")
    metadata_root = Path(raw_metadata_root)
    if not metadata_root.is_absolute():
        metadata_root = site_root / metadata_root
    try:
        relative_metadata_root = metadata_root.relative_to(site_root)
    except ValueError as exc:
        raise ValueError("distribution metadata escapes the installation root") from exc
    if (
        len(relative_metadata_root.parts) != 1
        or not _is_distribution_metadata_component(
            relative_metadata_root.name,
            PACKAGE_NAME,
        )
    ):
        raise ValueError("distribution metadata directory is not a Provelume metadata root")
    if _has_link_like_component(site_root, metadata_root):
        raise ValueError("distribution metadata root contains a link or reparse point")
    resolved_metadata_root = metadata_root.resolve(strict=False)
    if not _inside(site_root, resolved_metadata_root) or not metadata_root.is_dir():
        raise ValueError("distribution metadata root is unavailable or unsafe")
    return metadata_root


def _distribution_metadata_path(
    metadata_root: Path,
    site_root: Path,
    name: str,
    *,
    required: bool,
) -> Path:
    path = metadata_root / name
    if _has_link_like_component(site_root, path):
        raise ValueError(f"distribution {name} path contains a link or reparse point")
    resolved_path = path.resolve(strict=False)
    if not _inside(site_root, resolved_path):
        raise ValueError(f"distribution {name} path escapes the installation root")
    if required and not path.is_file():
        raise ValueError(f"distribution {name} file is unavailable or unsafe")
    if not required and path.exists() and not path.is_file():
        raise ValueError(f"distribution {name} path is not a regular file")
    return path


def _read_bounded_metadata_text(path: Path, site_root: Path) -> str:
    if _has_link_like_component(site_root, path):
        raise ValueError(f"distribution {path.name} path became unsafe before reading")
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_METADATA_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"distribution {path.name} could not be read safely") from exc
    if len(payload) > MAX_METADATA_BYTES:
        raise ValueError(
            f"distribution {path.name} exceeds the {MAX_METADATA_BYTES}-byte safety limit"
        )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"distribution {path.name} is not valid UTF-8") from exc


def _distribution_version(metadata_path: Path, site_root: Path) -> str:
    message = Parser().parsestr(
        _read_bounded_metadata_text(metadata_path, site_root),
        headersonly=True,
    )
    names = message.get_all("Name", [])
    versions = message.get_all("Version", [])
    if len(names) != 1 or not names[0].strip():
        raise ValueError("installed distribution name is missing or ambiguous")
    normalized_name = re.sub(r"[-_.]+", "-", names[0].strip()).casefold()
    normalized_expected = re.sub(r"[-_.]+", "-", DISTRIBUTION_NAME).casefold()
    if normalized_name != normalized_expected:
        raise ValueError("installed distribution name does not identify Provelume")
    if len(versions) != 1:
        raise ValueError("installed distribution version is missing or ambiguous")
    version = versions[0].strip()
    if PEP_440_VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("installed distribution version is missing or invalid")
    return version


def _raw_record_entries(record_path: Path) -> Iterable[RecordEntry]:
    with record_path.open("r", encoding="utf-8", newline="") as handle:
        for line_number in range(1, MAX_RECORD_ENTRIES + 2):
            line = handle.readline(MAX_RECORD_LINE_CHARS + 1)
            if line == "":
                return
            if line_number > MAX_RECORD_ENTRIES:
                yield RecordEntry(
                    path="<RECORD_LIMIT>",
                    hash_mode=None,
                    hash_value=None,
                    size_bytes=None,
                )
                return
            if len(line) > MAX_RECORD_LINE_CHARS:
                raise ValueError(
                    f"RECORD line {line_number} exceeds the safety limit"
                )
            try:
                row = next(csv.reader([line], strict=True))
            except (csv.Error, StopIteration) as exc:
                raise ValueError(f"RECORD line {line_number} is invalid CSV") from exc
            if len(row) != 3 or not row[0]:
                raise ValueError(f"RECORD line {line_number} must contain three fields")
            path_value, hash_field, size_field = row
            hash_mode: str | None = None
            hash_value: str | None = None
            if hash_field:
                hash_mode, separator, hash_value = hash_field.partition("=")
                if not separator or not hash_mode or not hash_value:
                    raise ValueError(f"RECORD line {line_number} has an invalid hash field")
            size_bytes: int | None = None
            if size_field:
                try:
                    size_bytes = int(size_field)
                except ValueError as exc:
                    raise ValueError(
                        f"RECORD line {line_number} has an invalid size"
                    ) from exc
                if size_bytes < 0:
                    raise ValueError(f"RECORD line {line_number} has a negative size")
            yield RecordEntry(
                path=path_value,
                hash_mode=hash_mode,
                hash_value=hash_value,
                size_bytes=size_bytes,
            )


def _finding(
    findings: _FindingLog,
    *,
    path: str,
    issue: str,
    detail: str,
    expected_sha256: str | None = None,
    actual_sha256: str | None = None,
) -> None:
    findings.add(
        InstallationFinding(
            path=_presentation_text(path),
            issue=issue,
            detail=_presentation_text(detail),
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha256,
        )
    )


def _record_entries_fail_closed(
    entries: Iterable[RecordEntry],
    findings: _FindingLog,
    state: _RecordIterationState,
) -> Iterable[RecordEntry]:
    try:
        yield from entries
    except (csv.Error, OSError, RuntimeError, TypeError, UnicodeError, ValueError) as exc:
        state.complete = False
        _finding(
            findings,
            path="<RECORD>",
            issue="invalid_record",
            detail=f"Wheel RECORD could not be parsed completely: {exc}.",
        )


def _unexpected_package_files(
    site_root: Path,
    package_name: str,
    tracked_package_paths: set[str],
    findings: _FindingLog,
    *,
    record_complete: bool,
    unexpected_issue: str = "unexpected_file",
    unexpected_detail: str = (
        "A package file is present but is not declared by wheel RECORD."
    ),
) -> int:
    package_root = site_root / package_name
    if _is_link_like(package_root):
        _finding(
            findings,
            path=package_name,
            issue="unsafe_path",
            detail="The installed package directory is a link or reparse point.",
        )
        return 1
    if not package_root.exists():
        return 0
    if not package_root.is_dir():
        _finding(
            findings,
            path=package_name,
            issue="unexpected_file",
            detail="The installed package path is not a directory.",
        )
        return 1

    unexpected = 0
    visited = 0

    def record_scan_limit(path: Path) -> None:
        _finding(
            findings,
            path=path.relative_to(site_root).as_posix(),
            issue="scan_limit",
            detail=(
                f"Package scan exceeded the {MAX_PACKAGE_ENTRIES}-entry safety limit."
            ),
        )

    def record_scan_error(error: OSError, scanned_root: Path) -> None:
        nonlocal unexpected
        unexpected += 1
        raw_path = Path(error.filename) if error.filename else scanned_root
        try:
            relative = raw_path.relative_to(site_root).as_posix()
        except ValueError:
            relative = package_name
        _finding(
            findings,
            path=relative,
            issue="unreadable_path",
            detail=f"The package directory could not be scanned completely: {error}.",
        )

    pending_directories = [package_root]
    while pending_directories:
        current_root = pending_directories.pop()
        remaining_budget = MAX_PACKAGE_ENTRIES - visited
        directory_entries: list[os.DirEntry[str]] = []
        limit_exceeded = False
        scan_failed = False
        try:
            with os.scandir(current_root) as iterator:
                for entry in iterator:
                    if len(directory_entries) >= remaining_budget:
                        limit_exceeded = True
                        break
                    directory_entries.append(entry)
        except OSError as exc:
            record_scan_error(exc, current_root)
            scan_failed = True
        if scan_failed:
            continue
        if limit_exceeded:
            record_scan_limit(current_root)
            return unexpected + 1

        child_directories: list[Path] = []
        for entry in sorted(directory_entries, key=lambda item: item.name):
            visited += 1
            path = Path(entry.path)
            relative = path.relative_to(site_root).as_posix()
            if _is_link_like(path):
                unexpected += 1
                _finding(
                    findings,
                    path=relative,
                    issue="unsafe_path",
                    detail="A link-like or reparse-point entry exists inside the package.",
                )
                continue
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
                is_regular_file = entry.is_file(follow_symlinks=False)
            except OSError as exc:
                unexpected += 1
                _finding(
                    findings,
                    path=relative,
                    issue="unreadable_path",
                    detail=f"The package entry could not be inspected safely: {exc}.",
                )
                continue
            if is_directory:
                child_directories.append(path)
                continue
            if not is_regular_file:
                unexpected += 1
                _finding(
                    findings,
                    path=relative,
                    issue="unsafe_path",
                    detail="A non-regular filesystem entry exists inside the package.",
                )
                continue
            relative_parts = tuple(PurePosixPath(relative).parts)
            if (
                entry.name in IGNORED_DISCOVERED_NAMES
                or _is_generated_bytecode(relative_parts)
            ):
                continue
            if record_complete and relative not in tracked_package_paths:
                unexpected += 1
                _finding(
                    findings,
                    path=relative,
                    issue=unexpected_issue,
                    detail=unexpected_detail,
                )
        pending_directories.extend(reversed(child_directories))
    return unexpected


def _unavailable_result(
    *,
    version: str | None,
    reason: str,
    editable: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "verification_unavailable",
        "package": {
            "distribution": DISTRIBUTION_NAME,
            "version": version,
            "editable": editable,
        },
        "integrity": {
            "verified": False,
            "checked_files": 0,
            "tracked_files": 0,
            "unhashed_files": 0,
            "unexpected_files": 0,
        },
        "origin": {
            "status": "not_established",
            "detail": (
                "Local package metadata cannot authenticate official Provelume origin. "
                "Use a trusted release manifest or signature when available."
            ),
        },
        "network_used": False,
        "reason": _presentation_text(reason),
        "findings": [],
        "findings_truncated": False,
    }


def verify_recorded_installation(
    site_root: Path | str,
    entries: Iterable[RecordEntry],
    *,
    version: str,
    package_name: str = PACKAGE_NAME,
    distribution_name: str = DISTRIBUTION_NAME,
    editable: bool = False,
) -> dict[str, Any]:
    """Verify installed package bytes from a synthetic or PEP 376 RECORD view."""

    if editable:
        return _unavailable_result(
            version=version,
            editable=True,
            reason=(
                "Editable installations reference a working tree rather than immutable "
                "wheel payload bytes."
            ),
        )

    root = Path(site_root).expanduser().resolve()
    if not root.is_dir():
        return _unavailable_result(
            version=version,
            reason="The distribution installation root is unavailable.",
        )

    findings = _FindingLog()
    tracked_package_paths: set[str] = set()
    tracked_files = 0
    checked_files = 0
    unhashed_files = 0
    relevant_entries = 0
    hashed_package_files = 0
    hashed_bytes_reserved = 0
    record_entries_seen = 0
    processed_record_paths: set[str] = set()
    record_state = _RecordIterationState()

    normalized_package = package_name.casefold()
    for entry in _record_entries_fail_closed(entries, findings, record_state):
        record_entries_seen += 1
        if record_entries_seen > MAX_RECORD_ENTRIES:
            record_state.complete = False
            _finding(
                findings,
                path="<RECORD>",
                issue="scan_limit",
                detail=(
                    "Wheel RECORD exceeded the "
                    f"{MAX_RECORD_ENTRIES}-entry safety limit."
                ),
            )
            break
        if not _looks_relevant_record_path(entry.path, package_name):
            continue
        try:
            parts = _safe_record_parts(entry.path)
        except ValueError as exc:
            _finding(
                findings,
                path=entry.path or "<empty>",
                issue="unsafe_path",
                detail=f"RECORD contains an unsafe path: {exc}.",
            )
            continue
        if not _is_relevant(parts, package_name):
            continue
        if _is_generated_bytecode(parts):
            continue
        relevant_entries += 1
        relative = PurePosixPath(*parts).as_posix()
        record_identity = os.path.normcase(relative)
        if record_identity in processed_record_paths:
            _finding(
                findings,
                path=relative,
                issue="invalid_record",
                detail="Wheel RECORD contains a duplicate relevant path.",
            )
            continue
        processed_record_paths.add(record_identity)
        is_package_entry = parts[0].casefold() == normalized_package
        if is_package_entry:
            tracked_package_paths.add(relative)
            if entry.hash_mode and entry.hash_value:
                try:
                    _expected_sha256(entry.hash_value)
                except ValueError:
                    pass
                else:
                    if entry.hash_mode.casefold() == "sha256":
                        hashed_package_files += 1
        target = root.joinpath(*parts)
        if _has_link_like_component(root, target):
            _finding(
                findings,
                path=relative,
                issue="unsafe_path",
                detail=(
                    "The installed path escapes the distribution root or contains a "
                    "link/reparse point."
                ),
            )
            continue
        try:
            resolved_target = target.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            _finding(
                findings,
                path=relative,
                issue="unsafe_path",
                detail=f"The installed path could not be resolved safely: {exc}.",
            )
            continue
        if not _inside(root, resolved_target):
            _finding(
                findings,
                path=relative,
                issue="unsafe_path",
                detail="The installed path escapes the distribution root or is a symlink.",
            )
            continue

        target_is_file = target.is_file()
        expected_sha256: str | None = None
        hash_usable = False
        if not entry.hash_mode or not entry.hash_value:
            if not _is_known_unhashed_metadata(parts):
                unhashed_files += 1
                _finding(
                    findings,
                    path=relative,
                    issue="unhashed_record",
                    detail="RECORD does not provide a cryptographic hash for this file.",
                )
        elif entry.hash_mode.casefold() != "sha256":
            unhashed_files += 1
            _finding(
                findings,
                path=relative,
                issue="unsupported_hash",
                detail=f"Unsupported RECORD hash algorithm: {entry.hash_mode}.",
            )
        else:
            tracked_files += 1
            try:
                expected_sha256 = _expected_sha256(entry.hash_value)
            except ValueError as exc:
                _finding(
                    findings,
                    path=relative,
                    issue="invalid_record",
                    detail=f"Invalid RECORD hash: {exc}.",
                )
            else:
                hash_usable = True
        if not target_is_file:
            _finding(
                findings,
                path=relative,
                issue="missing_file",
                detail="A file declared by wheel RECORD is missing.",
                expected_sha256=expected_sha256,
            )
            continue
        try:
            actual_size = target.stat().st_size
        except OSError as exc:
            _finding(
                findings,
                path=relative,
                issue="unreadable_file",
                detail=f"The installed file metadata could not be read: {exc}.",
                expected_sha256=expected_sha256,
            )
            continue
        if entry.size_bytes is not None and actual_size != entry.size_bytes:
            _finding(
                findings,
                path=relative,
                issue="modified_file",
                detail="The installed file size differs from wheel RECORD.",
                expected_sha256=expected_sha256,
            )
            continue
        if not hash_usable:
            continue
        remaining_hash_bytes = MAX_HASH_BYTES - hashed_bytes_reserved
        if actual_size > remaining_hash_bytes:
            _finding(
                findings,
                path=relative,
                issue="scan_limit",
                detail=(
                    "Hashing installed payloads would exceed the cumulative "
                    f"{MAX_HASH_BYTES}-byte safety limit."
                ),
                expected_sha256=expected_sha256,
            )
            continue
        hashed_bytes_reserved += actual_size
        try:
            actual_sha256 = _sha256_file(target, max_bytes=actual_size)
        except _HashBudgetExceeded:
            hashed_bytes_reserved = MAX_HASH_BYTES
            _finding(
                findings,
                path=relative,
                issue="scan_limit",
                detail=(
                    "The installed file grew beyond its inspected size while hashing "
                    f"under the {MAX_HASH_BYTES}-byte safety limit."
                ),
                expected_sha256=expected_sha256,
            )
            continue
        except OSError as exc:
            _finding(
                findings,
                path=relative,
                issue="unreadable_file",
                detail=f"The installed file could not be read: {exc}.",
                expected_sha256=expected_sha256,
            )
            continue
        checked_files += 1
        if actual_sha256 != expected_sha256:
            _finding(
                findings,
                path=relative,
                issue="modified_file",
                detail="The installed file SHA-256 differs from wheel RECORD.",
                expected_sha256=expected_sha256,
                actual_sha256=actual_sha256,
            )

    unexpected_files = _unexpected_package_files(
        root,
        package_name,
        tracked_package_paths,
        findings,
        record_complete=record_state.complete,
    )
    missing_package_evidence = (
        relevant_entries == 0 or tracked_files == 0 or hashed_package_files == 0
    )
    has_hard_issue = bool(findings.observed_issues & HARD_FINDING_ISSUES)
    metadata_incomplete = missing_package_evidence or bool(
        findings.observed_issues & METADATA_FINDING_ISSUES
    )
    if has_hard_issue:
        status = "modified_installation"
    elif metadata_incomplete:
        status = "verification_unavailable"
    else:
        status = "package_integrity_verified"

    return {
        "schema_version": 1,
        "status": status,
        "package": {
            "distribution": distribution_name,
            "version": version,
            "editable": False,
        },
        "integrity": {
            "verified": status == "package_integrity_verified",
            "checked_files": checked_files,
            "tracked_files": tracked_files,
            "unhashed_files": unhashed_files,
            "unexpected_files": unexpected_files,
        },
        "origin": {
            "status": "not_established",
            "detail": (
                "Matching wheel RECORD proves local package-byte integrity, not that the "
                "wheel was an official Provelume release."
            ),
        },
        "network_used": False,
        "reason": (
            "All hashed package files match wheel RECORD."
            if status == "package_integrity_verified"
            else (
                "Installed package files differ from wheel RECORD."
                if status == "modified_installation"
                else (
                    "No hashed Provelume package files were available in wheel RECORD."
                    if missing_package_evidence
                    else "Package metadata is insufficient for a complete integrity result."
                )
            )
        ),
        "findings": [asdict(finding) for finding in findings.items],
        "findings_truncated": findings.truncated,
    }


def _editable_installation(direct_url_path: Path, site_root: Path) -> bool:
    if not direct_url_path.exists():
        return False
    value = _read_bounded_metadata_text(direct_url_path, site_root)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("direct_url.json is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("direct_url.json must contain an object")
    directory_info = payload.get("dir_info")
    if directory_info is None:
        return False
    if not isinstance(directory_info, dict):
        raise ValueError("direct_url.json dir_info must contain an object")
    editable = directory_info.get("editable", False)
    if not isinstance(editable, bool):
        raise ValueError("direct_url.json editable must be a boolean")
    return editable


def _finding_log_from_result(result: dict[str, Any]) -> _FindingLog:
    findings = _FindingLog()
    for row in result.get("findings", []):
        if not isinstance(row, dict):
            continue
        findings.add(
            InstallationFinding(
                path=str(row.get("path", "<unknown>")),
                issue=str(row.get("issue", "invalid_record")),
                detail=str(row.get("detail", "Verification finding.")),
                expected_sha256=(
                    str(row["expected_sha256"])
                    if row.get("expected_sha256") is not None
                    else None
                ),
                actual_sha256=(
                    str(row["actual_sha256"])
                    if row.get("actual_sha256") is not None
                    else None
                ),
            )
        )
    findings.truncated = bool(result.get("findings_truncated")) or findings.truncated
    return findings


def _release_linkage_stub(*, status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "verified": False,
        "bundle": None,
        "wheel": None,
        "checked_files": 0,
        "unexpected_files": 0,
        "reason": _presentation_text(reason),
    }


def _release_linkage_not_run(
    result: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    linked = dict(result)
    linked["release_linkage"] = _release_linkage_stub(
        status="verification_unavailable",
        reason=reason,
    )
    return linked


def _release_linkage_failure(
    result: dict[str, Any],
    *,
    status: str,
    issue: str,
    reason: str,
) -> dict[str, Any]:
    linked = dict(result)
    linked["integrity"] = dict(result["integrity"])
    findings = _finding_log_from_result(result)
    _finding(
        findings,
        path="<RELEASE_BUNDLE>",
        issue=issue,
        detail=reason,
    )
    if linked["status"] != "modified_installation":
        linked["status"] = "verification_unavailable"
        linked["integrity"]["verified"] = False
        linked["reason"] = _presentation_text(reason)
    linked["origin"] = {
        "status": "not_established",
        "detail": (
            "The supplied release evidence could not be linked safely to the installed "
            "package bytes."
        ),
    }
    linked["findings"] = [asdict(finding) for finding in findings.items]
    linked["findings_truncated"] = findings.truncated
    linked["release_linkage"] = _release_linkage_stub(status=status, reason=reason)
    return linked


def _bundle_summary(bundle_result: dict[str, object]) -> dict[str, Any]:
    anchored = (
        bundle_result.get("origin_authentication")
        == "trusted_release_manifest_sha256"
    )
    return {
        "verification": bundle_result.get("result"),
        "version": bundle_result.get("version"),
        "tag": bundle_result.get("tag"),
        "source_commit": bundle_result.get("source_commit"),
        "release_manifest_sha256": bundle_result.get("release_manifest_sha256"),
        "externally_anchored": anchored,
    }


def _wheel_summary(evidence: ReleaseWheelEvidence) -> dict[str, Any]:
    return {
        "name": evidence.name,
        "sha256": evidence.sha256,
        "size_bytes": evidence.size_bytes,
        "checked_members": evidence.checked_members,
        "package_files": len(evidence.package_files),
    }


def _compare_installed_package_to_release_wheel(
    site_root: Path,
    evidence: ReleaseWheelEvidence,
) -> tuple[_FindingLog, int, int, str]:
    findings = _FindingLog()
    checked_files = 0
    hashed_bytes_reserved = 0
    tracked_paths = {item.path for item in evidence.package_files}
    for item in evidence.package_files:
        parts = _safe_record_parts(item.path)
        target = site_root.joinpath(*parts)
        if _has_link_like_component(site_root, target):
            _finding(
                findings,
                path=item.path,
                issue="unsafe_path",
                detail=(
                    "The installed path contains a link/reparse point while comparing "
                    "it with the release wheel."
                ),
                expected_sha256=item.sha256,
            )
            continue
        try:
            resolved_target = target.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            _finding(
                findings,
                path=item.path,
                issue="unsafe_path",
                detail=f"The installed path could not be resolved safely: {exc}.",
                expected_sha256=item.sha256,
            )
            continue
        if not _inside(site_root, resolved_target):
            _finding(
                findings,
                path=item.path,
                issue="unsafe_path",
                detail="The installed path escapes the distribution root.",
                expected_sha256=item.sha256,
            )
            continue
        if not target.is_file():
            _finding(
                findings,
                path=item.path,
                issue="release_file_missing",
                detail="A Core package file declared by the release wheel is missing.",
                expected_sha256=item.sha256,
            )
            continue
        try:
            actual_size = target.stat().st_size
        except OSError as exc:
            _finding(
                findings,
                path=item.path,
                issue="unreadable_file",
                detail=f"The installed file metadata could not be read: {exc}.",
                expected_sha256=item.sha256,
            )
            continue
        if actual_size != item.size_bytes:
            _finding(
                findings,
                path=item.path,
                issue="release_file_modified",
                detail="The installed file size differs from the release wheel.",
                expected_sha256=item.sha256,
            )
            continue
        remaining_hash_bytes = MAX_HASH_BYTES - hashed_bytes_reserved
        if actual_size > remaining_hash_bytes:
            _finding(
                findings,
                path=item.path,
                issue="scan_limit",
                detail=(
                    "Comparing installed files with the release wheel would exceed the "
                    f"cumulative {MAX_HASH_BYTES}-byte safety limit."
                ),
                expected_sha256=item.sha256,
            )
            continue
        hashed_bytes_reserved += actual_size
        try:
            actual_sha256 = _sha256_file(target, max_bytes=actual_size)
        except _HashBudgetExceeded:
            hashed_bytes_reserved = MAX_HASH_BYTES
            _finding(
                findings,
                path=item.path,
                issue="scan_limit",
                detail="The installed file grew while it was compared with the release wheel.",
                expected_sha256=item.sha256,
            )
            continue
        except OSError as exc:
            _finding(
                findings,
                path=item.path,
                issue="unreadable_file",
                detail=f"The installed file could not be read: {exc}.",
                expected_sha256=item.sha256,
            )
            continue
        checked_files += 1
        if actual_sha256 != item.sha256:
            _finding(
                findings,
                path=item.path,
                issue="release_file_modified",
                detail="The installed file SHA-256 differs from the release wheel.",
                expected_sha256=item.sha256,
                actual_sha256=actual_sha256,
            )

    unexpected_files = _unexpected_package_files(
        site_root,
        PACKAGE_NAME,
        tracked_paths,
        findings,
        record_complete=True,
        unexpected_issue="release_unexpected_file",
        unexpected_detail=(
            "A Core package file is installed but is not present in the release wheel."
        ),
    )
    definite_difference = bool(
        findings.observed_issues
        & {
            "release_file_missing",
            "release_file_modified",
            "release_unexpected_file",
        }
    )
    if definite_difference:
        status = "installed_bytes_differ"
    elif findings.observed_issues:
        status = "verification_unavailable"
    else:
        status = "verified"
    return findings, checked_files, unexpected_files, status


def _apply_release_linkage(
    result: dict[str, Any],
    *,
    site_root: Path,
    bundle_result: dict[str, object],
    wheel_evidence: ReleaseWheelEvidence,
) -> dict[str, Any]:
    release_findings, checked_files, unexpected_files, linkage_status = (
        _compare_installed_package_to_release_wheel(site_root, wheel_evidence)
    )
    linked = dict(result)
    linked["integrity"] = dict(result["integrity"])
    findings = _finding_log_from_result(result)
    for finding in release_findings.items:
        findings.add(finding)
    findings.truncated = (
        findings.truncated
        or release_findings.truncated
        or bool(result.get("findings_truncated"))
    )
    linked["findings"] = [asdict(finding) for finding in findings.items]
    linked["findings_truncated"] = findings.truncated
    linked["release_linkage"] = {
        "status": linkage_status,
        "verified": linkage_status == "verified",
        "bundle": _bundle_summary(bundle_result),
        "wheel": _wheel_summary(wheel_evidence),
        "checked_files": checked_files,
        "unexpected_files": unexpected_files,
        "reason": (
            "Installed Core package bytes match the verified release wheel."
            if linkage_status == "verified"
            else (
                "Installed Core package bytes differ from the verified release wheel."
                if linkage_status == "installed_bytes_differ"
                else (
                    "Installed Core package bytes could not be compared completely and "
                    "safely with the verified release wheel."
                )
            )
        ),
    }
    if linkage_status == "installed_bytes_differ":
        linked["status"] = "modified_installation"
        linked["integrity"]["verified"] = False
        linked["reason"] = (
            "Installed package files differ from the verified release wheel."
        )
    elif linkage_status == "verification_unavailable":
        if linked["status"] != "modified_installation":
            linked["status"] = "verification_unavailable"
            linked["integrity"]["verified"] = False
            linked["reason"] = (
                "Release-wheel linkage could not be verified completely and safely."
            )

    anchored = bool(linked["release_linkage"]["bundle"]["externally_anchored"])
    if linkage_status == "verified" and linked["status"] == "package_integrity_verified":
        if anchored:
            linked["origin"] = {
                "status": "trusted_manifest_sha256_matched",
                "detail": (
                    "The verified release bundle matches the operator-supplied manifest "
                    "SHA-256, and installed Core package bytes match that bundle's wheel. "
                    "This result depends on the trust placed in the independent source of "
                    "that hash."
                ),
            }
        else:
            linked["origin"] = {
                "status": "not_established",
                "detail": (
                    "Installed Core package bytes match a self-consistent release bundle, "
                    "but the bundle alone cannot authenticate its publisher."
                ),
            }
        linked["reason"] = (
            "Installed package bytes match wheel RECORD and the verified release wheel."
        )
    else:
        linked["origin"] = {
            "status": "not_established",
            "detail": (
                "Release evidence did not establish a complete trusted link to the "
                "installed Core package bytes."
            ),
        }
    return linked


def verify_current_installation(
    *,
    release_bundle: Path | str | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify the imported distribution and optional local release evidence offline."""

    if isinstance(release_bundle, str) and not release_bundle.strip():
        release_bundle = None
    if isinstance(expected_manifest_sha256, str):
        expected_manifest_sha256 = expected_manifest_sha256.strip() or None
    linkage_requested = (
        release_bundle is not None or expected_manifest_sha256 is not None
    )

    def unavailable(result: dict[str, Any]) -> dict[str, Any]:
        if not linkage_requested:
            return result
        return _release_linkage_not_run(
            result,
            reason=(
                "Release linkage was not attempted because the installed distribution "
                "could not be inspected safely."
            ),
        )

    try:
        distribution = metadata.distribution(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return unavailable(
            _unavailable_result(
                version=None,
                reason=(
                    "The Provelume distribution is not installed in this Python "
                    "environment."
                ),
            )
        )
    except (AttributeError, OSError, ValueError, TypeError, RuntimeError) as exc:
        return unavailable(
            _unavailable_result(
                version=None,
                reason=f"Installation metadata could not be verified safely: {exc}.",
            )
        )
    version: str | None = None
    try:
        site_root = Path(distribution.locate_file("")).expanduser().resolve()
        imported_package_root = Path(__file__).resolve().parent
        distribution_package_root = (site_root / PACKAGE_NAME).resolve()
        if imported_package_root != distribution_package_root:
            return unavailable(
                _unavailable_result(
                    version=version,
                    reason=(
                        "The imported Provelume package tree does not match the "
                        "installed distribution selected for verification."
                    ),
                )
            )
        metadata_root = _distribution_metadata_root(distribution, site_root)
        metadata_path = _distribution_metadata_path(
            metadata_root,
            site_root,
            "METADATA",
            required=True,
        )
        direct_url_path = _distribution_metadata_path(
            metadata_root,
            site_root,
            "direct_url.json",
            required=False,
        )
        version = _distribution_version(metadata_path, site_root)
        editable = _editable_installation(direct_url_path, site_root)
        if editable:
            return unavailable(
                _unavailable_result(
                    version=version,
                    editable=True,
                    reason=(
                        "Editable installations reference a working tree rather than "
                        "immutable wheel payload bytes."
                    ),
                )
            )
        if not _is_relevant_component(metadata_root.name, PACKAGE_NAME):
            raise ValueError("distribution metadata directory is not a Provelume dist-info")
        record_path = _distribution_metadata_path(
            metadata_root,
            site_root,
            "RECORD",
            required=True,
        )
        result = verify_recorded_installation(
            site_root,
            _raw_record_entries(record_path),
            version=version,
        )
        if not linkage_requested:
            return result
        if release_bundle is None:
            return _release_linkage_failure(
                result,
                status="bundle_invalid",
                issue="bundle_invalid",
                reason=(
                    "An expected manifest SHA-256 can be used only with an explicit local "
                    "release bundle."
                ),
            )
        if expected_manifest_sha256 is not None and re.fullmatch(
            r"[0-9a-fA-F]{64}", expected_manifest_sha256
        ) is None:
            return _release_linkage_failure(
                result,
                status="bundle_invalid",
                issue="bundle_invalid",
                reason="The expected release-manifest SHA-256 is invalid.",
            )
        try:
            bundle_result = verify_bundle(
                Path(release_bundle),
                expected_manifest_sha256=expected_manifest_sha256,
                expected_version=version,
                expected_tag=f"v{version}",
            )
        except OSError:
            return _release_linkage_failure(
                result,
                status="bundle_invalid",
                issue="bundle_invalid",
                reason="Release bundle verification failed because it could not be read safely.",
            )
        except VerificationError as exc:
            return _release_linkage_failure(
                result,
                status="bundle_invalid",
                issue="bundle_invalid",
                reason=f"Release bundle verification failed: {exc}.",
            )
        try:
            wheel_evidence = verify_release_wheel(
                release_bundle,
                bundle_result,
                expected_version=version,
            )
        except (OSError, WheelVerificationError) as exc:
            return _release_linkage_failure(
                result,
                status="wheel_invalid",
                issue="wheel_invalid",
                reason=f"Release wheel verification failed: {exc}.",
            )
        return _apply_release_linkage(
            result,
            site_root=site_root,
            bundle_result=bundle_result,
            wheel_evidence=wheel_evidence,
        )
    except (AttributeError, OSError, ValueError, TypeError, RuntimeError) as exc:
        return unavailable(
            _unavailable_result(
                version=version,
                reason=f"Installation metadata could not be verified safely: {exc}.",
            )
        )
