"""Verify two governed native inputs and compose a universal package, entirely offline."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from provelume.ai_runtime_identity import LOCK_SHA256  # noqa: E402
from provelume.ai_runtime_identity import read_runtime_lock as runtime_lock  # noqa: E402

MAX_INPUT_BYTES = 32 * 1024**2


def stage(source, inputs):
    if set(inputs) != {"windows", "linux"}:
        raise ValueError("both native platform inputs are required")
    package = Path(source) / "core/provelume"
    target = package / "native-ai"
    if target.exists() or target.is_symlink():
        raise ValueError("native package destination must be absent")
    records, staged = {}, {}
    for platform, path in sorted(inputs.items()):
        pin = runtime_lock()["platforms"][platform]
        path = Path(path)
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 < info.st_size <= MAX_INPUT_BYTES):
            raise ValueError("native build input path or size")
        raw = path.read_bytes()
        expected = {"native/" + name for name in pin} | {
            "notices/llama-LICENSE.txt", "notices/LLVM-OpenMP-LICENSE.txt",
            "candidate-components.cdx.json"}
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != len(expected) or {m.filename for m in members} != expected:
                raise ValueError("native input member inventory")
            for member in members:
                if (member.flag_bits or member.compress_type != zipfile.ZIP_STORED
                        or member.external_attr >> 16 != 0o100644 or member.extra
                        or member.comment or member.file_size != member.compress_size
                        or member.file_size > MAX_INPUT_BYTES):
                    raise ValueError("native input member framing")
                data = archive.read(member)
                if member.filename.startswith("native/"):
                    name = member.filename.removeprefix("native/")
                    if (len(data) != pin[name]["size"]
                            or hashlib.sha256(data).hexdigest() != pin[name]["sha256"]):
                        raise ValueError("native library integrity")
                    staged[platform + "/" + name] = data
                elif member.filename.startswith("notices/"):
                    notice = package / "runtime_notices" / Path(member.filename).name
                    if data != notice.read_bytes():
                        raise ValueError("native notice integrity")
                else:
                    if len(data) > 128 * 1024:
                        raise ValueError("native input SBOM byte limit")
                    sbom = json.loads(data)
                    properties = {r["name"]: r["value"] for r in
                                  sbom["metadata"]["component"]["properties"]}
                    if (properties.get("provelume:runtime-lock-sha256") != LOCK_SHA256
                            or properties.get("provelume:platform") != platform
                            or len(sbom["components"]) != len(pin)
                            or {r["name"] for r in sbom["components"]} != set(pin)):
                        raise ValueError("native input SBOM inventory")
                    for row in sbom["components"]:
                        license_id = ("Apache-2.0 WITH LLVM-exception"
                                      if row["name"] == "libomp.dll" else "MIT")
                        if row["hashes"] != [{"alg": "SHA-256", "content": pin[
                                row["name"]]["sha256"]}] or (
                            row["scope"] != "optional" or row["version"] != "b11379"
                            or row["licenses"] != [{"license": {"id": license_id}}]
                            or row["type"] != "library" or row["bom-ref"] != row["name"]
                        ):
                            raise ValueError("native input SBOM integrity")
        records[platform] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                             "files": len(pin)}
    # No destination exists until BOTH platforms, notices and SBOMs have passed.
    for name, raw in sorted(staged.items()):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    return {"runtime_lock": LOCK_SHA256, "platforms": records,
            "native_bytes": sum(map(len, staged.values())), "model_weights_included": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument("--linux", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.source, {"windows": args.windows, "linux": args.linux})))
