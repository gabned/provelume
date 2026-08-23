from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
from pathlib import Path
from types import ModuleType
from zipfile import ZipFile, ZipInfo

import pytest


def _load_module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "build_input_lock.py"
    spec = importlib.util.spec_from_file_location("provelume_build_input_lock", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wheel(
    directory: Path,
    name: str,
    version: str,
    *,
    filename: str | None = None,
    unsafe_member: str | None = None,
    symlink_member: bool = False,
) -> Path:
    path = directory / (
        filename
        or f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
    )
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n".encode()
    with ZipFile(path, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        if unsafe_member is not None:
            archive.writestr(unsafe_member, b"unsafe")
        if symlink_member:
            info = ZipInfo("linked")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"target")
    return path


def _direct(path: Path, content: str = "build==1.5.0\nhatchling==1.32.0\n") -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_generation_is_deterministic_and_hash_complete(tmp_path: Path) -> None:
    lock = _load_module()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    hatchling = _wheel(wheelhouse, "hatchling", "1.32.0")
    build = _wheel(wheelhouse, "build", "1.5.0")
    packaging = _wheel(wheelhouse, "packaging", "26.3")
    direct = _direct(tmp_path / "requirements-build.txt")

    projects = lock.projects_from_wheelhouse(wheelhouse)
    first = lock.render_lock(
        projects,
        direct_requirements=direct,
        target_python="CPython 3.12.14",
        target_platform="Linux x86_64",
    )
    second = lock.render_lock(
        list(reversed(projects)),
        direct_requirements=direct,
        target_python="CPython 3.12.14",
        target_platform="Linux x86_64",
    )

    assert first == second
    assert first.index("build==1.5.0") < first.index("hatchling==1.32.0")
    assert first.index("hatchling==1.32.0") < first.index("packaging==26.3")
    for wheel in (build, hatchling, packaging):
        assert hashlib.sha256(wheel.read_bytes()).hexdigest() in first

    output = tmp_path / "requirements-build.lock"
    output.write_text(first, encoding="utf-8")
    result = lock.check_lock(output, direct_requirements=direct)
    assert result["status"] == "valid"
    assert result["projects"] == 3
    assert result["artifact_hashes"] == 3


def test_generation_requires_every_direct_pin(tmp_path: Path) -> None:
    lock = _load_module()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "build", "1.5.0")
    direct = _direct(tmp_path / "requirements-build.txt")

    with pytest.raises(lock.BuildInputLockError, match="missing: hatchling"):
        lock.render_lock(
            lock.projects_from_wheelhouse(wheelhouse),
            direct_requirements=direct,
            target_python="CPython 3.12.14",
            target_platform="Linux x86_64",
        )


def test_generation_rejects_conflicting_project_versions(tmp_path: Path) -> None:
    lock = _load_module()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "demo-project", "1.0.0")
    _wheel(
        wheelhouse,
        "demo_project",
        "2.0.0",
        filename="demo_project-2.0.0-py3-none-any.whl",
    )

    with pytest.raises(lock.BuildInputLockError, match="conflicting versions"):
        lock.projects_from_wheelhouse(wheelhouse)


def test_wheelhouse_rejects_non_wheels_and_unsafe_members(tmp_path: Path) -> None:
    lock = _load_module()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "source.tar.gz").write_bytes(b"not a wheel")
    with pytest.raises(lock.BuildInputLockError, match="not a wheel"):
        lock.projects_from_wheelhouse(wheelhouse)

    (wheelhouse / "source.tar.gz").unlink()
    _wheel(wheelhouse, "unsafe", "1.0.0", unsafe_member="../escape")
    with pytest.raises(lock.BuildInputLockError, match="unsafe member path"):
        lock.projects_from_wheelhouse(wheelhouse)


def test_wheelhouse_rejects_symlink_members(tmp_path: Path) -> None:
    lock = _load_module()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "unsafe", "1.0.0", symlink_member=True)

    with pytest.raises(lock.BuildInputLockError, match="symlink member"):
        lock.projects_from_wheelhouse(wheelhouse)


def test_lock_detects_changed_direct_requirements(tmp_path: Path) -> None:
    lock = _load_module()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "build", "1.5.0")
    _wheel(wheelhouse, "hatchling", "1.32.0")
    direct = _direct(tmp_path / "requirements-build.txt")
    output = tmp_path / "requirements-build.lock"
    lock.generate_lock(
        wheelhouse,
        output,
        direct_requirements=direct,
        target_python="CPython 3.12.14",
        target_platform="Linux x86_64",
    )
    direct.write_text("build==1.5.0\nhatchling==1.31.0\n", encoding="utf-8")

    with pytest.raises(lock.BuildInputLockError, match="different direct requirements"):
        lock.check_lock(output, direct_requirements=direct)


def test_lock_parser_rejects_missing_hashes_and_duplicates(tmp_path: Path) -> None:
    lock = _load_module()
    direct = _direct(tmp_path / "requirements-build.txt", "build==1.5.0\n")
    digest = hashlib.sha256(direct.read_bytes()).hexdigest()
    header = (
        "# Provelume Python build-input lock\n"
        "# lock-schema-version: 1\n"
        "# target-python: CPython 3.12.14\n"
        "# target-platform: Linux x86_64\n"
        f"# direct-requirements-sha256: {digest}\n\n"
    )
    path = tmp_path / "requirements-build.lock"
    path.write_text(header + "build==1.5.0\n", encoding="utf-8")
    with pytest.raises(lock.BuildInputLockError, match="missing or duplicate hashes"):
        lock.parse_lock(path)

    value = "a" * 64
    path.write_text(
        header
        + f"build==1.5.0 --hash=sha256:{value}\n"
        + f"Build==1.5.0 --hash=sha256:{value}\n",
        encoding="utf-8",
    )
    with pytest.raises(lock.BuildInputLockError, match="duplicate locked project"):
        lock.parse_lock(path)


def test_cli_check_json_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lock = _load_module()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "build", "1.5.0")
    direct = _direct(tmp_path / "requirements-build.txt", "build==1.5.0\n")
    output = tmp_path / "requirements-build.lock"
    lock.generate_lock(
        wheelhouse,
        output,
        direct_requirements=direct,
        target_python="CPython 3.12.14",
        target_platform="Linux x86_64",
    )

    assert lock.main(["check", "--lock", str(output), "--direct", str(direct), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "valid"
