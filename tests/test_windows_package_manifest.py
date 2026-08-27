from __future__ import annotations

from pathlib import Path

import pytest

from scripts.windows_package_manifest import build_windows_update_manifest, sha256_file


def test_windows_update_manifest_records_unsigned_preview_boundary(tmp_path: Path) -> None:
    installer = tmp_path / "Provelume-Setup-0.4.0-x64.exe"
    installer.write_bytes(b"synthetic installer")

    value = build_windows_update_manifest(
        installer=installer,
        version="0.4.0",
        tag="v0.4.0",
        channel="preview",
        commit="a" * 40,
    )

    assert value["artifact"]["sha256"] == sha256_file(installer)
    assert value["artifact"]["automatic_apply"] is False
    assert value["artifact"]["minimum_windows_build"] == 19045
    assert value["trust"] == {
        "publisher_authentication": "not_established",
        "platform_signature": "unsigned_preview",
    }


def test_windows_update_manifest_rejects_mismatched_or_unsafe_inputs(tmp_path: Path) -> None:
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"setup")
    with pytest.raises(ValueError, match="tag"):
        build_windows_update_manifest(
            installer=installer,
            version="0.4.0",
            tag="v0.5.0",
            channel="preview",
            commit="a" * 40,
        )
    with pytest.raises(ValueError, match="baseline"):
        build_windows_update_manifest(
            installer=installer,
            version="0.4.0",
            tag="v0.4.0",
            channel="preview",
            commit="a" * 40,
            minimum_windows_build=1,
        )
