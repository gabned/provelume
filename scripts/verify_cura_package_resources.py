#!/usr/bin/env python3
"""Compare scoped wheel resources with actual frozen files, entirely offline.

This verifies resource parity only. Wheel identity/RECORD, branding, signatures,
runtime behavior and final release qualification retain their existing gates.
No installed or source-checkout provelume module is imported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

# Archive bounds do not exceed the existing release_wheel verifier's bounds.
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20_000
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_RESOURCE_BYTES = 1024 * 1024
MAX_RESOURCE_TOTAL_BYTES = 16 * 1024 * 1024
MAX_RESOURCE_FILES = 4096
SUBTREES = ("templates", "static/icons/lucide", "i18n", "notices")
STATIC_FILES = ("static/cura.css", "static/cura-shell.js")
REQUIRED = {
    *STATIC_FILES,
    "templates/base.html",
    "templates/cura/base.html",
    "i18n/en.json",
    "i18n/it.json",
    "notices/LICENSE",
    "notices/NOTICE.md",
    "notices/THIRD_PARTY_NOTICES.md",
    "notices/lucide-LICENSE.txt",
    "static/icons/lucide/subset.json",
}
RESERVED = {"AUX", "CON", "NUL", "PRN"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


class CuraResourceError(ValueError):
    """The scoped package resources cannot be safely reconciled."""


def _safe_name(name: str) -> str:
    value = name.removesuffix("/")
    path = PurePosixPath(value)
    if (
        not value
        or len(name) > 1024
        or path.is_absolute()
        or path.as_posix() != value
        or any(
            part in {".", ".."}
            or part.endswith((".", " "))
            or part.split(".", 1)[0].upper() in RESERVED
            for part in path.parts
        )
        or any(ord(char) < 32 or char in '\\:*?"<>|' for char in value)
    ):
        raise CuraResourceError("unsafe resource path")
    return value


def _plain_path(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (
            stat.S_ISLNK(info.st_mode)
            or item.is_junction()
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise CuraResourceError("linked or reparse resource path")


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _scoped(name: str) -> bool:
    return name in STATIC_FILES or any(name.startswith(tree + "/") for tree in SUBTREES)


def _wheel_resources(wheel: Path) -> tuple[dict[str, bytes], str]:
    _plain_path(wheel)
    if not wheel.is_file() or not 0 < wheel.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise CuraResourceError("wheel missing or archive byte limit exceeded")
    wheel_sha256 = _sha256(wheel)
    resources: dict[str, bytes] = {}
    with zipfile.ZipFile(wheel) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ARCHIVE_MEMBERS:
            raise CuraResourceError("wheel member limit exceeded")
        seen: set[str] = set()
        expanded = 0
        resource_total = 0
        for info in infos:
            # ZipInfo normalizes Windows separators and truncates at NUL; inspect
            # the original name so that normalization cannot hide unsafe input.
            name = _safe_name(info.orig_filename)
            if name.casefold() in seen:
                raise CuraResourceError("duplicate or case-colliding wheel member")
            seen.add(name.casefold())
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in {0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG}:
                raise CuraResourceError("linked or special wheel member")
            if info.flag_bits & 1:
                raise CuraResourceError("encrypted wheel member")
            expanded += info.file_size
            if (
                expanded > MAX_UNCOMPRESSED_BYTES
                or info.file_size > 64 * 1024 * 1024
                or info.file_size > max(1, info.compress_size) * 200
            ):
                raise CuraResourceError("wheel uncompressed or compression-ratio limit exceeded")
            if info.is_dir() or not name.startswith("provelume/"):
                continue
            relative = name.removeprefix("provelume/")
            if not _scoped(relative):
                continue
            resource_total += info.file_size
            if (
                info.file_size > MAX_RESOURCE_BYTES
                or resource_total > MAX_RESOURCE_TOTAL_BYTES
                or len(resources) >= MAX_RESOURCE_FILES
            ):
                raise CuraResourceError("Cura resource byte or file limit exceeded")
            with archive.open(info) as stream:
                payload = stream.read(MAX_RESOURCE_BYTES + 1)
            if len(payload) != info.file_size:
                raise CuraResourceError("wheel resource size mismatch")
            resources[relative] = payload
    if not resources.keys() >= REQUIRED:
        raise CuraResourceError("wheel missing required Cura resources")
    lucide = {name for name in resources if name.startswith("static/icons/lucide/")}
    if len(lucide) != 19 or sum(name.endswith(".svg") for name in lucide) != 18:
        raise CuraResourceError(
            "wheel must contain 19 Lucide assets plus the required packaged license"
        )
    for tree in ("i18n", "notices"):
        if {name for name in resources if name.startswith(tree + "/")} != {
            name for name in REQUIRED if name.startswith(tree + "/")
        }:
            raise CuraResourceError("wheel has unexpected language or notice resources")
    if _sha256(wheel) != wheel_sha256:
        raise CuraResourceError("wheel changed during verification")
    return resources, wheel_sha256


def _frozen_files(root: Path, expected: set[str]) -> dict[str, Path]:
    _plain_path(root)
    if not root.is_dir():
        raise CuraResourceError("frozen package root missing")
    directories = {str(parent) for name in expected for parent in PurePosixPath(name).parents}
    found: dict[str, Path] = {}
    for tree in SUBTREES:
        start = root / tree
        _plain_path(start)
        if not start.is_dir():
            raise CuraResourceError(f"frozen resource subtree missing: {tree}")
        pending = [start]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    _plain_path(path)
                    relative = path.relative_to(root).as_posix()
                    _safe_name(relative)
                    if entry.is_dir(follow_symlinks=False):
                        if relative not in directories:
                            raise CuraResourceError(f"extra frozen resource directory: {relative}")
                        pending.append(path)
                    elif entry.is_file(follow_symlinks=False) and relative in expected:
                        found[relative] = path
                    else:
                        raise CuraResourceError(f"extra or special frozen resource: {relative}")
    for relative in STATIC_FILES:
        path = root / relative
        _plain_path(path)
        if path.is_file():
            found[relative] = path
    missing = expected - found.keys()
    if missing:
        raise CuraResourceError("missing frozen resources: " + ", ".join(sorted(missing)))
    return found


def verify_cura_resources(wheel: Path, frozen_root: Path) -> dict[str, Any]:
    """Bind exact wheel bytes to a scoped manifest of actual frozen resource bytes."""
    wheel = Path(os.path.abspath(wheel))
    frozen_root = Path(os.path.abspath(frozen_root))
    expected, wheel_sha256 = _wheel_resources(wheel)
    actual = _frozen_files(frozen_root, set(expected))
    rows = []
    for name, payload in sorted(expected.items()):
        path = actual[name]
        if path.stat().st_size != len(payload):
            raise CuraResourceError(f"changed frozen resource: {name}")
        with path.open("rb") as stream:
            frozen_payload = stream.read(MAX_RESOURCE_BYTES + 1)
        if frozen_payload != payload:
            raise CuraResourceError(f"changed frozen resource: {name}")
        rows.append(
            {
                "path": name,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(frozen_payload).hexdigest(),
            }
        )
    _frozen_files(frozen_root, set(expected))
    manifest = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": 1,
        "scope": "cura_package_resource_parity",
        "status": "matched",
        "wheel": {"name": wheel.name, "sha256": wheel_sha256, "size_bytes": wheel.stat().st_size},
        "frozen_root": str(frozen_root),
        "resource_count": len(rows),
        "wheel_resources_sha256": hashlib.sha256(manifest).hexdigest(),
        "frozen_resources_sha256": hashlib.sha256(manifest).hexdigest(),
        "resources": rows,
        "qualification": "resource_parity_only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--frozen-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args(argv)
    try:
        if options.output:
            output = Path(os.path.abspath(options.output))
            _plain_path(output)
            if output == Path(os.path.abspath(options.wheel)) or output.is_relative_to(
                Path(os.path.abspath(options.frozen_root))
            ):
                raise CuraResourceError("output must be outside the compared artifacts")
        result = verify_cura_resources(options.wheel, options.frozen_root)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if options.output:
            options.output.write_text(rendered, encoding="utf-8")
        sys.stdout.write(rendered)
    except (CuraResourceError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
        print(f"Cura package resource verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
