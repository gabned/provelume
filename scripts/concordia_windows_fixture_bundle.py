"""Byte verification for the same-run synthetic Linux server bundle."""

import hashlib
import json
import re
from pathlib import Path

_ASSETS = {
    "guest-rootfs.tar",
    "fixture-image.tar",
    "fixture-build-original.json",
    "guest-build-original.log",
    "docker-build-original.log",
    *(
        f"{probe}-{stream}-original.log"
        for probe in ("python", "rsync", "sshd", "helper-import")
        for stream in ("stdout", "stderr")
    ),
}


def asset_identity(path):
    path = Path(path)
    size = path.stat().st_size
    if path.is_symlink() or path.is_junction() or not path.is_file() or size > 512 * 1024 * 1024:
        raise ValueError("fixture asset must be a bounded regular file")
    with path.open("rb") as stream:
        return {"bytes": size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def verify(bundle, *, head, tree, run_id, run_attempt, producer_attempt):
    if (
        bundle.is_symlink()
        or bundle.is_junction()
        or {entry.name for entry in bundle.iterdir()} != _ASSETS | {"manifest.json"}
    ):
        raise ValueError("unexpected fixture asset inventory")
    metadata = bundle / "manifest.json"
    if asset_identity(metadata)["bytes"] >= 16384:
        raise ValueError("fixture manifest limit")
    manifest = json.loads(metadata.read_text(encoding="utf-8"))
    if (
        manifest.get("schema") != "concordia-rsync-windows-server-input/v1"
        or manifest.get("head") != head
        or manifest.get("tree") != tree
        or manifest.get("run_id") != run_id
        or manifest.get("run_attempt") != producer_attempt
        or not re.fullmatch(r"[1-9][0-9]*", producer_attempt)
        or int(producer_attempt) > int(run_attempt)
        or manifest.get("credentials_in_inputs") is not False
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest.get("image_id", ""))
        or manifest.get("files") != {name: asset_identity(bundle / name) for name in _ASSETS}
    ):
        raise ValueError("fixture manifest or byte identity mismatch")
    prepared = json.loads((bundle / "fixture-build-original.json").read_text(encoding="utf-8"))
    if (
        (prepared["head"], prepared["tree"], prepared["image_id"])
        != (head, tree, manifest["image_id"])
        or prepared["credentials_in_image"] is not False
        or prepared["build_network"] != "NONE"
    ):
        raise ValueError("fixture build identity mismatch")
    return manifest
