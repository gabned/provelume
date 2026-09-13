"""Deterministic outer envelope around unchanged qualified release bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from provelume.publication import (
    READY_NAME,
    RECEIPT_NAME,
    PublicationError,
    canonical_bytes,
    file_identity,
    parse_receipt,
    read_metadata,
    safe_path,
    write_once,
)


def kit_members(bundle: Path, receipt: bytes) -> dict[str, Path | bytes]:
    value = parse_receipt(receipt)
    expected = {row["name"]: row for row in [value["manifest"], *value["artifacts"]]}
    entries = list(safe_path(bundle).iterdir())
    if {entry.name for entry in entries} != set(expected):
        raise PublicationError("kit input differs from the exact qualified bundle file set")
    members: dict[str, Path | bytes] = {"publication/" + RECEIPT_NAME: receipt}
    for entry in entries:
        if file_identity(entry) != expected[entry.name]:
            raise PublicationError("kit input differs from qualified bytes")
        members["release/" + entry.name] = entry
    return members


def verify_kit(path: Path, *, bundle: Path, receipt: bytes) -> dict:
    members = kit_members(bundle, receipt)
    with zipfile.ZipFile(safe_path(path)) as archive:
        infos = archive.infolist()
        if len(infos) != len(members) or {info.filename for info in infos} != set(members):
            raise PublicationError("kit archive members differ")
        for info in infos:
            source = members[info.filename]
            expected = (
                {"sha256": hashlib.sha256(source).hexdigest(), "size_bytes": len(source)}
                if isinstance(source, bytes)
                else file_identity(source)
            )
            if info.file_size != expected["size_bytes"] or info.flag_bits & 1:
                raise PublicationError("kit member size/type differs")
            if info.compress_type != zipfile.ZIP_STORED or info.external_attr >> 16 != 0o100644:
                raise PublicationError("kit member encoding differs")
            digest = hashlib.sha256()
            with archive.open(info) as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected["sha256"]:
                raise PublicationError("kit member bytes differ")
    return file_identity(path)


def create_kit(bundle: Path, receipt_path: Path, output: Path) -> dict:
    raw = read_metadata(receipt_path)
    value = parse_receipt(raw)
    members = kit_members(bundle, raw)
    output = safe_path(output)
    if output.name != f"provelume-{value['version']}-installation-kit.zip":
        raise PublicationError("kit filename differs from release identity")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        fd, temporary = tempfile.mkstemp(prefix="kit-", dir=output.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, source in sorted(members.items()):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    with archive.open(info, "w", force_zip64=True) as target:
                        if isinstance(source, bytes):
                            target.write(source)
                        else:
                            with source.open("rb") as handle:
                                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                                    target.write(chunk)
            verify_kit(Path(temporary), bundle=bundle, receipt=raw)
            os.link(temporary, output)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return verify_kit(output, bundle=bundle, receipt=raw)


def readiness(bundle: Path, receipt_path: Path, kit_path: Path) -> dict:
    raw = read_metadata(receipt_path)
    receipt = parse_receipt(raw)
    return {
        "schema_version": 1,
        "status": "installation_kit_ready",
        **{
            key: receipt[key]
            for key in ("source_repository", "version", "tag", "commit", "channel", "release_id")
        },
        "receipt": file_identity(receipt_path),
        "manifest": receipt["manifest"],
        "kit": verify_kit(kit_path, bundle=bundle, receipt=raw),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify", "ready"))
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "build":
        result = create_kit(args.bundle, args.receipt, args.kit)
    elif args.action == "verify":
        result = verify_kit(args.kit, bundle=args.bundle, receipt=read_metadata(args.receipt))
    else:
        result = readiness(args.bundle, args.receipt, args.kit)
        if args.output is None or args.output.name != READY_NAME:
            raise PublicationError("readiness output name is invalid")
        write_once(args.output, canonical_bytes(result))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
