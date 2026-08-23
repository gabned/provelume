#!/usr/bin/env python3
"""Compare Provelume distributions rebuilt in two separately scheduled jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from build_environment_lock import (
    BuildEnvironmentLockError,
    read_lock,
    validate_lock,
)

REPORT_SCHEMA_VERSION = 1
ASSURANCE = "pinned-oci-cross-job-rebuild"
SOURCE_REPOSITORY = "gabned/provelume"
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_DISTRIBUTION_BYTES = 250 * 1024 * 1024
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CrossJobRebuildError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FileIdentity:
    name: str
    size_bytes: int
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise CrossJobRebuildError(f"cannot read evidence file: {path}") from exc
    return digest.hexdigest()


def file_identity(path: Path) -> FileIdentity:
    if path.is_symlink() or not path.is_file():
        raise CrossJobRebuildError(f"evidence file is unavailable or a symlink: {path}")
    size = path.stat().st_size
    if size > MAX_DISTRIBUTION_BYTES:
        raise CrossJobRebuildError(
            f"distribution exceeds the {MAX_DISTRIBUTION_BYTES}-byte limit: {path.name}"
        )
    return FileIdentity(name=path.name, size_bytes=size, sha256=sha256_file(path))


def distribution_identities(directory: Path) -> list[FileIdentity]:
    if directory.is_symlink() or not directory.is_dir():
        raise CrossJobRebuildError(f"distribution directory is unavailable: {directory}")
    paths = sorted(path for path in directory.iterdir() if path.is_file())
    wheels = [path for path in paths if path.name.endswith(".whl")]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise CrossJobRebuildError(
            "each rebuild job must provide exactly one wheel and one source distribution"
        )
    return sorted(
        [file_identity(wheels[0]), file_identity(sdists[0])],
        key=lambda item: item.name,
    )


def read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CrossJobRebuildError(f"{label} is missing or a symlink")
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise CrossJobRebuildError(
            f"{label} exceeds the {MAX_EVIDENCE_BYTES}-byte safety limit"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise CrossJobRebuildError(f"{label} is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise CrossJobRebuildError(f"{label} is not valid JSON") from exc
    except OSError as exc:
        raise CrossJobRebuildError(f"cannot read {label}") from exc
    if not isinstance(value, dict):
        raise CrossJobRebuildError(f"{label} must contain a JSON object")
    return value


def _artifact_rows(value: Any, label: str) -> dict[str, FileIdentity]:
    if not isinstance(value, list) or len(value) != 2:
        raise CrossJobRebuildError(f"{label} must contain one wheel and one sdist")
    rows: dict[str, FileIdentity] = {}
    kinds: set[str] = set()
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise CrossJobRebuildError(f"{label}[{index}] must be an object")
        name = row.get("name")
        size = row.get("size_bytes")
        digest = row.get("sha256")
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise CrossJobRebuildError(f"{label}[{index}].name is unsafe")
        if name.endswith(".whl"):
            kinds.add("wheel")
        elif name.endswith(".tar.gz"):
            kinds.add("sdist")
        else:
            raise CrossJobRebuildError(f"{label}[{index}] has an unsupported artifact")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise CrossJobRebuildError(f"{label}[{index}].size_bytes is invalid")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise CrossJobRebuildError(f"{label}[{index}].sha256 is invalid")
        if name in rows:
            raise CrossJobRebuildError(f"duplicate artifact in {label}: {name}")
        rows[name] = FileIdentity(name=name, size_bytes=size, sha256=digest)
    if kinds != {"wheel", "sdist"}:
        raise CrossJobRebuildError(f"{label} must contain one wheel and one sdist")
    return rows


def _validate_build_report(
    report: dict[str, Any],
    *,
    label: str,
    commit: str,
    requirements_lock: Path,
    distributions: list[FileIdentity],
    expected_python: str,
    expected_os: str,
    expected_architecture: str,
) -> None:
    if report.get("schema_version") != 1:
        raise CrossJobRebuildError(f"{label} build report schema is unsupported")
    if report.get("result") != "match":
        raise CrossJobRebuildError(f"{label} internal double-build result is not match")
    if report.get("source_repository") != SOURCE_REPOSITORY:
        raise CrossJobRebuildError(f"{label} source repository is unexpected")
    if report.get("source_commit") != commit:
        raise CrossJobRebuildError(f"{label} source commit differs")
    if report.get("resolved_build_packages_match") is not True:
        raise CrossJobRebuildError(f"{label} resolved build packages differ")

    lock = report.get("build_input_lock")
    if not isinstance(lock, dict):
        raise CrossJobRebuildError(f"{label} has no build-input lock evidence")
    if lock.get("filename") != requirements_lock.name:
        raise CrossJobRebuildError(f"{label} build-input lock filename differs")
    if lock.get("sha256") != sha256_file(requirements_lock):
        raise CrossJobRebuildError(f"{label} build-input lock digest differs")

    builder = report.get("builder")
    if not isinstance(builder, dict):
        raise CrossJobRebuildError(f"{label} builder evidence is missing")
    if builder.get("python_implementation") != "CPython":
        raise CrossJobRebuildError(f"{label} did not use CPython")
    expected_version = expected_python.removeprefix("CPython ")
    if builder.get("python_version") != expected_version:
        raise CrossJobRebuildError(f"{label} Python version differs from environment lock")
    if str(builder.get("operating_system", "")).casefold() != expected_os.casefold():
        raise CrossJobRebuildError(f"{label} operating system differs from environment lock")
    machine = str(builder.get("machine", "")).casefold()
    accepted_architectures = {
        "amd64": {"amd64", "x86_64"},
    }
    if machine not in accepted_architectures.get(expected_architecture, {expected_architecture}):
        raise CrossJobRebuildError(f"{label} architecture differs from environment lock")

    reported = _artifact_rows(report.get("artifacts"), f"{label}.artifacts")
    actual = {item.name: item for item in distributions}
    if reported != actual:
        raise CrossJobRebuildError(f"{label} report identities differ from uploaded bytes")
    if any(not isinstance(row, dict) or row.get("matches") is not True for row in report["artifacts"]):
        raise CrossJobRebuildError(f"{label} internal artifact comparison did not match")


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare_jobs(
    *,
    left: Path,
    right: Path,
    commit: str,
    environment_lock: Path,
    requirements_lock: Path,
    report_path: Path,
) -> dict[str, Any]:
    if not FULL_COMMIT.fullmatch(commit):
        raise CrossJobRebuildError("source commit must be a full lowercase SHA")
    try:
        environment = validate_lock(
            read_lock(environment_lock),
            requirements_lock=requirements_lock,
        )
    except BuildEnvironmentLockError as exc:
        raise CrossJobRebuildError(f"build environment lock is invalid: {exc}") from exc

    job_data = []
    for label, root in (("A", left), ("B", right)):
        distributions = distribution_identities(root / "dist")
        evidence_path = root / "build-comparison.json"
        evidence = read_json(evidence_path, f"job {label} build comparison")
        _validate_build_report(
            evidence,
            label=f"job {label}",
            commit=commit,
            requirements_lock=requirements_lock,
            distributions=distributions,
            expected_python=environment["python"],
            expected_os=environment["operating_system"],
            expected_architecture=environment["architecture"],
        )
        job_data.append(
            {
                "label": label,
                "evidence_sha256": sha256_file(evidence_path),
                "artifacts": [asdict(item) for item in distributions],
            }
        )

    left_rows = {
        row["name"]: FileIdentity(**row)
        for row in job_data[0]["artifacts"]
    }
    right_rows = {
        row["name"]: FileIdentity(**row)
        for row in job_data[1]["artifacts"]
    }
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "assurance": ASSURANCE,
        "result": "pending",
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": commit,
        "environment_lock": {
            "filename": environment_lock.name,
            "sha256": sha256_file(environment_lock),
            "image_reference": environment["reference"],
            "image_digest": environment["digest"],
            "target": {
                "operating_system": environment["operating_system"],
                "architecture": environment["architecture"],
                "python": environment["python"],
            },
        },
        "build_input_lock": {
            "filename": requirements_lock.name,
            "sha256": sha256_file(requirements_lock),
        },
        "comparison_host": {
            "operating_system": platform.system(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "jobs": job_data,
        "artifacts": [],
        "limitations": [
            "Both jobs use the same pinned Linux/amd64 OCI image target.",
            "The GitHub Actions service and host kernel remain outside the image digest.",
            "The comparison is not an external third-party rebuild.",
        ],
    }

    try:
        if set(left_rows) != set(right_rows):
            raise CrossJobRebuildError("rebuild jobs produced different filenames")
        artifact_comparison = []
        mismatches = []
        for name in sorted(left_rows):
            first = left_rows[name]
            second = right_rows[name]
            matches = first == second
            artifact_comparison.append(
                {
                    "name": name,
                    "size_bytes": first.size_bytes,
                    "sha256": first.sha256,
                    "second_size_bytes": second.size_bytes,
                    "second_sha256": second.sha256,
                    "matches": matches,
                }
            )
            if not matches:
                mismatches.append(name)
        report["artifacts"] = artifact_comparison
        if mismatches:
            raise CrossJobRebuildError(
                "cross-job distribution bytes differ: " + ", ".join(mismatches)
            )
    except CrossJobRebuildError:
        report["result"] = "mismatch"
        _write_report(report_path, report)
        raise

    report["result"] = "match"
    _write_report(report_path, report)
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--left", type=Path, required=True)
    value.add_argument("--right", type=Path, required=True)
    value.add_argument("--commit", required=True)
    value.add_argument(
        "--environment-lock",
        type=Path,
        default=Path("build-environment.lock.json"),
    )
    value.add_argument(
        "--requirements-lock",
        type=Path,
        default=Path("requirements-build.lock"),
    )
    value.add_argument("--report", type=Path, default=Path("cross-job-rebuild.json"))
    return value


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        report = compare_jobs(
            left=arguments.left,
            right=arguments.right,
            commit=arguments.commit,
            environment_lock=arguments.environment_lock,
            requirements_lock=arguments.requirements_lock,
            report_path=arguments.report,
        )
    except (CrossJobRebuildError, OSError) as exc:
        print(f"cross-job rebuild comparison failed: {exc}", file=sys.stderr)
        return 1
    names = ", ".join(row["name"] for row in report["artifacts"])
    print(f"cross-job rebuild comparison passed: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
