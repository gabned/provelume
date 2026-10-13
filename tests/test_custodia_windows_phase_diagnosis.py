"""Check observer transparency and preserved failures without loading a model."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def harness():
    spec = importlib.util.spec_from_file_location(
        "custodia_phase_diagnosis", ROOT / "scripts/diagnose_custodia_windows.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wrapper_preserves_return_exception_and_cpu_wall_span():
    module = harness()

    class Target:
        @staticmethod
        def work(value):
            if value is None:
                raise ValueError("original error")
            return value

    module.wrap(Target, "work", "test")
    marker = object()
    assert Target.work(marker) is marker
    with pytest.raises(ValueError, match="original error"):
        Target.work(None)
    assert len(module._rows) == 2
    for row in module._rows:
        for field in ("wall_ns", "performance_ns", "cpu_ns", "thread_cpu_ns"):
            assert row["end"][field] >= row["start"][field]
        assert row["end"]["performance_ns"] > row["start"]["performance_ns"]


def test_worker_keeps_ipc_messages_and_correlates_first_decode(tmp_path, monkeypatch):
    from provelume import ai_llama, ai_model_file, ai_runtime_worker

    module = harness()
    messages = []
    request = "a" * 32
    # Register originals with monkeypatch before the harness installs wrappers.
    for target, name in [(ai_model_file, "verify_stream"),
                         (module.hashlib, "file_digest"), (ai_llama.Llama, "generate")]:
        monkeypatch.setattr(target, name, getattr(target, name))
    monkeypatch.setattr(ai_runtime_worker, "verify_stream", ai_runtime_worker.verify_stream)
    monkeypatch.setattr(ai_runtime_worker, "read", lambda: {"request": request})
    monkeypatch.setattr(ai_runtime_worker, "emit", messages.append)

    def fake_init(engine):
        engine.decode = lambda *args: 17

    monkeypatch.setattr(ai_llama.Llama, "__init__", fake_init)
    module.install_worker(tmp_path)
    assert ai_runtime_worker.read() == {"request": request}
    engine = ai_llama.Llama()
    before = {"event": "prefill", "phase": "native_prefill", "request": request, "pid": 1}
    first = {"event": "first", "seconds": 0.25}
    result = {"event": "result", "text": "synthetic"}
    ai_runtime_worker.emit(before)
    assert engine.decode(None) == 17
    ai_runtime_worker.emit(first)
    ai_runtime_worker.emit(result)
    assert messages == [before, first, result]
    rows = [json.loads(line) for line in next(tmp_path.glob("worker-*.jsonl")).read_text()
            .splitlines()]
    for phase in ("worker.request_read", "native.prefill_decode", "worker.emit.first"):
        matched = [row for row in rows if row["phase"] == phase]
        assert len(matched) == 1 and matched[0]["request"] == request
    assert all("text" not in row and "prompt" not in row for row in rows)
