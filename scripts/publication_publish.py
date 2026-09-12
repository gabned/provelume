"""Permanent, resumable publication finalization. Invoked only by the release publisher."""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from provelume.publication import (
    READY_NAME,
    RECEIPT_NAME,
    SOURCE_REPOSITORY,
    PublicationError,
    canonical_bytes,
    decode_json,
    file_identity,
    read_metadata,
    safe_path,
    utc_text,
    write_once,
)
from scripts.publication_receipt import create_receipt, validate_qualified_files
from scripts.release_kit import create_kit, readiness, verify_kit


class GitHub:
    def run(self, arguments: list[str], *, destination: Path | None = None) -> bytes:
        if destination is None:
            result = subprocess.run(["gh", *arguments], capture_output=True, check=False)
        else:
            destination = safe_path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                result = subprocess.run(
                    ["gh", *arguments], stdout=handle, stderr=subprocess.PIPE, check=False
                )
        if result.returncode:
            raise PublicationError(
                "GitHub publication operation failed; finalization remains pending"
            )
        return result.stdout or b""

    def release(self, tag: str) -> dict | None:
        result = subprocess.run(
            ["gh", "api", f"repos/{SOURCE_REPOSITORY}/releases/tags/{tag}"],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            if b"(HTTP 404)" in result.stderr:
                return None
            raise PublicationError("Release lookup failed; publication was not attempted")
        return decode_json(result.stdout)

    def download(self, release: dict, name: str, destination: Path) -> None:
        rows = [row for row in release.get("assets", []) if row.get("name") == name]
        if len(rows) != 1 or type(rows[0].get("id")) is not int:
            raise PublicationError("Published asset is missing or ambiguous")
        self.run(
            [
                "api",
                "-H",
                "Accept: application/octet-stream",
                f"repos/{SOURCE_REPOSITORY}/releases/assets/{rows[0]['id']}",
            ],
            destination=destination,
        )

    def upload_once(self, release: dict, path: Path, verification_directory: Path) -> None:
        if any(row.get("name") == path.name for row in release.get("assets", [])):
            observed = verification_directory / path.name
            self.download(release, path.name, observed)
            if file_identity(observed) != file_identity(path):
                raise PublicationError("Published asset conflicts; overwrite is forbidden")
        else:
            self.run(
                ["release", "upload", release["tag_name"], str(path), "--repo", SOURCE_REPOSITORY]
            )


def prepare(bundle: Path, stage: Path, *, commit: str, client: GitHub) -> None:
    manifest = validate_qualified_files(bundle)
    version, tag = manifest["version"], manifest["tag"]
    if manifest["commit"] != commit:
        raise PublicationError("Qualified manifest source differs from publisher source")
    configuration = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    if configuration["project"]["version"] != version:
        raise PublicationError("Package version differs from publication")
    title = f"Provelume {version} “{configuration['tool']['provelume']['release']['codename']}”"
    notes = Path("docs/releases") / f"{version}.md"
    if not notes.is_file():
        raise PublicationError("Public release notes are missing")
    resolved = decode_json(client.run(["api", f"repos/{SOURCE_REPOSITORY}/commits/{tag}"]))["sha"]
    if resolved != commit:
        raise PublicationError("Public tag moved from qualified source")
    release = client.release(tag)
    if release is None:
        names = [row["name"] for row in manifest["artifacts"]] + [
            manifest["sbom"]["name"],
            "release-manifest.json",
            "SHA256SUMS",
        ]
        if {p.name for p in bundle.iterdir()} != set(names):
            raise PublicationError("Qualified publication file set differs")
        arguments = [
            "release",
            "create",
            tag,
            *[str(bundle / name) for name in sorted(names)],
            "--repo",
            SOURCE_REPOSITORY,
            "--verify-tag",
            "--title",
            title,
            "--notes-file",
            str(notes),
        ]
        if manifest["channel"] == "preview":
            arguments.append("--prerelease")
        client.run(arguments)
        release = client.release(tag)
    if release is None:
        raise PublicationError("Published release observation is unavailable")
    resolved = decode_json(client.run(["api", f"repos/{SOURCE_REPOSITORY}/commits/{tag}"]))["sha"]
    if resolved != commit:
        raise PublicationError("Public tag moved from qualified source")
    if (
        release.get("draft") is not False
        or release.get("tag_name") != tag
        or release.get("prerelease") is not (manifest["channel"] == "preview")
        or release.get("name") != title
    ):
        raise PublicationError("Existing release differs from qualified publication identity")
    stage = safe_path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    public_bundle = stage / "public-bundle"
    public_bundle.mkdir(exist_ok=True)
    for path in sorted(bundle.iterdir()):
        # A failed initial multi-asset upload can leave a public event with missing assets.
        # Add only absent qualified bytes; an existing asset must compare identically.
        client.upload_once(release, path, stage / "existing")
    release = client.release(tag)
    if release is None:
        raise PublicationError("Completed payload observation is unavailable")
    for path in sorted(bundle.iterdir()):
        client.download(release, path.name, public_bundle / path.name)
        if file_identity(public_bundle / path.name) != file_identity(path):
            raise PublicationError("Public qualified artifact differs from prepublication bytes")
    receipt_path = stage / RECEIPT_NAME
    existing = None
    if any(row.get("name") == RECEIPT_NAME for row in release.get("assets", [])):
        observed = stage / "existing" / RECEIPT_NAME
        client.download(release, RECEIPT_NAME, observed)
        existing = read_metadata(observed)
    elif receipt_path.exists():
        existing = read_metadata(receipt_path)
    raw = create_receipt(
        release,
        bundle=public_bundle,
        resolved_commit=resolved,
        observed_at=utc_text(datetime.now(UTC)),
        existing=existing,
    )
    write_once(receipt_path, raw)
    create_kit(public_bundle, receipt_path, stage / f"provelume-{version}-installation-kit.zip")


def finalize(bundle: Path, stage: Path, *, client: GitHub) -> dict:
    manifest = validate_qualified_files(bundle)
    tag, version = manifest["tag"], manifest["version"]
    release = client.release(tag)
    if release is None:
        raise PublicationError("Public release is unavailable; finalization is pending")
    receipt_path = stage / RECEIPT_NAME
    kit_path = stage / f"provelume-{version}-installation-kit.zip"
    verify_kit(kit_path, bundle=bundle, receipt=read_metadata(receipt_path))
    for path in (receipt_path, kit_path):
        client.upload_once(release, path, stage / "existing")
    # A fresh inventory and downloads precede the readiness marker, including on retries.
    release = client.release(tag)
    if release is None:
        raise PublicationError("Finalization observation is unavailable")
    observed_root = stage / "observed"
    for path in (receipt_path, kit_path):
        client.download(release, path.name, observed_root / path.name)
        if file_identity(observed_root / path.name) != file_identity(path):
            raise PublicationError("Public finalization bytes differ")
    resolved = decode_json(client.run(["api", f"repos/{SOURCE_REPOSITORY}/commits/{tag}"]))["sha"]
    public_bundle = observed_root / "release"
    public_bundle.mkdir(parents=True, exist_ok=True)
    for path in sorted(bundle.iterdir()):
        client.download(release, path.name, public_bundle / path.name)
        if file_identity(public_bundle / path.name) != file_identity(path):
            raise PublicationError("Public qualified artifact changed during finalization")
    create_receipt(
        release,
        bundle=public_bundle,
        resolved_commit=resolved,
        observed_at=utc_text(datetime.now(UTC)),
        existing=read_metadata(observed_root / RECEIPT_NAME),
    )
    ready = readiness(public_bundle, observed_root / RECEIPT_NAME, observed_root / kit_path.name)
    ready_path = stage / READY_NAME
    write_once(ready_path, canonical_bytes(ready))
    client.upload_once(release, ready_path, stage / "existing")
    release = client.release(tag)
    if release is None:
        raise PublicationError("Readiness observation is unavailable")
    client.download(release, READY_NAME, observed_root / READY_NAME)
    if read_metadata(observed_root / READY_NAME) != read_metadata(ready_path):
        raise PublicationError("Public readiness marker differs")
    return {
        "status": "installation_kit_ready",
        "release_id": release["id"],
        "version": version,
        "receipt_sha256": ready["receipt"]["sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finalize"))
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--commit")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.commit is None:
            raise PublicationError("Publisher source identity is required")
        prepare(args.bundle, args.stage, commit=args.commit, client=GitHub())
    else:
        print(json.dumps(finalize(args.bundle, args.stage, client=GitHub()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
