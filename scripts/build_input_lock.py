#!/usr/bin/env python3
"""Create and verify the reviewed target-specific Python build-input lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from dataclasses import asdict, dataclass
from email.parser import Parser
from pathlib import Path
from typing import Any, Iterable
from zipfile import BadZipFile, ZipFile

from scripts.deterministic_build import sha256_file

SOURCE_REPOSITORY = "gabned/provelume"
LOCK_SCHEMA_VERSION = 1
TARGET_PYTHON = "3.12.14"
TARGET_IMPLEMENTATION = "CPython"
TARGET_SYSTEM = "linux"
TARGET_MACHINE = "x86_64"


class BuildInputLockError(RuntimeError):
    """Raised when the durable build-input lock contract is not satisfied."""


@dataclass(frozen=True, slots=True)
class DirectRequirement:
    distribution: str
    version: str


@dataclass(frozen=True, slots=True)
class LockedWheel:
    distribution: str
    normalized_distribution: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    requires_dist: tuple[str, ...]


def normalize_distribution(value: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", value).strip("-").casefold()
    if not normalized:
        raise BuildInputLockError("distribution name cannot be empty")
    return normalized


def _validate_full_commit(commit: str) -> None:
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise BuildInputLockError("generated-from commit must be a full lowercase Git SHA-1")


def _machine() -> str:
    value = platform.machine().casefold()
    return "x86_64" if value in {"amd64", "x86_64"} else value


def _target_payload() -> dict[str, str]:
    return {
        "implementation": TARGET_IMPLEMENTATION,
        "python": TARGET_PYTHON,
        "system": TARGET_SYSTEM,
        "machine": TARGET_MACHINE,
    }


def validate_target_environment() -> None:
    actual = {
        "implementation": platform.python_implementation(),
        "python": platform.python_version(),
        "system": platform.system().casefold(),
        "machine": _machine(),
    }
    expected = _target_payload()
    if actual != expected:
        raise BuildInputLockError(
            f"target environment mismatch: expected {expected}, found {actual}"
        )


def parse_direct_requirements(path: Path) -> dict[str, DirectRequirement]:
    path = path.resolve()
    if not path.is_file():
        raise BuildInputLockError(f"direct requirements file does not exist: {path}")
    requirements: dict[str, DirectRequirement] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9!+_.-]+)", line)
        if match is None:
            raise BuildInputLockError(
                f"direct requirement line {line_number} is not an exact pin: {line}"
            )
        distribution = match.group(1)
        normalized = normalize_distribution(distribution)
        requirement = DirectRequirement(distribution=distribution, version=match.group(2))
        if normalized in requirements:
            raise BuildInputLockError(
                f"duplicate direct requirement: {requirement.distribution}"
            )
        requirements[normalized] = requirement
    if not requirements:
        raise BuildInputLockError("direct requirements file is empty")
    return requirements


def _wheel_metadata(path: Path) -> LockedWheel:
    if path.is_symlink():
        raise BuildInputLockError(f"wheel symlink is not allowed: {path.name}")
    if not path.is_file() or path.suffix.casefold() != ".whl":
        raise BuildInputLockError(f"non-wheel build input is not allowed: {path.name}")
    try:
        with ZipFile(path) as archive:
            metadata_names = sorted(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )
            if len(metadata_names) != 1:
                raise BuildInputLockError(
                    f"wheel must contain exactly one METADATA file: {path.name}"
                )
            message = Parser().parsestr(
                archive.read(metadata_names[0]).decode("utf-8")
            )
    except BuildInputLockError:
        raise
    except (BadZipFile, KeyError, UnicodeDecodeError, OSError) as exc:
        raise BuildInputLockError(f"cannot inspect wheel {path.name}: {exc}") from exc

    distribution = str(message.get("Name") or "").strip()
    version = str(message.get("Version") or "").strip()
    if not distribution or not version:
        raise BuildInputLockError(f"wheel metadata lacks name/version: {path.name}")
    return LockedWheel(
        distribution=distribution,
        normalized_distribution=normalize_distribution(distribution),
        version=version,
        filename=path.name,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        requires_dist=tuple(sorted(message.get_all("Requires-Dist") or [])),
    )


def inspect_wheelhouse(path: Path) -> dict[str, LockedWheel]:
    path = path.resolve()
    if not path.is_dir():
        raise BuildInputLockError(f"wheelhouse does not exist: {path}")
    entries = sorted(path.iterdir(), key=lambda item: item.name)
    if not entries:
        raise BuildInputLockError("wheelhouse is empty")
    wheels: dict[str, LockedWheel] = {}
    for entry in entries:
        wheel = _wheel_metadata(entry)
        if wheel.normalized_distribution in wheels:
            previous = wheels[wheel.normalized_distribution]
            raise BuildInputLockError(
                "wheelhouse contains multiple files for distribution "
                f"{wheel.distribution}: {previous.filename}, {wheel.filename}"
            )
        wheels[wheel.normalized_distribution] = wheel
    return wheels


def _validate_direct_requirements(
    direct: dict[str, DirectRequirement],
    wheels: dict[str, LockedWheel],
) -> None:
    for normalized, requirement in direct.items():
        wheel = wheels.get(normalized)
        if wheel is None:
            raise BuildInputLockError(
                f"wheelhouse is missing direct requirement {requirement.distribution}"
            )
        if wheel.version != requirement.version:
            raise BuildInputLockError(
                f"direct requirement mismatch for {requirement.distribution}: "
                f"expected {requirement.version}, found {wheel.version}"
            )


def _lock_material(
    direct_requirements_sha256: str,
    wheels: dict[str, LockedWheel],
) -> dict[str, object]:
    return {
        "target": _target_payload(),
        "direct_requirements_sha256": direct_requirements_sha256,
        "wheels": [asdict(wheels[name]) for name in sorted(wheels)],
    }


def _lock_id(material: dict[str, object]) -> str:
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def render_requirements_lock(
    lock_id: str,
    direct_requirements_sha256: str,
    generated_from_commit: str,
    wheels: dict[str, LockedWheel],
) -> str:
    header = [
        "# Provelume reviewed target build-input lock.",
        "# Generated by: python -m scripts.build_input_lock create",
        f"# Lock ID: {lock_id}",
        f"# Target: {TARGET_SYSTEM}-{TARGET_MACHINE} CPython {TARGET_PYTHON}",
        f"# Direct requirements SHA-256: {direct_requirements_sha256}",
        f"# Generated from public commit: {generated_from_commit}",
        "# Do not edit individual hashes manually; refresh and review the complete lock.",
        "",
    ]
    rows = [
        f"{wheel.distribution}=={wheel.version} --hash=sha256:{wheel.sha256}"
        for wheel in (wheels[name] for name in sorted(wheels))
    ]
    return "\n".join([*header, *rows, ""])


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def create_lock(
    wheelhouse: Path,
    direct_requirements_path: Path,
    json_lock_path: Path,
    requirements_lock_path: Path,
    *,
    generated_from_commit: str,
    enforce_target: bool = True,
) -> dict[str, object]:
    _validate_full_commit(generated_from_commit)
    if enforce_target:
        validate_target_environment()
    direct_requirements_path = direct_requirements_path.resolve()
    direct = parse_direct_requirements(direct_requirements_path)
    wheels = inspect_wheelhouse(wheelhouse)
    _validate_direct_requirements(direct, wheels)
    direct_hash = sha256_file(direct_requirements_path)
    material = _lock_material(direct_hash, wheels)
    lock_id = _lock_id(material)
    payload: dict[str, object] = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "assurance_level": "reviewed_target_build_input_lock",
        "source_repository": SOURCE_REPOSITORY,
        "generated_from_commit": generated_from_commit,
        "lock_id": lock_id,
        **material,
        "limitations": [
            "the lock targets the declared Ubuntu x86_64 / CPython 3.12.14 "
            "package builder",
            "base Python, pip and operating-system runner image identity are declared "
            "outside this wheel lock",
            "platform installers and other package targets require separate locks and "
            "evidence",
        ],
    }
    requirements_content = render_requirements_lock(
        lock_id,
        direct_hash,
        generated_from_commit,
        wheels,
    )
    _atomic_json(json_lock_path, payload)
    _atomic_text(requirements_lock_path, requirements_content)
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildInputLockError(f"cannot read JSON lock {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildInputLockError("JSON lock must contain one object")
    return value


def _declared_wheels(payload: dict[str, Any]) -> dict[str, LockedWheel]:
    rows = payload.get("wheels")
    if not isinstance(rows, list) or not rows:
        raise BuildInputLockError("JSON lock has no wheel identities")
    wheels: dict[str, LockedWheel] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise BuildInputLockError("JSON lock contains an invalid wheel identity")
        try:
            requires_dist_value = row.get("requires_dist") or []
            if not isinstance(requires_dist_value, list):
                raise TypeError("requires_dist must be a list")
            wheel = LockedWheel(
                distribution=str(row["distribution"]),
                normalized_distribution=str(row["normalized_distribution"]),
                version=str(row["version"]),
                filename=str(row["filename"]),
                sha256=str(row["sha256"]),
                size_bytes=int(row["size_bytes"]),
                requires_dist=tuple(str(value) for value in requires_dist_value),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BuildInputLockError(
                "JSON lock contains an invalid wheel identity"
            ) from exc
        if wheel.normalized_distribution != normalize_distribution(wheel.distribution):
            raise BuildInputLockError(
                f"JSON lock has invalid normalized name: {wheel.distribution}"
            )
        if wheel.normalized_distribution in wheels:
            raise BuildInputLockError(
                f"JSON lock duplicates distribution: {wheel.distribution}"
            )
        wheels[wheel.normalized_distribution] = wheel
    return wheels


def verify_lock(
    wheelhouse: Path,
    direct_requirements_path: Path,
    json_lock_path: Path,
    requirements_lock_path: Path,
    *,
    enforce_target: bool = True,
) -> dict[str, Any]:
    if enforce_target:
        validate_target_environment()
    direct_requirements_path = direct_requirements_path.resolve()
    direct = parse_direct_requirements(direct_requirements_path)
    actual_wheels = inspect_wheelhouse(wheelhouse)
    _validate_direct_requirements(direct, actual_wheels)
    payload = _load_json(json_lock_path)
    if payload.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise BuildInputLockError("unsupported JSON lock schema")
    if payload.get("source_repository") != SOURCE_REPOSITORY:
        raise BuildInputLockError("unexpected source repository in JSON lock")
    generated_from_commit = str(payload.get("generated_from_commit") or "")
    _validate_full_commit(generated_from_commit)
    if payload.get("target") != _target_payload():
        raise BuildInputLockError("JSON lock target does not match repository policy")

    direct_hash = sha256_file(direct_requirements_path)
    if payload.get("direct_requirements_sha256") != direct_hash:
        raise BuildInputLockError("direct requirements hash differs from JSON lock")
    declared_wheels = _declared_wheels(payload)
    if actual_wheels != declared_wheels:
        raise BuildInputLockError("resolved wheelhouse differs from JSON lock")

    material = _lock_material(direct_hash, actual_wheels)
    expected_lock_id = _lock_id(material)
    if payload.get("lock_id") != expected_lock_id:
        raise BuildInputLockError("JSON lock ID does not match its contents")
    expected_requirements = render_requirements_lock(
        expected_lock_id,
        direct_hash,
        generated_from_commit,
        actual_wheels,
    )
    try:
        actual_requirements = requirements_lock_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildInputLockError(
            f"cannot read requirements lock {requirements_lock_path}: {exc}"
        ) from exc
    if actual_requirements != expected_requirements:
        raise BuildInputLockError("requirements lock differs from JSON lock")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--wheelhouse", type=Path, required=True)
        command.add_argument("--direct-requirements", type=Path, required=True)
        command.add_argument("--json-lock", type=Path, required=True)
        command.add_argument("--requirements-lock", type=Path, required=True)
        if name == "create":
            command.add_argument("--generated-from-commit", required=True)
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        if options.command == "create":
            payload = create_lock(
                options.wheelhouse,
                options.direct_requirements,
                options.json_lock,
                options.requirements_lock,
                generated_from_commit=options.generated_from_commit,
            )
        else:
            payload = verify_lock(
                options.wheelhouse,
                options.direct_requirements,
                options.json_lock,
                options.requirements_lock,
            )
    except (BuildInputLockError, OSError) as exc:
        print(f"build-input lock failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified build-input lock: {payload['lock_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
