from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from provelume.installation import verify_current_installation
from provelume.release_bundle import VerificationError
from provelume.release_wheel import WheelVerificationError, verify_release_wheel

VERSION = "0.2.0"
TAG = f"v{VERSION}"
COMMIT = "a" * 40
MODULE_BYTES = b"VALUE = 'released'\n"
INIT_BYTES = b"__version__ = '0.2.0'\n"


def _record_hash(payload: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()


def _record_row(path: str, payload: bytes) -> str:
    return f"{path},sha256={_record_hash(payload)},{len(payload)}\n"


def _wheel(
    tmp_path: Path,
    *,
    module_bytes: bytes = MODULE_BYTES,
    recorded_module_bytes: bytes | None = None,
    extra_member: tuple[zipfile.ZipInfo | str, bytes] | None = None,
    omit_from_record: str | None = None,
    duplicate_module: bool = False,
) -> Path:
    wheel = tmp_path / f"provelume-{VERSION}-py3-none-any.whl"
    dist_info = f"provelume-{VERSION}.dist-info"
    metadata = f"Name: provelume\nVersion: {VERSION}\n".encode()
    wheel_metadata = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    members: list[tuple[zipfile.ZipInfo | str, bytes]] = [
        ("provelume/__init__.py", INIT_BYTES),
        ("provelume/module.py", module_bytes),
        (f"{dist_info}/METADATA", metadata),
        (f"{dist_info}/WHEEL", wheel_metadata),
    ]
    if extra_member is not None:
        members.append(extra_member)
    recorded_payloads = {
        "provelume/__init__.py": INIT_BYTES,
        "provelume/module.py": recorded_module_bytes or module_bytes,
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": wheel_metadata,
    }
    if extra_member is not None:
        extra_name = (
            extra_member[0].filename
            if isinstance(extra_member[0], zipfile.ZipInfo)
            else extra_member[0]
        )
        recorded_payloads[extra_name] = extra_member[1]
    record = "".join(
        _record_row(name, payload)
        for name, payload in recorded_payloads.items()
        if name != omit_from_record
    )
    record += f"{dist_info}/RECORD,,\n"
    members.append((f"{dist_info}/RECORD", record.encode()))

    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
        if duplicate_module:
            archive.writestr("provelume/module.py", module_bytes)
    return wheel


def _bundle_result(wheel: Path, *, anchored: bool = False) -> dict[str, object]:
    return {
        "verified": True,
        "result": (
            "externally_anchored_bundle_verified"
            if anchored
            else "self_consistency_verified"
        ),
        "origin_authentication": (
            "trusted_release_manifest_sha256"
            if anchored
            else "not_established_by_bundle_alone"
        ),
        "network_used": False,
        "version": VERSION,
        "tag": TAG,
        "source_commit": COMMIT,
        "release_manifest_sha256": "b" * 64,
        "package_artifacts": [
            {
                "name": wheel.name,
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "size_bytes": wheel.stat().st_size,
            }
        ],
    }


def _installation(
    tmp_path: Path,
    *,
    module_bytes: bytes = MODULE_BYTES,
    extra_file: tuple[str, bytes] | None = None,
) -> tuple[Path, Path, Path]:
    root = tmp_path / "site-packages"
    package = root / "provelume"
    dist_info = root / f"provelume-{VERSION}.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir()
    (package / "__init__.py").write_bytes(INIT_BYTES)
    (package / "module.py").write_bytes(module_bytes)
    metadata = f"Name: provelume\nVersion: {VERSION}\n".encode()
    (dist_info / "METADATA").write_bytes(metadata)
    rows = [
        _record_row("provelume/__init__.py", INIT_BYTES),
        _record_row("provelume/module.py", module_bytes),
        _record_row(f"provelume-{VERSION}.dist-info/METADATA", metadata),
    ]
    if extra_file is not None:
        relative, payload = extra_file
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        rows.append(_record_row(relative, payload))
    rows.append(f"provelume-{VERSION}.dist-info/RECORD,,\n")
    (dist_info / "RECORD").write_text("".join(rows), encoding="utf-8")
    return root, package, dist_info


def _bind_installation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    root: Path,
    package: Path,
    dist_info: Path,
) -> None:
    class Distribution:
        _path = dist_info

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: Distribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )


def test_release_wheel_accepts_bounded_complete_record(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)

    evidence = verify_release_wheel(
        tmp_path,
        _bundle_result(wheel),
        expected_version=VERSION,
    )

    assert evidence.name == wheel.name
    assert evidence.checked_members == 5
    assert {item.path for item in evidence.package_files} == {
        "provelume/__init__.py",
        "provelume/module.py",
    }


def test_release_wheel_never_extracts_archive_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = _wheel(tmp_path)

    def forbidden_extraction(*_args, **_kwargs):
        raise AssertionError("release wheel members must remain in memory")

    monkeypatch.setattr(zipfile.ZipFile, "extract", forbidden_extraction)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden_extraction)

    evidence = verify_release_wheel(
        tmp_path,
        _bundle_result(wheel),
        expected_version=VERSION,
    )

    assert len(evidence.package_files) == 2


def test_release_wheel_rejects_member_that_differs_from_record(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, recorded_module_bytes=b"different bytes")

    with pytest.raises(WheelVerificationError, match="differs"):
        verify_release_wheel(
            tmp_path,
            _bundle_result(wheel),
            expected_version=VERSION,
        )


def test_release_wheel_rejects_incomplete_record_coverage(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, omit_from_record="provelume/module.py")

    with pytest.raises(WheelVerificationError, match="coverage differs"):
        verify_release_wheel(
            tmp_path,
            _bundle_result(wheel),
            expected_version=VERSION,
        )


def test_release_wheel_rejects_duplicate_member(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        wheel = _wheel(tmp_path, duplicate_module=True)

    with pytest.raises(WheelVerificationError, match="duplicate or case-colliding"):
        verify_release_wheel(
            tmp_path,
            _bundle_result(wheel),
            expected_version=VERSION,
        )


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../escape.py",
        "provelume/module.py:stream",
        "provelume/CON.py",
        "provelume/trailing.",
    ],
)
def test_release_wheel_rejects_unsafe_member_path(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    wheel = _wheel(tmp_path, extra_member=(unsafe_name, b"escape"))

    with pytest.raises(WheelVerificationError, match="unsafe member path"):
        verify_release_wheel(
            tmp_path,
            _bundle_result(wheel),
            expected_version=VERSION,
        )


def test_release_wheel_rejects_link_member(tmp_path: Path) -> None:
    link = zipfile.ZipInfo("provelume/linked.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    wheel = _wheel(tmp_path, extra_member=(link, b"module.py"))

    with pytest.raises(WheelVerificationError, match="non-regular or link-like"):
        verify_release_wheel(
            tmp_path,
            _bundle_result(wheel),
            expected_version=VERSION,
        )


def test_release_wheel_rejects_linked_bundle_root(tmp_path: Path) -> None:
    root = tmp_path / "release"
    root.mkdir()
    wheel = _wheel(root)
    linked = tmp_path / "linked-release"
    try:
        os.symlink(root, linked, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")

    with pytest.raises(WheelVerificationError, match="link-like"):
        verify_release_wheel(
            linked,
            _bundle_result(wheel),
            expected_version=VERSION,
        )


def test_release_wheel_enforces_member_count_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = _wheel(tmp_path)
    monkeypatch.setattr("provelume.release_wheel.MAX_WHEEL_MEMBERS", 4)

    with pytest.raises(WheelVerificationError, match="number of members"):
        verify_release_wheel(
            tmp_path,
            _bundle_result(wheel),
            expected_version=VERSION,
        )


def test_release_wheel_enforces_record_byte_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = _wheel(tmp_path)
    monkeypatch.setattr("provelume.release_wheel.MAX_WHEEL_RECORD_BYTES", 32)

    with pytest.raises(WheelVerificationError, match="metadata exceeds"):
        verify_release_wheel(
            tmp_path,
            _bundle_result(wheel),
            expected_version=VERSION,
        )


def test_release_linkage_matches_installed_bytes_without_origin_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(tmp_path)
    release_root = tmp_path / "release"
    release_root.mkdir()
    wheel = _wheel(release_root)
    bundle_result = _bundle_result(wheel)
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )
    monkeypatch.setattr(
        "provelume.installation.verify_bundle",
        lambda *_args, **_kwargs: bundle_result,
    )

    result = verify_current_installation(release_bundle=release_root)

    assert result["status"] == "package_integrity_verified"
    assert result["release_linkage"]["status"] == "verified"
    assert result["release_linkage"]["checked_files"] == 2
    assert result["origin"]["status"] == "not_established"
    assert result["network_used"] is False


def test_release_linkage_reports_only_operator_supplied_manifest_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(tmp_path)
    release_root = tmp_path / "release"
    release_root.mkdir()
    wheel = _wheel(release_root)
    bundle_result = _bundle_result(wheel, anchored=True)
    calls: list[dict[str, object]] = []

    def verify_stub(*_args, **kwargs):
        calls.append(kwargs)
        return bundle_result

    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )
    monkeypatch.setattr("provelume.installation.verify_bundle", verify_stub)

    result = verify_current_installation(
        release_bundle=release_root,
        expected_manifest_sha256="b" * 64,
    )

    assert calls[0]["expected_manifest_sha256"] == "b" * 64
    assert result["origin"]["status"] == "trusted_manifest_sha256_matched"
    assert "depends on the trust" in result["origin"]["detail"]


def test_modified_local_record_cannot_conceal_release_wheel_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = b"VALUE = 'locally changed'\n"
    install_root, package, dist_info = _installation(
        tmp_path,
        module_bytes=changed,
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    wheel = _wheel(release_root)
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )
    monkeypatch.setattr(
        "provelume.installation.verify_bundle",
        lambda *_args, **_kwargs: _bundle_result(wheel),
    )

    result = verify_current_installation(release_bundle=release_root)

    assert result["status"] == "modified_installation"
    assert result["release_linkage"]["status"] == "installed_bytes_differ"
    assert any(
        finding["path"] == "provelume/module.py"
        and finding["issue"] == "release_file_modified"
        for finding in result["findings"]
    )


def test_release_linkage_detects_file_absent_from_release_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(
        tmp_path,
        extra_file=("provelume/injected.py", b"INJECTED = True\n"),
    )
    release_root = tmp_path / "release"
    release_root.mkdir()
    wheel = _wheel(release_root)
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )
    monkeypatch.setattr(
        "provelume.installation.verify_bundle",
        lambda *_args, **_kwargs: _bundle_result(wheel),
    )

    result = verify_current_installation(release_bundle=release_root)

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume/injected.py"
        and finding["issue"] == "release_unexpected_file"
        for finding in result["findings"]
    )


def test_release_linkage_detects_file_missing_from_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(tmp_path)
    (package / "module.py").unlink()
    release_root = tmp_path / "release"
    release_root.mkdir()
    wheel = _wheel(release_root)
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )
    monkeypatch.setattr(
        "provelume.installation.verify_bundle",
        lambda *_args, **_kwargs: _bundle_result(wheel),
    )

    result = verify_current_installation(release_bundle=release_root)

    assert result["status"] == "modified_installation"
    assert result["release_linkage"]["status"] == "installed_bytes_differ"
    assert any(
        finding["path"] == "provelume/module.py"
        and finding["issue"] == "release_file_missing"
        for finding in result["findings"]
    )


def test_release_linkage_enforces_cumulative_installed_hash_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(tmp_path)
    release_root = tmp_path / "release"
    release_root.mkdir()
    wheel = _wheel(release_root)
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )
    monkeypatch.setattr(
        "provelume.installation.verify_bundle",
        lambda *_args, **_kwargs: _bundle_result(wheel),
    )
    monkeypatch.setattr("provelume.installation.MAX_HASH_BYTES", 1)

    result = verify_current_installation(release_bundle=release_root)

    assert result["release_linkage"]["status"] == "verification_unavailable"
    assert any(finding["issue"] == "scan_limit" for finding in result["findings"])


def test_release_linkage_fails_closed_on_invalid_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(tmp_path)
    release_root = tmp_path / "release"
    release_root.mkdir()
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )

    def invalid_bundle(*_args, **_kwargs):
        raise VerificationError("synthetic inconsistency")

    monkeypatch.setattr("provelume.installation.verify_bundle", invalid_bundle)

    result = verify_current_installation(release_bundle=release_root)

    assert result["status"] == "verification_unavailable"
    assert result["release_linkage"]["status"] == "bundle_invalid"
    assert any(finding["issue"] == "bundle_invalid" for finding in result["findings"])


def test_release_linkage_does_not_disclose_bundle_path_on_io_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(tmp_path)
    release_root = tmp_path / "operator-secret" / "release"
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )

    def unreadable_bundle(*_args, **_kwargs):
        raise OSError(f"cannot read {release_root}")

    monkeypatch.setattr("provelume.installation.verify_bundle", unreadable_bundle)

    result = verify_current_installation(release_bundle=release_root)

    assert result["status"] == "verification_unavailable"
    assert result["release_linkage"]["status"] == "bundle_invalid"
    assert str(release_root) not in json.dumps(result)


def test_release_linkage_fails_closed_on_invalid_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(tmp_path)
    release_root = tmp_path / "release"
    release_root.mkdir()
    wheel = _wheel(release_root, recorded_module_bytes=b"different bytes")
    bundle_result = _bundle_result(wheel)
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )
    monkeypatch.setattr(
        "provelume.installation.verify_bundle",
        lambda *_args, **_kwargs: bundle_result,
    )

    result = verify_current_installation(release_bundle=release_root)

    assert result["status"] == "verification_unavailable"
    assert result["release_linkage"]["status"] == "wheel_invalid"
    assert any(finding["issue"] == "wheel_invalid" for finding in result["findings"])


def test_manifest_anchor_without_bundle_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, package, dist_info = _installation(tmp_path)
    _bind_installation(
        monkeypatch,
        root=install_root,
        package=package,
        dist_info=dist_info,
    )

    result = verify_current_installation(expected_manifest_sha256="b" * 64)

    assert result["status"] == "verification_unavailable"
    assert result["release_linkage"]["status"] == "bundle_invalid"
