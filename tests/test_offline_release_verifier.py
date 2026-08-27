from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.verify_provelume_release import VerificationError, verify_bundle

VERSION = "0.1.0"
TAG = f"v{VERSION}"
COMMIT = "a" * 40
EPOCH = 1_700_000_000


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> dict[str, object]:
    return {"name": path.name, "sha256": _sha(path), "size_bytes": path.stat().st_size}


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    wheel = root / "provelume-0.1.0-py3-none-any.whl"
    sdist = root / "provelume-0.1.0.tar.gz"
    wheel.write_bytes(b"package-wheel")
    sdist.write_bytes(b"package-source")
    package_rows = [_identity(wheel), _identity(sdist)]

    locked_wheel_name = "build-1.5.0-py3-none-any.whl"
    locked_wheel_bytes = b"build-wheel"
    locked_wheel_hash = hashlib.sha256(locked_wheel_bytes).hexdigest()
    direct_hash = "d" * 64
    lock_wheels = [
        {
            "distribution": "build",
            "normalized_distribution": "build",
            "version": "1.5.0",
            "filename": locked_wheel_name,
            "sha256": locked_wheel_hash,
            "size_bytes": len(locked_wheel_bytes),
            "requires_dist": [],
        }
    ]
    lock_material = {
        "target": {
            "implementation": "CPython",
            "python": "3.12.14",
            "system": "linux",
            "machine": "x86_64",
        },
        "direct_requirements_sha256": direct_hash,
        "wheels": lock_wheels,
    }
    lock_id = "sha256:" + hashlib.sha256(
        json.dumps(lock_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    lock = {
        "schema_version": 1,
        "source_repository": "gabned/provelume",
        "generated_from_commit": "b" * 40,
        "lock_id": lock_id,
        **lock_material,
    }
    json_lock = root / "ubuntu-py312-x86_64.lock.json"
    _write_json(json_lock, lock)
    requirements_lock = root / "ubuntu-py312-x86_64.requirements.txt"
    requirements_lock.write_text(
        f"build==1.5.0 --hash=sha256:{locked_wheel_hash}\n", encoding="utf-8"
    )
    input_manifest = root / "build-input-manifest.json"
    _write_json(
        input_manifest,
        {
            "schema_version": 1,
            "source_repository": "gabned/provelume",
            "source_commit": COMMIT,
            "direct_requirements": {
                "path": "requirements-build.txt",
                "sha256": direct_hash,
            },
            "wheels": [
                {
                    "name": locked_wheel_name,
                    "sha256": locked_wheel_hash,
                    "size_bytes": len(locked_wheel_bytes),
                }
            ],
        },
    )

    common = {
        "schema_version": 1,
        "source_repository": "gabned/provelume",
        "source_commit": COMMIT,
        "source_date_epoch": EPOCH,
    }
    deterministic = root / "deterministic-build-report.json"
    rebuild = root / "rebuild-deterministic-build-report.json"
    independent = root / "independent-rebuild-report.json"
    offline = root / "offline-rebuild-evidence.json"
    deterministic_rows = [{**row, "byte_identical": True} for row in package_rows]
    deterministic_report = {
        **common,
        "assurance": "same-source-same-environment-byte-identical",
        "full_release_reproducibility_claimed": False,
        "artifacts": deterministic_rows,
    }
    _write_json(deterministic, deterministic_report)
    _write_json(rebuild, deterministic_report)
    _write_json(independent, {**common, "byte_identical": True, "artifacts": package_rows})
    _write_json(
        offline,
        {
            **common,
            "byte_identical": True,
            "package_artifacts": package_rows,
            "build_input_bundle": {
                "manifest": input_manifest.name,
                "manifest_sha256": _sha(input_manifest),
                "installation_mode": "pip --no-index --find-links verified-wheelhouse",
                "wheels": [
                    {
                        "name": locked_wheel_name,
                        "sha256": locked_wheel_hash,
                        "size_bytes": len(locked_wheel_bytes),
                    }
                ],
            },
        },
    )
    candidate = root / "candidate-identity.json"
    _write_json(
        candidate,
        {
            "schema_version": 1,
            "source_repository": "gabned/provelume",
            "source_commit": COMMIT,
            "source_date_epoch": EPOCH,
            "version": VERSION,
            "tag": TAG,
            "channel": "development",
            "build_lock_id": lock_id,
        },
    )
    verifier = root / "verify-provelume-release.py"
    verifier.write_text("# synthetic verifier fixture\n", encoding="utf-8")
    sbom = root / "provelume-0.1.0.cdx.json"
    sbom.write_text("{}\n", encoding="utf-8")

    evidence_paths = [
        json_lock,
        requirements_lock,
        input_manifest,
        deterministic,
        independent,
        offline,
    ]
    assurance = root / "release-assurance.json"
    _write_json(
        assurance,
        {
            "schema_version": 1,
            "assurance_level": "reviewed_lock_offline_separate_runner_release_gate",
            "publication_gate": "passed",
            "source_repository": "gabned/provelume",
            "version": VERSION,
            "tag": TAG,
            "channel": "development",
            "source_commit": COMMIT,
            "source_date_epoch": EPOCH,
            "build_lock": {
                "lock_id": lock_id,
                "target": lock_material["target"],
                "json_lock": _identity(json_lock),
                "requirements_lock": _identity(requirements_lock),
                "per_run_manifest": _identity(input_manifest),
                "wheel_count": 1,
            },
            "package_artifacts": package_rows,
            "evidence": [_identity(path) for path in evidence_paths],
        },
    )

    artifact_paths = [
        wheel,
        sdist,
        json_lock,
        requirements_lock,
        input_manifest,
        deterministic,
        rebuild,
        independent,
        offline,
        candidate,
        assurance,
        verifier,
    ]
    manifest = root / "release-manifest.json"
    _write_json(
        manifest,
        {
            "schema_version": 1,
            "source_repository": "gabned/provelume",
            "version": VERSION,
            "tag": TAG,
            "commit": COMMIT,
            "channel": "development",
            "artifacts": [_identity(path) for path in artifact_paths],
            "sbom": _identity(sbom),
        },
    )
    checksums = root / "SHA256SUMS"
    checksums.write_text(
        "".join(
            f"{_sha(path)}  {path.name}\n"
            for path in sorted([*artifact_paths, sbom], key=lambda item: item.name)
        ),
        encoding="utf-8",
    )
    return root


def test_offline_verifier_reports_self_consistency_without_origin_claim(
    tmp_path: Path,
) -> None:
    root = _bundle(tmp_path)
    result = verify_bundle(root)
    assert result["verified"] is True
    assert result["result"] == "self_consistency_verified"
    assert result["origin_authentication"] == "not_established_by_bundle_alone"
    assert result["network_used"] is False


def test_offline_verifier_accepts_trusted_manifest_hash(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    result = verify_bundle(
        root,
        expected_manifest_sha256=_sha(root / "release-manifest.json"),
        expected_version=VERSION,
        expected_tag=TAG,
        expected_commit=COMMIT,
    )
    assert result["result"] == "externally_anchored_bundle_verified"
    assert result["origin_authentication"] == "trusted_release_manifest_sha256"


def test_offline_verifier_rejects_tampered_package(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "provelume-0.1.0-py3-none-any.whl").write_bytes(b"tampered")
    with pytest.raises(VerificationError, match="SHA256SUMS mismatch"):
        verify_bundle(root)


def test_offline_verifier_rejects_extra_untracked_file(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    (root / "unexpected.bin").write_bytes(b"extra")
    with pytest.raises(VerificationError, match="file set differs"):
        verify_bundle(root)


def test_offline_verifier_rejects_coordinated_manifest_change_when_anchored(
    tmp_path: Path,
) -> None:
    root = _bundle(tmp_path)
    trusted_hash = _sha(root / "release-manifest.json")
    manifest = json.loads((root / "release-manifest.json").read_text())
    manifest["channel"] = "stable"
    (root / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(VerificationError, match="trusted SHA-256"):
        verify_bundle(root, expected_manifest_sha256=trusted_hash)


def test_offline_verifier_rejects_symlinked_bundle_file(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    target = root / "deterministic-build-report.json"
    replacement = tmp_path / "outside.json"
    replacement.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.symlink(replacement, target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(VerificationError, match="symlinked|symlink"):
        verify_bundle(root)


def test_offline_verifier_rejects_symlinked_bundle_root(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    linked = tmp_path / "linked-release"
    try:
        os.symlink(root, linked, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")

    with pytest.raises(VerificationError, match="safe regular directory"):
        verify_bundle(linked)


def test_packaged_bundle_verifier_remains_standalone(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    source = (
        Path(__file__).resolve().parents[1]
        / "core"
        / "provelume"
        / "release_bundle.py"
    )
    verifier = root / "verify-provelume-release.py"
    verifier.write_bytes(source.read_bytes())

    manifest_path = root / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verifier_identity = _identity(verifier)
    for row in manifest["artifacts"]:
        if row["name"] == verifier.name:
            row.update(verifier_identity)
            break
    else:
        raise AssertionError("fixture manifest has no verifier identity")
    _write_json(manifest_path, manifest)

    checksums_path = root / "SHA256SUMS"
    checksums = []
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        if line.endswith(f"  {verifier.name}"):
            checksums.append(f"{_sha(verifier)}  {verifier.name}")
        else:
            checksums.append(line)
    checksums_path.write_text("\n".join(checksums) + "\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(verifier), "--root", str(root), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["result"] == "self_consistency_verified"
    assert result["network_used"] is False
