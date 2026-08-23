#!/usr/bin/env python3
"""Generate or validate Provelume's hash-locked Python build toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import stat
import sys
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Sequence
from zipfile import BadZipFile, ZipFile

LOCK_SCHEMA_VERSION = 1
MAX_WHEELS = 256
MAX_WHEEL_BYTES = 100 * 1024 * 1024
PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NORMALIZE_NAME = re.compile(r"[-_.]+")


class BuildInputLockError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LockedProject:
    name: str
    version: str
    hashes: tuple[str, ...]


def _normalise_name(value: str) -> str:
    return NORMALIZE_NAME.sub("-", value).casefold()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_wheel_member(value: str) -> PurePosixPath:
    if not value or "\x00" in value or "\\" in value:
        raise BuildInputLockError(f"wheel contains an unsafe member name: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {".", ".."}:
        raise BuildInputLockError(f"wheel contains an unsafe member path: {value!r}")
    return path


def _is_symlink(external_attr: int) -> bool:
    mode = (external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


def _wheel_project(path: Path) -> tuple[str, str]:
    if path.suffix != ".whl":
        raise BuildInputLockError(f"build input is not a wheel: {path.name}")
    if path.is_symlink() or not path.is_file():
        raise BuildInputLockError(f"build input is unavailable or a symlink: {path.name}")
    if path.stat().st_size > MAX_WHEEL_BYTES:
        raise BuildInputLockError(
            f"build input exceeds the {MAX_WHEEL_BYTES}-byte limit: {path.name}"
        )
    try:
        with ZipFile(path) as archive:
            metadata_members = []
            for info in archive.infolist():
                member = _safe_wheel_member(info.filename)
                if _is_symlink(info.external_attr):
                    raise BuildInputLockError(
                        f"wheel contains a symlink member: {path.name}:{member}"
                    )
                if member.as_posix().endswith(".dist-info/METADATA"):
                    metadata_members.append(info)
            if len(metadata_members) != 1:
                raise BuildInputLockError(
                    f"wheel must contain exactly one .dist-info/METADATA: {path.name}"
                )
            message = BytesParser().parsebytes(archive.read(metadata_members[0]))
    except BadZipFile as exc:
        raise BuildInputLockError(f"build input is not a valid wheel: {path.name}") from exc
    except OSError as exc:
        raise BuildInputLockError(f"cannot read build input wheel: {path.name}") from exc

    name = message.get("Name")
    version = message.get("Version")
    if not name or not PROJECT_NAME.fullmatch(name):
        raise BuildInputLockError(f"wheel METADATA has an invalid Name: {path.name}")
    if not version or not VERSION.fullmatch(version):
        raise BuildInputLockError(f"wheel METADATA has an invalid Version: {path.name}")
    return name, version


def _direct_requirements(path: Path) -> dict[str, tuple[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BuildInputLockError(f"cannot read direct requirements: {path}") from exc
    requirements: dict[str, tuple[str, str]] = {}
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line or any(token in line for token in (";", "[", "]", "@")):
            raise BuildInputLockError(
                f"direct requirement line {number} must be an exact name==version pin"
            )
        name, version = line.split("==", 1)
        if not PROJECT_NAME.fullmatch(name) or not VERSION.fullmatch(version):
            raise BuildInputLockError(f"invalid direct requirement line {number}")
        normalized = _normalise_name(name)
        if normalized in requirements:
            raise BuildInputLockError(f"duplicate direct requirement: {name}")
        requirements[normalized] = (name, version)
    if not requirements:
        raise BuildInputLockError("direct requirements contain no package pins")
    return requirements


def _requirements_digest(path: Path) -> str:
    try:
        return _sha256_file(path)
    except OSError as exc:
        raise BuildInputLockError(f"cannot hash direct requirements: {path}") from exc


def projects_from_wheelhouse(wheelhouse: Path) -> list[LockedProject]:
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise BuildInputLockError("build-input wheelhouse is unavailable or a symlink")
    paths = sorted(path for path in wheelhouse.iterdir() if path.is_file())
    if not paths:
        raise BuildInputLockError("build-input wheelhouse is empty")
    if len(paths) > MAX_WHEELS:
        raise BuildInputLockError(
            f"build-input wheelhouse exceeds the {MAX_WHEELS}-wheel limit"
        )

    grouped: dict[str, tuple[str, str, set[str]]] = {}
    for path in paths:
        name, version = _wheel_project(path)
        normalized = _normalise_name(name)
        digest = _sha256_file(path)
        existing = grouped.get(normalized)
        if existing is None:
            grouped[normalized] = (name, version, {digest})
            continue
        existing_name, existing_version, hashes = existing
        if existing_version != version:
            raise BuildInputLockError(
                f"wheelhouse contains conflicting versions for {existing_name}"
            )
        hashes.add(digest)

    return [
        LockedProject(name=name, version=version, hashes=tuple(sorted(hashes)))
        for _normalized, (name, version, hashes) in sorted(grouped.items())
    ]


def render_lock(
    projects: list[LockedProject],
    *,
    direct_requirements: Path,
    target_python: str,
    target_platform: str,
) -> str:
    direct = _direct_requirements(direct_requirements)
    by_name = {_normalise_name(project.name): project for project in projects}
    for normalized, (name, version) in direct.items():
        project = by_name.get(normalized)
        if project is None:
            raise BuildInputLockError(f"direct build requirement is missing: {name}")
        if project.version != version:
            raise BuildInputLockError(
                f"direct build requirement resolved to {project.version}, expected {version}: {name}"
            )

    header = [
        "# Provelume Python build-input lock",
        f"# lock-schema-version: {LOCK_SCHEMA_VERSION}",
        f"# target-python: {target_python}",
        f"# target-platform: {target_platform}",
        f"# direct-requirements-sha256: {_requirements_digest(direct_requirements)}",
        "# Generated from wheel METADATA; every accepted artifact is SHA-256 pinned.",
        "",
    ]
    rows = []
    for project in projects:
        hashes = " ".join(f"--hash=sha256:{digest}" for digest in project.hashes)
        rows.append(f"{project.name}=={project.version} {hashes}")
    return "\n".join([*header, *rows, ""])


def generate_lock(
    wheelhouse: Path,
    output: Path,
    *,
    direct_requirements: Path,
    target_python: str,
    target_platform: str,
) -> None:
    content = render_lock(
        projects_from_wheelhouse(wheelhouse),
        direct_requirements=direct_requirements,
        target_python=target_python,
        target_platform=target_platform,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def _header_value(lines: list[str], key: str) -> str:
    prefix = f"# {key}: "
    matches = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    if len(matches) != 1 or not matches[0]:
        raise BuildInputLockError(f"lock must contain exactly one {key} header")
    return matches[0]


def parse_lock(path: Path) -> tuple[dict[str, str], list[LockedProject]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BuildInputLockError(f"cannot read build-input lock: {path}") from exc
    headers = {
        "lock-schema-version": _header_value(lines, "lock-schema-version"),
        "target-python": _header_value(lines, "target-python"),
        "target-platform": _header_value(lines, "target-platform"),
        "direct-requirements-sha256": _header_value(
            lines,
            "direct-requirements-sha256",
        ),
    }
    if headers["lock-schema-version"] != str(LOCK_SCHEMA_VERSION):
        raise BuildInputLockError("unsupported build-input lock schema version")
    if not SHA256.fullmatch(headers["direct-requirements-sha256"]):
        raise BuildInputLockError("lock direct-requirements digest is invalid")

    projects: list[LockedProject] = []
    seen: set[str] = set()
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = shlex.split(line)
        if not parts or "==" not in parts[0]:
            raise BuildInputLockError(f"lock line {number} has no exact package pin")
        name, version = parts[0].split("==", 1)
        if not PROJECT_NAME.fullmatch(name) or not VERSION.fullmatch(version):
            raise BuildInputLockError(f"lock line {number} has an invalid package pin")
        normalized = _normalise_name(name)
        if normalized in seen:
            raise BuildInputLockError(f"duplicate locked project: {name}")
        seen.add(normalized)
        hashes = []
        for token in parts[1:]:
            prefix = "--hash=sha256:"
            if not token.startswith(prefix) or not SHA256.fullmatch(token[len(prefix) :]):
                raise BuildInputLockError(f"lock line {number} has an invalid hash token")
            hashes.append(token[len(prefix) :])
        if not hashes or len(hashes) != len(set(hashes)):
            raise BuildInputLockError(f"lock line {number} has missing or duplicate hashes")
        projects.append(
            LockedProject(
                name=name,
                version=version,
                hashes=tuple(sorted(hashes)),
            )
        )
    if not projects:
        raise BuildInputLockError("build-input lock contains no package pins")
    return headers, projects


def check_lock(path: Path, *, direct_requirements: Path) -> dict[str, object]:
    headers, projects = parse_lock(path)
    actual_direct_digest = _requirements_digest(direct_requirements)
    if headers["direct-requirements-sha256"] != actual_direct_digest:
        raise BuildInputLockError(
            "build-input lock was generated from different direct requirements"
        )
    direct = _direct_requirements(direct_requirements)
    by_name = {_normalise_name(project.name): project for project in projects}
    for normalized, (name, version) in direct.items():
        project = by_name.get(normalized)
        if project is None or project.version != version:
            raise BuildInputLockError(
                f"build-input lock does not contain the direct pin {name}=={version}"
            )
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "status": "valid",
        "target_python": headers["target-python"],
        "target_platform": headers["target-platform"],
        "direct_requirements_sha256": actual_direct_digest,
        "projects": len(projects),
        "artifact_hashes": sum(len(project.hashes) for project in projects),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    subparsers = value.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--wheelhouse", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--direct", type=Path, default=Path("requirements-build.txt"))
    generate.add_argument("--target-python", required=True)
    generate.add_argument("--target-platform", required=True)

    check = subparsers.add_parser("check")
    check.add_argument("--lock", type=Path, default=Path("requirements-build.lock"))
    check.add_argument("--direct", type=Path, default=Path("requirements-build.txt"))
    check.add_argument("--json", action="store_true")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "generate":
            generate_lock(
                arguments.wheelhouse,
                arguments.output,
                direct_requirements=arguments.direct,
                target_python=arguments.target_python,
                target_platform=arguments.target_platform,
            )
            print(f"wrote build-input lock: {arguments.output}")
        else:
            result = check_lock(
                arguments.lock,
                direct_requirements=arguments.direct,
            )
            if arguments.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(
                    "valid build-input lock: "
                    f"{result['projects']} projects / {result['artifact_hashes']} hashes"
                )
    except (BuildInputLockError, OSError) as exc:
        print(f"build-input lock error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
