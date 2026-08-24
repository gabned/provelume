#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from datetime import UTC, datetime
from pathlib import Path

SOURCE_REPOSITORY = "gabned/provelume"
SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: Path) -> dict[str, object]:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "name": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "media_type": media_type,
    }


def build_manifest(
    *,
    version: str,
    tag: str,
    commit: str,
    channel: str,
    artifacts: list[Path],
    sbom: Path,
    built_at: str | None = None,
) -> dict[str, object]:
    if tag != f"v{version}":
        raise ValueError("release tag must equal v<package version>")
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise ValueError("commit must be a lowercase 40-character SHA-1")
    if channel not in {"stable", "preview", "development"}:
        raise ValueError("unsupported release channel")
    if not artifacts:
        raise ValueError("at least one release artifact is required")
    for path in [*artifacts, sbom]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"release input is missing, unsafe or empty: {path}")

    timestamp = built_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "tag": tag,
        "commit": commit,
        "source_repository": SOURCE_REPOSITORY,
        "channel": channel,
        "built_at": timestamp,
        "artifacts": [artifact_record(path) for path in sorted(artifacts)],
        "sbom": {
            "name": sbom.name,
            "sha256": sha256_file(sbom),
            "size_bytes": sbom.stat().st_size,
            "format": "cyclonedx-json",
        },
    }


def write_checksums(paths: list[Path], destination: Path) -> None:
    rows = [f"{sha256_file(path)}  {path.name}" for path in sorted(paths)]
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Provelume release metadata")
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--artifact", action="append", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checksums", type=Path, required=True)
    args = parser.parse_args()

    manifest = build_manifest(
        version=args.version,
        tag=args.tag,
        commit=args.commit,
        channel=args.channel,
        artifacts=args.artifact,
        sbom=args.sbom,
        built_at=os.environ.get("PROVELUME_BUILD_TIMESTAMP"),
    )
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_checksums([*args.artifact, args.sbom, args.manifest], args.checksums)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
