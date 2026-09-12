from __future__ import annotations

import hashlib
import json
import socket
import stat
import zipfile
from pathlib import Path

import pytest

from scripts import verify_cura_package_resources as verifier


@pytest.fixture
def package(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    # Deliberately synthetic bytes: these tests prove detection, never a frozen build.
    resources = {name: (name + " synthetic fixture\n").encode() for name in verifier.REQUIRED}
    resources.update({f"static/icons/lucide/icon-{i}.svg": b"<svg/>" for i in range(18)})
    resources["templates/cura/home.html"] = b"synthetic Cura home"
    resources["templates/search.html"] = b"synthetic existing search"
    wheel = tmp_path / "provelume-0.0.0-py3-none-any.whl"
    frozen = tmp_path / "dist/Provelume/_internal/provelume"
    _write_wheel(wheel, resources)
    for name, payload in resources.items():
        path = frozen / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return wheel, frozen, resources


def _write_wheel(wheel: Path, resources: dict[str, bytes]) -> None:
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, payload in resources.items():
            archive.writestr("provelume/" + name, payload)
        archive.writestr("provelume/cli.py", b"raise RuntimeError('never import candidate')")


def test_synthetic_parity_binds_bytes_without_network_or_candidate_import(package, monkeypatch):
    wheel, frozen, resources = package

    def forbidden(*args, **kwargs):
        raise AssertionError("network is forbidden")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    result = verifier.verify_cura_resources(wheel, frozen)
    assert result["scope"] == "cura_package_resource_parity"
    assert result["qualification"] == "resource_parity_only"
    assert result["wheel"]["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert result["resource_count"] == len(resources)
    assert result["wheel_resources_sha256"] == result["frozen_resources_sha256"]
    assert {row["path"] for row in result["resources"]} == set(resources)
    assert result == verifier.verify_cura_resources(wheel, frozen)


@pytest.mark.parametrize(
    "name",
    [
        "templates/legacy/base.html",
        "templates/cura/home.html",
        "templates/search.html",
        "notices/THIRD_PARTY_NOTICES.md",
        "static/icons/lucide/LICENSE",
        "i18n/it.json",
        "static/cura-shell.js",
    ],
)
@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_frozen_missing_or_changed_resources_are_rejected(package, name, mutation):
    wheel, frozen, _ = package
    path = frozen / name
    if mutation == "missing":
        path.unlink()
    else:
        payload = path.read_bytes()
        path.write_bytes(b"!" + payload[1:])  # Same length must still fail.
    with pytest.raises(verifier.CuraResourceError, match="missing|changed"):
        verifier.verify_cura_resources(wheel, frozen)


@pytest.mark.parametrize(
    "name",
    [
        "templates/legacy/unexpected.html",
        "notices/extra.txt",
        "i18n/fr.json",
        "static/icons/lucide/extra.svg",
        "templates/unused/empty-directory",
    ],
)
def test_extra_files_and_empty_directories_within_scoped_subtrees_fail(package, name):
    wheel, frozen, _ = package
    extra = frozen / name
    if name.endswith("empty-directory"):
        extra.mkdir(parents=True)
    else:
        extra.write_bytes(b"unexpected")
    with pytest.raises(verifier.CuraResourceError, match="extra"):
        verifier.verify_cura_resources(wheel, frozen)


def test_unrelated_brand_resources_retain_their_separate_gate(package):
    wheel, frozen, _ = package
    brand = frozen / "static/brand/provelume.png"
    brand.parent.mkdir()
    brand.write_bytes(b"existing separately verified brand fixture")
    assert verifier.verify_cura_resources(wheel, frozen)["status"] == "matched"


@pytest.mark.parametrize("name", ["templates/legacy/base.html", "notices/LICENSE"])
def test_missing_in_both_artifacts_cannot_hide_required_resources(package, name):
    wheel, frozen, resources = package
    del resources[name]
    (frozen / name).unlink()
    _write_wheel(wheel, resources)
    with pytest.raises(verifier.CuraResourceError, match="wheel missing required"):
        verifier.verify_cura_resources(wheel, frozen)


@pytest.mark.parametrize(
    "name",
    [
        "provelume/templates/../outside",
        "/absolute",
        "provelume/templates/AUX.txt",
        "provelume/templates/back\\slash",
        "provelume/templates/file:stream",
        "provelume/templates/base.html",
        "provelume/templates/BASE.html",
    ],
)
def test_unsafe_duplicate_or_case_colliding_zip_members_fail(package, name):
    wheel, frozen, _ = package
    with zipfile.ZipFile(wheel, "a") as archive:
        if name == "provelume/templates/base.html":
            with pytest.warns(UserWarning, match="Duplicate"):
                archive.writestr(name, b"unsafe")
        else:
            entry = zipfile.ZipInfo("placeholder")
            entry.filename = entry.orig_filename = name
            archive.writestr(entry, b"unsafe")
    with pytest.raises(verifier.CuraResourceError, match="unsafe|duplicate"):
        verifier.verify_cura_resources(wheel, frozen)


def test_zip_symlink_is_rejected(package):
    wheel, frozen, _ = package
    link = zipfile.ZipInfo("provelume/templates/link.html")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(link, "base.html")
    with pytest.raises(verifier.CuraResourceError, match="linked"):
        verifier.verify_cura_resources(wheel, frozen)


def test_frozen_junction_or_symlink_boundary_is_rejected(package, monkeypatch):
    wheel, frozen, _ = package
    original = Path.is_junction
    boundary = frozen / "templates"
    monkeypatch.setattr(Path, "is_junction", lambda path: path == boundary or original(path))
    with pytest.raises(verifier.CuraResourceError, match="linked or reparse"):
        verifier.verify_cura_resources(wheel, frozen)


def test_oversized_resource_is_rejected_before_read(package, monkeypatch):
    wheel, frozen, _ = package
    monkeypatch.setattr(verifier, "MAX_RESOURCE_BYTES", 8)
    with pytest.raises(verifier.CuraResourceError, match="limit"):
        verifier.verify_cura_resources(wheel, frozen)


def test_cli_writes_scoped_json_and_returns_failure_for_mismatch(package, tmp_path, capsys):
    wheel, frozen, _ = package
    output = tmp_path / "parity.json"
    args = ["--wheel", str(wheel), "--frozen-root", str(frozen), "--output", str(output)]
    assert verifier.main(args) == 0
    assert json.loads(output.read_text())["status"] == "matched"
    assert json.loads(capsys.readouterr().out)["qualification"] == "resource_parity_only"
    (frozen / "notices/NOTICE.md").unlink()
    assert verifier.main(args[:-2]) == 1
    assert "missing frozen" in capsys.readouterr().err


def test_cli_cannot_overwrite_wheel_or_frozen_tree(package, capsys):
    wheel, frozen, _ = package
    for output in (wheel, frozen / "parity.json"):
        assert (
            verifier.main(
                ["--wheel", str(wheel), "--frozen-root", str(frozen), "--output", str(output)]
            )
            == 1
        )
        assert "outside" in capsys.readouterr().err
