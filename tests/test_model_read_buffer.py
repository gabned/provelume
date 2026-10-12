from __future__ import annotations

import hashlib
import tracemalloc
from types import SimpleNamespace

from provelume.ai_model_file import verify_stream


def test_model_verification_has_one_bounded_payload_buffer(tmp_path):
    data = b"GGUF\x03\0\0\0" + b"synthetic\0" * (1024 * 1024 // 10 * 4)
    path = tmp_path / "synthetic.gguf"
    path.write_bytes(data)
    entry = SimpleNamespace(model_size=len(data), model_sha256=hashlib.sha256(data).hexdigest())
    # Trace only verification, not fixture creation. The old read loop retains
    # its previous MiB block while allocating the next one (over two MiB peak).
    tracemalloc.start()
    try:
        with path.open("rb") as stream:
            verify_stream(stream, entry)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1536 * 1024
