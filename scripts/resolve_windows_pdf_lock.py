"""Resolve one PDF dependency correction on genuine Windows; preserve other pins."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PDF_VERSION = "6.20.0"


def pins(raw):
    rows = re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", raw, re.MULTILINE)
    result = {re.sub(r"[-_.]+", "-", name).lower(): version for name, version in rows}
    if not rows or len(result) != len(rows) or "pypdf" not in result:
        raise ValueError("incomplete dependency inventory")
    return result


def replace_pdf(raw, wheel_sha256):
    if not re.fullmatch(r"[0-9a-f]{64}", wheel_sha256):
        raise ValueError("invalid PDF wheel digest")
    block = (f"pypdf=={PDF_VERSION} \\\n"
             f"    --hash=sha256:{wheel_sha256}\n"
             "    # via -r build-lock/windows-py312-x86_64.in\n")
    changed, count = re.subn(r"(?m)^pypdf==[^\n]*\n(?:[ \t]+[^\n]*\n)*",
                            lambda _: block, raw)
    if count != 1:
        raise ValueError("PDF lock block is not unique")
    before, after = pins(raw), pins(changed)
    if after != {**before, "pypdf": PDF_VERSION}:
        raise ValueError("unrelated dependency changed")
    note = ("# PDF-only correction: native Windows Python 3.12 pip resolution and wheel hash;\n"
            "# all other existing pip-compile pins and hashes are retained.\n")
    return changed if note in changed else note + changed


def resolve(root, output):
    if (sys.platform != "win32" or sys.version_info[:2] != (3, 12)
            or platform.machine().lower() not in {"amd64", "x86_64"}):
        raise ValueError("a genuine Windows x64 Python 3.12 resolver is required")
    source = root / "build-lock/windows-py312-x86_64.requirements.txt"
    source_bytes = source.read_bytes()
    if len(source_bytes) > 1024 * 1024:
        raise ValueError("dependency lock byte limit")
    raw = source_bytes.decode("utf-8")
    selected = {**pins(raw), "pypdf": PDF_VERSION}
    output.mkdir(parents=True, exist_ok=False)
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("PIP_")}
    environment.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1")
    with tempfile.TemporaryDirectory(prefix="provelume-pdf-resolution-") as directory:
        work = Path(directory)
        requirements, report = work / "selected.txt", work / "resolution.json"
        requirements.write_text("".join(f"{k}=={v}\n" for k, v in sorted(selected.items())))
        subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run",
                        "--ignore-installed", "--only-binary=:all:",
                        "--index-url", "https://pypi.org/simple", "--report", str(report),
                        "-r", str(requirements)], env=environment, check=True, timeout=180)
        resolution = json.loads(report.read_text(encoding="utf-8"))
        observed = {re.sub(r"[-_.]+", "-", r["metadata"]["name"]).lower():
                    r["metadata"]["version"] for r in resolution["install"]}
        if observed != selected or len(observed) != len(resolution["install"]):
            raise ValueError("resolver changed or omitted an existing pin")
        wheel_dir = work / "wheel"
        subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps",
                        "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
                        "--dest", str(wheel_dir), f"pypdf=={PDF_VERSION}"],
                       env=environment, check=True, timeout=120)
        wheels = list(wheel_dir.iterdir())
        if len(wheels) != 1 or wheels[0].name != f"pypdf-{PDF_VERSION}-py3-none-any.whl":
            raise ValueError("unexpected PDF wheel")
        wheel = wheels[0].read_bytes()
        wheel_digest = hashlib.sha256(wheel).hexdigest()
        pdf = next(r for r in resolution["install"] if r["metadata"]["name"].lower() == "pypdf")
        if pdf["download_info"]["archive_info"]["hashes"]["sha256"] != wheel_digest:
            raise ValueError("resolver and downloaded wheel disagree")
        with zipfile.ZipFile(wheels[0]) as archive:
            metadata = archive.read(f"pypdf-{PDF_VERSION}.dist-info/METADATA").decode()
            if f"\nVersion: {PDF_VERSION}\n" not in metadata:
                raise ValueError("PDF wheel version mismatch")
        candidate = replace_pdf(raw, wheel_digest).encode()
        (output / source.name).write_bytes(candidate)
        evidence = {
            "status": "RESOLVED_NOT_APPLIED", "platform": sys.platform,
            "python": platform.python_version(), "architecture": platform.machine(),
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            "source_lock_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "candidate_lock_sha256": hashlib.sha256(candidate).hexdigest(),
            "wheel_sha256": wheel_digest, "wheel_bytes": len(wheel),
            "resolved_pins": observed, "changed_packages": ["pypdf"],
            "other_pins_preserved": True,
        }
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(resolve(Path(__file__).resolve().parents[1], args.output), indent=2))


if __name__ == "__main__":
    main()
