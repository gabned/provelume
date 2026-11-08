from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from provelume import capture_journal
from provelume.capture_journal import CaptureJournalError
from provelume.local_path_guard import kernel_no_links


def require_kernel(path):
    if not kernel_no_links(path):
        pytest.skip("Linux kernel no-link path guard unavailable")


def test_capture_guard_avoids_redundant_metadata_stops(tmp_path, monkeypatch):
    target = tmp_path / "missing/deeper/record.json"
    require_kernel(target)
    original = Path.lstat
    observations = []

    def observe(path, *args, **kwargs):
        observations.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", observe)
    capture_journal._safe(target)
    assert observations == []


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("position", ["ancestor", "middle", "leaf"])
def test_capture_guard_rejects_links_with_existing_or_missing_leaf(
    tmp_path, monkeypatch, fast, position,
):
    real = tmp_path / "real"
    real.mkdir()
    target = real / "middle/record.json"
    target.parent.mkdir()
    target.write_bytes(b"synthetic")
    if fast:
        require_kernel(target)
    else:
        monkeypatch.setattr(capture_journal, "kernel_no_links", lambda path: False)
    link = {"ancestor": real, "middle": target.parent, "leaf": target}[position]
    moved = tmp_path / "moved"
    link.rename(moved)
    try:
        link.symlink_to(moved, target_is_directory=position != "leaf")
    except OSError as exc:
        if os.name == "nt" and exc.winerror == 1314:
            pytest.skip("Windows denied symbolic-link privilege")
        raise
    with pytest.raises(CaptureJournalError):
        capture_journal._safe(target)
    if position != "leaf":
        with pytest.raises(CaptureJournalError):
            capture_journal._safe(link / "missing/record.json")


def test_capture_guard_reobserves_replacement_between_calls(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "missing/record.json"
    require_kernel(target)
    capture_journal._safe(target)
    moved = tmp_path / "moved"
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    with pytest.raises(CaptureJournalError):
        capture_journal._safe(target)
    assert not (moved / "missing").exists()


def test_unsupported_kernel_retains_full_component_observations(tmp_path, monkeypatch):
    target = tmp_path / "missing/record.json"
    monkeypatch.setattr(capture_journal, "kernel_no_links", lambda path: False)
    original = Path.lstat
    observations = []

    def observe(path):
        observations.append(path)
        return original(path)

    monkeypatch.setattr(Path, "lstat", observe)
    capture_journal._safe(target)
    assert observations == [target, *target.parents]


def test_relative_capture_path_retains_original_walk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def unexpected(path):
        pytest.fail("A relative path cannot use absolute kernel validation")

    monkeypatch.setattr(capture_journal, "kernel_no_links", unexpected)
    capture_journal._safe(Path("missing/record.json"))


def test_kernel_unsafe_result_cannot_select_fallback(tmp_path, monkeypatch):
    def unsafe(path):
        raise OSError(errno.ELOOP, "synthetic replaced component")

    def unexpected(path):
        pytest.fail("An unsafe kernel result cannot select the original fallback")

    monkeypatch.setattr(capture_journal, "kernel_no_links", unsafe)
    monkeypatch.setattr(Path, "lstat", unexpected)
    with pytest.raises(CaptureJournalError):
        capture_journal._safe(tmp_path / "record.json")


def test_kernel_capture_guard_preserves_invalid_path_rejection(tmp_path):
    require_kernel(tmp_path)
    with pytest.raises((CaptureJournalError, ValueError)):
        capture_journal._safe(tmp_path / "record.json\0suffix")
    regular = tmp_path / "regular"
    regular.write_bytes(b"synthetic")
    with pytest.raises((CaptureJournalError, OSError)):
        capture_journal._safe(regular / "record.json")


def test_repeated_capture_guard_does_not_leak_descriptors(tmp_path):
    require_kernel(tmp_path)
    descriptors = Path("/proc/self/fd")
    if not descriptors.is_dir():
        pytest.skip("Linux descriptor inventory unavailable")
    before = len(list(descriptors.iterdir()))
    for index in range(100):
        capture_journal._safe(tmp_path / "missing" / str(index))
    assert len(list(descriptors.iterdir())) == before
