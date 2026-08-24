from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.artifact_identity import discover_artifacts
from scripts.deterministic_build import sha256_file
from scripts.release_assurance import (
    ReleaseAssuranceError,
    create_release_assurance,
)

COMMIT = "a" * 40
VERSION = "0.1.0"
TAG = f"v{VERSION}"


def _artifact_rows(
    directory: Path,
    *,
    deterministic: bool = False,
) -> list[dict[str, object]]:
    return [
        {
            "name": identity.name,
            "sha256": identity.sha256,
            "size_bytes": identity.size_bytes,
            **({"byte_identical": True} if deterministic else {}),
        }
        for identity in discover_artifacts(directory).values()
    ]


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> dict[str, Path]:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "provelume-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    (candidate / "provelume-0.1.0.tar.gz").write_bytes(b"source")

    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "build-1.5.0-py3-none-any.whl").write_bytes(b"build")
    direct = tmp_path / "requirements-build.txt"
    direct.write_text("build==1.5.0\n", encoding="utf-8")
    json_lock = tmp_path / "lock.json"
    json_lock.write_text("{}", encoding="utf-8")
    requirements_lock = tmp_path / "lock.txt"
    requirements_lock.write_text("build==1.5.0\n", encoding="utf-8")
    build_manifest = tmp_path / "build-input-manifest.json"
    build_manifest.write_text("{}", encoding="utf-8")

    deterministic = tmp_path / "deterministic-build-report.json"
    _write_json(
        deterministic,
        {
            "schema_version": 1,
            "assurance": "same-source-same-environment-byte-identical",
            "full_release_reproducibility_claimed": False,
            "source_repository": "gabned/provelume",
            "source_commit": COMMIT,
            "source_date_epoch": 1_700_000_000,
            "artifacts": _artifact_rows(candidate, deterministic=True),
        },
    )
    common_green = {
        "schema_version": 1,
        "byte_identical": True,
        "source_repository": "gabned/provelume",
        "source_commit": COMMIT,
        "source_date_epoch": 1_700_000_000,
    }
    independent = tmp_path / "independent-rebuild-report.json"
    _write_json(
        independent,
        {**common_green, "artifacts": _artifact_rows(candidate)},
    )
    offline = tmp_path / "offline-rebuild-evidence.json"
    _write_json(
        offline,
        {
            **common_green,
            "package_artifacts": _artifact_rows(candidate),
            "build_input_bundle": {
                "manifest": build_manifest.name,
                "manifest_sha256": sha256_file(build_manifest),
                "installation_mode": "pip --no-index --find-links verified-wheelhouse",
                "wheels": [
                    {
                        "name": "build-1.5.0-py3-none-any.whl",
                        "sha256": "b" * 64,
                        "size_bytes": 5,
                    }
                ],
            },
        },
    )
    return {
        "candidate": candidate,
        "wheelhouse": wheelhouse,
        "direct": direct,
        "json_lock": json_lock,
        "requirements_lock": requirements_lock,
        "build_manifest": build_manifest,
        "deterministic": deterministic,
        "independent": independent,
        "offline": offline,
        "output": tmp_path / "release-assurance.json",
    }


def _patch_verified_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_wheels = [
        {
            "distribution": "build",
            "normalized_distribution": "build",
            "version": "1.5.0",
            "filename": "build-1.5.0-py3-none-any.whl",
            "sha256": "b" * 64,
            "size_bytes": 5,
            "requires_dist": [],
        }
    ]
    manifest_wheels = [
        {
            "name": "build-1.5.0-py3-none-any.whl",
            "sha256": "b" * 64,
            "size_bytes": 5,
        }
    ]
    monkeypatch.setattr(
        "scripts.release_assurance.verify_lock",
        lambda *args, **kwargs: {
            "lock_id": "sha256:" + "c" * 64,
            "target": {"python": "3.12.14"},
            "wheels": lock_wheels,
        },
    )
    monkeypatch.setattr(
        "scripts.release_assurance.verify_manifest",
        lambda *args, **kwargs: {"wheels": manifest_wheels},
    )


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return create_release_assurance(
        candidate_directory=paths["candidate"],
        wheelhouse=paths["wheelhouse"],
        direct_requirements=paths["direct"],
        json_lock=paths["json_lock"],
        requirements_lock=paths["requirements_lock"],
        build_input_manifest=paths["build_manifest"],
        deterministic_report=paths["deterministic"],
        independent_report=paths["independent"],
        offline_report=paths["offline"],
        output=paths["output"],
        version=VERSION,
        tag=TAG,
        channel="development",
        commit=COMMIT,
        enforce_target=False,
    )


def test_release_assurance_accepts_consistent_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path)
    _patch_verified_inputs(monkeypatch)
    report = _run(paths)
    assert report["publication_gate"] == "passed"
    assert report["build_lock"]["lock_id"].startswith("sha256:")
    assert len(report["package_artifacts"]) == 2
    assert json.loads(paths["output"].read_text())["source_commit"] == COMMIT


def test_release_assurance_recomputes_candidate_artifact_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path)
    _patch_verified_inputs(monkeypatch)
    (paths["candidate"] / "provelume-0.1.0-py3-none-any.whl").write_bytes(
        b"changed"
    )
    with pytest.raises(ReleaseAssuranceError, match="does not match candidate"):
        _run(paths)


def test_release_assurance_rejects_offline_manifest_hash_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path)
    _patch_verified_inputs(monkeypatch)
    payload = json.loads(paths["offline"].read_text())
    payload["build_input_bundle"]["manifest_sha256"] = "0" * 64
    _write_json(paths["offline"], payload)
    with pytest.raises(ReleaseAssuranceError, match="manifest hash mismatch"):
        _run(paths)


def test_release_assurance_rejects_source_commit_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path)
    _patch_verified_inputs(monkeypatch)
    payload = json.loads(paths["independent"].read_text())
    payload["source_commit"] = "d" * 40
    _write_json(paths["independent"], payload)
    with pytest.raises(ReleaseAssuranceError, match="source commit mismatch"):
        _run(paths)


def test_release_assurance_rejects_non_identical_deterministic_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path)
    _patch_verified_inputs(monkeypatch)
    payload = json.loads(paths["deterministic"].read_text())
    payload["artifacts"][0]["byte_identical"] = False
    _write_json(paths["deterministic"], payload)
    with pytest.raises(ReleaseAssuranceError, match="non-identical"):
        _run(paths)


def test_release_assurance_rejects_tag_version_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path)
    _patch_verified_inputs(monkeypatch)
    with pytest.raises(ReleaseAssuranceError, match="does not match version"):
        create_release_assurance(
            candidate_directory=paths["candidate"],
            wheelhouse=paths["wheelhouse"],
            direct_requirements=paths["direct"],
            json_lock=paths["json_lock"],
            requirements_lock=paths["requirements_lock"],
            build_input_manifest=paths["build_manifest"],
            deterministic_report=paths["deterministic"],
            independent_report=paths["independent"],
            offline_report=paths["offline"],
            output=paths["output"],
            version=VERSION,
            tag="v9.9.9",
            channel="development",
            commit=COMMIT,
            enforce_target=False,
        )
