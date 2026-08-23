from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_input_bundle import (
    BuildInputBundleError,
    create_manifest,
    verify_manifest,
)
from scripts.offline_rebuild_evidence import (
    OfflineRebuildEvidenceError,
    create_offline_rebuild_evidence,
)

COMMIT = "a" * 40


def _wheelhouse(root: Path) -> Path:
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "build-1.5.0-py3-none-any.whl").write_bytes(b"build-wheel")
    (wheelhouse / "hatchling-1.32.0-py3-none-any.whl").write_bytes(
        b"hatchling-wheel"
    )
    (wheelhouse / "packaging-26.3-py3-none-any.whl").write_bytes(
        b"packaging-wheel"
    )
    return wheelhouse


def _requirements(root: Path) -> Path:
    path = root / "requirements-build.txt"
    path.write_text("build==1.5.0\nhatchling==1.32.0\n", encoding="utf-8")
    return path


def test_create_and_verify_immutable_wheelhouse_manifest(tmp_path: Path) -> None:
    wheelhouse = _wheelhouse(tmp_path)
    requirements = _requirements(tmp_path)
    manifest_path = tmp_path / "build-input-manifest.json"

    manifest = create_manifest(
        wheelhouse,
        requirements,
        manifest_path,
        commit=COMMIT,
    )
    assert len(manifest["wheels"]) == 3
    verified = verify_manifest(
        wheelhouse,
        requirements,
        manifest_path,
        expected_commit=COMMIT,
    )
    assert verified["source_commit"] == COMMIT


def test_verify_manifest_rejects_changed_wheel_bytes(tmp_path: Path) -> None:
    wheelhouse = _wheelhouse(tmp_path)
    requirements = _requirements(tmp_path)
    manifest_path = tmp_path / "build-input-manifest.json"
    create_manifest(wheelhouse, requirements, manifest_path, commit=COMMIT)

    (wheelhouse / "packaging-26.3-py3-none-any.whl").write_bytes(b"changed")
    with pytest.raises(BuildInputBundleError, match="identity mismatch"):
        verify_manifest(
            wheelhouse,
            requirements,
            manifest_path,
            expected_commit=COMMIT,
        )


def test_wheelhouse_rejects_non_wheel_input(tmp_path: Path) -> None:
    wheelhouse = _wheelhouse(tmp_path)
    requirements = _requirements(tmp_path)
    (wheelhouse / "unexpected.txt").write_text("not allowed", encoding="utf-8")
    with pytest.raises(BuildInputBundleError, match="non-wheel"):
        create_manifest(
            wheelhouse,
            requirements,
            tmp_path / "manifest.json",
            commit=COMMIT,
        )


def test_offline_rebuild_evidence_combines_verified_inputs(tmp_path: Path) -> None:
    wheelhouse = _wheelhouse(tmp_path)
    requirements = _requirements(tmp_path)
    manifest_path = tmp_path / "build-input-manifest.json"
    create_manifest(wheelhouse, requirements, manifest_path, commit=COMMIT)

    independent_path = tmp_path / "independent-rebuild-report.json"
    independent_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "byte_identical": True,
                "source_repository": "gabned/provelume",
                "source_commit": COMMIT,
                "source_date_epoch": 1_700_000_000,
                "candidate_environment": {"python": "3.12.14"},
                "rebuild_environment": {"python": "3.12.14"},
                "artifacts": [
                    {
                        "name": "provelume-0.1.0-py3-none-any.whl",
                        "sha256": "b" * 64,
                        "size_bytes": 123,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "offline-rebuild-evidence.json"
    report = create_offline_rebuild_evidence(
        wheelhouse,
        requirements,
        manifest_path,
        independent_path,
        output,
        expected_commit=COMMIT,
    )
    assert report["byte_identical"] is True
    assert report["build_input_bundle"]["wheel_count"] == 3
    assert json.loads(output.read_text())["source_commit"] == COMMIT


def test_offline_evidence_rejects_non_green_independent_report(
    tmp_path: Path,
) -> None:
    wheelhouse = _wheelhouse(tmp_path)
    requirements = _requirements(tmp_path)
    manifest_path = tmp_path / "build-input-manifest.json"
    create_manifest(wheelhouse, requirements, manifest_path, commit=COMMIT)
    independent_path = tmp_path / "independent.json"
    independent_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "byte_identical": False,
                "source_repository": "gabned/provelume",
                "source_commit": COMMIT,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(OfflineRebuildEvidenceError, match="not green"):
        create_offline_rebuild_evidence(
            wheelhouse,
            requirements,
            manifest_path,
            independent_path,
            tmp_path / "output.json",
            expected_commit=COMMIT,
        )
