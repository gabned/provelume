#!/usr/bin/env python3
"""Compare a package candidate with a separately provisioned rebuild.

The comparison recomputes artifact identities from bytes on disk and verifies
that both deterministic-build reports describe the same public source commit,
source epoch and exact direct toolchain. A green result is independent-runner
package evidence, not a claim that every release input is hash-locked.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from scripts.deterministic_build import (
    ArtifactIdentity,
    DeterministicBuildError,
    compare_artifact_sets,
    discover_artifacts,
)

SOURCE_REPOSITORY = "gabned/provelume"


class IndependentRebuildError(RuntimeError):
    """Raised when candidate and independent rebuild evidence is inconsistent."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndependentRebuildError(f"cannot read evidence report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise IndependentRebuildError(f"evidence report is not a JSON object: {path}")
    return value


def _reported_artifacts(report: dict[str, Any], path: Path) -> dict[str, ArtifactIdentity]:
    rows = report.get("artifacts")
    if not isinstance(rows, list):
        raise IndependentRebuildError(f"evidence report has no artifact list: {path}")
    artifacts: dict[str, ArtifactIdentity] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise IndependentRebuildError(f"invalid artifact entry in {path}")
        try:
            identity = ArtifactIdentity(
                name=str(row["name"]),
                sha256=str(row["sha256"]),
                size_bytes=int(row["size_bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IndependentRebuildError(f"invalid artifact identity in {path}") from exc
        if identity.name in artifacts:
            raise IndependentRebuildError(
                f"duplicate artifact identity in {path}: {identity.name}"
            )
        artifacts[identity.name] = identity
    return artifacts


def _validate_deterministic_report(
    report: dict[str, Any],
    path: Path,
    actual: dict[str, ArtifactIdentity],
    expected_commit: str,
) -> tuple[int, dict[str, Any]]:
    if report.get("schema_version") != 1:
        raise IndependentRebuildError(f"unsupported deterministic report schema: {path}")
    if report.get("byte_identical") is not True:
        raise IndependentRebuildError(f"deterministic report is not green: {path}")
    if report.get("source_repository") != SOURCE_REPOSITORY:
        raise IndependentRebuildError(f"unexpected source repository in {path}")
    if report.get("source_commit") != expected_commit:
        raise IndependentRebuildError(
            f"source commit mismatch in {path}: {report.get('source_commit')}"
        )
    try:
        source_date_epoch = int(report["source_date_epoch"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IndependentRebuildError(f"invalid source epoch in {path}") from exc
    if source_date_epoch <= 0:
        raise IndependentRebuildError(f"source epoch must be positive in {path}")

    reported = _reported_artifacts(report, path)
    try:
        compare_artifact_sets(actual, reported)
    except DeterministicBuildError as exc:
        raise IndependentRebuildError(
            f"report does not match artifact bytes for {path}: {exc}"
        ) from exc

    environment = report.get("environment")
    if not isinstance(environment, dict):
        raise IndependentRebuildError(f"missing build environment in {path}")
    tools = environment.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise IndependentRebuildError(f"missing direct build tool identity in {path}")
    return source_date_epoch, environment


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def compare_independent_rebuild(
    candidate_directory: Path,
    rebuild_directory: Path,
    candidate_report_path: Path,
    rebuild_report_path: Path,
    output_report_path: Path,
    *,
    expected_commit: str,
) -> dict[str, object]:
    candidate_directory = candidate_directory.resolve()
    rebuild_directory = rebuild_directory.resolve()
    candidate = discover_artifacts(candidate_directory)
    rebuild = discover_artifacts(rebuild_directory)

    candidate_report = _load_json(candidate_report_path)
    rebuild_report = _load_json(rebuild_report_path)
    candidate_epoch, candidate_environment = _validate_deterministic_report(
        candidate_report,
        candidate_report_path,
        candidate,
        expected_commit,
    )
    rebuild_epoch, rebuild_environment = _validate_deterministic_report(
        rebuild_report,
        rebuild_report_path,
        rebuild,
        expected_commit,
    )
    if candidate_epoch != rebuild_epoch:
        raise IndependentRebuildError(
            "candidate and rebuild use different SOURCE_DATE_EPOCH values"
        )
    if candidate_environment.get("tools") != rebuild_environment.get("tools"):
        raise IndependentRebuildError(
            "candidate and rebuild use different direct build tool versions"
        )

    try:
        identities = compare_artifact_sets(candidate, rebuild)
    except DeterministicBuildError as exc:
        raise IndependentRebuildError(
            f"independent rebuild differs from candidate: {exc}"
        ) from exc

    report: dict[str, object] = {
        "schema_version": 1,
        "assurance_level": "separate_ci_runner_package_rebuild_match",
        "byte_identical": True,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": expected_commit,
        "source_date_epoch": candidate_epoch,
        "candidate_environment": candidate_environment,
        "rebuild_environment": rebuild_environment,
        "artifacts": [asdict(identity) for identity in identities],
        "limitations": [
            "the two jobs are separately provisioned but use the same CI provider",
            "direct build tools are exact while the transitive dependency closure is not "
            "yet hash-locked",
            "the evidence covers Python wheel and source distribution only",
        ],
    }
    _write_json(output_report_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--rebuild-dir", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--rebuild-report", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        report = compare_independent_rebuild(
            options.candidate_dir,
            options.rebuild_dir,
            options.candidate_report,
            options.rebuild_report,
            options.output_report,
            expected_commit=options.commit,
        )
    except (IndependentRebuildError, DeterministicBuildError, OSError) as exc:
        print(f"independent rebuild verification failed: {exc}", file=sys.stderr)
        return 1
    for artifact in report["artifacts"]:
        assert isinstance(artifact, dict)
        print(f"{artifact['sha256']}  {artifact['name']}")
    print(f"independent rebuild report: {options.output_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
