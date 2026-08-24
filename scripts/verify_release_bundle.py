#!/usr/bin/env python3
"""Verify release-manifest identities and the final release assurance gate."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.deterministic_build import sha256_file

SOURCE_REPOSITORY = "gabned/provelume"


class ReleaseBundleError(RuntimeError):
    """Raised when a final release bundle does not match its declared identities."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseBundleError(f"cannot read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseBundleError(f"JSON file must contain one object: {path}")
    return value


def _validate_commit(commit: str) -> None:
    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise ReleaseBundleError("expected commit must be a full lowercase Git SHA-1")


def _safe_flat_name(value: object, source: Path) -> str:
    name = str(value or "")
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not name
        or normalized != name
        or path.is_absolute()
        or len(path.parts) != 1
        or path.name != name
        or name in {".", ".."}
        or re.match(r"^[A-Za-z]:", name)
        or "\x00" in name
    ):
        raise ReleaseBundleError(f"invalid artifact filename in {source}: {name}")
    return name


def _verify_identity(root: Path, row: Any, source: Path) -> str:
    if not isinstance(row, dict):
        raise ReleaseBundleError(f"invalid artifact identity in {source}")
    name = _safe_flat_name(row.get("name"), source)
    path = root / name
    if not path.is_file() or path.is_symlink():
        raise ReleaseBundleError(f"declared artifact is missing or unsafe: {name}")
    try:
        expected_size = int(row["size_bytes"])
        expected_digest = str(row["sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseBundleError(f"invalid artifact identity in {source}: {name}") from exc
    if expected_size <= 0 or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ReleaseBundleError(f"invalid artifact identity in {source}: {name}")
    if path.stat().st_size != expected_size:
        raise ReleaseBundleError(f"artifact size mismatch: {name}")
    if sha256_file(path) != expected_digest:
        raise ReleaseBundleError(f"artifact SHA-256 mismatch: {name}")
    return name


def _verify_checksums(root: Path, path: Path) -> set[str]:
    if not path.is_file() or path.is_symlink():
        raise ReleaseBundleError("SHA256SUMS is missing or unsafe")
    names: set[str] = set()
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", raw)
        if match is None:
            raise ReleaseBundleError(f"invalid SHA256SUMS line {line_number}")
        digest, raw_name = match.groups()
        name = _safe_flat_name(raw_name, path)
        if name in names:
            raise ReleaseBundleError(f"duplicate SHA256SUMS entry: {name}")
        artifact = root / name
        if not artifact.is_file() or artifact.is_symlink():
            raise ReleaseBundleError(
                f"checksummed artifact is missing or unsafe: {name}"
            )
        if sha256_file(artifact) != digest:
            raise ReleaseBundleError(f"SHA256SUMS mismatch: {name}")
        names.add(name)
    if not names:
        raise ReleaseBundleError("SHA256SUMS is empty")
    return names


def _schema_one(payload: dict[str, Any], source: Path) -> None:
    value = payload.get("schema_version")
    if isinstance(value, bool) or value != 1:
        raise ReleaseBundleError(f"unsupported schema in {source}")


def verify_release_bundle(
    root: Path,
    *,
    expected_version: str,
    expected_tag: str,
    expected_commit: str,
) -> dict[str, object]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ReleaseBundleError("release bundle root is not a directory")
    _validate_commit(expected_commit)
    if expected_tag != f"v{expected_version}":
        raise ReleaseBundleError("expected tag/version identity is inconsistent")
    manifest_path = root / "release-manifest.json"
    assurance_path = root / "release-assurance.json"
    manifest = _load_json(manifest_path)
    assurance = _load_json(assurance_path)
    _schema_one(manifest, manifest_path)
    _schema_one(assurance, assurance_path)

    for payload, source in ((manifest, manifest_path), (assurance, assurance_path)):
        if payload.get("source_repository") != SOURCE_REPOSITORY:
            raise ReleaseBundleError(f"unexpected source repository in {source}")
        if payload.get("version") != expected_version:
            raise ReleaseBundleError(f"version mismatch in {source}")
        if payload.get("tag") != expected_tag:
            raise ReleaseBundleError(f"tag mismatch in {source}")
        commit_value = payload.get("commit", payload.get("source_commit"))
        if commit_value != expected_commit:
            raise ReleaseBundleError(f"commit mismatch in {source}")

    if assurance.get("publication_gate") != "passed":
        raise ReleaseBundleError("release assurance publication gate is not passed")

    declared_names: set[str] = set()
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReleaseBundleError("release manifest has no artifacts")
    for row in artifacts:
        name = _verify_identity(root, row, manifest_path)
        if name in declared_names:
            raise ReleaseBundleError(f"duplicate manifest artifact: {name}")
        declared_names.add(name)
    sbom = manifest.get("sbom")
    if sbom is not None:
        name = _verify_identity(root, sbom, manifest_path)
        if name in declared_names:
            raise ReleaseBundleError(f"SBOM duplicates an artifact identity: {name}")
        declared_names.add(name)

    checksum_names = _verify_checksums(root, root / "SHA256SUMS")
    if not declared_names.issubset(checksum_names):
        missing = sorted(declared_names - checksum_names)
        raise ReleaseBundleError(
            f"manifest artifacts are missing from SHA256SUMS: {missing}"
        )

    required = {
        "release-manifest.json",
        "release-assurance.json",
        "deterministic-build-report.json",
        "independent-rebuild-report.json",
        "offline-rebuild-evidence.json",
        "build-input-manifest.json",
        "ubuntu-py312-x86_64.lock.json",
        "ubuntu-py312-x86_64.requirements.txt",
    }
    missing_required = sorted(required - checksum_names)
    if missing_required:
        raise ReleaseBundleError(
            "required assurance files are missing from SHA256SUMS: "
            f"{missing_required}"
        )

    actual_names: set[str] = set()
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ReleaseBundleError(f"release bundle contains an unsafe entry: {path.name}")
        actual_names.add(_safe_flat_name(path.name, root))
    expected_names = checksum_names | {"SHA256SUMS"}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        unexpected = sorted(actual_names - expected_names)
        raise ReleaseBundleError(
            f"release bundle file set differs; missing={missing}, unexpected={unexpected}"
        )

    return {
        "verified": True,
        "version": expected_version,
        "tag": expected_tag,
        "commit": expected_commit,
        "manifest_artifacts": sorted(declared_names),
        "checksummed_artifacts": sorted(checksum_names),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        result = verify_release_bundle(
            options.root,
            expected_version=options.version,
            expected_tag=options.tag,
            expected_commit=options.commit,
        )
    except (ReleaseBundleError, OSError) as exc:
        print(f"release bundle verification failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"verified release bundle {result['tag']} at {result['commit']} "
        f"({len(result['checksummed_artifacts'])} checksummed files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
