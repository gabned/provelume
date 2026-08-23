from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_manifest import build_manifest, sha256_file, write_checksums


def _file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def test_release_manifest_records_public_source_and_hashes(tmp_path: Path) -> None:
    wheel = _file(tmp_path / "provelume-0.1.0-py3-none-any.whl", b"wheel")
    source = _file(tmp_path / "provelume-0.1.0.tar.gz", b"source")
    sbom = _file(tmp_path / "provelume-0.1.0.cdx.json", b'{"bomFormat":"CycloneDX"}')

    manifest = build_manifest(
        version="0.1.0",
        tag="v0.1.0",
        commit="a" * 40,
        channel="stable",
        artifacts=[wheel, source],
        sbom=sbom,
        built_at="2026-08-23T16:00:00+00:00",
    )

    assert manifest["source_repository"] == "gabned/provelume"
    assert manifest["tag"] == "v0.1.0"
    assert manifest["commit"] == "a" * 40
    records = {item["name"]: item for item in manifest["artifacts"]}
    assert records[wheel.name]["sha256"] == sha256_file(wheel)
    assert records[source.name]["sha256"] == sha256_file(source)
    assert manifest["sbom"]["sha256"] == sha256_file(sbom)


def test_release_manifest_fails_closed_on_identity_mismatch(tmp_path: Path) -> None:
    artifact = _file(tmp_path / "artifact.whl", b"artifact")
    sbom = _file(tmp_path / "sbom.json", b"{}")

    with pytest.raises(ValueError, match="release tag"):
        build_manifest(
            version="0.1.0",
            tag="v0.2.0",
            commit="b" * 40,
            channel="stable",
            artifacts=[artifact],
            sbom=sbom,
        )

    with pytest.raises(ValueError, match="commit"):
        build_manifest(
            version="0.1.0",
            tag="v0.1.0",
            commit="not-a-commit",
            channel="stable",
            artifacts=[artifact],
            sbom=sbom,
        )


def test_checksum_file_is_stable_and_includes_manifest(tmp_path: Path) -> None:
    artifact = _file(tmp_path / "b.whl", b"b")
    sbom = _file(tmp_path / "a.cdx.json", b"a")
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(json.dumps({"version": "0.1.0"}) + "\n", encoding="utf-8")
    destination = tmp_path / "SHA256SUMS"

    write_checksums([artifact, sbom, manifest], destination)
    lines = destination.read_text(encoding="utf-8").splitlines()

    assert lines == sorted(lines, key=lambda row: row.split("  ", 1)[1])
    assert any(line.endswith("  release-manifest.json") for line in lines)
