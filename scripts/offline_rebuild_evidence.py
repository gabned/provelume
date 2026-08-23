#!/usr/bin/env python3
"""Combine verified wheelhouse and independent package rebuild evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from scripts.build_input_bundle import BuildInputBundleError, verify_manifest
from scripts.deterministic_build import sha256_file

SOURCE_REPOSITORY = "gabned/provelume"


class OfflineRebuildEvidenceError(RuntimeError):
    """Raised when offline rebuild evidence cannot be trusted."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OfflineRebuildEvidenceError(f"cannot read evidence report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OfflineRebuildEvidenceError(f"evidence report is not a JSON object: {path}")
    return value


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def create_offline_rebuild_evidence(
    wheelhouse: Path,
    requirements: Path,
    build_input_manifest_path: Path,
    independent_report_path: Path,
    output_path: Path,
    *,
    expected_commit: str,
) -> dict[str, object]:
    build_inputs = verify_manifest(
        wheelhouse,
        requirements,
        build_input_manifest_path,
        expected_commit=expected_commit,
    )
    independent = _load_json(independent_report_path)
    if independent.get("schema_version") != 1:
        raise OfflineRebuildEvidenceError("unsupported independent rebuild report schema")
    if independent.get("byte_identical") is not True:
        raise OfflineRebuildEvidenceError("independent rebuild report is not green")
    if independent.get("source_repository") != SOURCE_REPOSITORY:
        raise OfflineRebuildEvidenceError(
            "unexpected source repository in independent rebuild report"
        )
    if independent.get("source_commit") != expected_commit:
        raise OfflineRebuildEvidenceError(
            "source commit mismatch in independent rebuild report"
        )
    artifacts = independent.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise OfflineRebuildEvidenceError(
            "independent rebuild report has no package artifacts"
        )

    direct_requirements = build_inputs.get("direct_requirements")
    wheels = build_inputs.get("wheels")
    assert isinstance(direct_requirements, dict)
    assert isinstance(wheels, list)
    report: dict[str, object] = {
        "schema_version": 1,
        "assurance_level": "separate_runner_offline_wheelhouse_package_rebuild_match",
        "byte_identical": True,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": expected_commit,
        "source_date_epoch": independent.get("source_date_epoch"),
        "build_input_bundle": {
            "manifest": build_input_manifest_path.name,
            "manifest_sha256": sha256_file(build_input_manifest_path),
            "direct_requirements": direct_requirements,
            "wheel_count": len(wheels),
            "wheels": wheels,
            "installation_mode": "pip --no-index --find-links verified-wheelhouse",
        },
        "candidate_environment": independent.get("candidate_environment"),
        "rebuild_environment": independent.get("rebuild_environment"),
        "package_artifacts": artifacts,
        "limitations": [
            "the transitive wheel closure is immutable for this workflow run but is "
            "not yet a reviewed repository lock",
            "candidate and rebuild jobs use separately provisioned runners from the "
            "same CI provider",
            "the evidence covers Python wheel and source distribution only",
        ],
    }
    _write_json(output_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--build-input-manifest", type=Path, required=True)
    parser.add_argument("--independent-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        report = create_offline_rebuild_evidence(
            options.wheelhouse,
            options.requirements,
            options.build_input_manifest,
            options.independent_report,
            options.output,
            expected_commit=options.commit,
        )
    except (BuildInputBundleError, OfflineRebuildEvidenceError, OSError) as exc:
        print(f"offline rebuild evidence failed: {exc}", file=sys.stderr)
        return 1
    bundle = report["build_input_bundle"]
    assert isinstance(bundle, dict)
    print(
        f"verified offline rebuild with {bundle['wheel_count']} build-input wheels: "
        f"{options.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
