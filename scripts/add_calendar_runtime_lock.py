"""Propose additive pure-wheel runtime pins; native Windows CI remains mandatory."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

from scripts.resolve_windows_pdf_lock import pins

ADDITIONS = {"icalendar": "7.3.0", "python-dateutil": "4.0.0"}


def propose(root, wheels, output):
    source = root / "build-lock/windows-py312-x86_64.requirements.txt"
    raw = source.read_text(encoding="utf-8")
    before = pins(raw)
    additions, evidence = [], []
    for name, version in sorted(ADDITIONS.items()):
        selected = list(wheels.glob(name.replace("-", "_") + "-" + version + "-*.whl"))
        if len(selected) != 1 or not selected[0].name.endswith("-py3-none-any.whl"):
            raise ValueError("exact platform-independent calendar wheel is required")
        wheel = selected[0]
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as archive:
            metadata_files = [item for item in archive.namelist() if item.endswith("/METADATA")]
            if len(metadata_files) != 1:
                raise ValueError("ambiguous wheel metadata")
            metadata = Parser().parsestr(archive.read(metadata_files[0]).decode())
            if metadata["Version"] != version:
                raise ValueError("wheel version disagrees with proposal")
        block = (f"{name}=={version} \\\n"
                 f"    --hash=sha256:{digest}\n"
                 "    # via Concordia S12 pure-wheel addition\n")
        if name not in before:
            additions.append(block)
        elif before[name] != version or block not in raw:
            raise ValueError("existing calendar pin must not be rewritten")
        evidence.append({"name": name, "version": version, "filename": wheel.name,
                         "sha256": digest, "size_bytes": wheel.stat().st_size,
                         "requires_dist": metadata.get_all("Requires-Dist", [])})
    candidate = raw + ("\n" + "".join(additions) if additions else "")
    if pins(candidate) != {**before, **ADDITIONS}:
        raise ValueError("unrelated pin changed")
    output.mkdir(parents=True, exist_ok=False)
    (output / source.name).write_text(candidate, encoding="utf-8", newline="\n")
    receipt = {"status": "PROPOSED_NATIVE_WINDOWS_NOT_RUN", "source_sha256":
               hashlib.sha256(source.read_bytes()).hexdigest(), "candidate_sha256":
               hashlib.sha256(candidate.encode()).hexdigest(), "additions": evidence,
               "unrelated_pins_and_hashes_preserved": True}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    options.wheels.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
                    "--index-url", "https://pypi.org/simple", "--dest", str(options.wheels),
                    *(name + "==" + version for name, version in ADDITIONS.items())], check=True)
    propose(Path(__file__).absolute().parents[1], options.wheels, options.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
