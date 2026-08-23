from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from provelume.release_verification import verify_release_bundle

COMMIT = "1" * 40
VERSION = "0.1.0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    return {
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _comparison_identity(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bundle(tmp_path: Path, *, deterministic: bool = True) -> tuple[Path, dict[str, Path]]:
    root = tmp_path / "release"
    root.mkdir()
    files = {
        "wheel": root / f"provelume-{VERSION}-py3-none-any.whl",
        "sdist": root / f"provelume-{VERSION}.tar.gz",
        "license": root / "LICENSE",
        "sbom": root / f"provelume-{VERSION}.cdx.json",
    }
    files["wheel"].write_bytes(b"synthetic wheel bytes")
    files["sdist"].write_bytes(b"synthetic source distribution bytes")
    files["license"].write_text("Synthetic public test license\n", encoding="utf-8")
    _write_json(
        files["sbom"],
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "serialNumber": "urn:uuid:00000000-0000-4000-8000-000000000001",
            "version": 1,
            "components": [],
        },
    )

    artifact_paths = [files["wheel"], files["sdist"], files["license"]]
    if deterministic:
        report_path = root / "build-comparison.json"
        schema_path = root / "build-comparison.schema.json"
        artifact_rows = [
            {
                **_comparison_identity(files["wheel"]),
                "matches": True,
                "second_size_bytes": files["wheel"].stat().st_size,
                "second_sha256": _sha256(files["wheel"]),
            },
            {
                **_comparison_identity(files["sdist"]),
                "matches": True,
                "second_size_bytes": files["sdist"].stat().st_size,
                "second_sha256": _sha256(files["sdist"]),
            },
        ]
        run_artifacts = [
            _comparison_identity(files["wheel"]),
            _comparison_identity(files["sdist"]),
        ]
        _write_json(
            report_path,
            {
                "schema_version": 1,
                "assurance": "same-source-same-inputs-same-platform-double-build",
                "result": "match",
                "source_repository": "gabned/provelume",
                "source_commit": COMMIT,
                "source_date_epoch": 1,
                "source_timestamp": "1970-01-01T00:00:01Z",
                "source_snapshot": {
                    "name": "source.tar",
                    "size_bytes": 1,
                    "sha256": "2" * 64,
                },
                "builder": {
                    "python_implementation": "CPython",
                    "python_version": "3.12.14",
                    "operating_system": "Linux",
                    "machine": "x86_64",
                },
                "environment_controls": {
                    "python_hash_seed": "0",
                    "timezone": "UTC",
                    "locale": "C.UTF-8",
                    "network_during_build": "disabled-after-wheelhouse-resolution",
                },
                "build_input_artifacts": [
                    {
                        "name": "build.whl",
                        "size_bytes": 1,
                        "sha256": "3" * 64,
                    }
                ],
                "resolved_build_packages": ["build==1.5.0"],
                "resolved_build_packages_match": True,
                "runs": [
                    {"label": "A", "artifacts": run_artifacts},
                    {"label": "B", "artifacts": run_artifacts},
                ],
                "artifacts": artifact_rows,
                "limitations": ["Synthetic public test evidence."],
            },
        )
        _write_json(schema_path, {"$schema": "https://json-schema.org/draft/2020-12/schema"})
        files["report"] = report_path
        files["comparison_schema"] = schema_path
        artifact_paths.extend([report_path, schema_path])

    manifest = {
        "schema_version": 1,
        "version": VERSION,
        "tag": f"v{VERSION}",
        "commit": COMMIT,
        "source_repository": "gabned/provelume",
        "channel": "preview",
        "build_timestamp": "2026-08-23T17:00:00Z",
        "assurance_level": "traceable-build",
        "artifacts": [_identity(path) for path in artifact_paths],
        "sbom": {**_identity(files["sbom"]), "format": "CycloneDX 1.6"},
    }
    manifest_path = root / "release-manifest.json"
    _write_json(manifest_path, manifest)
    files["manifest"] = manifest_path

    checksummed = [*artifact_paths, files["sbom"]]
    checksums_path = root / "SHA256SUMS"
    checksums_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksummed),
        encoding="utf-8",
    )
    files["checksums"] = checksums_path
    return root, files


def test_verified_deterministic_bundle_requires_no_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _files = _bundle(tmp_path)

    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline verifier attempted network access")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    result = verify_release_bundle(root)

    assert result.status == "verified"
    assert result.verified is True
    assert result.version == VERSION
    assert result.commit == COMMIT
    assert result.checked_files == 6
    assert result.deterministic_python_distributions == "verified"
    assert not [finding for finding in result.findings if finding.severity == "error"]


def test_traceable_bundle_without_comparison_remains_verifiable(tmp_path: Path) -> None:
    root, _files = _bundle(tmp_path, deterministic=False)
    result = verify_release_bundle(root)

    assert result.status == "verified"
    assert result.deterministic_python_distributions == "not_present"


def test_modified_artifact_is_detected(tmp_path: Path) -> None:
    root, files = _bundle(tmp_path)
    files["wheel"].write_bytes(b"modified after release assembly")

    result = verify_release_bundle(root)

    assert result.status == "modified"
    assert any(finding.code == "artifact.identity" for finding in result.findings)


def test_missing_manifest_is_unavailable(tmp_path: Path) -> None:
    root, files = _bundle(tmp_path)
    files["manifest"].unlink()

    result = verify_release_bundle(root)

    assert result.status == "unavailable"
    assert result.verified is False


def test_manifest_rejects_traversal_and_windows_drive_names(tmp_path: Path) -> None:
    root, files = _bundle(tmp_path)
    manifest = json.loads(files["manifest"].read_text(encoding="utf-8"))
    manifest["artifacts"][0]["filename"] = "../outside.whl"
    _write_json(files["manifest"], manifest)
    assert verify_release_bundle(root).status == "modified"

    manifest["artifacts"][0]["filename"] = "C:outside.whl"
    _write_json(files["manifest"], manifest)
    assert verify_release_bundle(root).status == "modified"
    assert not (tmp_path / "outside.whl").exists()


def test_duplicate_or_incomplete_checksum_coverage_fails_closed(tmp_path: Path) -> None:
    root, files = _bundle(tmp_path)
    lines = files["checksums"].read_text(encoding="utf-8").splitlines()
    files["checksums"].write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")
    duplicate = verify_release_bundle(root)
    assert duplicate.status == "modified"
    assert any(finding.code == "checksums.invalid" for finding in duplicate.findings)

    files["checksums"].write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    incomplete = verify_release_bundle(root)
    assert incomplete.status == "modified"


def test_build_comparison_must_match_manifest_source_and_artifacts(tmp_path: Path) -> None:
    root, files = _bundle(tmp_path)
    report = json.loads(files["report"].read_text(encoding="utf-8"))
    report["source_commit"] = "4" * 40
    _write_json(files["report"], report)

    manifest = json.loads(files["manifest"].read_text(encoding="utf-8"))
    for row in manifest["artifacts"]:
        if row["filename"] == files["report"].name:
            row.update(_identity(files["report"]))
    _write_json(files["manifest"], manifest)
    lines = files["checksums"].read_text(encoding="utf-8").splitlines()
    lines = [
        f"{_sha256(files['report'])}  {files['report'].name}"
        if line.endswith(f"  {files['report'].name}")
        else line
        for line in lines
    ]
    files["checksums"].write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_release_bundle(root)

    assert result.status == "modified"
    assert result.deterministic_python_distributions == "invalid"
    assert any(finding.code == "build_comparison.invalid" for finding in result.findings)


def test_untrusted_comparison_evidence_is_rejected(tmp_path: Path) -> None:
    root, files = _bundle(tmp_path, deterministic=False)
    _write_json(root / "build-comparison.json", {"result": "match"})

    result = verify_release_bundle(root)

    assert result.status == "modified"
    assert result.deterministic_python_distributions == "invalid"


def test_declared_symlink_is_rejected_without_reading_target(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are not supported")
    root, files = _bundle(tmp_path)
    outside = tmp_path / "outside.whl"
    outside.write_bytes(files["wheel"].read_bytes())
    files["wheel"].unlink()
    try:
        os.symlink(outside, files["wheel"])
    except OSError:
        pytest.skip("symlink creation is not permitted")

    result = verify_release_bundle(root)

    assert result.status == "modified"
    assert outside.read_bytes() == b"synthetic wheel bytes"


def test_extra_files_are_visible_but_do_not_invalidate_bundle(tmp_path: Path) -> None:
    root, _files = _bundle(tmp_path)
    (root / "operator-note.txt").write_text("local note\n", encoding="utf-8")

    result = verify_release_bundle(root)

    assert result.status == "verified"
    assert any(finding.code == "bundle.extra_files" for finding in result.findings)
