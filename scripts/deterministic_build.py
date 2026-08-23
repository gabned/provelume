#!/usr/bin/env python3
"""Build and compare Provelume Python distributions from clean source copies."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCE_REPOSITORY = "gabned/provelume"
EVIDENCE_SCHEMA_VERSION = 1
IGNORED_NAMES = {
    ".git",
    ".local",
    ".mypy_cache",
    ".pytest_cache",
    ".release-runtime",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "release",
}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


class DeterministicBuildError(RuntimeError):
    """Raised when a deterministic build invariant is not satisfied."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_date_epoch(value: str | None) -> int:
    if value is None:
        raise DeterministicBuildError("SOURCE_DATE_EPOCH is required")
    try:
        timestamp = int(value)
    except ValueError as exc:
        raise DeterministicBuildError("SOURCE_DATE_EPOCH must be an integer") from exc
    if timestamp < 0:
        raise DeterministicBuildError("SOURCE_DATE_EPOCH must not be negative")
    return timestamp


def project_configuration(source: Path) -> tuple[str, str]:
    with (source / "pyproject.toml").open("rb") as handle:
        configuration = tomllib.load(handle)
    version = configuration.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise DeterministicBuildError("project version is missing")
    requirements = configuration.get("build-system", {}).get("requires", [])
    backend_requirements = [
        requirement for requirement in requirements if str(requirement).startswith("hatchling")
    ]
    if len(backend_requirements) != 1 or "==" not in str(backend_requirements[0]):
        raise DeterministicBuildError("Hatchling build backend must be pinned exactly")
    backend_version = str(backend_requirements[0]).split("==", 1)[1]
    reproducible = (
        configuration.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("reproducible")
    )
    if reproducible is not True:
        raise DeterministicBuildError("Hatch reproducible build mode must be explicit")
    installed_backend = importlib.metadata.version("hatchling")
    if installed_backend != backend_version:
        raise DeterministicBuildError(
            f"installed Hatchling {installed_backend} does not match pinned {backend_version}"
        )
    return version, backend_version


def _ignored(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in IGNORED_NAMES for part in relative.parts):
        return True
    return path.suffix in IGNORED_SUFFIXES


def validate_source_tree(source: Path) -> None:
    for path in source.rglob("*"):
        if _ignored(path, source):
            continue
        if path.is_symlink():
            relative = path.relative_to(source).as_posix()
            raise DeterministicBuildError(
                f"source symlinks are not accepted by the release builder: {relative}"
            )


def source_fingerprint(source: Path) -> str:
    validate_source_tree(source)
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if _ignored(path, source) or not path.is_file():
            continue
        relative = path.relative_to(source).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
        digest.update(b"\n")
    return digest.hexdigest()


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in IGNORED_NAMES}
    ignored.update(name for name in names if Path(name).suffix in IGNORED_SUFFIXES)
    return ignored


def _build_environment(epoch: int) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "SOURCE_DATE_EPOCH": str(epoch),
            "TZ": "UTC",
        }
    )
    if os.name != "nt":
        environment.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
    return environment


def build_once(source: Path, workspace: Path, epoch: int) -> dict[str, Path]:
    checkout = workspace / "source"
    output = workspace / "dist"
    shutil.copytree(source, checkout, ignore=_copy_ignore, copy_function=shutil.copy2)
    output.mkdir(parents=True)
    command = [
        sys.executable,
        "-m",
        "build",
        "--no-isolation",
        "--sdist",
        "--wheel",
        "--outdir",
        str(output),
    ]
    subprocess.run(
        command,
        cwd=checkout,
        env=_build_environment(epoch),
        check=True,
    )
    artifacts = sorted(output.iterdir())
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise DeterministicBuildError("each build must produce exactly one wheel and one sdist")
    return {"wheel": wheels[0], "sdist": sdists[0]}


def compare_builds(
    first: dict[str, Path],
    second: dict[str, Path],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for kind in ("wheel", "sdist"):
        first_path = first[kind]
        second_path = second[kind]
        first_hash = sha256_file(first_path)
        second_hash = sha256_file(second_path)
        record = {
            "kind": kind,
            "name": first_path.name,
            "sha256": first_hash,
            "second_sha256": second_hash,
            "size_bytes": first_path.stat().st_size,
            "second_size_bytes": second_path.stat().st_size,
            "byte_identical": (
                first_path.name == second_path.name
                and first_hash == second_hash
                and first_path.stat().st_size == second_path.stat().st_size
            ),
        }
        records.append(record)
    return records


def _distribution_names(version: str, records: list[dict[str, Any]]) -> None:
    expected_sdist = f"provelume-{version}.tar.gz"
    for record in records:
        name = str(record["name"])
        if record["kind"] == "wheel" and not name.startswith(f"provelume-{version}-"):
            raise DeterministicBuildError("wheel filename does not match project version")
        if record["kind"] == "sdist" and name != expected_sdist:
            raise DeterministicBuildError("sdist filename does not match project version")


def evidence_payload(
    *,
    source: Path,
    epoch: int,
    commit: str | None,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    version, backend_version = project_configuration(source)
    _distribution_names(version, records)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "assurance": "same-source-same-environment-byte-identical",
        "full_release_reproducibility_claimed": False,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": commit,
        "source_fingerprint_sha256": source_fingerprint(source),
        "source_date_epoch": epoch,
        "source_date_utc": datetime.fromtimestamp(epoch, UTC).isoformat(),
        "project_version": version,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "build_frontend": {
            "name": "build",
            "version": importlib.metadata.version("build"),
        },
        "build_backend": {
            "name": "hatchling",
            "version": backend_version,
        },
        "artifacts": records,
    }


def run(
    *,
    source: Path,
    output_dir: Path,
    evidence: Path,
    commit: str | None,
) -> dict[str, Any]:
    source = source.expanduser().resolve(strict=True)
    if commit is not None and (
        len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise DeterministicBuildError("commit must be a lowercase 40-character SHA-1")
    if not (source / "pyproject.toml").is_file():
        raise DeterministicBuildError("source directory does not contain pyproject.toml")
    validate_source_tree(source)
    epoch = source_date_epoch(os.environ.get("SOURCE_DATE_EPOCH"))
    with tempfile.TemporaryDirectory(prefix="provelume-build-") as temporary:
        root = Path(temporary)
        first = build_once(source, root / "first", epoch)
        second = build_once(source, root / "second", epoch)
        records = compare_builds(first, second)
        payload = evidence_payload(
            source=source,
            epoch=epoch,
            commit=commit,
            records=records,
        )
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        mismatches = [record for record in records if not record["byte_identical"]]
        if mismatches:
            names = ", ".join(str(record["name"]) for record in mismatches)
            raise DeterministicBuildError(f"distribution builds differ: {names}")
        output_dir.mkdir(parents=True, exist_ok=True)
        for existing in output_dir.iterdir():
            if existing.is_file() and (
                existing.suffix == ".whl" or existing.name.endswith(".tar.gz")
            ):
                existing.unlink()
        for path in first.values():
            shutil.copy2(path, output_dir / path.name)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Provelume distributions twice and require byte-identical output"
    )
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--evidence", type=Path, default=Path("build-determinism.json"))
    parser.add_argument("--commit")
    args = parser.parse_args()
    try:
        payload = run(
            source=args.source,
            output_dir=args.output_dir,
            evidence=args.evidence,
            commit=args.commit,
        )
    except (DeterministicBuildError, subprocess.CalledProcessError) as exc:
        print(f"deterministic build failed: {exc}", file=sys.stderr)
        return 1
    for artifact in payload["artifacts"]:
        print(f"{artifact['sha256']}  {artifact['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
