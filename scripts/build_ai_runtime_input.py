"""Offline deterministic native build input; never a model-registry updater."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from provelume import __version__  # noqa: E402
from provelume.ai_runtime_contract import LOCK_SHA256, runtime_lock  # noqa: E402


def build(directory, platform, output):
    lock = runtime_lock()
    inventory = lock["platforms"][platform]
    if {p.name for p in directory.iterdir()} != set(inventory):
        raise ValueError("native build input inventory differs")
    members = {}
    components = []
    for name, expected in sorted(inventory.items()):
        path = directory / name
        if path.is_symlink() or path.stat().st_size != expected["size"]:
            raise ValueError("native build input size/path")
        data = path.read_bytes()  # Closed small library inventory, never model weights.
        if hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError("native build input integrity")
        members["native/" + name] = data
        license_id = "Apache-2.0 WITH LLVM-exception" if name == "libomp.dll" else "MIT"
        components.append({"bom-ref": name, "type": "library", "name": name,
            "version": "b11379", "scope": "optional",
            "licenses": [{"license": {"id": license_id}}],
            "hashes": [{"alg": "SHA-256", "content": expected["sha256"]}]})
    notices = Path(__file__).resolve().parents[1] / "core/provelume/runtime_notices"
    for name in ("llama-LICENSE.txt", "LLVM-OpenMP-LICENSE.txt"):
        members["notices/" + name] = (notices / name).read_bytes()
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
            "metadata": {"component": {"type": "application", "name": "Provelume",
                "version": __version__, "properties": [
                    {"name": "provelume:qualification", "value": "NATIVE_LIBRARIES_ONLY"},
                    {"name": "provelume:platform", "value": platform},
                    {"name": "provelume:runtime-lock-sha256", "value": LOCK_SHA256}]}},
            "components": components}
    members["candidate-components.cdx.json"] = (
        json.dumps(sbom, indent=2, sort_keys=True) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system, info.external_attr = 3, 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(output) as archive:
        if set(archive.namelist()) != set(members) or any(
            archive.read(name) != data for name, data in members.items()
        ):
            raise ValueError("native build input parity")
    return {"platform": platform, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "runtime_lock": LOCK_SHA256, "weights_included": False, "published": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--platform", choices=("windows", "linux"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.directory, args.platform, args.output)))


if __name__ == "__main__":
    main()
