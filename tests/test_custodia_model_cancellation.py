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


@pytest.mark.parametrize("signal", ["immediate", "authority", "at_eof", "deadline"])
def test_read_authority_preserves_cancellation_and_final_boundary(tmp_path, monkeypatch, signal):
    data = b"GGUF\x03\0\0\0" + bytes(12 * 1024 * 1024)
    path = tmp_path / "bounded.gguf"
    path.write_bytes(data)
    entry = SimpleNamespace(model_size=len(data), model_sha256=hashlib.sha256(data).hexdigest())
    clock, reads, checks = [100.0], [], []
    changed, immediate = threading.Event(), threading.Event()
    monkeypatch.setattr(ai_model_file.time, "monotonic", lambda: clock[0])

    def authority():
        checks.append(clock[0])
        return changed.is_set()

    with path.open("rb") as handle:
        class ObservedRead:
            def __getattr__(self, name):
                return getattr(handle, name)

            def read(self, amount):
                block = handle.read(amount)
                reads.append(clock[0])
                clock[0] += 0.009
                if signal == "immediate":
                    immediate.set()
                elif (signal == "authority" and len(reads) == 1) or (
                    signal == "at_eof" and not block
                ):
                    changed.set()
                return block

        probe = ai_model_file.ReadAuthority(authority, immediate=immediate.is_set)
        with pytest.raises(ModelError, match="model_" + (
            "timeout" if signal == "deadline" else "cancelled"
        )):
            ai_model_file.verify_stream(
                ObservedRead(), entry, cancel=probe,
                deadline=100.024 if signal == "deadline" else float("inf"),
            )
    if signal == "immediate":
        assert len(reads) == 1
    elif signal == "authority":
        assert clock[0] - 100.009 < 0.101
        assert len(checks) < len(reads)
    elif signal == "deadline":
        assert len(reads) == 3
    else:
        assert len(reads) == 14 and changed.is_set()


def test_read_authority_never_caches_dispatch_or_publication_authority(monkeypatch):
    monkeypatch.setattr(ai_model_file.time, "monotonic", lambda: 100.0)
    denied = threading.Event()
    probe = ai_model_file.ReadAuthority(denied.is_set)
    assert not probe.reading()
    denied.set()
    # Same clock tick: only internal file-read polling may coalesce its probe.
    assert probe() is True


def test_expensive_source_check_does_not_turn_each_hash_chunk_into_another_audit(monkeypatch):
    clock, calls = [100.0], []
    stopped = threading.Event()
    monkeypatch.setattr(ai_model_file.time, "monotonic", lambda: clock[0])

    def authority():
        calls.append(clock[0])
        clock[0] += 0.140  # A document audit can exceed even the new poll interval.
        return False

    probe = ai_model_file.ReadAuthority(authority, immediate=stopped.is_set)
    assert not probe.reading()
    for _ in range(10):
        clock[0] += 0.001
        assert not probe.reading()
    assert len(calls) == 1
    clock[0] += 0.091
    assert not probe.reading() and len(calls) == 2
    stopped.set()
    assert probe.reading() is True
    assert len(calls) == 2
