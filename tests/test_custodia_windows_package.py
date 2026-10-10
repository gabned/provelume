"""Public frozen inventory boundaries; these tests do not claim Windows execution."""

import hashlib
import json
import os

import pytest

from provelume.ai_models import ModelError
from provelume.ai_windows_package import build_inventory, inventory


def package(tmp_path):
    root = tmp_path / "public-installation"
    (root / "_internal/provelume").mkdir(parents=True)
    (root / "Provelume.exe").write_bytes(b"public frozen executable stand-in")
    (root / "_internal/provelume/public.json").write_text('{"public":true}')
    return root


def test_frozen_inventory_identifies_public_bytes_but_excludes_installer_files(tmp_path):
    root = package(tmp_path)
    raw = build_inventory(root, "a" * 40)
    value = json.loads(raw)
    assert value["directories"] == ["_internal", "_internal/provelume"]
    assert value["files"] == {"_internal/provelume/public.json": {
        "bytes": 15, "sha256": hashlib.sha256(b'{"public":true}').hexdigest()}}
    (root / "unins000.exe").write_bytes(b"installer-owned metadata")
    (root / "unins000.dat").write_bytes(b"installer-owned data")
    observed, _ = inventory(root, installed=True)
    assert set(observed) == set(value["files"])
    with pytest.raises(ModelError, match="untrusted"):
        build_inventory(root, "a" * 40)


def test_unexpected_root_data_and_hardlinks_are_not_public_code(tmp_path):
    root = package(tmp_path)
    private = root / "private-document.txt"
    private.write_text("synthetic private canary")
    with pytest.raises(ModelError, match="untrusted"):
        inventory(root, installed=True)
    private.unlink()
    outside = tmp_path / "private-canary.txt"
    outside.write_text("outside public code")
    os.link(outside, root / "_internal/private.txt")
    with pytest.raises(ModelError, match="unsafe_path"):
        inventory(root, installed=True)
    assert outside.read_text() == "outside public code"


def test_reparse_or_symlink_directory_is_never_traversed(tmp_path):
    root = package(tmp_path)
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "canary").write_text("private")
    try:
        (root / "_internal/linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit symlink creation")
    with pytest.raises(ModelError, match="unsafe_path"):
        inventory(root, installed=True)
