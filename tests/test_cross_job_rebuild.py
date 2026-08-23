from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

COMMIT = "6" * 40


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _modules() -> tuple[ModuleType, ModuleType]:
    scripts = Path(__file__).parents[1] / "scripts"
    environment = _load_module(
        "build_environment_lock",
        scripts / "build_environment_lock.py",
    )
    cross = _load_module(
        "provelume_cross_job_rebuild",
        scripts / "cross_job_rebuild.py",
    )
    return environment, cross


def _locks(tmp_path: Path, environment: ModuleType) -> tuple[Path, Path]:
    requirements = tmp_path / "requirements-build.lock"
    requirements.write_text(
        "# synthetic public lock\n"
        "build==1.5.0 --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    environment_lock = tmp_path / "build-environment.lock.json"
    environment.write_lock(
        environment_lock,
        environment.generate_payload(
            tag="3.12.14-slim-bookworm",
            digest="sha256:" + "b" * 64,
            python_target="CPython 3.12.14",
            requirements_lock=requirements,
        ),
    )
    return requirements, environment_lock


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _job(
    root: Path,
    cross: ModuleType,
    requirements: Path,
    *,
    wheel: bytes = b"identical wheel",
    sdist: bytes = b"identical source",
    commit: str = COMMIT,
    machine: str = "x86_64",
) -> Path:
    dist = root / "dist"
    dist.mkdir(parents=True)
    wheel_path = dist / "provelume-0.1.0-py3-none-any.whl"
    sdist_path = dist / "provelume-0.1.0.tar.gz"
    wheel_path.write_bytes(wheel)
    sdist_path.write_bytes(sdist)
    identities = cross.distribution_identities(dist)
    artifact_rows = [
        {
            "name": item.name,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "second_size_bytes": item.size_bytes,
            "second_sha256": item.sha256,
            "matches": True,
        }
        for item in identities
    ]
    _write_json(
        root / "build-comparison.json",
        {
            "schema_version": 1,
            "result": "match",
            "source_repository": "gabned/provelume",
            "source_commit": commit,
            "resolved_build_packages_match": True,
            "build_input_lock": {
                "filename": requirements.name,
                "sha256": cross.sha256_file(requirements),
            },
            "builder": {
                "python_implementation": "CPython",
                "python_version": "3.12.14",
                "operating_system": "Linux",
                "machine": machine,
            },
            "artifacts": artifact_rows,
        },
    )
    return root


def test_cross_job_rebuild_match_writes_machine_evidence(tmp_path: Path) -> None:
    environment, cross = _modules()
    requirements, environment_lock = _locks(tmp_path, environment)
    left = _job(tmp_path / "left", cross, requirements)
    right = _job(tmp_path / "right", cross, requirements)
    report_path = tmp_path / "cross-job-rebuild.json"

    report = cross.compare_jobs(
        left=left,
        right=right,
        commit=COMMIT,
        environment_lock=environment_lock,
        requirements_lock=requirements,
        report_path=report_path,
    )

    assert report["result"] == "match"
    assert report["assurance"] == "pinned-oci-cross-job-rebuild"
    assert report["environment_lock"]["image_digest"] == "sha256:" + "b" * 64
    assert [job["label"] for job in report["jobs"]] == ["A", "B"]
    assert all(row["matches"] is True for row in report["artifacts"])
    assert json.loads(report_path.read_text(encoding="utf-8"))["result"] == "match"


def test_cross_job_byte_mismatch_fails_and_preserves_report(tmp_path: Path) -> None:
    environment, cross = _modules()
    requirements, environment_lock = _locks(tmp_path, environment)
    left = _job(tmp_path / "left", cross, requirements)
    right = _job(
        tmp_path / "right",
        cross,
        requirements,
        wheel=b"different wheel",
    )
    report_path = tmp_path / "cross-job-rebuild.json"

    with pytest.raises(cross.CrossJobRebuildError, match="bytes differ"):
        cross.compare_jobs(
            left=left,
            right=right,
            commit=COMMIT,
            environment_lock=environment_lock,
            requirements_lock=requirements,
            report_path=report_path,
        )

    assert json.loads(report_path.read_text(encoding="utf-8"))["result"] == "mismatch"


def test_job_report_source_or_environment_mismatch_fails_closed(tmp_path: Path) -> None:
    environment, cross = _modules()
    requirements, environment_lock = _locks(tmp_path, environment)
    left = _job(tmp_path / "left", cross, requirements, commit="7" * 40)
    right = _job(tmp_path / "right", cross, requirements)

    with pytest.raises(cross.CrossJobRebuildError, match="source commit differs"):
        cross.compare_jobs(
            left=left,
            right=right,
            commit=COMMIT,
            environment_lock=environment_lock,
            requirements_lock=requirements,
            report_path=tmp_path / "report.json",
        )

    left = _job(tmp_path / "arch-left", cross, requirements, machine="arm64")
    right = _job(tmp_path / "arch-right", cross, requirements)
    with pytest.raises(cross.CrossJobRebuildError, match="architecture differs"):
        cross.compare_jobs(
            left=left,
            right=right,
            commit=COMMIT,
            environment_lock=environment_lock,
            requirements_lock=requirements,
            report_path=tmp_path / "arch-report.json",
        )


def test_uploaded_bytes_must_match_each_job_report(tmp_path: Path) -> None:
    environment, cross = _modules()
    requirements, environment_lock = _locks(tmp_path, environment)
    left = _job(tmp_path / "left", cross, requirements)
    right = _job(tmp_path / "right", cross, requirements)
    (left / "dist" / "provelume-0.1.0.tar.gz").write_bytes(b"modified after report")

    with pytest.raises(cross.CrossJobRebuildError, match="uploaded bytes"):
        cross.compare_jobs(
            left=left,
            right=right,
            commit=COMMIT,
            environment_lock=environment_lock,
            requirements_lock=requirements,
            report_path=tmp_path / "report.json",
        )


def test_environment_lock_or_requirements_lock_drift_fails(tmp_path: Path) -> None:
    environment, cross = _modules()
    requirements, environment_lock = _locks(tmp_path, environment)
    left = _job(tmp_path / "left", cross, requirements)
    right = _job(tmp_path / "right", cross, requirements)
    requirements.write_text("changed\n", encoding="utf-8")

    with pytest.raises(cross.CrossJobRebuildError, match="environment lock is invalid"):
        cross.compare_jobs(
            left=left,
            right=right,
            commit=COMMIT,
            environment_lock=environment_lock,
            requirements_lock=requirements,
            report_path=tmp_path / "report.json",
        )


def test_distribution_inventory_rejects_symlinks_or_extra_artifacts(tmp_path: Path) -> None:
    _environment, cross = _modules()
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "provelume-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "provelume-0.1.0.tar.gz").write_bytes(b"source")
    (dist / "second.whl").write_bytes(b"extra")
    with pytest.raises(cross.CrossJobRebuildError, match="exactly one wheel"):
        cross.distribution_identities(dist)
