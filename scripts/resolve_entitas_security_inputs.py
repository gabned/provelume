"""Resolve only the two affected Windows pins on the actual Windows target."""

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

CHANGES = {"pypdf": "6.21.2", "setuptools": "84.1.0"}


def pins(raw):
    rows = re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", raw, re.MULTILINE)
    result = {re.sub(r"[-_.]+", "-", name).lower(): version for name, version in rows}
    assert len(rows) == len(result) and set(CHANGES) <= set(result)
    return result


def resolve(root, output):
    assert sys.platform == "win32" and sys.version_info[:2] == (3, 12)
    assert platform.machine().lower() in {"amd64", "x86_64"}
    source = root / "build-lock/windows-py312-x86_64.requirements.txt"
    original = source.read_bytes()
    raw = original.decode("utf-8")
    selected = {**pins(raw), **CHANGES}
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="entitas-security-inputs-") as directory:
        work = Path(directory)
        requirements = work / "selected.txt"
        report = output / "native-pip-resolution.json"
        requirements.write_text("".join(f"{k}=={v}\n" for k, v in sorted(selected.items())))
        environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("PIP_")}
        environment.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--only-binary=:all:",
                "--index-url",
                "https://pypi.org/simple",
                "--report",
                str(report),
                "-r",
                str(requirements),
            ],
            env=environment,
            check=True,
            timeout=180,
        )
        resolved = json.loads(report.read_text())
        observed = {
            re.sub(r"[-_.]+", "-", row["metadata"]["name"]).lower(): row["metadata"]["version"]
            for row in resolved["install"]
        }
        assert observed == selected and len(observed) == len(resolved["install"])
        candidate = raw
        wheels = []
        for name, version in CHANGES.items():
            wheel_root = work / name
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    "--no-deps",
                    "--only-binary=:all:",
                    "--index-url",
                    "https://pypi.org/simple",
                    "--dest",
                    str(wheel_root),
                    f"{name}=={version}",
                ],
                env=environment,
                check=True,
                timeout=120,
            )
            paths = list(wheel_root.iterdir())
            assert len(paths) == 1 and paths[0].name == f"{name}-{version}-py3-none-any.whl"
            data = paths[0].read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            item = next(x for x in resolved["install"] if x["metadata"]["name"].lower() == name)
            assert item["download_info"]["archive_info"]["hashes"]["sha256"] == digest
            with zipfile.ZipFile(paths[0]) as archive:
                metadata = archive.read(f"{name}-{version}.dist-info/METADATA").decode()
                assert f"\nVersion: {version}\n" in metadata
            pattern = rf"(?m)^{name}==[^\n]*\n(?:[ \t]+[^\n]*\n)*"
            before = re.search(pattern, candidate)
            assert before
            comments = "".join(
                line for line in before[0].splitlines(True) if line.lstrip().startswith("#")
            )
            block = f"{name}=={version} \\\n    --hash=sha256:{digest}\n" + comments
            candidate, count = re.subn(pattern, lambda _, replacement=block: replacement, candidate)
            assert count == 1
            wheels.append(
                {
                    "name": name,
                    "version": version,
                    "filename": paths[0].name,
                    "sha256": digest,
                    "size_bytes": len(data),
                }
            )
        assert pins(candidate) == selected
        for name in set(selected) - set(CHANGES):
            pattern = rf"(?m)^{re.escape(name)}==[^\n]*\n(?:[ \t]+[^\n]*\n)*"
            assert re.search(pattern, raw)[0] == re.search(pattern, candidate)[0]
        candidate = candidate.replace(
            "# PDF-only correction: native Windows Python 3.12 pip resolution and wheel hash;\n"
            "# all other existing pip-compile pins and hashes are retained.\n",
            "# Security correction: native Windows Python 3.12 resolution of "
            "pypdf and setuptools;\n"
            "# all other existing pip-compile pins and hashes are retained.\n",
        )
        payload = candidate.encode()
        (output / source.name).write_bytes(payload)
        result = {
            "result": "RESOLVED_NOT_APPLIED_NOT_QUALIFIED",
            "changed_packages": CHANGES,
            "platform": sys.platform,
            "python": platform.python_version(),
            "architecture": platform.machine(),
            "resolved_pins": observed,
            "other_pin_blocks_byte_identical": True,
            "wheels": wheels,
            "source_lock_sha256": hashlib.sha256(original).hexdigest(),
            "candidate_lock_sha256": hashlib.sha256(payload).hexdigest(),
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
        }
        (output / "evidence.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    resolve(Path(__file__).resolve().parents[1], args.output)
