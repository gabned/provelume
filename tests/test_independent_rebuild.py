from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.artifact_identity import discover_artifacts
from scripts.independent_rebuild import (
    IndependentRebuildError,
    compare_independent_rebuild,
)

COMMIT = "a" * 40


def _write_artifacts(directory: Path, *, wheel: bytes = b"wheel") -> None:
    directory.mkdir(parents=True)
    (directory / "provelume-0.1.0-py3-none-any.whl").write_bytes(wheel)
    (directory / "provelume-0.1.0.tar.gz").write_bytes(b"source")


def _write_report(path: Path, artifacts: Path, *, commit: str = COMMIT) -> None:
    identities = discover_artifacts(artifacts)
    payload = {
        "schema_version": 1,
        "assurance": "same-source-same-environment-byte-identical",
        "full_release_reproducibility_claimed": False,
        "source_repository": "gabned/provelume",
        "source_commit": commit,
        "source_date_epoch": 1_700_000_000,
        "source_fingerprint_sha256": "f" * 64,
        "source_date_utc": "2023-11-14T22:13:20+00:00",
        "project_version": "0.1.0",
        "python": "3.12.14",
        "implementation": "CPython",
        "platform": "Linux-test",
        "build_frontend": {"name": "build", "version": "1.5.0"},
        "build_backend": {"name": "hatchling", "version": "1.31.0"},
        "artifacts": [
            {
                "kind": "wheel" if identity.name.endswith(".whl") else "sdist",
                "name": identity.name,
                "sha256": identity.sha256,
                "second_sha256": identity.sha256,
                "size_bytes": identity.size_bytes,
                "second_size_bytes": identity.size_bytes,
                "byte_identical": True,
            }
            for identity in identities.values()
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    candidate = tmp_path / "candidate"
    rebuild = tmp_path / "rebuild"
    _write_artifacts(candidate)
    _write_artifacts(rebuild)
    candidate_report = tmp_path / "candidate.json"
    rebuild_report = tmp_path / "rebuild.json"
    output_report = tmp_path / "independent.json"
    _write_report(candidate_report, candidate)
    _write_report(rebuild_report, rebuild)
    return candidate, rebuild, candidate_report, rebuild_report, output_report


def test_independent_rebuild_accepts_equal_artifact_bytes(tmp_path: Path) -> None:
    candidate, rebuild, candidate_report, rebuild_report, output_report = _fixture(
        tmp_path
    )
    report = compare_independent_rebuild(
        candidate,
        rebuild,
        candidate_report,
        rebuild_report,
        output_report,
        expected_commit=COMMIT,
    )
    assert report["byte_identical"] is True
    assert report["assurance_level"] == "separate_ci_runner_package_rebuild_match"
    assert len(report["artifacts"]) == 2
    assert json.loads(output_report.read_text())["source_commit"] == COMMIT


def test_independent_rebuild_recomputes_bytes_instead_of_trusting_report(
    tmp_path: Path,
) -> None:
    candidate, rebuild, candidate_report, rebuild_report, output_report = _fixture(
        tmp_path
    )
    (rebuild / "provelume-0.1.0-py3-none-any.whl").write_bytes(b"different")
    with pytest.raises(IndependentRebuildError, match="report does not match"):
        compare_independent_rebuild(
            candidate,
            rebuild,
            candidate_report,
            rebuild_report,
            output_report,
            expected_commit=COMMIT,
        )


def test_independent_rebuild_rejects_different_source_commit(tmp_path: Path) -> None:
    candidate, rebuild, candidate_report, rebuild_report, output_report = _fixture(
        tmp_path
    )
    _write_report(rebuild_report, rebuild, commit="b" * 40)
    with pytest.raises(IndependentRebuildError, match="source commit mismatch"):
        compare_independent_rebuild(
            candidate,
            rebuild,
            candidate_report,
            rebuild_report,
            output_report,
            expected_commit=COMMIT,
        )


def test_independent_rebuild_rejects_reported_hash_mismatch(tmp_path: Path) -> None:
    candidate, rebuild, candidate_report, rebuild_report, output_report = _fixture(
        tmp_path
    )
    payload = json.loads(candidate_report.read_text())
    payload["artifacts"][0]["sha256"] = "0" * 64
    candidate_report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(IndependentRebuildError, match="report does not match"):
        compare_independent_rebuild(
            candidate,
            rebuild,
            candidate_report,
            rebuild_report,
            output_report,
            expected_commit=COMMIT,
        )


def test_independent_rebuild_rejects_non_identical_deterministic_row(
    tmp_path: Path,
) -> None:
    candidate, rebuild, candidate_report, rebuild_report, output_report = _fixture(
        tmp_path
    )
    payload = json.loads(candidate_report.read_text())
    payload["artifacts"][0]["byte_identical"] = False
    candidate_report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(IndependentRebuildError, match="not byte-identical"):
        compare_independent_rebuild(
            candidate,
            rebuild,
            candidate_report,
            rebuild_report,
            output_report,
            expected_commit=COMMIT,
        )
