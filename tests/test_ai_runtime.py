"""Synthetic supervisor contracts; real inference belongs to the explicit native workflow."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from provelume import ai_runtime as runtime
from provelume.ai_model_file import VerifiedModelFile, verify_stream
from provelume.ai_model_store import VerifiedModel
from provelume.ai_models import ModelError, ModelRegistry
from provelume.ai_runtime_contract import CONFIGURATION, MODEL_ID, MODEL_SHA256, runtime_lock
from provelume.service import ProvelumeInstance

SCRIPT = '''
import sys,json,time,os
json.loads(sys.stdin.readline())
print(json.dumps({'event':'loaded','seconds':0.01,'pid':os.getpid(),'memory':{},'limits':{}}),flush=True)
for line in sys.stdin:
    p=json.loads(line)['prompt']
    if p=='hang': time.sleep(120)
    if p=='crash': os._exit(7)
    if p=='malformed': print('not JSON',flush=True);time.sleep(120)
    if p=='oversized': print('x'*40000,flush=True);time.sleep(120)
    print(json.dumps({'event':'result','text':'ORCHID','seconds':0.01,'memory':{}}),flush=True)
'''


@pytest.fixture
def model(tmp_path):
    entry = ModelRegistry.packaged().entry(MODEL_ID)
    return VerifiedModel(entry, VerifiedModelFile(tmp_path / "model", entry.model_size,
                                                entry.model_sha256), b"")


@pytest.fixture
def host(tmp_path, monkeypatch):
    original = subprocess.Popen

    def process(command, **kwargs):
        return original([getattr(sys, "_base_executable", sys.executable),
                         "-I", "-c", SCRIPT], **kwargs)

    monkeypatch.setattr(runtime.subprocess, "Popen", process)
    monkeypatch.setattr(runtime, "hardware", lambda: {})
    monkeypatch.setattr(runtime.LocalRuntime, "validate_installation", lambda self: None)
    host = runtime.LocalRuntime(tmp_path)
    yield host
    host.close()


def test_candidate_and_shipped_runtime_lock_have_no_execution_authority():
    entry = ModelRegistry.packaged().entry(MODEL_ID)
    assert entry.qualification == "CANDIDATE_NOT_QUALIFIED"
    assert entry.model_sha256 == MODEL_SHA256
    assert entry.model_size == 1117320736
    assert entry.profile.model == MODEL_ID
    assert runtime_lock()["version"] == "b11379"
    assert set(runtime_lock()["platforms"]) == {"windows", "linux"}
    assert CONFIGURATION["queue"] == 0
    assert ProvelumeInstance.ai_execution_status()["enabled"] is False


@pytest.mark.parametrize("field,value", [
    ("id", "onnx"), ("version", "other"), ("format", "pickle"),
    ("platform", "darwin"), ("app_version", "0.12.0"), ("configuration", b"{}"),
])
def test_closed_runtime_matrix(field, value):
    selection = dataclasses.replace(runtime.native_selection(), **{field: value})
    with pytest.raises(ModelError, match="compatibility"):
        selection.validate(ModelRegistry.packaged().entry(MODEL_ID))


def test_lazy_reuse_unload_and_next_explicit_caller(host, model):
    assert not host.loaded
    first = host._infer(model, runtime.native_selection(), "first")
    second = host._infer(model, runtime.native_selection(), "second")
    assert first["cold"] and not second["cold"]
    assert first["load"]["pid"] == second["load"]["pid"]
    stale_timer = host._timer
    third = host._infer(model, runtime.native_selection(), "third")
    host._idle(stale_timer)
    assert host.loaded and third["load"]["pid"] == first["load"]["pid"]
    host.close()
    assert not host.loaded
    assert host._infer(model, runtime.native_selection(), "again")["cold"]


@pytest.mark.parametrize("kind", ["crash", "malformed", "oversized", "hang"])
def test_faults_cleanup_no_retry_and_following_caller(host, model, kind):
    began = time.monotonic()
    with pytest.raises(ModelError):
        host._infer(model, runtime.native_selection(), kind,
                    cancel=lambda: time.monotonic() - began > 0.3)
    assert time.monotonic() - began < 2
    assert not host.loaded
    assert host._infer(model, runtime.native_selection(), "next")["text"] == "ORCHID"


@pytest.mark.parametrize("stage", ["construct", "reader_start"])
def test_construction_start_failure_releases_slot(host, model, monkeypatch, stage):
    target, attribute = ((runtime.subprocess, "Popen") if stage == "construct" else
                         (runtime.threading.Thread, "start"))
    original = getattr(target, attribute)

    def broken(*args, **kwargs):
        raise OSError("synthetic-private-failure-detail")

    monkeypatch.setattr(target, attribute, broken)
    with pytest.raises(ModelError) as raised:
        host._infer(model, runtime.native_selection(), "hello")
    assert "private" not in str(raised.value)
    assert not host.loaded
    monkeypatch.setattr(target, attribute, original)
    assert host._infer(model, runtime.native_selection(), "next")["text"] == "ORCHID"


def test_global_process_ceiling_has_no_queue(host, model, tmp_path):
    host._infer(model, runtime.native_selection(), "one")
    other = runtime.LocalRuntime(tmp_path)
    try:
        with pytest.raises(ModelError, match="busy"):
            other._infer(model, runtime.native_selection(), "two")
        assert host.loaded
        host.close()
        assert other._infer(model, runtime.native_selection(), "three")["text"] == "ORCHID"
    finally:
        other.close()


@pytest.mark.parametrize("prompt", ["", "x" * 4097, "<|im_start|>", "<|im_end|>"])
def test_input_refused_before_worker(host, model, prompt):
    with pytest.raises(ModelError, match="limit"):
        host._infer(model, runtime.native_selection(), prompt)
    assert not host.loaded


def test_cancel_before_start_and_no_implicit_install(host, model):
    with pytest.raises(ModelError, match="cancelled"):
        host._infer(model, runtime.native_selection(), "hello", cancel=lambda: True)
    assert not host.loaded
    with pytest.raises(ModelError, match="consent"):
        host.qualify(None, "hello")


def test_gguf_verification_streams_bounded_chunks_and_rejects_changes(tmp_path):
    raw = b"GGUF\x03\0\0\0" + b"x" * (2 * 1024 * 1024)
    path = tmp_path / "model"
    path.write_bytes(raw)
    entry = SimpleNamespace(model_size=len(raw), model_sha256=hashlib.sha256(raw).hexdigest())
    with path.open("rb") as stream:
        verify_stream(stream, entry)
    path.write_bytes(raw[:-1] + b"y")
    with path.open("rb") as stream, pytest.raises(ModelError, match="integrity"):
        verify_stream(stream, entry)


@pytest.mark.skipif(sys.platform != "linux", reason="native Linux seccomp only")
def test_linux_os_limits_deny_network_and_process_creation():
    code = '''
import sys,socket,os,json
sys.path.insert(0,sys.argv[1])
from provelume.ai_runtime_limits import contain
_,limits=contain()
observed=[]
for call in (lambda:socket.socket(),lambda:os.fork()):
    try: call()
    except PermissionError: observed.append('denied')
print(json.dumps({'denied':observed,'limits':limits}))
'''
    result = subprocess.run([sys.executable, "-I", "-c", code,
                             str(Path(__file__).resolve().parents[1] / "core")],
                            capture_output=True, timeout=5, check=True)
    assert json.loads(result.stdout)["denied"] == ["denied", "denied"]


def test_failed_termination_keeps_process_ownership_and_global_slot(monkeypatch, tmp_path):
    host = runtime.LocalRuntime(tmp_path)
    assert runtime._SLOT.acquire(blocking=False)
    host._slot = True
    alive = True

    def wait(**kwargs):
        if alive:
            raise subprocess.TimeoutExpired("synthetic-worker", 2)

    worker = SimpleNamespace(pid=1, poll=lambda: None if alive else 0,
                             kill=lambda: None, wait=wait,
                             stdin=SimpleNamespace(close=lambda: None),
                             stdout=SimpleNamespace(close=lambda: None))
    host._process = worker
    if sys.platform != "win32":
        monkeypatch.setattr(runtime.os, "killpg", lambda *args: None)
    try:
        with pytest.raises(ModelError, match="busy"):
            host.close()
        assert host._process is worker and host._slot
        assert not runtime._SLOT.acquire(blocking=False)
    finally:
        alive = False
        host.close()
    assert runtime._SLOT.acquire(blocking=False)
    runtime._SLOT.release()


@pytest.mark.skipif(sys.platform != "linux", reason="native Linux sealed snapshots only")
def test_native_snapshot_is_immutable_and_refuses_source_substitution(tmp_path):
    from contextlib import ExitStack

    from provelume.ai_runtime_worker import sealed_snapshot

    source = tmp_path / "source"
    source.write_bytes(b"bounded synthetic snapshot")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    with ExitStack() as stack, source.open("rb") as stream:
        path = sealed_snapshot(stack, stream, source.stat().st_size, expected)
        source.write_bytes(b"replacement")
        assert Path(path).read_bytes() == b"bounded synthetic snapshot"
        with pytest.raises(PermissionError), open(path, "wb") as out:
            out.write(b"x")
    with ExitStack() as stack, source.open("rb") as stream, pytest.raises(ModelError):
        sealed_snapshot(stack, stream, 26, expected)
