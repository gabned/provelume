"""Permanent offline exercise of the production publication parser and finalizer."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import tomllib
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
    validate_delivery,
)
from scripts.publication_publish import GitHub, finalize, prepare

SYNTHETIC_PUBLICATION_TIME = "2026-01-01T12:00:00Z"


def synthetic_bundle(root: Path) -> tuple[Path, dict]:
    """Small, explicitly fictitious payloads; never represented as release qualification."""
    configuration = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = configuration["project"]["version"]
    bundle = root / "synthetic-bundle"
    bundle.mkdir(parents=True)
    names = [
        f"provelume-{version}-py3-none-any.whl",
        f"provelume-{version}.tar.gz",
        f"Provelume-Setup-{version}-x64.exe",
    ]
    for name in [*names, f"provelume-{version}.cdx.json"]:
        (bundle / name).write_bytes(b"EXPLICIT OFFLINE DRY-RUN FIXTURE: " + name.encode())
    manifest = {
        "schema_version": 1,
        "source_repository": SOURCE_REPOSITORY,
        "version": version,
        "tag": f"v{version}",
        "commit": "a" * 40,
        "channel": "preview",
        "built_at": "2025-12-01T00:00:00Z",
        "artifacts": [file_identity(bundle / name) for name in names],
        "sbom": file_identity(bundle / f"provelume-{version}.cdx.json"),
    }
    (bundle / "release-manifest.json").write_bytes(canonical_bytes(manifest))
    (bundle / "SHA256SUMS").write_text("EXPLICIT OFFLINE DRY-RUN CHECKSUM FIXTURE\n")
    return bundle, manifest


class OfflinePublicRecord(GitHub):
    """Filesystem transport double. Every gh/network entry point is replaced."""

    def __init__(self, bundle: Path, root: Path, *, published: bool = True):
        self.root = root
        self.root.mkdir(parents=True)
        self.manifest = decode_json(read_metadata(bundle / "release-manifest.json"))
        configuration = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        version = self.manifest["version"]
        codename = configuration["tool"]["provelume"]["release"]["codename"]
        self.event = {
            "id": 123456789,
            "draft": False,
            "prerelease": self.manifest["channel"] == "preview",
            "tag_name": self.manifest["tag"],
            "name": f"Provelume {version} “{codename}”",
            "html_url": f"https://github.com/{SOURCE_REPOSITORY}/releases/tag/v{version}",
            "published_at": SYNTHETIC_PUBLICATION_TIME,
        }
        self.published = published
        self.fail_upload: str | None = None
        self.create_count = 0
        if published:
            for path in bundle.iterdir():
                shutil.copyfile(path, self.root / path.name)

    def release(self, tag: str) -> dict | None:
        assert tag == self.manifest["tag"]
        if not self.published:
            return None
        event = copy.deepcopy(self.event)
        event["assets"] = [
            {
                "id": index + 1,
                "name": path.name,
                "state": "uploaded",
                "size": file_identity(path)["size_bytes"],
                "digest": "sha256:" + file_identity(path)["sha256"],
                "browser_download_url": f"https://github.com/{SOURCE_REPOSITORY}/releases/"
                f"download/{tag}/{path.name}",
            }
            for index, path in enumerate(sorted(self.root.iterdir()))
        ]
        return event

    def download(self, release: dict, name: str, destination: Path) -> None:
        assert release["id"] == self.event["id"]
        destination = safe_path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.root / name, destination)

    def run(self, arguments: list[str], *, destination: Path | None = None) -> bytes:
        assert destination is None
        if arguments == ["api", f"repos/{SOURCE_REPOSITORY}/commits/{self.manifest['tag']}"]:
            return canonical_bytes({"sha": self.manifest["commit"]})
        if arguments[:2] == ["release", "create"]:
            assert not self.published
            self.create_count += 1
            self.published = True
            for item in arguments[3 : arguments.index("--repo")]:
                path = Path(item)
                shutil.copyfile(path, self.root / path.name)
            return b""
        if arguments[:2] == ["release", "upload"]:
            source = Path(arguments[3])
            if source.name == self.fail_upload:
                raise PublicationError("Explicit synthetic interrupted upload")
            target = self.root / source.name
            assert not target.exists(), "Production must never request an overwrite"
            shutil.copyfile(source, target)
            return b""
        raise AssertionError("Offline transport received an unsupported operation")


def exercise(bundle: Path, root: Path) -> dict:
    manifest = decode_json(read_metadata(bundle / "release-manifest.json"))
    before = {p.name: file_identity(p) for p in bundle.iterdir()}
    client = OfflinePublicRecord(bundle, root / "fake-public-record", published=False)
    stage = root / "stage"
    prepare(bundle, stage, commit=manifest["commit"], client=client)
    client.fail_upload = f"provelume-{manifest['version']}-installation-kit.zip"
    try:
        finalize(bundle, stage, client=client)
    except PublicationError as exc:
        if str(exc) != "Explicit synthetic interrupted upload":
            raise
    else:
        raise AssertionError("Expected the deliberate finalization interruption")
    assert not (client.root / READY_NAME).exists()
    client.fail_upload = None
    # A new local stage models a fresh failed-job retry, reusing the public receipt bytes.
    resumed = root / "resumed-stage"
    prepare(bundle, resumed, commit=manifest["commit"], client=client)
    finalize(bundle, resumed, client=client)
    public_before = {p.name: file_identity(p) for p in client.root.iterdir()}
    prepare(bundle, resumed, commit=manifest["commit"], client=client)
    finalize(bundle, resumed, client=client)
    assert public_before == {p.name: file_identity(p) for p in client.root.iterdir()}
    assert before == {p.name: file_identity(p) for p in bundle.iterdir()}
    assert client.create_count == 1
    receipt = validate_delivery(
        read_metadata(client.root / RECEIPT_NAME),
        decode_json(read_metadata(client.root / READY_NAME)),
    )
    assert receipt["published_at"] == SYNTHETIC_PUBLICATION_TIME
    return {
        "schema_version": 1,
        "status": "offline_dry_run_pass",
        "publication_event": "explicitly_synthetic",
        "network_used": False,
        "credentials_used": False,
        "qualified_input_bytes_unchanged": True,
        "interrupted_finalization_recovered": True,
        "repeat_is_idempotent": True,
        "actual_release_publication": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    root = safe_path(args.work_dir)
    root.mkdir(parents=True, exist_ok=False)
    bundle = args.bundle or synthetic_bundle(root)[0]
    print(json.dumps(exercise(bundle, root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
