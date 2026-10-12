from __future__ import annotations

import hashlib
import os
import time
import warnings

import pytest

from provelume import model_file_digest


@pytest.mark.parametrize("length", [0, 1, 63, 64, 65, 1024 * 1024, 1024 * 1024 + 13])
def test_model_digest_preserves_sha256_across_binary_chunk_boundaries(length):
    data = (b"GGUF\x03\0\0\0\xff" * ((length + 8) // 9))[:length]
    with model_file_digest.model_digest() as digest:
        for start in range(0, len(data), 1024 * 1024):
            digest.update(data[start:start + 1024 * 1024])
        assert digest.hexdigest() == hashlib.sha256(data).hexdigest()


@pytest.mark.skipif(os.name != "nt", reason="Real Windows SHA-256 provider")
def test_windows_hash_state_is_released_on_read_failure():
    selected = model_file_digest.WindowsSha256()
    selected.update(b"synthetic\0binary")
    selected.close()
    assert selected.handle.value is None and selected.algorithm.value is None
    selected.close()


def test_digest_context_closes_provider_on_cancellation(monkeypatch):
    closed = []

    class Provider:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(model_file_digest, "_WINDOWS", True)
    monkeypatch.setattr(model_file_digest, "WindowsSha256", Provider)
    with pytest.raises(RuntimeError), model_file_digest.model_digest():
        raise RuntimeError("synthetic cancellation")
    assert closed == [True]


@pytest.mark.skipif(os.name != "nt", reason="Real Windows provider comparison")
def test_windows_sha256_preserves_digest_with_recorded_operation_cost():
    block = b"synthetic binary\0" * (1024 * 1024 // 17)
    results = {}
    outputs = {}
    for name, factory in [("hashlib", hashlib.sha256),
                          ("system_sha256", model_file_digest.WindowsSha256)]:
        digest = factory()
        start = time.perf_counter()
        try:
            for _ in range(64):
                digest.update(block)
            outputs[name] = digest.hexdigest()
            results[name] = time.perf_counter() - start
        finally:
            if hasattr(digest, "close"):
                digest.close()
    assert outputs["hashlib"] == outputs["system_sha256"]
    # Timing is diagnostic only, never a new threshold or qualification PASS.
    warnings.warn(f"Synthetic Windows SHA-256 operation costs: {results}",
                  UserWarning, stacklevel=1)
