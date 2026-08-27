#!/usr/bin/env python3
"""Verify the complete package-build evidence chain before release publication."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.artifact_identity import (
    ArtifactIdentity,
    ArtifactIdentityError,
    compare_artifact_sets,
    discover_artifacts,
)
from scripts.build_input_bundle import BuildInputBundleError, verify_manifest
from scripts.build_input_lock import BuildInputLockError, verify_lock
from scripts.deterministic_build import sha256_file

SOURCE_REPOSITORY = "gabned/provelume"
DETERMINISTIC_ASSURANCE = "same-source-same-environment-byte-identical"


class ReleaseAssuranceError(RuntimeError):
    """Raised when release evidence is incomplete, inconsistent or forged."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseAssuranceError(f"cannot read evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseAssuranceError(f"evidence must contain one JSON object: {path}")
    return value


def _validate_commit(commit: str) -> None:
    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise ReleaseAssuranceError("source commit must be a full lowercase Git SHA-1")


def _validate_release_identity(version: str, tag: str, channel: str) -> None:
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise ReleaseAssuranceError(f"invalid semantic version: {version}")
    if tag != f"v{version}":
        raise ReleaseAssuranceError(f"tag {tag} does not match version {version}")
    if channel not in {"development", "preview", "stable"}:
        raise ReleaseAssuranceError(f"unsupported release channel: {channel}")


def _artifact_rows(
    report: dict[str, Any],
    field: str,
    path: Path,
    *,
    require_row_byte_identical: bool = False,
) -> dict[str, ArtifactIdentity]:
    rows = report.get(field)
    if not isinstance(rows, list) or not rows:
        raise ReleaseAssuranceError(f"{path} has no {field} identities")
    identities: dict[str, ArtifactIdentity] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReleaseAssuranceError(f"invalid {field} identity in {path}")
        if require_row_byte_identical and row.get("byte_identical") is not True:
            raise ReleaseAssuranceError(
                f"non-identical deterministic artifact identity in {path}"
            )
        try:
            identity = ArtifactIdentity(
                name=str(row["name"]),
                sha256=str(row["sha256"]),
                size_bytes=int(row["size_bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReleaseAssuranceError(
                f"invalid {field} identity in {path}"
            ) from exc
        if identity.name in identities:
            raise ReleaseAssuranceError(
                f"duplicate artifact identity in {path}: {identity.name}"
            )
        identities[identity.name] = identity
    return identities


def _require_artifact_match(
    actual: dict[str, ArtifactIdentity],
    report: dict[str, Any],
    field: str,
    path: Path,
    *,
    require_row_byte_identical: bool = False,
) -> None:
    declared = _artifact_rows(
        report,
        field,
        path,
        require_row_byte_identical=require_row_byte_identical,
    )
    try:
        compare_artifact_sets(actual, declared)
    except ArtifactIdentityError as exc:
        raise ReleaseAssuranceError(
            f"{path} does not match candidate artifact bytes: {exc}"
        ) from exc


def _validate_schema(report: dict[str, Any], path: Path) -> None:
    schema_version = report.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise ReleaseAssuranceError(f"unsupported evidence schema: {path}")


def _validate_source_identity(
    report: dict[str, Any],
    path: Path,
    expected_commit: str,
) -> int:
    _validate_schema(report, path)
    if report.get("source_repository") != SOURCE_REPOSITORY:
        raise ReleaseAssuranceError(f"unexpected source repository in {path}")
    if report.get("source_commit") != expected_commit:
        raise ReleaseAssuranceError(f"source commit mismatch in {path}")
    try:
        epoch = int(report["source_date_epoch"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseAssuranceError(f"invalid source epoch in {path}") from exc
    if epoch <= 0:
        raise ReleaseAssuranceError(f"source epoch must be positive in {path}")
    return epoch


def _validate_green_report(
    report: dict[str, Any],
    path: Path,
    expected_commit: str,
) -> int:
    epoch = _validate_source_identity(report, path, expected_commit)
    if report.get("byte_identical") is not True:
        raise ReleaseAssuranceError(f"evidence is not green: {path}")
    return epoch


def _validate_deterministic_report(
    report: dict[str, Any],
    path: Path,
    expected_commit: str,
) -> int:
    epoch = _validate_source_identity(report, path, expected_commit)
    if report.get("assurance") != DETERMINISTIC_ASSURANCE:
        raise ReleaseAssuranceError(f"unexpected deterministic assurance in {path}")
    if report.get("full_release_reproducibility_claimed") is not False:
        raise ReleaseAssuranceError(f"invalid reproducibility claim in {path}")
    return epoch


def _wheel_identity_map(rows: Any, *, path: Path) -> dict[str, tuple[str, int]]:
    if not isinstance(rows, list) or not rows:
        raise ReleaseAssuranceError(f"wheel identity list is missing in {path}")
    identities: dict[str, tuple[str, int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReleaseAssuranceError(f"invalid wheel identity in {path}")
        name_value = row.get("filename", row.get("name"))
        try:
            name = str(name_value)
            digest = str(row["sha256"])
            size = int(row["size_bytes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ReleaseAssuranceError(f"invalid wheel identity in {path}") from exc
        if not name or name == "None" or name in identities:
            raise ReleaseAssuranceError(f"duplicate/empty wheel identity in {path}")
        identities[name] = (digest, size)
    return identities


def _file_identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ReleaseAssuranceError(f"evidence is not a regular file: {path}")
    return {
        "name": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def create_release_assurance(
    *,
    candidate_directory: Path,
    wheelhouse: Path,
    direct_requirements: Path,
    json_lock: Path,
    requirements_lock: Path,
    build_input_manifest: Path,
    deterministic_report: Path,
    independent_report: Path,
    offline_report: Path,
    output: Path,
    version: str,
    tag: str,
    channel: str,
    commit: str,
    enforce_target: bool = True,
) -> dict[str, object]:
    _validate_commit(commit)
    _validate_release_identity(version, tag, channel)
    candidate = discover_artifacts(candidate_directory.resolve())
    wheel_names = [name for name in candidate if name.endswith(".whl")]
    source_names = [name for name in candidate if name.endswith(".tar.gz")]
    if len(wheel_names) != 1 or not wheel_names[0].startswith(
        f"provelume-{version}-"
    ):
        raise ReleaseAssuranceError("candidate wheel does not match release version")
    if source_names != [f"provelume-{version}.tar.gz"]:
        raise ReleaseAssuranceError(
            "candidate source distribution does not match version"
        )

    lock_payload = verify_lock(
        wheelhouse,
        direct_requirements,
        json_lock,
        requirements_lock,
        enforce_target=enforce_target,
    )
    per_run_manifest = verify_manifest(
        wheelhouse,
        direct_requirements,
        build_input_manifest,
        expected_commit=commit,
    )
    committed_wheels = _wheel_identity_map(lock_payload.get("wheels"), path=json_lock)
    per_run_wheels = _wheel_identity_map(
        per_run_manifest.get("wheels"), path=build_input_manifest
    )
    if committed_wheels != per_run_wheels:
        raise ReleaseAssuranceError(
            "per-run build-input manifest differs from the reviewed build lock"
        )

    deterministic = _load_json(deterministic_report)
    independent = _load_json(independent_report)
    offline = _load_json(offline_report)
    source_epoch = _validate_deterministic_report(
        deterministic,
        deterministic_report,
        commit,
    )
    independent_epoch = _validate_green_report(
        independent,
        independent_report,
        commit,
    )
    offline_epoch = _validate_green_report(offline, offline_report, commit)
    if {source_epoch, independent_epoch, offline_epoch} != {source_epoch}:
        raise ReleaseAssuranceError("evidence reports use different source epochs")
    _require_artifact_match(
        candidate,
        deterministic,
        "artifacts",
        deterministic_report,
        require_row_byte_identical=True,
    )
    _require_artifact_match(candidate, independent, "artifacts", independent_report)
    _require_artifact_match(candidate, offline, "package_artifacts", offline_report)

    bundle = offline.get("build_input_bundle")
    if not isinstance(bundle, dict):
        raise ReleaseAssuranceError("offline evidence has no build-input bundle")
    if bundle.get("manifest") != build_input_manifest.name:
        raise ReleaseAssuranceError("offline evidence references another input manifest")
    if bundle.get("manifest_sha256") != sha256_file(build_input_manifest):
        raise ReleaseAssuranceError("offline evidence input-manifest hash mismatch")
    if (
        bundle.get("installation_mode")
        != "pip --no-index --find-links verified-wheelhouse"
    ):
        raise ReleaseAssuranceError(
            "offline evidence does not prove offline installation"
        )
    if _wheel_identity_map(bundle.get("wheels"), path=offline_report) != per_run_wheels:
        raise ReleaseAssuranceError(
            "offline evidence wheel set differs from reviewed lock"
        )

    evidence_paths = [
        json_lock,
        requirements_lock,
        build_input_manifest,
        deterministic_report,
        independent_report,
        offline_report,
    ]
    payload: dict[str, object] = {
        "schema_version": 1,
        "assurance_level": "reviewed_lock_offline_separate_runner_release_gate",
        "publication_gate": "passed",
        "source_repository": SOURCE_REPOSITORY,
        "version": version,
        "tag": tag,
        "channel": channel,
        "source_commit": commit,
        "source_date_epoch": source_epoch,
        "build_lock": {
            "lock_id": lock_payload.get("lock_id"),
            "target": lock_payload.get("target"),
            "json_lock": _file_identity(json_lock),
            "requirements_lock": _file_identity(requirements_lock),
            "per_run_manifest": _file_identity(build_input_manifest),
            "wheel_count": len(per_run_wheels),
        },
        "package_artifacts": [
            asdict(candidate[name]) for name in sorted(candidate)
        ],
        "evidence": [_file_identity(path) for path in evidence_paths],
        "limitations": [
            "candidate and rebuild jobs use separately provisioned runners from the "
            "same CI provider",
            "the reviewed lock targets Ubuntu x86_64 / CPython 3.12.14 package builds",
            "the Windows preview runtime has a retained hash lock, but installer "
            "reproducibility, independent rebuild and code signing are not established; "
            "container images still need their own retained locks and evidence",
        ],
    }
    _atomic_json(output, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--direct-requirements", type=Path, required=True)
    parser.add_argument("--json-lock", type=Path, required=True)
    parser.add_argument("--requirements-lock", type=Path, required=True)
    parser.add_argument("--build-input-manifest", type=Path, required=True)
    parser.add_argument("--deterministic-report", type=Path, required=True)
    parser.add_argument("--independent-report", type=Path, required=True)
    parser.add_argument("--offline-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--commit", required=True)
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        payload = create_release_assurance(
            candidate_directory=options.candidate_dir,
            wheelhouse=options.wheelhouse,
            direct_requirements=options.direct_requirements,
            json_lock=options.json_lock,
            requirements_lock=options.requirements_lock,
            build_input_manifest=options.build_input_manifest,
            deterministic_report=options.deterministic_report,
            independent_report=options.independent_report,
            offline_report=options.offline_report,
            output=options.output,
            version=options.version,
            tag=options.tag,
            channel=options.channel,
            commit=options.commit,
        )
    except (
        ArtifactIdentityError,
        BuildInputBundleError,
        BuildInputLockError,
        ReleaseAssuranceError,
        OSError,
    ) as exc:
        print(f"release assurance failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"release assurance passed for {payload['tag']} at "
        f"{payload['source_commit']}: {options.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
