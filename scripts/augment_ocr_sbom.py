"""Bind one optional OCR asset, its original installed evidence and native inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "core"))

from provelume.ocr_kit import MANIFEST, MAX_BYTES, MAX_FILES, validate_manifest  # noqa: E402
from provelume.publication import canonical_bytes, file_identity  # noqa: E402

PREFIX = "urn:provelume:ocr:"


def augment(sbom, kit, build_report, installed_report, commit, installer):
    result = deepcopy(sbom)
    identity = file_identity(kit)
    if build_report["kit"] != identity or installed_report["kit"] != identity:
        raise ValueError("OCR evidence differs from the exact asset")
    if installed_report["result"] != "PASS" or installed_report["installer"] != file_identity(
        installer
    ):
        raise ValueError("OCR installed evidence is not bound to this Setup")
    if build_report["source_commit"] != commit or installed_report["source_commit"] != commit:
        raise ValueError("OCR source differs from the release")
    with zipfile.ZipFile(kit) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 1 or sum(i.file_size for i in infos) > MAX_BYTES + 2097152:
            raise ValueError("OCR asset exceeds its inventory bound")
        info = archive.getinfo(MANIFEST)
        if info.file_size > 2097152:
            raise ValueError("OCR manifest exceeds its bound")
        raw = archive.read(info)
        if hashlib.sha256(raw).hexdigest() != build_report["manifest_sha256"]:
            raise ValueError("OCR manifest differs from producer evidence")
        manifest = json.loads(raw)
        lock = json.loads((SOURCE / "packaging/ocr/windows-py312-x64.json").read_text())
        application = result["metadata"]["component"]
        validate_manifest(
            manifest,
            build_report["build_identity"],
            python_version=lock["python"],
        )
        if (
            manifest["version"] != application["version"]
            or manifest["commit"] != commit
            or installed_report["build_identity"] != build_report["build_identity"]
        ):
            raise ValueError("OCR build/installed identity differs from the release")
        expected = {row["path"]: row for row in manifest["files"]}
        if len(infos) != len(expected) + 1 or set(archive.namelist()) != set(expected) | {MANIFEST}:
            raise ValueError("OCR asset inventory differs")
        for name, row in expected.items():
            digest = hashlib.sha256()
            info = archive.getinfo(name)
            if info.file_size != row["size_bytes"]:
                raise ValueError("OCR asset file size differs")
            with archive.open(info) as stream:
                for chunk in iter(lambda: stream.read(1048576), b""):
                    digest.update(chunk)
            if digest.hexdigest() != row["sha256"]:
                raise ValueError("OCR asset file digest differs")
    if manifest["components"] != build_report["components"]:
        raise ValueError("OCR component inventory differs from producer evidence")
    kit_ref = PREFIX + "kit:" + identity["sha256"]
    added = [
        {
            "type": "file",
            "name": identity["name"],
            "bom-ref": kit_ref,
            "hashes": [{"alg": "SHA-256", "content": identity["sha256"]}],
        }
    ]
    for component in manifest["components"]:
        if (
            not component.get("license")
            or not component.get("notices")
            or any(name not in expected for name in component["notices"])
        ):
            raise ValueError("OCR component license/notices are incomplete")
        reference = PREFIX + "component:" + hashlib.sha256(canonical_bytes(component)).hexdigest()
        added.append(
            {
                "type": "library",
                "name": component["name"],
                "version": component["version"],
                "bom-ref": reference,
                "licenses": [{"license": {"name": component["license"]}}],
                "properties": [
                    {"name": "provelume:source", "value": component["source"]},
                    {"name": "provelume:notices", "value": ";".join(component["notices"])},
                ],
            }
        )
    for native in manifest["native_dependencies"]:
        row = expected[native["path"]]
        if native["architecture"] != "AMD64" or native["sha256"] != row["sha256"]:
            raise ValueError("OCR native file identity differs")
        reference = PREFIX + "native:" + hashlib.sha256(native["path"].encode()).hexdigest()
        added.append(
            {
                "type": "file",
                "name": native["path"],
                "bom-ref": reference,
                "hashes": [{"alg": "SHA-256", "content": row["sha256"]}],
                "properties": [
                    {"name": "provelume:architecture", "value": "AMD64"},
                    {
                        "name": "provelume:imports",
                        "value": json.dumps(native["imports"], sort_keys=True),
                    },
                ],
            }
        )
    existing = result.setdefault("components", [])
    if any(c.get("bom-ref", "").startswith(PREFIX) for c in existing):
        raise ValueError("OCR inventory was already added; preserve original SBOM")
    existing.extend(added)
    dependencies = result.setdefault("dependencies", [])
    root = next((row for row in dependencies if row["ref"] == application["bom-ref"]), None)
    if root is None:
        root = {"ref": application["bom-ref"], "dependsOn": []}
        dependencies.append(root)
    root["dependsOn"] = sorted(set(root["dependsOn"]) | {kit_ref})
    dependencies.append({"ref": kit_ref, "dependsOn": sorted(c["bom-ref"] for c in added[1:])})
    dependencies.extend({"ref": c["bom-ref"], "dependsOn": []} for c in added[1:])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sbom", "kit", "build-report", "installed-report", "installer"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    value = augment(
        json.loads(args.sbom.read_text()),
        args.kit,
        json.loads(args.build_report.read_text()),
        json.loads(args.installed_report.read_text()),
        args.commit,
        args.installer,
    )
    args.sbom.write_bytes(canonical_bytes(value))
