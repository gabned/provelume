"""Real bounded file I/O; inert GGUF framing is never passed to native inference."""

import hashlib
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from provelume import ai_model_file
from provelume.ai_model_store import ModelStore, SelfTestEvidence
from provelume.ai_models import ModelError
from provelume.ai_runtime import native_selection
from provelume.ai_runtime_contract import MODEL_ID


@pytest.mark.parametrize("action", ["verify", "self_test", "install", "activate", "use"])
@pytest.mark.parametrize("when", ["before", "first_read"])
def test_model_lifecycle_stops_file_reads_on_cancellation(tmp_path, monkeypatch, action, when):
    data = b"GGUF\x03\0\0\0" + b"public inert fixture\n" * 160000
    store = ModelStore(tmp_path / "models")
    entry = replace(store.registry.entry(MODEL_ID), model_size=len(data),
                    model_sha256=hashlib.sha256(data).hexdigest())
    selection = native_selection()
    with store._hold():
        path = store._path(entry)
        path.write_bytes(data)
        store._write_state({"schema_version": 1, "active": MODEL_ID, "previous": None})
    monkeypatch.setattr(store, "_entry", lambda *_: entry)
    evidence = SelfTestEvidence(MODEL_ID, store._binding(entry, selection), "PASSED",
                                time.monotonic() + 60)
    store._evidence[MODEL_ID] = evidence
    store._native_runners[MODEL_ID] = SimpleNamespace(validate_installation=lambda: None)
    stopped = threading.Event()
    if when == "before":
        stopped.set()
    reads = []
    original_open = ai_model_file.open_local_file

    class Observed:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self, amount):
            reads.append(stopped.is_set())
            block = self.handle.read(amount)
            stopped.set()
            return block

    @contextmanager
    def observed_open(value):
        with original_open(value) as handle:
            yield Observed(handle)

    monkeypatch.setattr(ai_model_file, "open_local_file", observed_open)
    with pytest.raises(ModelError, match="model_cancelled"):
        if action == "verify":
            store.verify(MODEL_ID, selection, cancel=stopped.is_set)
        elif action == "self_test":
            store.self_test(MODEL_ID, selection, None, requested=True, cancel=stopped.is_set)
        elif action == "install":
            store.install(MODEL_ID, selection, requested=True, license_accepted=entry.license,
                          cancel=stopped.is_set)
        elif action == "activate":
            store.activate(MODEL_ID, selection, evidence, requested=True, cancel=stopped.is_set)
        else:
            with store.use(selection, cancel=stopped.is_set):
                pytest.fail("cancelled model admitted")
    assert reads == ([] if when == "before" else [False])
    assert path.read_bytes() == data
    if action == "self_test":
        assert MODEL_ID not in store._evidence


def test_raw_verification_observes_cancellation_at_eof(tmp_path):
    data = b"GGUF\x03\0\0\0" + b"public inert bytes"
    path = tmp_path / "model.gguf"
    path.write_bytes(data)
    entry = SimpleNamespace(model_size=len(data), model_sha256=hashlib.sha256(data).hexdigest())
    stopped = threading.Event()
    with path.open("rb") as handle:
        class CancelAtEof:
            def __getattr__(self, name):
                return getattr(handle, name)

            def read(self, amount):
                result = handle.read(amount)
                if not result:
                    stopped.set()
                return result

        with pytest.raises(ModelError, match="model_cancelled"):
            ai_model_file.verify_stream(CancelAtEof(), entry, cancel=stopped.is_set)
