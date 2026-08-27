#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SOURCE_REPOSITORY = "gabned/provelume"
SCHEMA_VERSION = 1
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,254}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_windows_update_manifest(
    *,
    installer: Path,
    version: str,
    tag: str,
    channel: str,
    commit: str,
    minimum_windows_build: int = 19045,
) -> dict[str, Any]:
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise ValueError("version must use exact X.Y.Z syntax")
    if tag != f"v{version}":
        raise ValueError("tag must match the Windows package version")
    if channel not in {"development", "preview", "stable"}:
        raise ValueError("unsupported Windows package channel")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("commit must be a full lowercase Git SHA-1")
    if (
        installer.is_symlink()
        or not installer.is_file()
        or installer.stat().st_size <= 0
        or SAFE_NAME.fullmatch(installer.name) is None
    ):
        raise ValueError("Windows installer is missing, unsafe or empty")
    if type(minimum_windows_build) is not int or minimum_windows_build < 19045:
        raise ValueError("minimum Windows build is below the supported baseline")
    return {
        "schema_version": SCHEMA_VERSION,
        "source_repository": SOURCE_REPOSITORY,
        "version": version,
        "tag": tag,
        "commit": commit,
        "channel": channel,
        "artifact": {
            "name": installer.name,
            "sha256": sha256_file(installer),
            "size_bytes": installer.stat().st_size,
            "platform": "windows",
            "architecture": "x86_64",
            "installer_type": "inno_setup",
            "minimum_windows_build": minimum_windows_build,
            "automatic_apply": False,
        },
        "trust": {
            "publisher_authentication": "not_established",
            "platform_signature": "unsigned_preview",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Windows preview update metadata")
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-windows-build", type=int, default=19045)
    options = parser.parse_args()
    payload = build_windows_update_manifest(
        installer=options.installer,
        version=options.version,
        tag=options.tag,
        channel=options.channel,
        commit=options.commit,
        minimum_windows_build=options.minimum_windows_build,
    )
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
