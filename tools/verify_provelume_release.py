#!/usr/bin/env python3
"""Verify a Provelume release bundle offline using the Python standard library.

The verifier performs no network requests. A bundle can prove its own internal
consistency, but it cannot authenticate itself. Supply a manifest SHA-256 from
an independently trusted channel to cryptographically anchor the result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SOURCE_REPOSITORY = "gabned/provelume"
MAX_BUNDLE_FILES = 200
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_CHECKSUM_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
REQUIRED_FILES = {
    "release-manifest.json",
    "SHA256SUMS",
    "release-assurance.json",
    "candidate-identity.json",
    "deterministic-build-report.json",
    "rebuild-deterministic-build-report.json",
    "independent-rebuild-report.json",
    "offline-rebuild-evidence.json",
    "build-input-manifest.json",
    "ubuntu-py312-x86_64.lock.json",
    "ubuntu-py312-x86_64.requirements.txt",
    "verify-provelume-release.py",
}


class VerificationError(RuntimeError):
    """Raised when an offline release bundle is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class Identity:
    name: str
    sha256: str
    size_bytes: int


def _safe_name(value: Any) -> str:
    name = str(value or "")
    if (
        not name
        or len(name) > 255
        or name in {".", ".."}
        or name != name.strip()
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]*", name) is None
    ):
        raise VerificationError(f"unsafe or invalid bundle filename: {name!r}")
    return name


def _safe_file(root: Path, name: str, *, metadata: bool = False) -> Path:
    name = _safe_name(name)
    path = root / name
    if not path.is_file() or path.is_symlink():
        raise VerificationError(f"missing, non-regular or symlinked file: {name}")
    size = path.stat().st_size
    limit = MAX_METADATA_BYTES if metadata else MAX_ARTIFACT_BYTES
    if size > limit:
        raise VerificationError(f"bundle file exceeds the {limit}-byte limit: {name}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> Identity:
    return Identity(path.name, _sha256(path), path.stat().st_size)


def _load_json(root: Path, name: str) -> dict[str, Any]:
    path = _safe_file(root, name, metadata=True)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot parse {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{name} must contain one JSON object")
    return value


def _validate_full_commit(value: Any, *, label: str) -> str:
    commit = str(value or "")
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise VerificationError(f"{label} must be a full lowercase Git SHA-1")
    return commit


def _identity_from_row(row: Any, *, source: str) -> Identity:
    if not isinstance(row, dict):
        raise VerificationError(f"invalid identity in {source}")
    try:
        identity = Identity(
            name=_safe_name(row["name"]),
            sha256=str(row["sha256"]),
            size_bytes=int(row["size_bytes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError(f"invalid identity in {source}") from exc
    if re.fullmatch(r"[0-9a-f]{64}", identity.sha256) is None:
        raise VerificationError(f"invalid SHA-256 in {source}: {identity.name}")
    if identity.size_bytes < 0 or identity.size_bytes > MAX_ARTIFACT_BYTES:
        raise VerificationError(f"invalid size in {source}: {identity.name}")
    return identity


def _identity_map(rows: Any, *, source: str) -> dict[str, Identity]:
    if not isinstance(rows, list) or not rows:
        raise VerificationError(f"{source} has no identities")
    result: dict[str, Identity] = {}
    for row in rows:
        identity = _identity_from_row(row, source=source)
        if identity.name in result:
            raise VerificationError(f"duplicate identity in {source}: {identity.name}")
        result[identity.name] = identity
    return result


def _verify_identity(root: Path, identity: Identity, *, source: str) -> None:
    path = _safe_file(root, identity.name, metadata=identity.name.endswith(".json"))
    actual = _identity(path)
    if actual.size_bytes != identity.size_bytes:
        raise VerificationError(f"size mismatch for {identity.name} declared by {source}")
    if actual.sha256 != identity.sha256:
        raise VerificationError(f"SHA-256 mismatch for {identity.name} declared by {source}")


def _parse_checksums(root: Path) -> dict[str, str]:
    path = _safe_file(root, "SHA256SUMS", metadata=True)
    if path.stat().st_size > MAX_CHECKSUM_BYTES:
        raise VerificationError("SHA256SUMS exceeds its safety limit")
    checksums: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", raw)
        if match is None:
            raise VerificationError(f"invalid SHA256SUMS line {line_number}")
        digest, raw_name = match.groups()
        name = _safe_name(raw_name)
        if name in checksums:
            raise VerificationError(f"duplicate SHA256SUMS entry: {name}")
        checksums[name] = digest
    if not checksums or len(checksums) > MAX_BUNDLE_FILES:
        raise VerificationError("SHA256SUMS has an invalid number of entries")
    for name, expected in checksums.items():
        path = _safe_file(root, name, metadata=name.endswith(".json"))
        if _sha256(path) != expected:
            raise VerificationError(f"SHA256SUMS mismatch: {name}")
    return checksums


def _common_identity(
    payload: dict[str, Any],
    *,
    source: str,
    version: str,
    tag: str,
    commit: str,
) -> None:
    if payload.get("source_repository") != SOURCE_REPOSITORY:
        raise VerificationError(f"unexpected source repository in {source}")
    if payload.get("version") != version:
        raise VerificationError(f"version mismatch in {source}")
    if payload.get("tag") != tag:
        raise VerificationError(f"tag mismatch in {source}")
    payload_commit = payload.get("commit", payload.get("source_commit"))
    if payload_commit != commit:
        raise VerificationError(f"commit mismatch in {source}")


def _verify_report(
    payload: dict[str, Any],
    *,
    source: str,
    commit: str,
    source_epoch: int,
    package_identities: dict[str, Identity],
    field: str,
    deterministic: bool = False,
) -> None:
    if payload.get("schema_version") != 1:
        raise VerificationError(f"{source} is not a schema-1 report")
    rows = payload.get(field)
    if deterministic:
        if (
            payload.get("assurance")
            != "same-source-same-environment-byte-identical"
            or payload.get("full_release_reproducibility_claimed") is not False
            or not isinstance(rows, list)
            or any(
                not isinstance(row, dict) or row.get("byte_identical") is not True
                for row in rows
            )
        ):
            raise VerificationError(f"{source} is not a green deterministic report")
    elif payload.get("byte_identical") is not True:
        raise VerificationError(f"{source} is not a green rebuild report")
    if payload.get("source_repository") != SOURCE_REPOSITORY:
        raise VerificationError(f"unexpected source repository in {source}")
    if payload.get("source_commit") != commit:
        raise VerificationError(f"source commit mismatch in {source}")
    try:
        epoch = int(payload["source_date_epoch"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError(f"invalid source epoch in {source}") from exc
    if epoch != source_epoch:
        raise VerificationError(f"source epoch mismatch in {source}")
    declared = _identity_map(rows, source=f"{source}:{field}")
    if declared != package_identities:
        raise VerificationError(f"package identities differ in {source}")


def _normalize_distribution(value: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", value).strip("-").casefold()
    if not normalized:
        raise VerificationError("empty distribution name in build lock")
    return normalized


def _verify_build_lock(
    root: Path, assurance: dict[str, Any], commit: str
) -> tuple[str, dict[str, Identity]]:
    lock = _load_json(root, "ubuntu-py312-x86_64.lock.json")
    if lock.get("schema_version") != 1 or lock.get("source_repository") != SOURCE_REPOSITORY:
        raise VerificationError("unsupported or foreign build-input lock")
    _validate_full_commit(lock.get("generated_from_commit"), label="lock generation commit")
    lock_id = str(lock.get("lock_id") or "")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", lock_id) is None:
        raise VerificationError("invalid build-input lock ID")
    material = {
        "target": lock.get("target"),
        "direct_requirements_sha256": lock.get("direct_requirements_sha256"),
        "wheels": lock.get("wheels"),
    }
    computed = "sha256:" + hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if computed != lock_id:
        raise VerificationError("build-input lock ID does not match its contents")

    build_lock = assurance.get("build_lock")
    if not isinstance(build_lock, dict) or build_lock.get("lock_id") != lock_id:
        raise VerificationError("release assurance references another build lock")
    if build_lock.get("target") != lock.get("target"):
        raise VerificationError("release assurance build-lock target mismatch")

    wheel_rows = lock.get("wheels")
    if not isinstance(wheel_rows, list) or not wheel_rows:
        raise VerificationError("build-input lock has no wheels")
    wheel_identities: dict[str, Identity] = {}
    lock_packages: dict[str, tuple[str, str]] = {}
    for row in wheel_rows:
        if not isinstance(row, dict):
            raise VerificationError("invalid wheel row in build-input lock")
        try:
            filename = _safe_name(row["filename"])
            identity = Identity(filename, str(row["sha256"]), int(row["size_bytes"]))
            distribution = str(row["distribution"])
            version = str(row["version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VerificationError("invalid wheel row in build-input lock") from exc
        if re.fullmatch(r"[0-9a-f]{64}", identity.sha256) is None:
            raise VerificationError(f"invalid locked wheel hash: {filename}")
        normalized = _normalize_distribution(distribution)
        if normalized in lock_packages or filename in wheel_identities:
            raise VerificationError("duplicate wheel/distribution in build-input lock")
        lock_packages[normalized] = (version, identity.sha256)
        wheel_identities[filename] = identity

    requirements = _safe_file(
        root, "ubuntu-py312-x86_64.requirements.txt", metadata=True
    ).read_text(encoding="utf-8")
    requirements_packages: dict[str, tuple[str, str]] = {}
    for raw in requirements.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9_.-]+)==([A-Za-z0-9!+_.-]+) --hash=sha256:([0-9a-f]{64})",
            line,
        )
        if match is None:
            raise VerificationError("invalid reviewed requirements-lock line")
        name, version, digest = match.groups()
        normalized = _normalize_distribution(name)
        if normalized in requirements_packages:
            raise VerificationError("duplicate distribution in requirements lock")
        requirements_packages[normalized] = (version, digest)
    if requirements_packages != lock_packages:
        raise VerificationError("JSON and requirements build locks differ")

    manifest = _load_json(root, "build-input-manifest.json")
    if manifest.get("source_repository") != SOURCE_REPOSITORY:
        raise VerificationError("foreign per-run build-input manifest")
    if manifest.get("source_commit") != commit:
        raise VerificationError("build-input manifest commit mismatch")
    if manifest.get("direct_requirements", {}).get("sha256") != lock.get(
        "direct_requirements_sha256"
    ):
        raise VerificationError("direct requirements hash mismatch")
    manifest_wheels = _identity_map(
        manifest.get("wheels"), source="build-input-manifest.json:wheels"
    )
    if manifest_wheels != wheel_identities:
        raise VerificationError("per-run wheel manifest differs from reviewed lock")
    return lock_id, wheel_identities


def verify_bundle(
    root: Path,
    *,
    expected_manifest_sha256: str | None = None,
    expected_version: str | None = None,
    expected_tag: str | None = None,
    expected_commit: str | None = None,
) -> dict[str, object]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise VerificationError(f"release root is not a directory: {root}")
    entries = sorted(root.iterdir(), key=lambda item: item.name)
    if len(entries) > MAX_BUNDLE_FILES:
        raise VerificationError("release bundle contains too many files")
    for entry in entries:
        if entry.is_symlink():
            raise VerificationError(f"release bundle contains a symlinked file: {entry.name}")
        if not entry.is_file():
            raise VerificationError(
                f"release bundle must be flat regular files only: {entry.name}"
            )

    missing = sorted(name for name in REQUIRED_FILES if not (root / name).is_file())
    if missing:
        raise VerificationError(f"required release files are missing: {missing}")
    checksums = _parse_checksums(root)
    manifest_path = _safe_file(root, "release-manifest.json", metadata=True)
    manifest_digest = _sha256(manifest_path)
    if expected_manifest_sha256 is not None:
        anchor = expected_manifest_sha256.casefold()
        if re.fullmatch(r"[0-9a-f]{64}", anchor) is None:
            raise VerificationError("expected manifest SHA-256 is invalid")
        if manifest_digest != anchor:
            raise VerificationError("release manifest does not match trusted SHA-256")

    manifest = _load_json(root, "release-manifest.json")
    assurance = _load_json(root, "release-assurance.json")
    version = str(manifest.get("version") or "")
    tag = str(manifest.get("tag") or "")
    commit = _validate_full_commit(manifest.get("commit"), label="manifest commit")
    channel = str(manifest.get("channel") or "")
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None or tag != f"v{version}":
        raise VerificationError("release manifest version/tag identity is invalid")
    if expected_version is not None and version != expected_version:
        raise VerificationError("release version differs from external expectation")
    if expected_tag is not None and tag != expected_tag:
        raise VerificationError("release tag differs from external expectation")
    if expected_commit is not None and commit != _validate_full_commit(
        expected_commit, label="expected commit"
    ):
        raise VerificationError("release commit differs from external expectation")
    _common_identity(
        manifest,
        source="release-manifest.json",
        version=version,
        tag=tag,
        commit=commit,
    )
    _common_identity(
        assurance,
        source="release-assurance.json",
        version=version,
        tag=tag,
        commit=commit,
    )
    if assurance.get("schema_version") != 1 or assurance.get(
        "publication_gate"
    ) != "passed":
        raise VerificationError("release assurance publication gate is not passed")
    if assurance.get("channel") != channel:
        raise VerificationError("release assurance channel mismatch")
    try:
        source_epoch = int(assurance["source_date_epoch"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError("release assurance source epoch is invalid") from exc
    if source_epoch <= 0:
        raise VerificationError("release assurance source epoch must be positive")

    manifest_identities = _identity_map(
        manifest.get("artifacts"), source="release-manifest.json:artifacts"
    )
    sbom_row = manifest.get("sbom")
    if sbom_row is not None:
        sbom = _identity_from_row(sbom_row, source="release-manifest.json:sbom")
        if sbom.name in manifest_identities:
            raise VerificationError("SBOM duplicates a manifest artifact")
        manifest_identities[sbom.name] = sbom
    for identity in manifest_identities.values():
        _verify_identity(root, identity, source="release-manifest.json")
        if checksums.get(identity.name) != identity.sha256:
            raise VerificationError(
                f"manifest identity is missing/different in SHA256SUMS: {identity.name}"
            )

    package_identities = _identity_map(
        assurance.get("package_artifacts"), source="release-assurance.json:package_artifacts"
    )
    for identity in package_identities.values():
        _verify_identity(root, identity, source="release-assurance.json")
        if manifest_identities.get(identity.name) != identity:
            raise VerificationError("release assurance package differs from manifest")

    evidence_identities = _identity_map(
        assurance.get("evidence"), source="release-assurance.json:evidence"
    )
    for identity in evidence_identities.values():
        _verify_identity(root, identity, source="release-assurance.json")
        if manifest_identities.get(identity.name) != identity:
            raise VerificationError("release assurance evidence differs from manifest")

    lock_id, locked_wheels = _verify_build_lock(root, assurance, commit)
    deterministic = _load_json(root, "deterministic-build-report.json")
    rebuild = _load_json(root, "rebuild-deterministic-build-report.json")
    independent = _load_json(root, "independent-rebuild-report.json")
    offline = _load_json(root, "offline-rebuild-evidence.json")
    _verify_report(
        deterministic,
        source="deterministic-build-report.json",
        commit=commit,
        source_epoch=source_epoch,
        package_identities=package_identities,
        field="artifacts",
        deterministic=True,
    )
    _verify_report(
        rebuild,
        source="rebuild-deterministic-build-report.json",
        commit=commit,
        source_epoch=source_epoch,
        package_identities=package_identities,
        field="artifacts",
        deterministic=True,
    )
    _verify_report(
        independent,
        source="independent-rebuild-report.json",
        commit=commit,
        source_epoch=source_epoch,
        package_identities=package_identities,
        field="artifacts",
    )
    _verify_report(
        offline,
        source="offline-rebuild-evidence.json",
        commit=commit,
        source_epoch=source_epoch,
        package_identities=package_identities,
        field="package_artifacts",
    )
    bundle = offline.get("build_input_bundle")
    if not isinstance(bundle, dict):
        raise VerificationError("offline evidence has no build-input bundle")
    if bundle.get("installation_mode") != "pip --no-index --find-links verified-wheelhouse":
        raise VerificationError("offline evidence does not prove offline installation")
    if bundle.get("manifest") != "build-input-manifest.json" or bundle.get(
        "manifest_sha256"
    ) != _sha256(root / "build-input-manifest.json"):
        raise VerificationError("offline evidence manifest identity mismatch")
    if _identity_map(bundle.get("wheels"), source="offline wheel identities") != locked_wheels:
        raise VerificationError("offline evidence wheel set differs from reviewed lock")

    candidate = _load_json(root, "candidate-identity.json")
    _common_identity(
        candidate,
        source="candidate-identity.json",
        version=version,
        tag=tag,
        commit=commit,
    )
    if candidate.get("channel") != channel or candidate.get("build_lock_id") != lock_id:
        raise VerificationError("candidate identity differs from release assurance")
    if int(candidate.get("source_date_epoch", 0)) != source_epoch:
        raise VerificationError("candidate source epoch mismatch")

    tracked = set(manifest_identities) | {"release-manifest.json", "SHA256SUMS"}
    actual_names = {entry.name for entry in entries}
    extras = sorted(actual_names - tracked)
    missing_tracked = sorted(tracked - actual_names)
    if extras or missing_tracked:
        raise VerificationError(
            f"bundle file set differs from manifest: extras={extras}, missing={missing_tracked}"
        )

    anchored = expected_manifest_sha256 is not None
    return {
        "verified": True,
        "result": (
            "externally_anchored_bundle_verified"
            if anchored
            else "self_consistency_verified"
        ),
        "origin_authentication": (
            "trusted_release_manifest_sha256"
            if anchored
            else "not_established_by_bundle_alone"
        ),
        "network_used": False,
        "source_repository": SOURCE_REPOSITORY,
        "version": version,
        "tag": tag,
        "channel": channel,
        "source_commit": commit,
        "release_manifest_sha256": manifest_digest,
        "build_lock_id": lock_id,
        "package_artifacts": [
            asdict(package_identities[name]) for name in sorted(package_identities)
        ],
        "checksummed_file_count": len(checksums),
        "limitations": [
            "bundle self-consistency does not authenticate official origin without an "
            "externally trusted manifest hash or future signature",
            "GitHub/Sigstore attestations are not checked by this offline standard-library tool",
            "the current evidence covers the declared Python package release target",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-tag")
    parser.add_argument("--expected-commit")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        result = verify_bundle(
            options.root,
            expected_manifest_sha256=options.expected_manifest_sha256,
            expected_version=options.expected_version,
            expected_tag=options.expected_tag,
            expected_commit=options.expected_commit,
        )
    except (VerificationError, OSError) as exc:
        if options.json_output:
            print(json.dumps({"verified": False, "error": str(exc)}, sort_keys=True))
        else:
            print(f"Provelume release verification failed: {exc}", file=sys.stderr)
        return 1
    if options.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Result: {result['result']}")
        print(f"Version: {result['version']} ({result['tag']})")
        print(f"Commit: {result['source_commit']}")
        print(f"Manifest SHA-256: {result['release_manifest_sha256']}")
        print(f"Origin authentication: {result['origin_authentication']}")
        print("Network used: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
