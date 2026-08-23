from __future__ import annotations

import hashlib
import json
import re
import stat
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, LargeZipFile, ZipFile

from .build_info import BuildInfoError, parse_build_info

SOURCE_REPOSITORY = "gabned/provelume"
RELEASE_MANIFEST = "release-manifest.json"
CHECKSUMS = "SHA256SUMS"
DETERMINISM_EVIDENCE = "build-determinism.json"
MANIFEST_SCHEMA_VERSION = 1
DETERMINISM_SCHEMA_VERSION = 1
MAX_CONTROL_BYTES = 2 * 1024 * 1024
MAX_SBOM_BYTES = 16 * 1024 * 1024
MAX_BUILD_INFO_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
MAX_BUNDLE_ENTRIES = 256
MAX_WHEEL_ENTRIES = 20_000
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
SEMANTIC_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHANNELS = {"development", "preview", "stable"}
VERIFIED_STATUS = "bundle_integrity_verified"
MODIFIED_STATUS = "bundle_modified"
INVALID_STATUS = "bundle_invalid"


class BundleVerificationError(ValueError):
    def __init__(self, check_id: str, message: str, *, category: str = "invalid"):
        super().__init__(message)
        self.check_id = check_id
        self.category = category


@dataclass(frozen=True, slots=True)
class VerifiedFile:
    name: str
    path: Path
    sha256: str
    size_bytes: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value):
        raise BundleVerificationError(
            "safe_names",
            f"{label} must be a portable direct-child filename",
        )
    return value


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BundleVerificationError("manifest_schema", f"{label} must be a non-empty string")
    return value


def _strict_integer(value: Any, *, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise BundleVerificationError(
            "manifest_schema",
            f"{label} must be an integer greater than or equal to {minimum}",
        )
    return value


def _strict_boolean(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise BundleVerificationError("manifest_schema", f"{label} must be a boolean")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise BundleVerificationError("manifest_schema", f"{label} must be a lowercase SHA-256")
    return value


def _commit(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not COMMIT_SHA.fullmatch(value):
        raise BundleVerificationError(
            "manifest_schema",
            f"{label} must be a lowercase 40-character commit SHA",
        )
    return value


def _aware_datetime(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BundleVerificationError("manifest_schema", f"{label} must be an ISO timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise BundleVerificationError(
            "manifest_schema",
            f"{label} must be an ISO timestamp",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BundleVerificationError("manifest_schema", f"{label} must include a timezone")
    return value


def _utc_from_epoch(value: int) -> str:
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (OSError, OverflowError, ValueError) as exc:
        raise BundleVerificationError(
            "determinism_evidence",
            "source_date_epoch is outside the supported range",
        ) from exc


def _exact_fields(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    fields = set(value)
    missing = expected - fields
    unknown = fields - expected
    if missing:
        raise BundleVerificationError(
            "manifest_schema",
            f"{label} is missing fields: {', '.join(sorted(missing))}",
        )
    if unknown:
        raise BundleVerificationError(
            "manifest_schema",
            f"{label} has unknown fields: {', '.join(sorted(unknown))}",
        )


def _read_direct_file(
    root: Path,
    name: str,
    *,
    maximum: int,
    missing_category: str = "invalid",
) -> Path:
    safe_name = _safe_name(name, label="bundle filename")
    path = root / safe_name
    if path.is_symlink():
        raise BundleVerificationError(
            "safe_files",
            f"bundle file must not be a symlink: {safe_name}",
        )
    if not path.exists():
        raise BundleVerificationError(
            "required_files",
            f"bundle file is missing: {safe_name}",
            category=missing_category,
        )
    if not path.is_file():
        raise BundleVerificationError(
            "safe_files",
            f"bundle entry is not a regular file: {safe_name}",
        )
    size = path.stat().st_size
    if size <= 0:
        raise BundleVerificationError(
            "required_files",
            f"bundle file is empty: {safe_name}",
            category=missing_category,
        )
    if size > maximum:
        raise BundleVerificationError(
            "resource_limits",
            f"bundle file exceeds the {maximum}-byte verification limit: {safe_name}",
        )
    return path


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise BundleVerificationError(
            "control_files",
            f"{label} is not valid UTF-8",
        ) from exc
    except json.JSONDecodeError as exc:
        raise BundleVerificationError(
            "control_files",
            f"{label} is not valid JSON",
        ) from exc
    except OSError as exc:
        raise BundleVerificationError(
            "control_files",
            f"{label} cannot be read",
        ) from exc
    if not isinstance(value, dict):
        raise BundleVerificationError("control_files", f"{label} must be a JSON object")
    return value


def _parse_artifact_record(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleVerificationError("manifest_schema", f"{label} must be an object")
    _exact_fields(value, {"name", "sha256", "size_bytes", "media_type"}, label=label)
    return {
        "name": _safe_name(value["name"], label=f"{label}.name"),
        "sha256": _sha(value["sha256"], label=f"{label}.sha256"),
        "size_bytes": _strict_integer(value["size_bytes"], label=f"{label}.size_bytes", minimum=1),
        "media_type": _string(value["media_type"], label=f"{label}.media_type"),
    }


def parse_release_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleVerificationError("manifest_schema", "release manifest must be an object")
    _exact_fields(
        value,
        {
            "schema_version",
            "version",
            "tag",
            "commit",
            "source_repository",
            "channel",
            "built_at",
            "artifacts",
            "sbom",
        },
        label="release manifest",
    )
    schema_version = value["schema_version"]
    if type(schema_version) is not int or schema_version != MANIFEST_SCHEMA_VERSION:
        raise BundleVerificationError("manifest_schema", "unsupported release manifest schema")
    version = _string(value["version"], label="version")
    if not SEMANTIC_VERSION.fullmatch(version):
        raise BundleVerificationError("manifest_schema", "version must be semantic X.Y.Z")
    tag = _string(value["tag"], label="tag")
    if tag != f"v{version}":
        raise BundleVerificationError("manifest_schema", "tag must match the release version")
    commit = _commit(value["commit"], label="commit")
    if value["source_repository"] != SOURCE_REPOSITORY:
        raise BundleVerificationError("manifest_schema", "source repository is not canonical")
    channel = _string(value["channel"], label="channel")
    if channel not in CHANNELS:
        raise BundleVerificationError("manifest_schema", "release channel is unsupported")
    built_at = _aware_datetime(value["built_at"], label="built_at")

    artifacts_value = value["artifacts"]
    if not isinstance(artifacts_value, list) or not 1 <= len(artifacts_value) <= 100:
        raise BundleVerificationError(
            "manifest_schema",
            "artifacts must contain between 1 and 100 records",
        )
    artifacts = [
        _parse_artifact_record(item, label=f"artifacts[{index}]")
        for index, item in enumerate(artifacts_value)
    ]
    names = [str(item["name"]) for item in artifacts]
    if len(names) != len(set(names)):
        raise BundleVerificationError("safe_names", "release manifest contains duplicate names")

    required = {
        "LICENSE",
        "COMMERCIAL-LICENSE.md",
        "THIRD_PARTY_NOTICES.md",
        DETERMINISM_EVIDENCE,
    }
    missing_required = required - set(names)
    if missing_required:
        raise BundleVerificationError(
            "manifest_schema",
            f"release manifest is missing required assets: {', '.join(sorted(missing_required))}",
        )
    wheels = [name for name in names if name.endswith(".whl")]
    sdists = [name for name in names if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise BundleVerificationError(
            "manifest_schema",
            "release manifest must contain exactly one wheel and one source distribution",
        )

    sbom_value = value["sbom"]
    if not isinstance(sbom_value, dict):
        raise BundleVerificationError("manifest_schema", "sbom must be an object")
    _exact_fields(sbom_value, {"name", "sha256", "format"}, label="sbom")
    sbom = {
        "name": _safe_name(sbom_value["name"], label="sbom.name"),
        "sha256": _sha(sbom_value["sha256"], label="sbom.sha256"),
        "format": sbom_value["format"],
    }
    if sbom["format"] != "cyclonedx-json":
        raise BundleVerificationError("manifest_schema", "SBOM format must be cyclonedx-json")
    if sbom["name"] in set(names):
        raise BundleVerificationError("safe_names", "SBOM name duplicates a release artifact")
    if not str(sbom["name"]).endswith(".cdx.json"):
        raise BundleVerificationError("manifest_schema", "SBOM filename must end in .cdx.json")

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "version": version,
        "tag": tag,
        "commit": commit,
        "source_repository": SOURCE_REPOSITORY,
        "channel": channel,
        "built_at": built_at,
        "artifacts": artifacts,
        "sbom": sbom,
        "wheel_name": wheels[0],
        "sdist_name": sdists[0],
    }


def _parse_checksums(value: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line_number, line in enumerate(value.splitlines(), start=1):
        if not line:
            raise BundleVerificationError(
                "checksums_schema",
                f"SHA256SUMS contains a blank row at line {line_number}",
            )
        if len(line) < 67 or line[64:66] != "  ":
            raise BundleVerificationError(
                "checksums_schema",
                f"SHA256SUMS line {line_number} has invalid formatting",
            )
        digest = _sha(line[:64], label=f"SHA256SUMS line {line_number}")
        name = _safe_name(line[66:], label=f"SHA256SUMS line {line_number} filename")
        if name in rows:
            raise BundleVerificationError(
                "checksums_schema",
                f"SHA256SUMS contains a duplicate filename: {name}",
            )
        rows[name] = digest
    if not rows:
        raise BundleVerificationError("checksums_schema", "SHA256SUMS is empty")
    return rows


def _parse_tool(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise BundleVerificationError("determinism_evidence", f"{label} must be an object")
    _exact_fields(value, {"name", "version"}, label=label)
    return {
        "name": _string(value["name"], label=f"{label}.name"),
        "version": _string(value["version"], label=f"{label}.version"),
    }


def _parse_determinism_artifact(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleVerificationError("determinism_evidence", f"{label} must be an object")
    _exact_fields(
        value,
        {
            "kind",
            "name",
            "sha256",
            "second_sha256",
            "size_bytes",
            "second_size_bytes",
            "byte_identical",
        },
        label=label,
    )
    kind = value["kind"]
    if kind not in {"wheel", "sdist"}:
        raise BundleVerificationError("determinism_evidence", f"{label}.kind is unsupported")
    first_hash = _sha(value["sha256"], label=f"{label}.sha256")
    second_hash = _sha(value["second_sha256"], label=f"{label}.second_sha256")
    first_size = _strict_integer(value["size_bytes"], label=f"{label}.size_bytes", minimum=1)
    second_size = _strict_integer(
        value["second_size_bytes"],
        label=f"{label}.second_size_bytes",
        minimum=1,
    )
    identical = _strict_boolean(value["byte_identical"], label=f"{label}.byte_identical")
    if not identical or first_hash != second_hash or first_size != second_size:
        raise BundleVerificationError(
            "determinism_evidence",
            f"{label} does not prove byte-identical outputs",
        )
    return {
        "kind": kind,
        "name": _safe_name(value["name"], label=f"{label}.name"),
        "sha256": first_hash,
        "size_bytes": first_size,
        "byte_identical": True,
    }


def parse_determinism_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleVerificationError("determinism_evidence", "build evidence must be an object")
    _exact_fields(
        value,
        {
            "schema_version",
            "assurance",
            "full_release_reproducibility_claimed",
            "source_repository",
            "source_commit",
            "source_fingerprint_sha256",
            "source_date_epoch",
            "source_date_utc",
            "project_version",
            "python",
            "implementation",
            "platform",
            "build_frontend",
            "build_backend",
            "artifacts",
        },
        label="build determinism evidence",
    )
    schema_version = value["schema_version"]
    if type(schema_version) is not int or schema_version != DETERMINISM_SCHEMA_VERSION:
        raise BundleVerificationError(
            "determinism_evidence",
            "unsupported build determinism evidence schema",
        )
    if value["assurance"] != "same-source-same-environment-byte-identical":
        raise BundleVerificationError("determinism_evidence", "build assurance is unsupported")
    if value["full_release_reproducibility_claimed"] is not False:
        raise BundleVerificationError(
            "determinism_evidence",
            "build evidence makes an unsupported reproducibility claim",
        )
    if value["source_repository"] != SOURCE_REPOSITORY:
        raise BundleVerificationError(
            "determinism_evidence",
            "build evidence source repository is not canonical",
        )
    source_commit = _commit(value["source_commit"], label="source_commit")
    fingerprint = _sha(
        value["source_fingerprint_sha256"],
        label="source_fingerprint_sha256",
    )
    epoch = _strict_integer(value["source_date_epoch"], label="source_date_epoch")
    source_date_utc = _string(value["source_date_utc"], label="source_date_utc")
    if source_date_utc != _utc_from_epoch(epoch):
        raise BundleVerificationError(
            "determinism_evidence",
            "source_date_utc does not match source_date_epoch",
        )
    project_version = _string(value["project_version"], label="project_version")
    if not SEMANTIC_VERSION.fullmatch(project_version):
        raise BundleVerificationError(
            "determinism_evidence",
            "project_version must be semantic X.Y.Z",
        )
    for field in ("python", "implementation", "platform"):
        _string(value[field], label=field)
    frontend = _parse_tool(value["build_frontend"], label="build_frontend")
    backend = _parse_tool(value["build_backend"], label="build_backend")
    if frontend["name"] != "build" or backend["name"] != "hatchling":
        raise BundleVerificationError(
            "determinism_evidence",
            "build evidence tool identities are unsupported",
        )
    artifacts_value = value["artifacts"]
    if not isinstance(artifacts_value, list) or len(artifacts_value) != 2:
        raise BundleVerificationError(
            "determinism_evidence",
            "build evidence must contain one wheel and one sdist record",
        )
    artifacts = [
        _parse_determinism_artifact(item, label=f"build artifacts[{index}]")
        for index, item in enumerate(artifacts_value)
    ]
    if {item["kind"] for item in artifacts} != {"wheel", "sdist"}:
        raise BundleVerificationError(
            "determinism_evidence",
            "build evidence must contain distinct wheel and sdist records",
        )
    if len({item["name"] for item in artifacts}) != 2:
        raise BundleVerificationError(
            "determinism_evidence",
            "build evidence contains duplicate artifact names",
        )
    return {
        "source_commit": source_commit,
        "source_fingerprint_sha256": fingerprint,
        "source_date_epoch": epoch,
        "source_date_utc": source_date_utc,
        "project_version": project_version,
        "build_frontend": frontend,
        "build_backend": backend,
        "artifacts": artifacts,
    }


def _parse_sbom(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleVerificationError("sbom", "SBOM must be a JSON object")
    if value.get("bomFormat") != "CycloneDX":
        raise BundleVerificationError("sbom", "SBOM bomFormat must be CycloneDX")
    if value.get("specVersion") != "1.6":
        raise BundleVerificationError("sbom", "SBOM specVersion must be 1.6")
    return value


def _wheel_build_info(path: Path, *, package_version: str) -> dict[str, Any]:
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_WHEEL_ENTRIES:
                raise BundleVerificationError(
                    "wheel_identity",
                    f"wheel exceeds the {MAX_WHEEL_ENTRIES}-entry inspection limit",
                )
            matches = [item for item in entries if item.filename == "provelume/build_info.json"]
            if len(matches) != 1:
                raise BundleVerificationError(
                    "wheel_identity",
                    "wheel must contain exactly one provelume/build_info.json",
                )
            info = matches[0]
            if info.flag_bits & 0x1:
                raise BundleVerificationError("wheel_identity", "wheel build identity is encrypted")
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and stat.S_ISLNK(mode):
                raise BundleVerificationError("wheel_identity", "wheel build identity is a symlink")
            if info.file_size <= 0 or info.file_size > MAX_BUILD_INFO_BYTES:
                raise BundleVerificationError(
                    "wheel_identity",
                    "wheel build identity exceeds the safe inspection limit",
                )
            if info.file_size > 1024 and info.file_size / max(info.compress_size, 1) > 100:
                raise BundleVerificationError(
                    "wheel_identity",
                    "wheel build identity has an unsafe compression ratio",
                )
            raw = archive.read(info)
    except BundleVerificationError:
        raise
    except (BadZipFile, LargeZipFile, OSError, RuntimeError, zlib.error) as exc:
        raise BundleVerificationError("wheel_identity", "wheel cannot be inspected safely") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleVerificationError(
            "wheel_identity",
            "wheel build identity is not valid UTF-8 JSON",
        ) from exc
    try:
        return parse_build_info(value, package_version=package_version)
    except BuildInfoError as exc:
        raise BundleVerificationError("wheel_identity", str(exc)) from exc


class _ResultBuilder:
    def __init__(self, bundle_name: str):
        self.bundle_name = bundle_name
        self.checks: list[dict[str, str]] = []
        self.invalid = False
        self.modified = False
        self.identity: dict[str, Any] | None = None

    def passed(self, check_id: str, message: str) -> None:
        self.checks.append({"id": check_id, "status": "passed", "message": message})

    def warning(self, check_id: str, message: str) -> None:
        self.checks.append({"id": check_id, "status": "warning", "message": message})

    def failed(self, problem: BundleVerificationError) -> None:
        if problem.category == "modified":
            self.modified = True
        else:
            self.invalid = True
        self.checks.append(
            {"id": problem.check_id, "status": "failed", "message": str(problem)}
        )

    def finish(self) -> dict[str, Any]:
        if self.invalid:
            status = INVALID_STATUS
        elif self.modified:
            status = MODIFIED_STATUS
        else:
            status = VERIFIED_STATUS
        counts = {
            state: sum(check["status"] == state for check in self.checks)
            for state in ("passed", "failed", "warning")
        }
        return {
            "schema_version": 1,
            "status": status,
            "bundle_name": self.bundle_name,
            "offline": True,
            "network_used": False,
            "identity": self.identity,
            "summary": counts,
            "checks": self.checks,
            "boundaries": {
                "bundle_authenticity": "not_verified",
                "artifact_attestations": "not_verified_offline",
                "platform_signature": "not_verified",
                "installed_runtime": "not_verified",
            },
        }


def _verify_manifest_file(
    root: Path,
    record: dict[str, Any],
) -> VerifiedFile:
    name = str(record["name"])
    path = _read_direct_file(
        root,
        name,
        maximum=MAX_ARTIFACT_BYTES,
        missing_category="modified",
    )
    size = path.stat().st_size
    digest = _sha256_file(path)
    if size != record["size_bytes"] or digest != record["sha256"]:
        raise BundleVerificationError(
            "artifact_integrity",
            f"artifact does not match release manifest: {name}",
            category="modified",
        )
    return VerifiedFile(name=name, path=path, sha256=digest, size_bytes=size)


def verify_release_bundle(bundle: Path | str) -> dict[str, Any]:
    requested = Path(bundle).expanduser()
    result = _ResultBuilder(requested.name or "release")
    if requested.is_symlink():
        result.failed(
            BundleVerificationError("bundle_root", "bundle directory must not be a symlink")
        )
        return result.finish()
    try:
        root = requested.resolve(strict=True)
    except OSError:
        result.failed(BundleVerificationError("bundle_root", "bundle directory does not exist"))
        return result.finish()
    if not root.is_dir():
        result.failed(BundleVerificationError("bundle_root", "bundle path is not a directory"))
        return result.finish()
    try:
        entries = list(root.iterdir())
    except OSError:
        result.failed(BundleVerificationError("bundle_root", "bundle directory cannot be read"))
        return result.finish()
    if len(entries) > MAX_BUNDLE_ENTRIES:
        result.failed(
            BundleVerificationError(
                "resource_limits",
                f"bundle exceeds the {MAX_BUNDLE_ENTRIES}-entry verification limit",
            )
        )
        return result.finish()
    result.passed("bundle_root", "bundle directory is readable and bounded")

    try:
        manifest_path = _read_direct_file(
            root,
            RELEASE_MANIFEST,
            maximum=MAX_CONTROL_BYTES,
        )
        manifest = parse_release_manifest(
            _read_json(manifest_path, label="release manifest")
        )
    except BundleVerificationError as problem:
        result.failed(problem)
        return result.finish()
    result.identity = {
        key: manifest[key]
        for key in ("version", "tag", "commit", "source_repository", "channel")
    }
    result.passed("manifest_schema", "release manifest is structurally valid")

    manifest_records = {
        str(record["name"]): record for record in manifest["artifacts"]
    }
    verified: dict[str, VerifiedFile] = {}
    for record in [*manifest["artifacts"], manifest["sbom"]]:
        name = str(record["name"])
        normalized_record = dict(record)
        if "size_bytes" not in normalized_record:
            try:
                path = _read_direct_file(
                    root,
                    name,
                    maximum=MAX_SBOM_BYTES,
                    missing_category="modified",
                )
            except BundleVerificationError as problem:
                result.failed(problem)
                continue
            digest = _sha256_file(path)
            if digest != record["sha256"]:
                result.failed(
                    BundleVerificationError(
                        "artifact_integrity",
                        f"SBOM does not match release manifest: {name}",
                        category="modified",
                    )
                )
                continue
            verified[name] = VerifiedFile(
                name=name,
                path=path,
                sha256=digest,
                size_bytes=path.stat().st_size,
            )
            result.passed("artifact_integrity", f"verified {name}")
            continue
        try:
            item = _verify_manifest_file(root, normalized_record)
        except BundleVerificationError as problem:
            result.failed(problem)
        else:
            verified[name] = item
            result.passed("artifact_integrity", f"verified {name}")

    try:
        checksums_path = _read_direct_file(
            root,
            CHECKSUMS,
            maximum=MAX_CONTROL_BYTES,
        )
        try:
            checksums_text = checksums_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise BundleVerificationError(
                "checksums_schema",
                "SHA256SUMS cannot be read as UTF-8",
            ) from exc
        checksums = _parse_checksums(checksums_text)
        expected_checksum_names = {
            *manifest_records,
            str(manifest["sbom"]["name"]),
            RELEASE_MANIFEST,
        }
        if set(checksums) != expected_checksum_names:
            raise BundleVerificationError(
                "checksums_schema",
                "SHA256SUMS filenames do not match manifest-controlled files",
            )
        for name, expected_digest in checksums.items():
            path = _read_direct_file(
                root,
                name,
                maximum=(
                    MAX_CONTROL_BYTES
                    if name == RELEASE_MANIFEST
                    else MAX_SBOM_BYTES
                    if name == manifest["sbom"]["name"]
                    else MAX_ARTIFACT_BYTES
                ),
                missing_category="modified",
            )
            if _sha256_file(path) != expected_digest:
                raise BundleVerificationError(
                    "checksums_integrity",
                    f"file does not match SHA256SUMS: {name}",
                    category="modified",
                )
            if name in manifest_records and expected_digest != manifest_records[name]["sha256"]:
                raise BundleVerificationError(
                    "checksums_schema",
                    f"SHA256SUMS disagrees with release manifest: {name}",
                )
            if name == manifest["sbom"]["name"] and expected_digest != manifest["sbom"]["sha256"]:
                raise BundleVerificationError(
                    "checksums_schema",
                    "SHA256SUMS disagrees with release manifest SBOM",
                )
    except BundleVerificationError as problem:
        result.failed(problem)
    else:
        result.passed("checksums_integrity", "SHA256SUMS matches all controlled files")

    evidence_name = DETERMINISM_EVIDENCE
    evidence: dict[str, Any] | None = None
    if evidence_name in verified:
        try:
            evidence = parse_determinism_evidence(
                _read_json(verified[evidence_name].path, label="build determinism evidence")
            )
            if evidence["source_commit"] != manifest["commit"]:
                raise BundleVerificationError(
                    "identity_consistency",
                    "build evidence commit does not match release manifest",
                )
            if evidence["project_version"] != manifest["version"]:
                raise BundleVerificationError(
                    "identity_consistency",
                    "build evidence version does not match release manifest",
                )
            for record in evidence["artifacts"]:
                manifest_record = manifest_records.get(record["name"])
                if manifest_record is None:
                    raise BundleVerificationError(
                        "identity_consistency",
                        f"build evidence artifact is absent from manifest: {record['name']}",
                    )
                if (
                    manifest_record["sha256"] != record["sha256"]
                    or manifest_record["size_bytes"] != record["size_bytes"]
                ):
                    raise BundleVerificationError(
                        "identity_consistency",
                        f"build evidence disagrees with manifest: {record['name']}",
                    )
        except BundleVerificationError as problem:
            result.failed(problem)
        else:
            result.passed(
                "determinism_evidence",
                "deterministic build evidence matches the release manifest",
            )

    sbom_name = str(manifest["sbom"]["name"])
    if sbom_name in verified:
        try:
            _parse_sbom(_read_json(verified[sbom_name].path, label="CycloneDX SBOM"))
        except BundleVerificationError as problem:
            result.failed(problem)
        else:
            result.passed("sbom", "CycloneDX 1.6 SBOM is structurally recognizable")

    wheel_name = str(manifest["wheel_name"])
    if wheel_name in verified and evidence is not None:
        try:
            build = _wheel_build_info(
                verified[wheel_name].path,
                package_version=str(manifest["version"]),
            )
            if build["commit"] != manifest["commit"]:
                raise BundleVerificationError(
                    "identity_consistency",
                    "wheel build identity commit does not match release manifest",
                )
            if build["source_date_epoch"] != evidence["source_date_epoch"]:
                raise BundleVerificationError(
                    "identity_consistency",
                    "wheel source timestamp does not match build evidence",
                )
            channel = str(manifest["channel"])
            if channel == "development":
                if build["official"] or build["tag"] is not None or build["channel"] != channel:
                    raise BundleVerificationError(
                        "identity_consistency",
                        "development bundle contains official or mismatched wheel identity",
                    )
            elif (
                not build["official"]
                or build["tag"] != manifest["tag"]
                or build["channel"] != channel
            ):
                raise BundleVerificationError(
                    "identity_consistency",
                    "official bundle wheel identity does not match release manifest",
                )
        except BundleVerificationError as problem:
            result.failed(problem)
        else:
            result.passed(
                "wheel_identity",
                "embedded wheel identity matches manifest and build evidence",
            )

    controlled = {
        *manifest_records,
        sbom_name,
        RELEASE_MANIFEST,
        CHECKSUMS,
    }
    extras = sorted(path.name for path in entries if path.name not in controlled)
    if extras:
        result.warning(
            "extra_entries",
            "unreferenced bundle entries were not verified: " + ", ".join(extras[:20]),
        )
    else:
        result.passed("extra_entries", "bundle contains no unreferenced entries")

    return result.finish()
