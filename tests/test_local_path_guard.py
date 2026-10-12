from __future__ import annotations

import os
from pathlib import Path

import pytest

from provelume import atomic_commit
from provelume.atomic_commit import AtomicCommitIntegrityError
from provelume.local_path_guard import kernel_no_links
from provelume.storage import InstanceStore


def test_atomic_target_does_not_repeat_python_metadata_walk(tmp_path, monkeypatch):
    store = InstanceStore.initialise(tmp_path / "instance")
    target = store.paths.root / "state/missing/deeper/item.bin"
    if not kernel_no_links(target):
        pytest.skip("Kernel path guard unavailable")
    original = os.lstat
    repeated = []

    def observe(path, *args, **kwargs):
        repeated.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", observe)
    resolved, relative = atomic_commit._instance_target(
        store, "state/missing/deeper/item.bin", error_type=AtomicCommitIntegrityError)
    assert resolved == target and relative == "state/missing/deeper/item.bin"
    assert repeated == []


def test_kernel_guard_rejects_an_internal_alias_and_missing_below_file(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    if not kernel_no_links(target):
        pytest.skip("Kernel path guard unavailable")
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError):
        kernel_no_links(alias / "missing")
    file = target / "file"
    file.write_bytes(b"synthetic")
    with pytest.raises(OSError):
        kernel_no_links(file / "missing")


def test_unsupported_kernel_preserves_original_atomic_resolver(tmp_path, monkeypatch):
    store = InstanceStore.initialise(tmp_path / "instance")
    expected = store.paths.root / "state/item.bin"
    observed = []
    original = Path.resolve
    monkeypatch.setattr(atomic_commit, "kernel_no_links", lambda path: False)

    def resolve(path, *args, **kwargs):
        observed.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    resolved, _ = atomic_commit._instance_target(
        store, "state/item.bin", error_type=AtomicCommitIntegrityError)
    assert resolved == expected and expected in observed


def test_kernel_guard_retains_no_file_descriptors(tmp_path):
    if not kernel_no_links(tmp_path) or not Path("/proc/self/fd").exists():
        pytest.skip("Kernel descriptor observation unavailable")
    before = len(list(Path("/proc/self/fd").iterdir()))
    for index in range(100):
        assert kernel_no_links(tmp_path / "missing" / str(index))
    assert len(list(Path("/proc/self/fd").iterdir())) == before
