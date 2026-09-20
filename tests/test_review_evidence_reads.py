from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from provelume.review_decisions import read_bytes
from provelume.review_effects import ReviewUnavailable


def _store(root):
    return SimpleNamespace(paths=SimpleNamespace(root=root))


@pytest.mark.parametrize("size", [65_535, 65_536, 65_537, 131_072])
def test_review_evidence_retains_exact_binary_content_across_read_boundaries(tmp_path, size):
    payload = (bytes(range(256)) * ((size // 256) + 1))[:size]
    (tmp_path / "evidence.bin").write_bytes(payload)
    assert read_bytes(_store(tmp_path), "evidence.bin", maximum=size) == payload


@pytest.mark.parametrize("size", [65_536, 65_537])
def test_review_evidence_enforces_bound_when_file_grows_after_stat(tmp_path, monkeypatch, size):
    path = tmp_path / "evidence.bin"
    original = b"Synthetic initial observation"
    path.write_bytes(original)
    payload = b"A" * size
    real_open = Path.open
    growth = []

    def grow_before_read(current, mode="r", *args, **kwargs):
        if current == path and mode == "rb":
            # The production size check has already run; change the real file
            # before the reader opens it, without replacing its read behavior.
            assert current.stat().st_size == len(original)
            with real_open(current, "wb") as writer:
                writer.write(payload)
            growth.append(size)
        return real_open(current, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_before_read)
    if size == 65_536:
        assert read_bytes(_store(tmp_path), "evidence.bin", maximum=65_536) == payload
    else:
        with pytest.raises(ReviewUnavailable, match="exceeds its bound"):
            read_bytes(_store(tmp_path), "evidence.bin", maximum=65_536)
    assert growth == [size]


def test_review_evidence_rejects_linked_parent_without_reading_target(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evidence.bin").write_bytes(b"Must not cross this link")
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name == "nt" and exc.winerror == 1314:
            pytest.skip(f"Windows symlink privilege is unavailable: {exc}")
        raise
    with pytest.raises(ReviewUnavailable, match="cannot traverse links"):
        read_bytes(_store(root), "linked/evidence.bin")
