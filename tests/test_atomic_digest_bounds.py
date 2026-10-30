"""Fresh-size bounds for the digest's transient reads, including concurrent mutation."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from provelume.atomic_commit import AtomicCommitError, _bounded_file_digest


@pytest.mark.parametrize("size", [0, 51, 1024, 1024 * 1024 - 1,
                                  1024 * 1024, 1024 * 1024 + 1])
def test_digest_preserves_exact_bytes_and_limit(tmp_path, size):
    target = tmp_path / "candidate.bin"
    payload = b"j" * size
    target.write_bytes(payload)
    assert _bounded_file_digest(
        target, limit=size, error_type=AtomicCommitError,
    ) == (hashlib.sha256(payload).hexdigest(), size)
    if size:
        with pytest.raises(AtomicCommitError):
            _bounded_file_digest(target, limit=size - 1, error_type=AtomicCommitError)


@pytest.mark.parametrize("mutation", ["grow", "shrink", "same_size"])
def test_digest_rejects_mutation_and_bounds_growth_read(tmp_path, monkeypatch, mutation):
    target = tmp_path / "candidate.bin"
    payload = b"original journal"
    target.write_bytes(payload)
    before = target.stat()
    real_open = Path.open
    consumed = 0

    class MutatingReader:
        def __init__(self, stream):
            self.stream = stream
            self.changed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size):
            nonlocal consumed
            if not self.changed:
                self.changed = True
                replacement = {
                    "grow": payload + b"x" * 65536,
                    "shrink": payload[:-1],
                    "same_size": b"x" * len(payload),
                }[mutation]
                with real_open(target, "wb") as writer:
                    writer.write(replacement)
                os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000))
            data = self.stream.read(size)
            consumed += len(data)
            return data

    def observed_open(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        return MutatingReader(stream) if path == target and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", observed_open)
    with pytest.raises(AtomicCommitError):
        _bounded_file_digest(target, limit=1024 * 1024, error_type=AtomicCommitError)
    assert consumed <= len(payload) + 1
