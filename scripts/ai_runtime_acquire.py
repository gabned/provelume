"""Explicit developer/build acquisition of one locked S05 candidate. Never imported by Core."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from provelume.ai_runtime_contract import (  # noqa: E402
    MODEL_SHA256,
    MODEL_SIZE,
    MODEL_URL,
    runtime_lock,
)

ARCHIVES = {
    "windows": ("llama-b11379-bin-win-cpu-x64.zip", 19352297,
                "ec014c2c2a27b18786d24eba3e8650d4e68b9003ca6cf91714125b71975eb7ea"),
    "linux": ("llama-b11379-bin-ubuntu-x64.tar.gz", 17658949,
              "8ab0e8588e2b282ed4882a47a26dbf1a2ae920578deb24a8dfe390110c1bb924"),
}


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.username or parsed.password or
                parsed.port not in (None, 443) or parsed.hostname not in {
                    "huggingface.co", "cdn-lfs.huggingface.co", "cdn-lfs-us-1.hf.co",
                    "cas-bridge.xethub.hf.co", "us.aws.cdn.hf.co",
                    "release-assets.githubusercontent.com"}):
            raise ValueError("unapproved acquisition redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def verified(path, size, digest):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == digest


def acquire(url, path, size, digest):
    if path.exists():
        if not verified(path, size, digest):
            raise ValueError("existing artifact is not the locked artifact")
        return
    stage = path.with_suffix(path.suffix + ".part")
    # No ambient proxy, cookies, credentials or retry. Redirects exist only in
    # this explicit build tool. The native product downloader separately pins
    # its smaller model-only origin set and numeric peers (ADR 0052).
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
    deadline = time.monotonic() + 300
    with opener.open(url, timeout=15) as response, stage.open("xb") as out:
        count = 0
        while block := response.read(1024 * 1024):
            count += len(block)
            if count > size or time.monotonic() >= deadline:
                raise ValueError("acquisition limit")
            out.write(block)
    if not verified(stage, size, digest):
        raise ValueError("artifact integrity")
    stage.rename(path)


def prepare(root, system, *, model):
    root = root.absolute()
    root.mkdir(parents=True, exist_ok=True)
    (root / ".gitignore").write_text("*\n", encoding="ascii")
    if shutil.disk_usage(root).free < 5 * 1024**3:
        raise ValueError("five GiB free space required")
    name, size, digest = ARCHIVES[system]
    archive_path = root / name
    acquire("https://github.com/ggml-org/llama.cpp/releases/download/b11379/" + name,
            archive_path, size, digest)
    destination = root / system
    destination.mkdir(exist_ok=True)
    inventory = runtime_lock()["platforms"][system]
    with (zipfile.ZipFile(archive_path) if system == "windows" else
          tarfile.open(archive_path)) as archive:
        for member, expected in inventory.items():
            path = destination / member
            if path.exists():
                if not verified(path, expected["size"], expected["sha256"]):
                    raise ValueError("runtime inventory mismatch")
                continue
            source = member
            if system == "linux":
                source = {"libllama.so.0": "libllama.so.0.5.0",
                          "libggml.so.0": "libggml.so.0.25.3",
                          "libggml-base.so.0": "libggml-base.so.0.25.3"}.get(member, member)
                raw = archive.extractfile("llama-b11379/" + source).read(expected["size"] + 1)
            else:
                raw = archive.read(source)
            if (len(raw) != expected["size"] or
                    hashlib.sha256(raw).hexdigest() != expected["sha256"]):
                raise ValueError("native library integrity")
            with path.open("xb") as stream:
                stream.write(raw)
    if model:
        acquire(MODEL_URL, root / "model.gguf", MODEL_SIZE, MODEL_SHA256)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--accept-licenses", action="store_true", required=True)
    parser.add_argument("--include-model", action="store_true")
    parser.add_argument("--platform", choices=("windows", "linux", "all"))
    args = parser.parse_args()
    selected = args.platform or ("windows" if os.name == "nt" else "linux")
    for system in (("windows", "linux") if selected == "all" else (selected,)):
        prepare(args.directory, system, model=args.include_model)
    print("Locked artifacts verified; no activation or product inference authorized.")


if __name__ == "__main__":
    main()
