from __future__ import annotations

import errno
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from provelume import review_decisions
from provelume.review_decisions import checked_path
from provelume.review_effects import ReviewUnavailable


def _store(root: Path):
    return SimpleNamespace(paths=SimpleNamespace(root=root))


def _symlink(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        if os.name == "nt" and error.winerror == 1314:
            pytest.skip("Windows denied the privilege for this real symbolic link")
        raise


@pytest.mark.parametrize("leaf_directory", [False, True])
def test_regular_path_preserves_leaf_type_and_bytes(tmp_path, leaf_directory):
    root = tmp_path / "instance"
    parent = root / "state" / "review"
    parent.mkdir(parents=True)
    leaf = parent / "evidence"
    if leaf_directory:
        leaf.mkdir()
    else:
        leaf.write_bytes(b"synthetic evidence")
    assert checked_path(_store(root), "state/review/evidence") == leaf
    if leaf_directory:
        assert leaf.is_dir() and not list(leaf.iterdir())
    else:
        assert leaf.read_bytes() == b"synthetic evidence"


@pytest.mark.parametrize("existing_depth", [0, 1, 2, 3])
def test_absent_components_are_observed_without_creating_them(tmp_path, existing_depth):
    root = tmp_path / "instance"
    parts = [root, root / "state", root / "state" / "review"]
    for path in parts[:existing_depth]:
        path.mkdir()
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert checked_path(_store(root), "state/review/new.json") == root / "state/review/new.json"
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == before


@pytest.mark.parametrize("file_parent", ["root", "middle"])
def test_existing_file_cannot_be_a_parent(tmp_path, file_parent):
    root = tmp_path / "instance"
    if file_parent == "root":
        root.write_bytes(b"not a directory")
    else:
        root.mkdir()
        (root / "state").write_bytes(b"not a directory")
    with pytest.raises(ReviewUnavailable, match="parent is not a directory"):
        checked_path(_store(root), "state/review/new.json")


@pytest.mark.parametrize("position", ["root", "middle", "leaf"])
@pytest.mark.parametrize("dangling", [False, True])
def test_real_symbolic_links_are_rejected_at_every_position(tmp_path, position, dangling):
    root = tmp_path / "instance"
    external = tmp_path / "external"
    directory = position != "leaf"
    if not dangling:
        if directory:
            external.mkdir()
        else:
            external.write_bytes(b"must not be followed")
    if position == "root":
        link = root
    elif position == "middle":
        root.mkdir()
        link = root / "state"
    else:
        (root / "state" / "review").mkdir(parents=True)
        link = root / "state" / "review" / "item.json"
    _symlink(link, external, directory=directory)
    with pytest.raises(ReviewUnavailable, match="cannot traverse links"):
        checked_path(_store(root), "state/review/item.json")


@pytest.mark.skipif(os.name != "nt", reason="Real Windows junction observation")
@pytest.mark.parametrize("position", ["root", "middle", "leaf"])
def test_real_windows_junctions_are_rejected(tmp_path, position):
    command = shutil.which("cmd.exe")
    assert command is not None, "Windows command processor is required for a real junction"
    root = tmp_path / "instance"
    target = tmp_path / "junction-target"
    target.mkdir()
    if position == "root":
        link = root
    elif position == "middle":
        root.mkdir()
        link = root / "state"
    else:
        (root / "state" / "review").mkdir(parents=True)
        link = root / "state" / "review" / "item.json"
    assert link.resolve().is_relative_to(tmp_path.resolve())
    assert target.resolve().is_relative_to(tmp_path.resolve())
    result = subprocess.run(
        [command, "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert link.is_junction()
    with pytest.raises(ReviewUnavailable, match="cannot traverse links"):
        checked_path(_store(root), "state/review/item.json")
    assert target.is_dir() and not list(target.iterdir())


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.ELOOP])
def test_observation_errors_never_become_permission_to_proceed(tmp_path, monkeypatch, error_number):
    root = tmp_path / "instance"
    (root / "state").mkdir(parents=True)
    original = Path.lstat
    error = OSError(error_number, "Synthetic filesystem observation failure")

    def denied(path):
        if path == root / "state":
            raise error
        return original(path)

    monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(OSError) as raised:
        checked_path(_store(root), "state/review/item.json")
    assert raised.value is error


def test_second_observation_rejects_a_new_parent_file(tmp_path):
    root = tmp_path / "instance"
    root.mkdir()
    assert checked_path(_store(root), "state/review/item.json") == root / "state/review/item.json"
    (root / "state").write_bytes(b"created after the first observation")
    with pytest.raises(ReviewUnavailable, match="parent is not a directory"):
        checked_path(_store(root), "state/review/item.json")


def test_second_observation_rejects_a_new_link(tmp_path):
    root = tmp_path / "instance"
    root.mkdir()
    store = _store(root)
    assert checked_path(store, "state/review/item.json") == root / "state/review/item.json"
    external = tmp_path / "external"
    external.mkdir()
    _symlink(root / "state", external, directory=True)
    with pytest.raises(ReviewUnavailable, match="cannot traverse links"):
        checked_path(store, "state/review/item.json")


def test_read_rejects_leaf_replaced_by_link_after_path_observation(tmp_path, monkeypatch):
    root = tmp_path / "instance"
    leaf = root / "state" / "review" / "item.json"
    leaf.parent.mkdir(parents=True)
    leaf.write_bytes(b"original synthetic record")
    target = tmp_path / "target.json"
    target.write_bytes(b"must never be opened")
    original_open = Path.open

    def replace_after_observation(store, relative):
        observed = checked_path(store, relative)
        assert observed == leaf
        leaf.unlink()
        _symlink(leaf, target, directory=False)
        return observed

    def forbidden_target_open(path, *args, **kwargs):
        if path in (leaf, target):
            pytest.fail("Read followed the leaf replacement instead of rejecting it")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(review_decisions, "checked_path", replace_after_observation)
    monkeypatch.setattr(Path, "open", forbidden_target_open)
    with pytest.raises(ReviewUnavailable):
        review_decisions.read_bytes(_store(root), "state/review/item.json")
