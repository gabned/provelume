"""Produce publication evidence from an observed public event, never from build time."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from provelume.publication import (
    MAX_PAYLOAD_BYTES,
    MAX_RECEIPT_BYTES,
    SOURCE_REPOSITORY,
    PublicationError,
    _identity,
    artifact_identity,
    canonical_bytes,
    decode_json,
    file_identity,
    parse_receipt,
    read_metadata,
    timestamp,
    utc_text,
    write_once,
)


def create_receipt(
    release: dict,
    *,
    bundle: Path,
    resolved_commit: str,
    observed_at: str,
    existing: bytes | None = None,
) -> bytes:
    manifest_path = bundle / "release-manifest.json"
    manifest = decode_json(read_metadata(manifest_path))
    _identity(manifest)
    if release.get("draft") is not False or type(release.get("prerelease")) is not bool:
        raise PublicationError("publication event is not a public release")
    if manifest.get("commit") != resolved_commit:
        raise PublicationError("observed tag commit differs from qualified source")
    if release.get("tag_name") != manifest.get("tag"):
        raise PublicationError("observed release tag differs")
    if ("preview" if release["prerelease"] else "stable") != manifest.get("channel"):
        raise PublicationError("observed release channel differs")
    assets = release.get("assets")
    if not isinstance(assets, list) or len(assets) > 300:
        raise PublicationError("observed asset inventory is invalid")
    inventory = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise PublicationError("observed asset row is invalid")
        key = asset["name"].casefold()
        if key in inventory:
            raise PublicationError("observed release assets collide")
        inventory[key] = asset
    identities = []
    declared = manifest.get("artifacts")
    if not isinstance(declared, list) or not isinstance(manifest.get("sbom"), dict):
        raise PublicationError("qualified manifest artifacts are invalid")
    for item in [*declared, manifest["sbom"]]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise PublicationError("qualified manifest artifact is invalid")
        # Validate the untrusted name before constructing a filesystem path.
        expected = artifact_identity(
            {key: item.get(key) for key in ("name", "sha256", "size_bytes")}
        )
        actual = file_identity(bundle / expected["name"])
        if actual != expected:
            raise PublicationError("qualified artifact bytes differ")
        identities.append(actual)
    identities.append(file_identity(bundle / "SHA256SUMS"))
    manifest_identity = file_identity(manifest_path)
    for identity in [manifest_identity, *identities]:
        asset = inventory.get(identity["name"].casefold())
        if (
            not asset
            or asset.get("state") != "uploaded"
            or asset.get("size") != identity["size_bytes"]
        ):
            raise PublicationError("published qualified asset is missing or differs")
        if asset.get("digest") not in (None, "sha256:" + identity["sha256"]):
            raise PublicationError("published qualified asset digest differs")
    value = parse_receipt(
        {
            "schema_version": 1,
            "source_repository": SOURCE_REPOSITORY,
            "version": manifest.get("version"),
            "tag": manifest.get("tag"),
            "commit": resolved_commit,
            "channel": manifest.get("channel"),
            "published_at": utc_text(timestamp(release.get("published_at"))),
            "observed_at": utc_text(timestamp(observed_at)),
            "release_id": release.get("id"),
            "release_url": release.get("html_url"),
            "manifest": manifest_identity,
            "artifacts": sorted(identities, key=lambda row: row["name"]),
        }
    )
    if existing is not None:
        previous = parse_receipt(existing)
        if any(previous[key] != value[key] for key in value if key != "observed_at"):
            raise PublicationError("existing publication receipt conflicts with current evidence")
        return existing
    return canonical_bytes(value)


def validate_qualified_files(bundle: Path) -> dict:
    """Pre-mutation consistency of the exact already-qualified local core file set."""
    manifest = decode_json(read_metadata(bundle / "release-manifest.json"))
    _identity(manifest)
    declared = manifest.get("artifacts")
    if not isinstance(declared, list) or not isinstance(manifest.get("sbom"), dict):
        raise PublicationError("qualified manifest artifacts are invalid")
    names = {"release-manifest.json", "SHA256SUMS"}
    total = 0
    for value in [*declared, manifest["sbom"]]:
        if not isinstance(value, dict):
            raise PublicationError("qualified manifest artifact is invalid")
        identity = artifact_identity(
            {key: value.get(key) for key in ("name", "sha256", "size_bytes")}
        )
        if identity["name"].casefold() in {name.casefold() for name in names}:
            raise PublicationError("qualified file identities collide")
        names.add(identity["name"])
        if file_identity(bundle / identity["name"]) != identity:
            raise PublicationError("qualified artifact bytes differ")
        total += identity["size_bytes"]
    if {path.name for path in bundle.iterdir()} != names:
        raise PublicationError("qualified publication file set differs")
    for name in ("release-manifest.json", "SHA256SUMS"):
        total += file_identity(bundle / name)["size_bytes"]
    # Reserve bounded metadata plus more than each fixed ZIP64 header/name can occupy.
    # A known container-size failure must be detected before publishing the public event.
    if total + MAX_RECEIPT_BYTES + (len(names) + 1) * 1024 > MAX_PAYLOAD_BYTES:
        raise PublicationError("qualified input exceeds bounded installation kit capacity")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--resolved-commit", required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw = create_receipt(
        decode_json(read_metadata(args.release)),
        bundle=args.bundle,
        resolved_commit=args.resolved_commit,
        observed_at=args.observed_at or utc_text(datetime.now(UTC)),
        existing=read_metadata(args.output) if args.output.exists() else None,
    )
    write_once(args.output, raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
