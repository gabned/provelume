from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.deterministic_build import sha256_file
from scripts.verify_release_bundle import ReleaseBundleError, verify_release_bundle

VERSION = "0.1.0"
TAG = f"v{VERSION}"
COMMIT = "a" * 40


def _identity(path: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    names = {
        "provelume-0.1.0-py3-none-any.whl": b"wheel",
        "provelume-0.1.0.tar.gz": b"source",
        "provelume-0.1.0.cdx.json": b"{}",
        "release-assurance.json": b"",
        "deterministic-build-report.json": b"{}",
        "rebuild-deterministic-build-report.json": b"{}",
        "independent-rebuild-report.json": b"{}",
        "offline-rebuild-evidence.json": b"{}",
        "build-input-manifest.json": b"{}",
        "candidate-identity.json": b"{}",
        "ubuntu-py312-x86_64.lock.json": b"{}",
        "ubuntu-py312-x86_64.requirements.txt": b"build==1.5.0\n",
    }
    for name, content in names.items():
        (root / name).write_bytes(content)

    assurance = {
        "schema_version": 1,
        "publication_gate": "passed",
        "source_repository": "gabned/provelume",
        "version": VERSION,
        "tag": TAG,
        "source_commit": COMMIT,
    }
    (root / "release-assurance.json").write_text(
        json.dumps(assurance),
        encoding="utf-8",
    )
    artifact_names = [
        name for name in names if name != "provelume-0.1.0.cdx.json"
    ]
    manifest = {
        "schema_version": 1,
        "source_repository": "gabned/provelume",
        "version": VERSION,
        "tag": TAG,
        "commit": COMMIT,
        "artifacts": [_identity(root / name) for name in sorted(artifact_names)],
        "sbom": _identity(root / "provelume-0.1.0.cdx.json"),
    }
    manifest_path = root / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    checksum_names = [
        *artifact_names,
        "provelume-0.1.0.cdx.json",
        "release-manifest.json",
    ]
    (root / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(root / name)}  {name}\n"
            for name in sorted(checksum_names)
        ),
        encoding="utf-8",
    )
    return root


def test_verify_release_bundle_accepts_complete_identity_chain(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    result = verify_release_bundle(
        root,
        expected_version=VERSION,
        expected_tag=TAG,
        expected_commit=COMMIT,
    )
    assert result["verified"] is True
    assert "release-assurance.json" in result["manifest_artifacts"]
    assert "release-manifest.json" in result["checksummed_artifacts"]


def test_verify_release_bundle_rejects_tampered_artifact(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    (root / "provelume-0.1.0-py3-none-any.whl").write_bytes(b"tampered")
    with pytest.raises(ReleaseBundleError, match="size mismatch|SHA-256 mismatch"):
        verify_release_bundle(
            root,
            expected_version=VERSION,
            expected_tag=TAG,
            expected_commit=COMMIT,
        )


def test_verify_release_bundle_rejects_failed_assurance(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    assurance = json.loads((root / "release-assurance.json").read_text())
    assurance["publication_gate"] = "failed"
    (root / "release-assurance.json").write_text(
        json.dumps(assurance),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseBundleError, match="not passed"):
        verify_release_bundle(
            root,
            expected_version=VERSION,
            expected_tag=TAG,
            expected_commit=COMMIT,
        )


def test_verify_release_bundle_rejects_checksum_tampering(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    checksums = (root / "SHA256SUMS").read_text()
    (root / "SHA256SUMS").write_text(
        checksums.replace(checksums[:64], "0" * 64, 1),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseBundleError, match="SHA256SUMS mismatch"):
        verify_release_bundle(
            root,
            expected_version=VERSION,
            expected_tag=TAG,
            expected_commit=COMMIT,
        )


def test_verify_release_bundle_rejects_manifest_path_escape(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    manifest = json.loads((root / "release-manifest.json").read_text())
    manifest["artifacts"][0]["name"] = "../escape"
    (root / "release-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseBundleError, match="invalid artifact filename"):
        verify_release_bundle(
            root,
            expected_version=VERSION,
            expected_tag=TAG,
            expected_commit=COMMIT,
        )


def test_verify_release_bundle_rejects_unchecksummed_extra_file(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    (root / "unexpected.txt").write_text("not declared", encoding="utf-8")
    with pytest.raises(ReleaseBundleError, match="file set differs"):
        verify_release_bundle(
            root,
            expected_version=VERSION,
            expected_tag=TAG,
            expected_commit=COMMIT,
        )


def test_verify_release_bundle_rejects_boolean_schema_version(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    manifest = json.loads((root / "release-manifest.json").read_text())
    manifest["schema_version"] = True
    (root / "release-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseBundleError, match="unsupported schema"):
        verify_release_bundle(
            root,
            expected_version=VERSION,
            expected_tag=TAG,
            expected_commit=COMMIT,
        )
