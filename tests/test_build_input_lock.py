from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.build_input_lock import (
    BuildInputLockError,
    create_lock,
    parse_direct_requirements,
    verify_lock,
)

COMMIT = "a" * 40


def _wheel(
    directory: Path,
    distribution: str,
    version: str,
    *,
    requires_dist: tuple[str, ...] = (),
    payload: bytes = b"payload",
) -> Path:
    filename_name = distribution.replace("-", "_")
    path = directory / f"{filename_name}-{version}-py3-none-any.whl"
    metadata = [
        "Metadata-Version: 2.4",
        f"Name: {distribution}",
        f"Version: {version}",
    ]
    metadata.extend(f"Requires-Dist: {value}" for value in requires_dist)
    metadata.append("")
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{filename_name}-{version}.dist-info/METADATA",
            "\n".join(metadata),
        )
        archive.writestr(f"{filename_name}/payload.bin", payload)
    return path


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _wheel(
        wheelhouse,
        "build",
        "1.5.0",
        requires_dist=("packaging>=24.0", "pyproject_hooks"),
    )
    _wheel(
        wheelhouse,
        "hatchling",
        "1.32.0",
        requires_dist=("packaging>=24.2", "pluggy>=1.0.0"),
    )
    _wheel(wheelhouse, "packaging", "26.3")
    _wheel(wheelhouse, "pluggy", "1.6.0")
    _wheel(wheelhouse, "pyproject-hooks", "1.2.0")
    direct = tmp_path / "requirements-build.txt"
    direct.write_text("build==1.5.0\nhatchling==1.32.0\n", encoding="utf-8")
    json_lock = tmp_path / "lock.json"
    requirements_lock = tmp_path / "lock.txt"
    return wheelhouse, direct, json_lock, requirements_lock


def test_create_and_verify_target_lock(tmp_path: Path) -> None:
    wheelhouse, direct, json_lock, requirements_lock = _fixture(tmp_path)
    created = create_lock(
        wheelhouse,
        direct,
        json_lock,
        requirements_lock,
        generated_from_commit=COMMIT,
        enforce_target=False,
    )
    assert created["lock_id"].startswith("sha256:")
    assert len(created["wheels"]) == 5
    assert "build==1.5.0 --hash=sha256:" in requirements_lock.read_text()

    verified = verify_lock(
        wheelhouse,
        direct,
        json_lock,
        requirements_lock,
        enforce_target=False,
    )
    assert verified["lock_id"] == created["lock_id"]


def test_lock_rejects_changed_wheel_bytes(tmp_path: Path) -> None:
    wheelhouse, direct, json_lock, requirements_lock = _fixture(tmp_path)
    create_lock(
        wheelhouse,
        direct,
        json_lock,
        requirements_lock,
        generated_from_commit=COMMIT,
        enforce_target=False,
    )
    wheel = next(wheelhouse.glob("packaging-*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"changed")
    with pytest.raises(BuildInputLockError, match="differs from JSON lock"):
        verify_lock(
            wheelhouse,
            direct,
            json_lock,
            requirements_lock,
            enforce_target=False,
        )


def test_lock_rejects_requirements_text_tampering(tmp_path: Path) -> None:
    wheelhouse, direct, json_lock, requirements_lock = _fixture(tmp_path)
    create_lock(
        wheelhouse,
        direct,
        json_lock,
        requirements_lock,
        generated_from_commit=COMMIT,
        enforce_target=False,
    )
    requirements_lock.write_text(
        requirements_lock.read_text() + "unexpected==1 --hash=sha256:" + "0" * 64 + "\n",
        encoding="utf-8",
    )
    with pytest.raises(BuildInputLockError, match="requirements lock differs"):
        verify_lock(
            wheelhouse,
            direct,
            json_lock,
            requirements_lock,
            enforce_target=False,
        )


def test_create_rejects_direct_version_mismatch(tmp_path: Path) -> None:
    wheelhouse, direct, json_lock, requirements_lock = _fixture(tmp_path)
    direct.write_text("build==1.4.0\nhatchling==1.32.0\n", encoding="utf-8")
    with pytest.raises(BuildInputLockError, match="expected 1.4.0"):
        create_lock(
            wheelhouse,
            direct,
            json_lock,
            requirements_lock,
            generated_from_commit=COMMIT,
            enforce_target=False,
        )


def test_direct_requirements_must_be_exact_pins(tmp_path: Path) -> None:
    path = tmp_path / "requirements.txt"
    path.write_text("build>=1.5\n", encoding="utf-8")
    with pytest.raises(BuildInputLockError, match="not an exact pin"):
        parse_direct_requirements(path)


def test_json_lock_id_cannot_be_forged(tmp_path: Path) -> None:
    wheelhouse, direct, json_lock, requirements_lock = _fixture(tmp_path)
    create_lock(
        wheelhouse,
        direct,
        json_lock,
        requirements_lock,
        generated_from_commit=COMMIT,
        enforce_target=False,
    )
    payload = json.loads(json_lock.read_text())
    payload["lock_id"] = "sha256:" + "0" * 64
    json_lock.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuildInputLockError, match="lock ID"):
        verify_lock(
            wheelhouse,
            direct,
            json_lock,
            requirements_lock,
            enforce_target=False,
        )
