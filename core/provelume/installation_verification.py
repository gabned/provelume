from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import stat
from dataclasses import asdict, dataclass, field
from email.parser import Parser
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from zipfile import BadZipFile, ZipFile

from .release_verification import MANIFEST_FILENAME, verify_release_bundle

RESULT_SCHEMA_VERSION = 1
MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_RECORD_ENTRIES = 20_000
MAX_CORE_FILES = 20_000
MAX_WHEEL_MEMBERS = 20_000
MAX_WHEEL_MEMBER_BYTES = 50 * 1024 * 1024
MAX_WHEEL_TOTAL_BYTES = 250 * 1024 * 1024
MAX_WHEEL_COMPRESSION_RATIO = 250
DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
NORMALIZE_NAME = re.compile(r"[-_.]+")

InstallationStatus = Literal["verified", "modified", "unavailable"]
FindingSeverity = Literal["error", "warning", "info"]
ReleaseWheelStatus = Literal["not_checked", "verified", "modified", "unavailable"]


@dataclass(frozen=True, slots=True)
class InstallationFinding:
    severity: FindingSeverity
    code: str
    message: str
    path: str | None = None


@dataclass(slots=True)
class InstallationVerificationResult:
    status: InstallationStatus
    distribution: str
    installation_root: str | None = None
    record_path: str | None = None
    version: str | None = None
    checked_files: int = 0
    core_files: int = 0
    ignored_generated_files: int = 0
    out_of_scope_entries: int = 0
    release_wheel_status: ReleaseWheelStatus = "not_checked"
    release_version: str | None = None
    release_commit: str | None = None
    matched_release_wheel: str | None = None
    findings: list[InstallationFinding] = field(default_factory=list)
    schema_version: int = RESULT_SCHEMA_VERSION

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["verified"] = self.verified
        return payload


@dataclass(frozen=True, slots=True)
class RecordEntry:
    name: str
    hash_value: str
    size_value: str


@dataclass(frozen=True, slots=True)
class FileIdentity:
    size_bytes: int
    sha256: str


class InstallationUnavailableError(RuntimeError):
    pass


class InstallationModifiedError(RuntimeError):
    pass


def _normalise_distribution_name(value: str) -> str:
    return NORMALIZE_NAME.sub("-", value).casefold()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(path: Path) -> FileIdentity:
    try:
        return FileIdentity(size_bytes=path.stat().st_size, sha256=_sha256_file(path))
    except OSError as exc:
        raise InstallationUnavailableError(f"cannot read installed file: {path}") from exc


def _decode_record_hash(value: str, label: str) -> str:
    try:
        algorithm, encoded = value.split("=", 1)
    except ValueError as exc:
        raise InstallationModifiedError(f"{label} has an invalid RECORD hash") from exc
    if algorithm != "sha256" or not encoded:
        raise InstallationModifiedError(f"{label} does not use a SHA-256 RECORD hash")
    padding = "=" * (-len(encoded) % 4)
    try:
        digest = base64.b64decode(
            encoded + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise InstallationModifiedError(f"{label} has invalid base64url hash data") from exc
    if len(digest) != hashlib.sha256().digest_size:
        raise InstallationModifiedError(f"{label} has an invalid SHA-256 digest length")
    return digest.hex()


def _safe_record_name(value: str, label: str) -> PurePosixPath:
    if not value or "\x00" in value or "\\" in value:
        raise InstallationModifiedError(f"{label} is not a safe RECORD path")
    if DRIVE_PREFIX.match(value):
        raise InstallationModifiedError(f"{label} uses a Windows drive prefix")
    path = PurePosixPath(value)
    if path.is_absolute() or value in {".", ".."}:
        raise InstallationModifiedError(f"{label} is not a relative RECORD path")
    return path


def _read_record_bytes(data: bytes, label: str) -> list[RecordEntry]:
    if len(data) > MAX_RECORD_BYTES:
        raise InstallationModifiedError(
            f"{label} exceeds the {MAX_RECORD_BYTES}-byte safety limit"
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallationModifiedError(f"{label} is not UTF-8") from exc
    rows: list[RecordEntry] = []
    seen: set[str] = set()
    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        for number, row in enumerate(reader, start=1):
            if number > MAX_RECORD_ENTRIES:
                raise InstallationModifiedError(
                    f"{label} exceeds the {MAX_RECORD_ENTRIES}-entry safety limit"
                )
            if len(row) != 3:
                raise InstallationModifiedError(f"{label} row {number} must have 3 fields")
            name, hash_value, size_value = row
            if name in seen:
                raise InstallationModifiedError(f"duplicate {label} path: {name}")
            seen.add(name)
            rows.append(RecordEntry(name, hash_value, size_value))
    except csv.Error as exc:
        raise InstallationModifiedError(f"{label} is not valid CSV: {exc}") from exc
    if not rows:
        raise InstallationModifiedError(f"{label} contains no entries")
    return rows


def _read_record(path: Path) -> list[RecordEntry]:
    if path.is_symlink():
        raise InstallationModifiedError("installed RECORD must not be a symlink")
    if not path.is_file():
        raise InstallationUnavailableError("installed RECORD is missing or not a file")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InstallationUnavailableError("cannot read installed RECORD") from exc
    return _read_record_bytes(data, "installed RECORD")


def _record_candidate(
    root: Path,
    pure_path: PurePosixPath,
    label: str,
) -> tuple[Path, bool]:
    candidate = root.joinpath(*pure_path.parts)
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise InstallationUnavailableError(f"cannot resolve {label}") from exc
    if resolved.is_relative_to(root):
        if ".." in pure_path.parts:
            raise InstallationModifiedError(f"{label} contains a traversal alias")
        return candidate, True
    if ".." in pure_path.parts:
        return candidate, False
    raise InstallationModifiedError(f"{label} escapes the installation root")


def _parse_size(value: str, label: str) -> int:
    if not value:
        raise InstallationUnavailableError(f"{label} has no recorded size")
    try:
        size = int(value)
    except ValueError as exc:
        raise InstallationModifiedError(f"{label} has an invalid recorded size") from exc
    if size < 0:
        raise InstallationModifiedError(f"{label} has a negative recorded size")
    return size


def _is_generated_bytecode(path: PurePosixPath) -> bool:
    return path.suffix == ".pyc" or "__pycache__" in path.parts


def _verify_record_identity(
    path: Path,
    entry: RecordEntry,
    label: str,
) -> FileIdentity:
    if path.is_symlink():
        raise InstallationModifiedError(f"installed file is a symlink: {entry.name}")
    if not path.exists():
        raise InstallationModifiedError(f"installed file is missing: {entry.name}")
    if not path.is_file():
        raise InstallationModifiedError(f"installed path is not a file: {entry.name}")
    expected_size = _parse_size(entry.size_value, label)
    expected_digest = _decode_record_hash(entry.hash_value, label)
    actual = _identity(path)
    if actual.size_bytes != expected_size:
        raise InstallationModifiedError(
            f"installed file size differs from RECORD: {entry.name}"
        )
    if not hmac.compare_digest(actual.sha256, expected_digest):
        raise InstallationModifiedError(
            f"installed file SHA-256 differs from RECORD: {entry.name}"
        )
    return actual


def _metadata_identity(
    root: Path,
    entries: list[RecordEntry],
) -> tuple[Path, RecordEntry]:
    matches: list[tuple[Path, RecordEntry]] = []
    for entry in entries:
        pure = _safe_record_name(entry.name, f"RECORD path {entry.name!r}")
        if not entry.name.endswith(".dist-info/METADATA"):
            continue
        candidate, in_scope = _record_candidate(root, pure, f"RECORD path {entry.name!r}")
        if in_scope:
            matches.append((candidate, entry))
    if len(matches) != 1:
        raise InstallationModifiedError(
            "installed RECORD must contain exactly one in-scope .dist-info/METADATA"
        )
    return matches[0]


def _parse_metadata(
    path: Path,
    expected_distribution: str,
    expected_version: str | None,
) -> str:
    try:
        message = Parser().parsestr(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallationUnavailableError("cannot read installed METADATA") from exc
    name = message.get("Name")
    version = message.get("Version")
    if not name or _normalise_distribution_name(name) != _normalise_distribution_name(
        expected_distribution
    ):
        raise InstallationModifiedError("installed METADATA distribution name is unexpected")
    if not version:
        raise InstallationModifiedError("installed METADATA has no version")
    if expected_version is not None and version != expected_version:
        raise InstallationModifiedError(
            f"installed version {version} does not match expected {expected_version}"
        )
    return version


def _scan_core_tree(root: Path, recorded: set[str]) -> list[str]:
    core = root / "provelume"
    if core.is_symlink():
        raise InstallationModifiedError("installed Provelume Core directory is a symlink")
    if not core.is_dir():
        raise InstallationUnavailableError("installed Provelume Core package directory is missing")

    unexpected: list[str] = []
    scanned = 0
    for current, directory_names, file_names in os.walk(core, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for directory_name in directory_names:
            directory = current_path / directory_name
            if directory.is_symlink():
                relative = directory.relative_to(root).as_posix()
                unexpected.append(relative + "/")
            else:
                retained.append(directory_name)
        directory_names[:] = retained
        for file_name in file_names:
            path = current_path / file_name
            scanned += 1
            if scanned > MAX_CORE_FILES:
                raise InstallationModifiedError(
                    f"installed Core exceeds the {MAX_CORE_FILES}-file safety limit"
                )
            relative = path.relative_to(root).as_posix()
            pure = PurePosixPath(relative)
            if _is_generated_bytecode(pure):
                continue
            if path.is_symlink() or relative not in recorded:
                unexpected.append(relative)
    return sorted(unexpected)


def _wheel_member_name(value: str) -> PurePosixPath:
    if not value or "\x00" in value or "\\" in value or DRIVE_PREFIX.match(value):
        raise InstallationModifiedError(f"wheel contains an unsafe member name: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise InstallationModifiedError(f"wheel contains an unsafe member path: {value!r}")
    return path


def _wheel_symlink(external_attr: int) -> bool:
    mode = (external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


def _wheel_core_identities(path: Path) -> dict[str, FileIdentity]:
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_WHEEL_MEMBERS:
                raise InstallationModifiedError(
                    f"release wheel exceeds the {MAX_WHEEL_MEMBERS}-member safety limit"
                )
            total = sum(info.file_size for info in infos if not info.is_dir())
            if total > MAX_WHEEL_TOTAL_BYTES:
                raise InstallationModifiedError(
                    "release wheel exceeds the total uncompressed-size safety limit"
                )
            names: set[str] = set()
            record_infos = []
            for info in infos:
                pure = _wheel_member_name(info.filename)
                name = pure.as_posix()
                if name in names:
                    raise InstallationModifiedError(f"duplicate release wheel member: {name}")
                names.add(name)
                if _wheel_symlink(info.external_attr):
                    raise InstallationModifiedError(
                        f"release wheel contains a symlink member: {name}"
                    )
                if info.is_dir():
                    continue
                if info.file_size > MAX_WHEEL_MEMBER_BYTES:
                    raise InstallationModifiedError(
                        f"release wheel member exceeds the size limit: {name}"
                    )
                if (
                    info.file_size > 1024 * 1024
                    and info.file_size / max(info.compress_size, 1)
                    > MAX_WHEEL_COMPRESSION_RATIO
                ):
                    raise InstallationModifiedError(
                        f"release wheel member has an unsafe compression ratio: {name}"
                    )
                if name.endswith(".dist-info/RECORD"):
                    record_infos.append(info)
            if len(record_infos) != 1:
                raise InstallationModifiedError(
                    "release wheel must contain exactly one .dist-info/RECORD"
                )
            record_info = record_infos[0]
            rows = _read_record_bytes(
                archive.read(record_info),
                "release wheel RECORD",
            )
            info_by_name = {info.filename: info for info in infos if not info.is_dir()}
            core: dict[str, FileIdentity] = {}
            for entry in rows:
                pure = _wheel_member_name(entry.name)
                name = pure.as_posix()
                if name == record_info.filename:
                    continue
                info = info_by_name.get(name)
                if info is None:
                    raise InstallationModifiedError(
                        f"release wheel RECORD member is missing: {name}"
                    )
                if not entry.hash_value or not entry.size_value:
                    raise InstallationUnavailableError(
                        f"release wheel RECORD cannot verify: {name}"
                    )
                expected_size = _parse_size(entry.size_value, f"wheel RECORD {name}")
                expected_digest = _decode_record_hash(
                    entry.hash_value,
                    f"wheel RECORD {name}",
                )
                data = archive.read(info)
                actual = FileIdentity(
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
                if actual.size_bytes != expected_size or not hmac.compare_digest(
                    actual.sha256,
                    expected_digest,
                ):
                    raise InstallationModifiedError(
                        f"release wheel bytes differ from its RECORD: {name}"
                    )
                if name.startswith("provelume/") and not _is_generated_bytecode(pure):
                    core[name] = actual
            if not core:
                raise InstallationModifiedError(
                    "release wheel RECORD contains no Provelume Core package files"
                )
            return core
    except BadZipFile as exc:
        raise InstallationModifiedError("release wheel is not a valid ZIP archive") from exc
    except OSError as exc:
        raise InstallationUnavailableError("cannot read release wheel") from exc


def _release_wheel(
    bundle: Path,
    version: str,
) -> tuple[Path, str, str]:
    manifest_path = bundle / MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallationUnavailableError("cannot read verified release manifest") from exc
    if not isinstance(manifest, dict):
        raise InstallationModifiedError("verified release manifest is not an object")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise InstallationModifiedError("verified release manifest has no artifact list")
    expected_prefix = f"provelume-{version}-"
    names = [
        row.get("filename")
        for row in artifacts
        if isinstance(row, dict)
        and isinstance(row.get("filename"), str)
        and row["filename"].startswith(expected_prefix)
        and row["filename"].endswith(".whl")
    ]
    if len(names) != 1:
        raise InstallationModifiedError(
            "release manifest must contain exactly one wheel for the installed version"
        )
    wheel = bundle / names[0]
    if wheel.is_symlink() or not wheel.is_file():
        raise InstallationModifiedError("verified release wheel is unavailable or a symlink")
    commit = manifest.get("commit")
    release_version = manifest.get("version")
    if not isinstance(commit, str) or not isinstance(release_version, str):
        raise InstallationModifiedError("verified release manifest identity is incomplete")
    return wheel, release_version, commit


def _add(
    result: InstallationVerificationResult,
    severity: FindingSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> None:
    result.findings.append(
        InstallationFinding(
            severity=severity,
            code=code,
            message=message,
            path=path,
        )
    )


def _record_error(
    result: InstallationVerificationResult,
    exc: InstallationUnavailableError | InstallationModifiedError,
    code: str,
) -> None:
    _add(result, "error", code, str(exc))
    if isinstance(exc, InstallationUnavailableError):
        result.status = "unavailable"
    elif result.status != "unavailable":
        result.status = "modified"


def verify_record_installation(
    installation_root: Path | str,
    record_path: Path | str,
    *,
    distribution_name: str = "provelume",
    expected_version: str | None = None,
    release_bundle: Path | str | None = None,
) -> InstallationVerificationResult:
    result = InstallationVerificationResult(
        status="verified",
        distribution=distribution_name,
        installation_root=str(installation_root),
        record_path=str(record_path),
    )
    try:
        supplied_root = Path(installation_root).expanduser()
        if supplied_root.is_symlink():
            raise InstallationModifiedError("installation root must not be a symlink")
        root = supplied_root.resolve(strict=True)
        if not root.is_dir():
            raise InstallationUnavailableError("installation root is not a directory")
        supplied_record = Path(record_path).expanduser()
        record = supplied_record.resolve(strict=False)
        if not record.is_relative_to(root):
            raise InstallationModifiedError("installed RECORD escapes the installation root")
        entries = _read_record(record)
    except OSError as exc:
        _record_error(
            result,
            InstallationUnavailableError(f"cannot access installed distribution: {exc}"),
            "installation.unavailable",
        )
        return result
    except (InstallationUnavailableError, InstallationModifiedError) as exc:
        _record_error(result, exc, "installation.invalid")
        return result

    result.installation_root = str(root)
    result.record_path = str(record)
    installed: dict[str, FileIdentity] = {}
    core: dict[str, FileIdentity] = {}
    recorded_core: set[str] = set()

    try:
        metadata_path, metadata_entry = _metadata_identity(root, entries)
    except (InstallationUnavailableError, InstallationModifiedError) as exc:
        _record_error(result, exc, "metadata.invalid")
        return result

    for entry in entries:
        try:
            pure = _safe_record_name(entry.name, f"RECORD path {entry.name!r}")
            candidate, in_scope = _record_candidate(
                root,
                pure,
                f"RECORD path {entry.name!r}",
            )
            if not in_scope:
                result.out_of_scope_entries += 1
                continue
            if candidate.resolve(strict=False) == record:
                continue
            if _is_generated_bytecode(pure):
                result.ignored_generated_files += 1
                continue
            if not entry.hash_value or not entry.size_value:
                raise InstallationUnavailableError(
                    f"installed RECORD has no verifiable identity for {entry.name}"
                )
            identity = _verify_record_identity(
                candidate,
                entry,
                f"RECORD entry {entry.name}",
            )
            installed[entry.name] = identity
            result.checked_files += 1
            if entry.name.startswith("provelume/"):
                core[entry.name] = identity
                recorded_core.add(entry.name)
        except (InstallationUnavailableError, InstallationModifiedError) as exc:
            _record_error(result, exc, "record.identity")

    try:
        result.version = _parse_metadata(
            metadata_path,
            distribution_name,
            expected_version,
        )
    except (InstallationUnavailableError, InstallationModifiedError) as exc:
        _record_error(result, exc, "metadata.identity")

    if metadata_entry.name not in installed:
        _record_error(
            result,
            InstallationUnavailableError("installed METADATA identity was not verified"),
            "metadata.unverified",
        )
    if not core:
        _record_error(
            result,
            InstallationUnavailableError(
                "installed RECORD contains no verifiable Provelume Core package files"
            ),
            "core.unavailable",
        )
    else:
        result.core_files = len(core)
        try:
            unexpected = _scan_core_tree(root, recorded_core)
            for path in unexpected:
                _record_error(
                    result,
                    InstallationModifiedError(
                        f"installed Core contains an unrecorded file or symlink: {path}"
                    ),
                    "core.unrecorded",
                )
        except (InstallationUnavailableError, InstallationModifiedError) as exc:
            _record_error(result, exc, "core.scan")

    if result.out_of_scope_entries:
        _add(
            result,
            "warning",
            "record.out_of_scope",
            f"Ignored {result.out_of_scope_entries} generated RECORD entries outside "
            "the installation root.",
        )
    if result.ignored_generated_files:
        _add(
            result,
            "info",
            "record.generated_bytecode",
            f"Ignored {result.ignored_generated_files} generated bytecode entries.",
        )

    if release_bundle is not None:
        bundle_result = verify_release_bundle(release_bundle)
        if bundle_result.status == "unavailable":
            result.release_wheel_status = "unavailable"
            _record_error(
                result,
                InstallationUnavailableError(
                    "release bundle verification material is unavailable"
                ),
                "release_bundle.unavailable",
            )
        elif bundle_result.status != "verified":
            result.release_wheel_status = "modified"
            _record_error(
                result,
                InstallationModifiedError("release bundle did not verify successfully"),
                "release_bundle.invalid",
            )
        elif result.version is not None and core:
            try:
                bundle_root = Path(release_bundle).expanduser().resolve(strict=True)
                wheel, release_version, release_commit = _release_wheel(
                    bundle_root,
                    result.version,
                )
                wheel_core = _wheel_core_identities(wheel)
                if set(core) != set(wheel_core):
                    missing = sorted(set(wheel_core) - set(core))
                    extra = sorted(set(core) - set(wheel_core))
                    details: list[str] = []
                    if missing:
                        details.append("missing: " + ", ".join(missing))
                    if extra:
                        details.append("unexpected: " + ", ".join(extra))
                    raise InstallationModifiedError(
                        "installed Core file inventory differs from release wheel ("
                        + "; ".join(details)
                        + ")"
                    )
                mismatches = [
                    name
                    for name in sorted(core)
                    if core[name] != wheel_core[name]
                ]
                if mismatches:
                    raise InstallationModifiedError(
                        "installed Core bytes differ from release wheel: "
                        + ", ".join(mismatches)
                    )
                result.release_wheel_status = "verified"
                result.release_version = release_version
                result.release_commit = release_commit
                result.matched_release_wheel = wheel.name
            except OSError as exc:
                result.release_wheel_status = "unavailable"
                _record_error(
                    result,
                    InstallationUnavailableError(
                        f"cannot access verified release wheel: {exc}"
                    ),
                    "release_wheel.unavailable",
                )
            except (InstallationUnavailableError, InstallationModifiedError) as exc:
                result.release_wheel_status = (
                    "unavailable"
                    if isinstance(exc, InstallationUnavailableError)
                    else "modified"
                )
                _record_error(result, exc, "release_wheel.invalid")

    if result.status == "verified":
        if result.release_wheel_status == "verified":
            _add(
                result,
                "info",
                "installation.release_match",
                "Installed Core files match both local RECORD metadata and the "
                "verified release wheel.",
            )
            _add(
                result,
                "warning",
                "trust.manifest_signature_not_verified",
                "The release manifest still lacks a detached provider-independent "
                "signature trust check.",
            )
        else:
            _add(
                result,
                "info",
                "installation.record_match",
                "Installed Core files match the local distribution RECORD.",
            )
            _add(
                result,
                "warning",
                "trust.local_record_only",
                "Local RECORD metadata is not an independent trust anchor; provide a "
                "verified release bundle for stronger byte linkage.",
            )
    return result


def verify_installed_distribution(
    distribution_name: str = "provelume",
    *,
    expected_version: str | None = None,
    release_bundle: Path | str | None = None,
) -> InstallationVerificationResult:
    try:
        distribution = metadata.distribution(distribution_name)
    except metadata.PackageNotFoundError:
        result = InstallationVerificationResult(
            status="unavailable",
            distribution=distribution_name,
        )
        _add(
            result,
            "error",
            "distribution.not_found",
            f"Installed distribution was not found: {distribution_name}",
        )
        return result

    files = distribution.files or []
    record_entries = [
        value
        for value in files
        if value.as_posix().endswith(".dist-info/RECORD")
    ]
    if len(record_entries) != 1:
        result = InstallationVerificationResult(
            status="unavailable",
            distribution=distribution_name,
            version=distribution.version,
        )
        _add(
            result,
            "error",
            "distribution.record_unavailable",
            "Installed distribution does not expose exactly one RECORD file.",
        )
        return result

    record_path = Path(distribution.locate_file(record_entries[0]))
    root = record_path.parent.parent
    return verify_record_installation(
        root,
        record_path,
        distribution_name=distribution_name,
        expected_version=expected_version,
        release_bundle=release_bundle,
    )
