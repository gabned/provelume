from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import re
import stat
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any

MAX_WHEEL_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_WHEEL_MEMBERS = 20_000
MAX_WHEEL_NAME_CHARS = 1024
MAX_WHEEL_MEMBER_BYTES = 64 * 1024 * 1024
MAX_WHEEL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_WHEEL_RECORD_BYTES = 2 * 1024 * 1024
MAX_WHEEL_RECORD_LINE_CHARS = 64 * 1024
MAX_WHEEL_METADATA_BYTES = 1024 * 1024
MAX_WHEEL_COMPRESSION_RATIO = 200
HASH_CHUNK_BYTES = 1024 * 1024
KNOWN_UNHASHED_WHEEL_MEMBERS = {"RECORD", "RECORD.jws", "RECORD.p7s"}
WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class WheelVerificationError(RuntimeError):
    """Raised when a candidate release wheel is unsafe or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class WheelPackageFile:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ReleaseWheelEvidence:
    name: str
    sha256: str
    size_bytes: int
    dist_info: str
    checked_members: int
    package_files: tuple[WheelPackageFile, ...]


@dataclass(frozen=True, slots=True)
class _WheelIdentity:
    name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _WheelRecordEntry:
    path: str
    hash_mode: str | None
    hash_value: str | None
    size_bytes: int | None


def _normalize_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).strip("-").casefold()


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink() or path.is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _safe_flat_name(value: Any) -> str:
    name = str(value or "")
    if (
        not name
        or len(name) > 255
        or name != name.strip()
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]*", name) is None
    ):
        raise WheelVerificationError("release wheel identity has an unsafe filename")
    return name


def _identity_from_row(row: Any) -> _WheelIdentity:
    if not isinstance(row, dict):
        raise WheelVerificationError("release bundle has an invalid package identity")
    try:
        identity = _WheelIdentity(
            name=_safe_flat_name(row["name"]),
            sha256=str(row["sha256"]),
            size_bytes=int(row["size_bytes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WheelVerificationError(
            "release bundle has an invalid package identity"
        ) from exc
    if re.fullmatch(r"[0-9a-f]{64}", identity.sha256) is None:
        raise WheelVerificationError("release wheel identity has an invalid SHA-256")
    if not 0 < identity.size_bytes <= MAX_WHEEL_ARCHIVE_BYTES:
        raise WheelVerificationError(
            f"release wheel exceeds the {MAX_WHEEL_ARCHIVE_BYTES}-byte runtime limit"
        )
    return identity


def _candidate_wheel(
    bundle_result: dict[str, object],
    *,
    expected_version: str,
    distribution_name: str,
) -> _WheelIdentity:
    rows = bundle_result.get("package_artifacts")
    if not isinstance(rows, list):
        raise WheelVerificationError("verified bundle result has no package identities")
    identities = [_identity_from_row(row) for row in rows]
    names = [identity.name for identity in identities]
    if len(names) != len(set(names)):
        raise WheelVerificationError("verified bundle result has duplicate package identities")
    wheels = [identity for identity in identities if identity.name.endswith(".whl")]
    if len(wheels) != 1:
        raise WheelVerificationError(
            "release bundle must identify exactly one candidate Python wheel"
        )
    wheel = wheels[0]
    components = wheel.name[:-4].split("-")
    if len(components) < 5:
        raise WheelVerificationError("candidate release wheel filename is malformed")
    if _normalize_distribution(components[0]) != _normalize_distribution(
        distribution_name
    ):
        raise WheelVerificationError(
            "candidate release wheel identifies another distribution"
        )
    if components[1] != expected_version:
        raise WheelVerificationError(
            "candidate release wheel version differs from the installed distribution"
        )
    return wheel


def _sha256_file(path: Path, *, expected_size: int) -> str:
    digest = hashlib.sha256()
    bytes_read = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(min(HASH_CHUNK_BYTES, expected_size - bytes_read + 1))
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > expected_size:
                raise WheelVerificationError(
                    "candidate release wheel changed size while it was hashed"
                )
            digest.update(chunk)
    if bytes_read != expected_size:
        raise WheelVerificationError(
            "candidate release wheel changed size while it was hashed"
        )
    return digest.hexdigest()


def _safe_member_path(info: zipfile.ZipInfo) -> tuple[str, ...]:
    name = info.filename
    if (
        not name
        or len(name) > MAX_WHEEL_NAME_CHARS
        or "\\" in name
        or "\x00" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise WheelVerificationError("wheel contains an unsafe member name")
    lexical_name = name[:-1] if info.is_dir() and name.endswith("/") else name
    path = PurePosixPath(lexical_name)
    unsafe_windows_component = any(
        ":" in part
        or part.endswith((" ", "."))
        or part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
        for part in path.parts
    )
    if (
        not lexical_name
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or unsafe_windows_component
        or path.as_posix() != lexical_name
    ):
        raise WheelVerificationError(f"wheel contains an unsafe member path: {name!r}")
    return tuple(path.parts)


def _validate_member_type(info: zipfile.ZipInfo) -> None:
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    expected_type = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
    if file_type not in {0, expected_type}:
        raise WheelVerificationError(
            f"wheel contains a non-regular or link-like member: {info.filename}"
        )
    if info.flag_bits & 0x1:
        raise WheelVerificationError(
            f"wheel contains an encrypted member: {info.filename}"
        )
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise WheelVerificationError(
            f"wheel uses an unsupported compression method: {info.filename}"
        )
    if info.file_size < 0 or info.file_size > MAX_WHEEL_MEMBER_BYTES:
        raise WheelVerificationError(
            f"wheel member exceeds the {MAX_WHEEL_MEMBER_BYTES}-byte limit: "
            f"{info.filename}"
        )
    if info.compress_size < 0:
        raise WheelVerificationError(
            f"wheel member has an invalid compressed size: {info.filename}"
        )
    if (
        info.file_size > 1024 * 1024
        and (
            info.compress_size == 0
            or info.file_size > info.compress_size * MAX_WHEEL_COMPRESSION_RATIO
        )
    ):
        raise WheelVerificationError(
            f"wheel member exceeds the compression-ratio limit: {info.filename}"
        )


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_bytes: int,
) -> bytes:
    if info.file_size > max_bytes:
        raise WheelVerificationError(
            f"wheel metadata exceeds the {max_bytes}-byte limit: {info.filename}"
        )
    chunks: list[bytes] = []
    bytes_read = 0
    try:
        with archive.open(info, "r") as handle:
            while True:
                chunk = handle.read(min(HASH_CHUNK_BYTES, max_bytes - bytes_read + 1))
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > max_bytes or bytes_read > info.file_size:
                    raise WheelVerificationError(
                        f"wheel member expanded beyond its declared bounds: {info.filename}"
                    )
                chunks.append(chunk)
    except WheelVerificationError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise WheelVerificationError(
            f"wheel member could not be read safely: {info.filename}"
        ) from exc
    if bytes_read != info.file_size:
        raise WheelVerificationError(
            f"wheel member size differs from its archive metadata: {info.filename}"
        )
    return b"".join(chunks)


def _hash_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    bytes_read = 0
    try:
        with archive.open(info, "r") as handle:
            while True:
                chunk = handle.read(
                    min(HASH_CHUNK_BYTES, info.file_size - bytes_read + 1)
                )
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > info.file_size:
                    raise WheelVerificationError(
                        f"wheel member expanded beyond its declared size: {info.filename}"
                    )
                digest.update(chunk)
    except WheelVerificationError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise WheelVerificationError(
            f"wheel member could not be hashed safely: {info.filename}"
        ) from exc
    if bytes_read != info.file_size:
        raise WheelVerificationError(
            f"wheel member size differs from its archive metadata: {info.filename}"
        )
    return digest.hexdigest()


def _expected_sha256(value: str) -> str:
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise WheelVerificationError("wheel RECORD contains an invalid SHA-256 value")
    try:
        encoded = value + "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            encoded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise WheelVerificationError(
            "wheel RECORD contains an invalid SHA-256 value"
        ) from exc
    if len(decoded) != hashlib.sha256().digest_size:
        raise WheelVerificationError(
            "wheel RECORD contains an invalid SHA-256 digest length"
        )
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise WheelVerificationError(
            "wheel RECORD contains a noncanonical SHA-256 value"
        )
    return decoded.hex()


def _parse_record(payload: bytes) -> dict[str, _WheelRecordEntry]:
    if len(payload) > MAX_WHEEL_RECORD_BYTES:
        raise WheelVerificationError("wheel RECORD exceeds its safety limit")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WheelVerificationError("wheel RECORD is not valid UTF-8") from exc
    rows: dict[str, _WheelRecordEntry] = {}
    identities: set[str] = set()
    lines = text.splitlines(keepends=True)
    if len(lines) > MAX_WHEEL_MEMBERS:
        raise WheelVerificationError("wheel RECORD contains too many entries")
    for line_number, line in enumerate(lines, start=1):
        if len(line) > MAX_WHEEL_RECORD_LINE_CHARS:
            raise WheelVerificationError(
                f"wheel RECORD line {line_number} exceeds its safety limit"
            )
        try:
            row = next(csv.reader([line], strict=True))
        except (csv.Error, StopIteration) as exc:
            raise WheelVerificationError(
                f"wheel RECORD line {line_number} is invalid CSV"
            ) from exc
        if len(row) != 3 or not row[0]:
            raise WheelVerificationError(
                f"wheel RECORD line {line_number} must contain three fields"
            )
        raw_path = row[0]
        if "\x00" in raw_path:
            raise WheelVerificationError("wheel RECORD contains a null byte in a path")
        synthetic = zipfile.ZipInfo(raw_path)
        if synthetic.filename != raw_path:
            raise WheelVerificationError("wheel RECORD contains an unsafe path")
        if raw_path.endswith("/"):
            raise WheelVerificationError("wheel RECORD cannot identify a directory")
        parts = _safe_member_path(synthetic)
        path = PurePosixPath(*parts).as_posix()
        identity = path.casefold()
        if identity in identities:
            raise WheelVerificationError(f"wheel RECORD has a duplicate path: {path}")
        identities.add(identity)
        hash_mode: str | None = None
        hash_value: str | None = None
        if row[1]:
            hash_mode, separator, hash_value = row[1].partition("=")
            if not separator or not hash_mode or not hash_value:
                raise WheelVerificationError(
                    f"wheel RECORD line {line_number} has an invalid hash field"
                )
        size_bytes: int | None = None
        if row[2]:
            try:
                size_bytes = int(row[2])
            except ValueError as exc:
                raise WheelVerificationError(
                    f"wheel RECORD line {line_number} has an invalid size"
                ) from exc
            if size_bytes < 0 or size_bytes > MAX_WHEEL_MEMBER_BYTES:
                raise WheelVerificationError(
                    f"wheel RECORD line {line_number} has an unsafe size"
                )
        rows[path] = _WheelRecordEntry(
            path=path,
            hash_mode=hash_mode,
            hash_value=hash_value,
            size_bytes=size_bytes,
        )
    if not rows:
        raise WheelVerificationError("wheel RECORD is empty")
    return rows


def _verify_metadata(
    payload: bytes,
    *,
    expected_version: str,
    distribution_name: str,
) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WheelVerificationError("wheel METADATA is not valid UTF-8") from exc
    message = Parser().parsestr(text, headersonly=True)
    names = message.get_all("Name", [])
    versions = message.get_all("Version", [])
    if len(names) != 1 or _normalize_distribution(names[0]) != _normalize_distribution(
        distribution_name
    ):
        raise WheelVerificationError("wheel METADATA identifies another distribution")
    if len(versions) != 1 or versions[0].strip() != expected_version:
        raise WheelVerificationError(
            "wheel METADATA version differs from the installed distribution"
        )


def verify_release_wheel(
    bundle_root: Path | str,
    bundle_result: dict[str, object],
    *,
    expected_version: str,
    distribution_name: str = "provelume",
    package_name: str = "provelume",
) -> ReleaseWheelEvidence:
    """Validate the release wheel and return trusted package-member byte identities."""

    root_input = Path(bundle_root).expanduser()
    if _is_link_like(root_input) or not root_input.is_dir():
        raise WheelVerificationError("release bundle root is unavailable or link-like")
    try:
        root = root_input.resolve(strict=True)
    except OSError as exc:
        raise WheelVerificationError("release bundle root cannot be resolved safely") from exc
    wheel = _candidate_wheel(
        bundle_result,
        expected_version=expected_version,
        distribution_name=distribution_name,
    )
    wheel_path = root / wheel.name
    if _is_link_like(wheel_path) or not wheel_path.is_file():
        raise WheelVerificationError("candidate release wheel is unavailable or link-like")
    try:
        if wheel_path.resolve(strict=True).parent != root:
            raise WheelVerificationError("candidate release wheel escapes the bundle root")
        actual_size = wheel_path.stat().st_size
    except OSError as exc:
        raise WheelVerificationError("candidate release wheel cannot be inspected") from exc
    if actual_size != wheel.size_bytes:
        raise WheelVerificationError("candidate release wheel size changed after bundle check")
    try:
        actual_sha256 = _sha256_file(wheel_path, expected_size=actual_size)
    except OSError as exc:
        raise WheelVerificationError("candidate release wheel cannot be hashed") from exc
    if actual_sha256 != wheel.sha256:
        raise WheelVerificationError("candidate release wheel changed after bundle check")

    try:
        with zipfile.ZipFile(wheel_path, "r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_WHEEL_MEMBERS:
                raise WheelVerificationError("wheel has an invalid number of members")
            files: dict[str, zipfile.ZipInfo] = {}
            identities: set[str] = set()
            total_uncompressed = 0
            for info in infos:
                parts = _safe_member_path(info)
                _validate_member_type(info)
                if (
                    parts[0].casefold() == package_name.casefold()
                    and parts[0] != package_name
                ):
                    raise WheelVerificationError(
                        "wheel uses a noncanonical package-directory name"
                    )
                path = PurePosixPath(*parts).as_posix()
                identity = path.casefold()
                if identity in identities:
                    raise WheelVerificationError(
                        f"wheel has a duplicate or case-colliding member: {path}"
                    )
                identities.add(identity)
                if info.is_dir():
                    if info.file_size != 0:
                        raise WheelVerificationError(
                            f"wheel directory member has payload bytes: {path}"
                        )
                    continue
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_WHEEL_UNCOMPRESSED_BYTES:
                    raise WheelVerificationError(
                        "wheel exceeds the cumulative uncompressed-byte limit"
                    )
                files[path] = info

            wheel_filename_parts = wheel.name[:-4].split("-")
            dist_info = (
                f"{wheel_filename_parts[0]}-{wheel_filename_parts[1]}.dist-info"
            )
            record_path = f"{dist_info}/RECORD"
            metadata_path = f"{dist_info}/METADATA"
            record_info = files.get(record_path)
            metadata_info = files.get(metadata_path)
            if record_info is None or metadata_info is None:
                raise WheelVerificationError(
                    "wheel is missing its expected METADATA or RECORD file"
                )
            record_payload = _read_member(
                archive,
                record_info,
                max_bytes=MAX_WHEEL_RECORD_BYTES,
            )
            metadata_payload = _read_member(
                archive,
                metadata_info,
                max_bytes=MAX_WHEEL_METADATA_BYTES,
            )
            _verify_metadata(
                metadata_payload,
                expected_version=expected_version,
                distribution_name=distribution_name,
            )
            record = _parse_record(record_payload)
            if set(record) != set(files):
                missing = sorted(set(files) - set(record))[:5]
                extra = sorted(set(record) - set(files))[:5]
                raise WheelVerificationError(
                    "wheel RECORD coverage differs from archive members: "
                    f"missing={missing}, extra={extra}"
                )

            member_hashes: dict[str, str] = {}
            for path in sorted(files):
                info = files[path]
                entry = record[path]
                may_be_unhashed = path in {
                    f"{dist_info}/{name}" for name in KNOWN_UNHASHED_WHEEL_MEMBERS
                }
                if entry.size_bytes is None:
                    if not may_be_unhashed:
                        raise WheelVerificationError(
                            f"wheel RECORD omits the size for {path}"
                        )
                elif entry.size_bytes != info.file_size:
                    raise WheelVerificationError(
                        f"wheel RECORD size differs from archive member: {path}"
                    )
                if entry.hash_mode is None or entry.hash_value is None:
                    if not may_be_unhashed:
                        raise WheelVerificationError(
                            f"wheel RECORD omits the hash for {path}"
                        )
                    actual_digest = _hash_member(archive, info)
                else:
                    if entry.hash_mode.casefold() != "sha256":
                        raise WheelVerificationError(
                            f"wheel RECORD uses an unsupported hash for {path}"
                        )
                    expected_digest = _expected_sha256(entry.hash_value)
                    actual_digest = _hash_member(archive, info)
                    if actual_digest != expected_digest:
                        raise WheelVerificationError(
                            f"wheel member differs from RECORD: {path}"
                        )
                member_hashes[path] = actual_digest

            normalized_package = package_name.casefold()
            package_files = tuple(
                WheelPackageFile(
                    path=path,
                    sha256=member_hashes[path],
                    size_bytes=files[path].file_size,
                )
                for path in sorted(files)
                if PurePosixPath(path).parts[0].casefold() == normalized_package
            )
            if not package_files:
                raise WheelVerificationError(
                    "candidate release wheel has no Provelume package files"
                )
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        if isinstance(exc, WheelVerificationError):
            raise
        raise WheelVerificationError("candidate release wheel is not a readable wheel") from exc

    return ReleaseWheelEvidence(
        name=wheel.name,
        sha256=wheel.sha256,
        size_bytes=wheel.size_bytes,
        dist_info=dist_info,
        checked_members=len(files),
        package_files=package_files,
    )
