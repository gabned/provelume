"""Verify shipped native bytes and their optional release SBOM provenance."""

from __future__ import annotations

import hashlib
import stat
from importlib.resources import files
from pathlib import Path

from .ai_runtime_identity import LOCK_SHA256, read_runtime_lock

PREFIX = "provelume-native:"
NOTICES = {
    "llama-LICENSE.txt": "94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d",
    "LLVM-OpenMP-LICENSE.txt": "fdad1758a9e1f9d5a81e18879b3406772115edc92c24bfa36b70c654f325e8e4",
}


def _require(value, message):
    if not value:
        raise ValueError("native resources: " + message)


def _bytes(path, maximum):
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
             and info.st_size <= maximum, "unsafe or oversized member")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    _require(len(data) <= maximum, "oversized member")
    return data


def inventory(*, required=False):
    root = files("provelume")
    _require(isinstance(root, Path), "filesystem package required")
    native = root / "native-ai"
    if not native.exists() and not native.is_symlink():
        _require(not required, "both platform trees are required")
        return [], set()
    _require(native.is_dir() and not native.is_symlink(), "invalid tree")
    lock = read_runtime_lock()
    _require({p.name for p in native.iterdir()} == set(lock["platforms"]),
             "platform inventory differs")
    notice_root = root / "runtime_notices"
    _require(notice_root.is_dir() and not notice_root.is_symlink(), "invalid notice tree")
    notices = {name: hashlib.sha256(_bytes(notice_root / name, 131072)).hexdigest()
               for name in NOTICES}
    _require(notices == NOTICES, "notice integrity differs")
    members = {"provelume/ai_runtime_lock.json"} | {
        "provelume/runtime_notices/" + name for name in NOTICES}
    components = []
    for platform, selected in sorted(lock["platforms"].items()):
        directory = native / platform
        _require(directory.is_dir() and not directory.is_symlink(), "invalid platform tree")
        _require({p.name for p in directory.iterdir()} == set(selected), "member inventory differs")
        for name, expected in sorted(selected.items()):
            data = _bytes(directory / name, expected["size"])
            _require(len(data) == expected["size"]
                     and hashlib.sha256(data).hexdigest() == expected["sha256"],
                     "member integrity differs")
            resource = f"native-ai/{platform}/{name}"
            members.add("provelume/" + resource)
            notice = "LLVM-OpenMP-LICENSE.txt" if name == "libomp.dll" else "llama-LICENSE.txt"
            components.append({
                "bom-ref": PREFIX + platform + ":" + name,
                "type": "library", "name": name, "version": lock["version"], "scope": "optional",
                "licenses": [{"expression": "Apache-2.0 WITH LLVM-exception"
                              if name == "libomp.dll" else "MIT"}],
                "hashes": [{"alg": "SHA-256", "content": expected["sha256"]}],
                "properties": [
                    {"name": "provelume:native-platform", "value": platform},
                    {"name": "provelume:resource", "value": resource},
                    {"name": "provelume:source-revision", "value": lock["source_revision"]},
                    {"name": "provelume:runtime-lock-sha256", "value": LOCK_SHA256},
                    {"name": "provelume:license-resource", "value": "runtime_notices/" + notice},
                    {"name": "provelume:license-sha256", "value": notices[notice]},
                ],
            })
    return components, members


def is_native_component(row):
    properties = row.get("properties", [])
    return str(row.get("bom-ref", "")).startswith(PREFIX) or (
        isinstance(properties, list) and any(
            isinstance(value, dict) and value.get("name") == "provelume:native-platform"
            for value in properties))
