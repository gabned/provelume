#!/usr/bin/env python3
"""Create and verify an immutable per-run Python build-input wheelhouse manifest."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.deterministic_build import sha256_file

SOURCE_REPOSITORY = "gabned/provelume"
REQUIRED_DIRECT_WHEELS = {
    "build": "1.5.0",
    "hatchling": "1.31.0",
}


class BuildInputBundleError(RuntimeError):
    """Raised when a build-input bundle violates the offline build contract."""


@dataclass(frozen=True, slots=True)
class WheelIdentity:
    name: str
    sha256: str
    size_bytes: int


def _validate_commit(commit: str) -> None:
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise BuildInputBundleError("source commit must be a full lowercase Git SHA-1")


def wheelhouse_identities(wheelhouse: Path) -> dict[str, WheelIdentity]:
    wheelhouse = wheelhouse.resolve()
    if not wheelhouse.is_dir():
        raise BuildInputBundleError(f"wheelhouse does not exist: {wheelhouse}")
    entries = sorted(wheelhouse.iterdir(), key=lambda path: path.name)
    if not entries:
        raise BuildInputBundleError("wheelhouse is empty")

    identities: dict[str, WheelIdentity] = {}
    for path in entries:
        if path.is_symlink():
            raise BuildInputBundleError(f"wheelhouse symlink is not allowed: {path.name}")
        if not path.is_file() or path.suffix.casefold() != ".whl":
            raise BuildInputBundleError(
                f"wheelhouse contains a non-wheel input: {path.name}"
            )
        identity = WheelIdentity(
            name=path.name,
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        identities[path.name] = identity

    lower_names = [name.casefold() for name in identities]
    for distribution, version in REQUIRED_DIRECT_WHEELS.items():
        normalized = distribution.replace("-", "_").casefold()
        accepted_prefixes = (
            f"{distribution.casefold()}-{version}-",
            f"{normalized}-{version}-",
        )
        if not any(name.startswith(accepted_prefixes) for name in lower_names):
            raise BuildInputBundleError(
                f"wheelhouse is missing direct input {distribution}=={version}"
            )
    return identities


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def create_manifest(
    wheelhouse: Path,
    requirements: Path,
    output: Path,
    *,
    commit: str,
) -> dict[str, object]:
    _validate_commit(commit)
    requirements = requirements.resolve()
    if not requirements.is_file():
        raise BuildInputBundleError(f"requirements file does not exist: {requirements}")
    wheels = wheelhouse_identities(wheelhouse)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "assurance_level": "immutable_per_workflow_build_input_wheelhouse",
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": commit,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "cache_tag": sys.implementation.cache_tag,
            "platform": platform.system().lower(),
            "machine": platform.machine().lower(),
        },
        "direct_requirements": {
            "path": requirements.name,
            "sha256": sha256_file(requirements),
        },
        "wheels": [asdict(wheels[name]) for name in sorted(wheels)],
        "limitations": [
            "the transitive closure is resolved for this workflow run rather than "
            "maintained as a reviewed repository lock",
            "the wheelhouse targets the declared Python and runner platform only",
        ],
    }
    _write_json(output, manifest)
    return manifest


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildInputBundleError(f"cannot read build-input manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildInputBundleError("build-input manifest is not a JSON object")
    return value


def _manifest_wheels(manifest: dict[str, Any]) -> dict[str, WheelIdentity]:
    rows = manifest.get("wheels")
    if not isinstance(rows, list) or not rows:
        raise BuildInputBundleError("build-input manifest has no wheel identities")
    identities: dict[str, WheelIdentity] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise BuildInputBundleError("invalid wheel identity in build-input manifest")
        try:
            identity = WheelIdentity(
                name=str(row["name"]),
                sha256=str(row["sha256"]),
                size_bytes=int(row["size_bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BuildInputBundleError(
                "invalid wheel identity in build-input manifest"
            ) from exc
        if identity.name in identities:
            raise BuildInputBundleError(
                f"duplicate wheel identity in manifest: {identity.name}"
            )
        identities[identity.name] = identity
    return identities


def verify_manifest(
    wheelhouse: Path,
    requirements: Path,
    manifest_path: Path,
    *,
    expected_commit: str,
) -> dict[str, Any]:
    _validate_commit(expected_commit)
    requirements = requirements.resolve()
    manifest = _load_manifest(manifest_path)
    schema_version = manifest.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise BuildInputBundleError("unsupported build-input manifest schema")
    if manifest.get("source_repository") != SOURCE_REPOSITORY:
        raise BuildInputBundleError("unexpected source repository in build-input manifest")
    if manifest.get("source_commit") != expected_commit:
        raise BuildInputBundleError("source commit mismatch in build-input manifest")

    direct = manifest.get("direct_requirements")
    if not isinstance(direct, dict):
        raise BuildInputBundleError("missing direct requirements identity")
    if direct.get("path") != requirements.name:
        raise BuildInputBundleError("direct requirements filename mismatch")
    if direct.get("sha256") != sha256_file(requirements):
        raise BuildInputBundleError("direct requirements hash mismatch")

    actual = wheelhouse_identities(wheelhouse)
    declared = _manifest_wheels(manifest)
    if set(actual) != set(declared):
        raise BuildInputBundleError(
            "wheelhouse filenames differ from the build-input manifest"
        )
    for name in sorted(actual):
        if actual[name] != declared[name]:
            raise BuildInputBundleError(f"wheelhouse identity mismatch: {name}")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--wheelhouse", type=Path, required=True)
    create.add_argument("--requirements", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--commit", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--wheelhouse", type=Path, required=True)
    verify.add_argument("--requirements", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--commit", required=True)
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        if options.command == "create":
            manifest = create_manifest(
                options.wheelhouse,
                options.requirements,
                options.output,
                commit=options.commit,
            )
            path = options.output
        else:
            manifest = verify_manifest(
                options.wheelhouse,
                options.requirements,
                options.manifest,
                expected_commit=options.commit,
            )
            path = options.manifest
    except (BuildInputBundleError, OSError) as exc:
        print(f"build-input bundle verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified {len(manifest['wheels'])} build-input wheels: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
