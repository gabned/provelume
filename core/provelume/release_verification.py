from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

SOURCE_REPOSITORY = "gabned/provelume"
RESULT_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "release-manifest.json"
CHECKSUMS_FILENAME = "SHA256SUMS"
BUILD_COMPARISON_FILENAME = "build-comparison.json"
BUILD_COMPARISON_SCHEMA_FILENAME = "build-comparison.schema.json"
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_ENTRIES = 256
SEMANTIC_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")

VerificationStatus = Literal["verified", "modified", "unavailable"]
FindingSeverity = Literal["error", "warning", "info"]


@dataclass(frozen=True, slots=True)
class VerificationFinding:
    severity: FindingSeverity
    code: str
    message: str
    path: str | None = None


@dataclass(slots=True)
class VerificationResult:
    status: VerificationStatus
    bundle: str
    source_repository: str | None = None
    version: str | None = None
    tag: str | None = None
    commit: str | None = None
    assurance_level: str | None = None
    deterministic_python_distributions: Literal[
        "verified", "not_present", "invalid"
    ] = "not_present"
    checked_files: int = 0
    findings: list[VerificationFinding] = field(default_factory=list)
    schema_version: int = RESULT_SCHEMA_VERSION

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["verified"] = self.verified
        return payload


class BundleUnavailableError(RuntimeError):
    pass


class BundleModifiedError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_flat_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BundleModifiedError(f"{label} must be a non-empty filename")
    if "\x00" in value or value in {".", ".."}:
        raise BundleModifiedError(f"{label} is invalid: {value!r}")
    if "/" in value or "\\" in value or DRIVE_PREFIX.match(value):
        raise BundleModifiedError(f"{label} must be a safe flat filename: {value!r}")
    return value


def _parse_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BundleModifiedError(f"{label} must be a timestamp string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BundleModifiedError(f"{label} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise BundleModifiedError(f"{label} must include a timezone")
    return value


def _metadata_path(root: Path, filename: str) -> Path:
    path = root / filename
    if path.is_symlink():
        raise BundleModifiedError(f"verification metadata is a symlink: {filename}")
    if not path.exists():
        raise BundleUnavailableError(f"required verification metadata is missing: {filename}")
    if not path.is_file():
        raise BundleUnavailableError(f"verification metadata is not a file: {filename}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BundleUnavailableError(f"cannot inspect verification metadata: {filename}") from exc
    if size > MAX_METADATA_BYTES:
        raise BundleModifiedError(
            f"verification metadata exceeds the {MAX_METADATA_BYTES}-byte limit: {filename}"
        )
    return path


def _declared_file(root: Path, filename: str) -> Path:
    safe_name = _safe_flat_name(filename, "declared filename")
    path = root / safe_name
    if path.is_symlink():
        raise BundleModifiedError(f"declared release file is a symlink: {safe_name}")
    if not path.exists():
        raise BundleUnavailableError(f"declared release file is missing: {safe_name}")
    if not path.is_file():
        raise BundleModifiedError(f"declared release path is not a file: {safe_name}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BundleUnavailableError(f"cannot resolve declared release file: {safe_name}") from exc
    if resolved.parent != root:
        raise BundleModifiedError(f"declared release file escapes the bundle: {safe_name}")
    return path


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise BundleModifiedError(f"{label} is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise BundleModifiedError(f"{label} is not valid JSON") from exc
    except OSError as exc:
        raise BundleUnavailableError(f"cannot read {label}") from exc
    if not isinstance(value, dict):
        raise BundleModifiedError(f"{label} must contain a JSON object")
    return value


def _identity_record(value: Any, label: str) -> tuple[str, int, str]:
    if not isinstance(value, dict):
        raise BundleModifiedError(f"{label} must be an object")
    filename = _safe_flat_name(value.get("filename"), f"{label}.filename")
    size = value.get("size_bytes")
    digest = value.get("sha256")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise BundleModifiedError(f"{label}.size_bytes must be a non-negative integer")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise BundleModifiedError(f"{label}.sha256 must be a lowercase SHA-256 digest")
    return filename, size, digest


def _manifest_contract(
    manifest: dict[str, Any],
    expected_repository: str,
) -> tuple[dict[str, tuple[int, str]], tuple[str, int, str]]:
    if manifest.get("schema_version") != 1:
        raise BundleModifiedError("release manifest schema_version must be 1")

    version = manifest.get("version")
    tag = manifest.get("tag")
    commit = manifest.get("commit")
    repository = manifest.get("source_repository")
    channel = manifest.get("channel")
    assurance = manifest.get("assurance_level")

    if not isinstance(version, str) or not SEMANTIC_VERSION.fullmatch(version):
        raise BundleModifiedError("release manifest version is not semantic X.Y.Z")
    if tag != f"v{version}":
        raise BundleModifiedError("release manifest tag does not match its version")
    if not isinstance(commit, str) or not FULL_COMMIT.fullmatch(commit):
        raise BundleModifiedError("release manifest commit must be a full lowercase SHA")
    if repository != expected_repository:
        raise BundleModifiedError(
            f"release manifest source repository must be {expected_repository}"
        )
    if channel not in {"development", "preview", "stable"}:
        raise BundleModifiedError("release manifest channel is unsupported")
    _parse_timestamp(manifest.get("build_timestamp"), "release manifest build_timestamp")
    if assurance != "traceable-build":
        raise BundleModifiedError("release manifest assurance_level is unsupported")

    rows = manifest.get("artifacts")
    if not isinstance(rows, list) or not rows:
        raise BundleModifiedError("release manifest artifacts must be a non-empty list")
    artifacts: dict[str, tuple[int, str]] = {}
    for index, row in enumerate(rows):
        filename, size, digest = _identity_record(row, f"artifacts[{index}]")
        if filename in {MANIFEST_FILENAME, CHECKSUMS_FILENAME}:
            raise BundleModifiedError(f"reserved metadata filename declared as artifact: {filename}")
        if filename in artifacts:
            raise BundleModifiedError(f"duplicate artifact filename in manifest: {filename}")
        artifacts[filename] = (size, digest)

    sbom = _identity_record(manifest.get("sbom"), "sbom")
    if sbom[0] in artifacts:
        raise BundleModifiedError("SBOM filename is duplicated in manifest artifacts")
    sbom_value = manifest.get("sbom")
    assert isinstance(sbom_value, dict)
    if sbom_value.get("format") != "CycloneDX 1.6":
        raise BundleModifiedError("release manifest SBOM format must be CycloneDX 1.6")
    return artifacts, sbom


def _verify_identity(path: Path, size: int, digest: str) -> None:
    try:
        actual_size = path.stat().st_size
        actual_digest = _sha256_file(path)
    except OSError as exc:
        raise BundleUnavailableError(f"cannot read declared release file: {path.name}") from exc
    if actual_size != size:
        raise BundleModifiedError(
            f"size mismatch for {path.name}: expected {size}, found {actual_size}"
        )
    if actual_digest != digest:
        raise BundleModifiedError(f"SHA-256 mismatch for {path.name}")


def _parse_checksums(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise BundleModifiedError("SHA256SUMS is not UTF-8") from exc
    except OSError as exc:
        raise BundleUnavailableError("cannot read SHA256SUMS") from exc

    checksums: dict[str, str] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})[ \t]+\*?(.+)", line)
        if match is None:
            raise BundleModifiedError(f"invalid SHA256SUMS line {number}")
        digest, raw_name = match.groups()
        filename = _safe_flat_name(raw_name, f"SHA256SUMS line {number} filename")
        if filename in checksums:
            raise BundleModifiedError(f"duplicate SHA256SUMS entry: {filename}")
        checksums[filename] = digest
    if not checksums:
        raise BundleModifiedError("SHA256SUMS contains no entries")
    return checksums


def _verify_sbom(path: Path) -> None:
    sbom = _read_json(path, "CycloneDX SBOM")
    if sbom.get("bomFormat") != "CycloneDX":
        raise BundleModifiedError("SBOM bomFormat is not CycloneDX")
    if sbom.get("specVersion") != "1.6":
        raise BundleModifiedError("SBOM specVersion is not 1.6")
    if not isinstance(sbom.get("components"), list):
        raise BundleModifiedError("SBOM components must be a list")


def _comparison_identity(value: Any, label: str) -> tuple[str, int, str]:
    if not isinstance(value, dict):
        raise BundleModifiedError(f"{label} must be an object")
    filename = _safe_flat_name(value.get("name"), f"{label}.name")
    size = value.get("size_bytes")
    digest = value.get("sha256")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise BundleModifiedError(f"{label}.size_bytes must be a non-negative integer")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise BundleModifiedError(f"{label}.sha256 must be a lowercase SHA-256 digest")
    return filename, size, digest


def _verify_build_comparison(
    report: dict[str, Any],
    manifest: dict[str, Any],
    artifacts: dict[str, tuple[int, str]],
) -> None:
    if report.get("schema_version") != 1:
        raise BundleModifiedError("build comparison schema_version must be 1")
    if report.get("result") != "match":
        raise BundleModifiedError("build comparison result is not match")
    if report.get("source_repository") != manifest.get("source_repository"):
        raise BundleModifiedError("build comparison source repository differs from manifest")
    if report.get("source_commit") != manifest.get("commit"):
        raise BundleModifiedError("build comparison source commit differs from manifest")
    if report.get("resolved_build_packages_match") is not True:
        raise BundleModifiedError("build comparison package environments did not match")

    rows = report.get("artifacts")
    if not isinstance(rows, list) or len(rows) != 2:
        raise BundleModifiedError("build comparison must contain one wheel and one sdist")
    seen_suffixes: set[str] = set()
    for index, row in enumerate(rows):
        filename, size, digest = _comparison_identity(row, f"build artifacts[{index}]")
        if filename.endswith(".whl"):
            seen_suffixes.add("wheel")
        elif filename.endswith(".tar.gz"):
            seen_suffixes.add("sdist")
        else:
            raise BundleModifiedError(
                f"unsupported build comparison artifact type: {filename}"
            )
        if not isinstance(row, dict) or row.get("matches") is not True:
            raise BundleModifiedError(f"build comparison artifact did not match: {filename}")
        if row.get("second_size_bytes") != size or row.get("second_sha256") != digest:
            raise BundleModifiedError(
                f"build comparison second-run identity differs: {filename}"
            )
        if artifacts.get(filename) != (size, digest):
            raise BundleModifiedError(
                f"build comparison identity differs from release manifest: {filename}"
            )
    if seen_suffixes != {"wheel", "sdist"}:
        raise BundleModifiedError("build comparison must cover one wheel and one sdist")

    runs = report.get("runs")
    if not isinstance(runs, list) or len(runs) != 2:
        raise BundleModifiedError("build comparison must contain exactly two runs")
    expected = {
        filename: (size, digest)
        for filename, (size, digest) in artifacts.items()
        if filename.endswith(".whl") or filename.endswith(".tar.gz")
    }
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or run.get("label") not in {"A", "B"}:
            raise BundleModifiedError(f"build comparison run {index} is invalid")
        run_rows = run.get("artifacts")
        if not isinstance(run_rows, list) or len(run_rows) != 2:
            raise BundleModifiedError(f"build comparison run {index} is incomplete")
        actual: dict[str, tuple[int, str]] = {}
        for row_index, row in enumerate(run_rows):
            name, size, digest = _comparison_identity(
                row,
                f"build runs[{index}].artifacts[{row_index}]",
            )
            if name in actual:
                raise BundleModifiedError(f"duplicate build artifact in run {index}: {name}")
            actual[name] = (size, digest)
        if actual != expected:
            raise BundleModifiedError(f"build comparison run {index} differs from manifest")


def _add(
    result: VerificationResult,
    severity: FindingSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> None:
    result.findings.append(
        VerificationFinding(
            severity=severity,
            code=code,
            message=message,
            path=path,
        )
    )


def _record_error(
    result: VerificationResult,
    exc: BundleUnavailableError | BundleModifiedError,
    code: str,
) -> None:
    _add(result, "error", code, str(exc))
    if isinstance(exc, BundleUnavailableError):
        result.status = "unavailable"
    elif result.status != "unavailable":
        result.status = "modified"


def verify_release_bundle(
    bundle: Path | str,
    *,
    expected_repository: str = SOURCE_REPOSITORY,
) -> VerificationResult:
    supplied = Path(bundle).expanduser()
    result = VerificationResult(status="verified", bundle=str(supplied))

    try:
        if supplied.is_symlink():
            raise BundleModifiedError("release bundle directory must not be a symlink")
        root = supplied.resolve(strict=True)
        if not root.is_dir():
            raise BundleUnavailableError("release bundle path is not a directory")
        entries = list(root.iterdir())
        if len(entries) > MAX_BUNDLE_ENTRIES:
            raise BundleModifiedError(
                f"release bundle exceeds the {MAX_BUNDLE_ENTRIES}-entry safety limit"
            )
    except (OSError, BundleUnavailableError, BundleModifiedError) as exc:
        if isinstance(exc, OSError):
            wrapped = BundleUnavailableError(f"cannot access release bundle: {exc}")
        else:
            wrapped = exc
        _record_error(result, wrapped, "bundle.unavailable")
        return result

    try:
        manifest_path = _metadata_path(root, MANIFEST_FILENAME)
        checksums_path = _metadata_path(root, CHECKSUMS_FILENAME)
    except (BundleUnavailableError, BundleModifiedError) as exc:
        _record_error(result, exc, "metadata.required")
        return result

    try:
        manifest = _read_json(manifest_path, "release manifest")
        artifacts, sbom_identity = _manifest_contract(manifest, expected_repository)
        result.source_repository = manifest["source_repository"]
        result.version = manifest["version"]
        result.tag = manifest["tag"]
        result.commit = manifest["commit"]
        result.assurance_level = manifest["assurance_level"]
    except (BundleUnavailableError, BundleModifiedError) as exc:
        _record_error(result, exc, "manifest.invalid")
        return result

    declared = dict(artifacts)
    declared[sbom_identity[0]] = (sbom_identity[1], sbom_identity[2])
    paths: dict[str, Path] = {}
    for filename, (size, digest) in declared.items():
        try:
            path = _declared_file(root, filename)
            _verify_identity(path, size, digest)
            paths[filename] = path
            result.checked_files += 1
        except (BundleUnavailableError, BundleModifiedError) as exc:
            _record_error(result, exc, "artifact.identity")

    try:
        checksums = _parse_checksums(checksums_path)
        expected_names = set(declared)
        if set(checksums) != expected_names:
            missing = sorted(expected_names - set(checksums))
            extra = sorted(set(checksums) - expected_names)
            details: list[str] = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if extra:
                details.append("unexpected: " + ", ".join(extra))
            raise BundleModifiedError(
                "SHA256SUMS coverage differs from the release manifest ("
                + "; ".join(details)
                + ")"
            )
        for filename, (_size, digest) in declared.items():
            if checksums[filename] != digest:
                raise BundleModifiedError(
                    f"SHA256SUMS digest differs from manifest: {filename}"
                )
    except (BundleUnavailableError, BundleModifiedError) as exc:
        _record_error(result, exc, "checksums.invalid")

    sbom_path = paths.get(sbom_identity[0])
    if sbom_path is not None:
        try:
            _verify_sbom(sbom_path)
        except (BundleUnavailableError, BundleModifiedError) as exc:
            _record_error(result, exc, "sbom.invalid")

    report_declared = BUILD_COMPARISON_FILENAME in artifacts
    report_on_disk = (root / BUILD_COMPARISON_FILENAME).exists()
    if report_on_disk and not report_declared:
        _record_error(
            result,
            BundleModifiedError(
                "build-comparison.json exists but is not declared and checksummed"
            ),
            "build_comparison.untrusted",
        )
        result.deterministic_python_distributions = "invalid"
    elif report_declared:
        report_path = paths.get(BUILD_COMPARISON_FILENAME)
        if report_path is None:
            result.deterministic_python_distributions = "invalid"
        else:
            try:
                report = _read_json(report_path, "build comparison report")
                _verify_build_comparison(report, manifest, artifacts)
                result.deterministic_python_distributions = "verified"
            except (BundleUnavailableError, BundleModifiedError) as exc:
                _record_error(result, exc, "build_comparison.invalid")
                result.deterministic_python_distributions = "invalid"

    schema_on_disk = (root / BUILD_COMPARISON_SCHEMA_FILENAME).exists()
    schema_declared = BUILD_COMPARISON_SCHEMA_FILENAME in artifacts
    if schema_on_disk and not schema_declared:
        _record_error(
            result,
            BundleModifiedError(
                "build-comparison.schema.json exists but is not declared and checksummed"
            ),
            "build_comparison_schema.untrusted",
        )
    elif schema_declared and BUILD_COMPARISON_SCHEMA_FILENAME in paths:
        try:
            _read_json(paths[BUILD_COMPARISON_SCHEMA_FILENAME], "build comparison schema")
        except (BundleUnavailableError, BundleModifiedError) as exc:
            _record_error(result, exc, "build_comparison_schema.invalid")

    reserved = {MANIFEST_FILENAME, CHECKSUMS_FILENAME}
    known = set(declared) | reserved
    extras = sorted(entry.name for entry in entries if entry.name not in known)
    if extras:
        _add(
            result,
            "warning",
            "bundle.extra_files",
            "The bundle contains files that are not covered by the manifest: "
            + ", ".join(extras),
        )

    if result.status == "verified":
        if result.deterministic_python_distributions == "verified":
            message = (
                "Bundle identities are internally consistent and deterministic Python "
                "distribution evidence is valid."
            )
        else:
            message = (
                "Bundle identities are internally consistent; deterministic Python "
                "distribution evidence is not included."
            )
        _add(result, "info", "bundle.verified", message)
        _add(
            result,
            "warning",
            "assurance.signature_not_verified",
            "Offline verification does not yet authenticate a detached manifest signature "
            "or hosted provenance attestation.",
        )
    return result
