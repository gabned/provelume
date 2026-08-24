#!/usr/bin/env python3
"""Compute and compare bounded Python distribution artifact identities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


class ArtifactIdentityError(RuntimeError):
    """Raised when distribution artifacts are missing, unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """Stable byte identity for one distributable file."""

    name: str
    sha256: str
    size_bytes: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_artifacts(directory: Path) -> dict[str, ArtifactIdentity]:
    """Discover exactly one wheel and one source distribution in a directory."""

    root = directory.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ArtifactIdentityError(f"artifact path is not a directory: {directory}")

    paths: list[Path] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            raise ArtifactIdentityError(f"artifact symlinks are not allowed: {path.name}")
        if not path.is_file():
            continue
        if path.suffix == ".whl" or path.name.endswith(".tar.gz"):
            paths.append(path)

    wheels = [path for path in paths if path.suffix == ".whl"]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ArtifactIdentityError(
            "artifact directory must contain exactly one wheel and one source distribution"
        )

    return {
        path.name: ArtifactIdentity(
            name=path.name,
            sha256=_sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in paths
    }


def compare_artifact_sets(
    expected: dict[str, ArtifactIdentity],
    actual: dict[str, ArtifactIdentity],
) -> list[ArtifactIdentity]:
    """Require equal names, sizes and SHA-256 identities and return sorted identities."""

    if set(expected) != set(actual):
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise ArtifactIdentityError(
            f"artifact filename sets differ; missing={missing}, unexpected={unexpected}"
        )

    identities: list[ArtifactIdentity] = []
    for name in sorted(expected):
        expected_identity = expected[name]
        actual_identity = actual[name]
        if expected_identity.size_bytes != actual_identity.size_bytes:
            raise ArtifactIdentityError(f"artifact size differs: {name}")
        if expected_identity.sha256 != actual_identity.sha256:
            raise ArtifactIdentityError(f"artifact SHA-256 differs: {name}")
        identities.append(expected_identity)
    return identities
