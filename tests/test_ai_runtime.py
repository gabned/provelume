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
import sys,socket,os,json,ctypes
sys.path.insert(0,sys.argv[1])
from provelume.ai_runtime_limits import contain
_,limits=contain()
observed=[]
for call in (lambda:socket.socket(),lambda:os.fork()):
    try: call()
    except PermissionError: observed.append('denied')
libc=ctypes.CDLL(None,use_errno=True)
for number in (0x40000029,425,426,427):
    assert libc.syscall(number,0,0,0,0,0,0)==-1 and ctypes.get_errno()==1
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


def test_frozen_launcher_and_unsupported_hardware_fail_closed(monkeypatch):
    from provelume import ai_runtime_contract as contract

    monkeypatch.setattr(contract.sys, "frozen", True, raising=False)
    with pytest.raises(ModelError, match="compatibility"):
        contract.hardware()
    monkeypatch.setattr(contract.sys, "frozen", False)
    monkeypatch.setattr(contract.platform, "machine", lambda: "arm64")
    with pytest.raises(ModelError, match="compatibility"):
        contract.hardware()


@pytest.mark.skipif(sys.platform not in ("linux", "win32"), reason="native supported OS only")
def test_native_os_memory_ceiling_cannot_allocate_four_gibibytes():
    code = '''
import sys,ctypes,mmap,json,os
sys.path.insert(0,sys.argv[1])
from provelume.ai_runtime_limits import contain
job,limits=contain()
if os.name=='nt':
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.VirtualAlloc.restype=ctypes.c_void_p
    k.VirtualAlloc.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_ulong,ctypes.c_ulong]
    denied=not k.VirtualAlloc(None,4*1024**3,0x3000,4)
else:
    try: mmap.mmap(-1,4*1024**3);denied=False
    except (OSError,MemoryError): denied=True
print(json.dumps({'denied':denied,'limit':limits['memory_bytes']}))
'''
    import sysconfig

    # Base interpreter avoids Windows' redirector. Trusted package paths only.
    code = code.replace("sys.path.insert(0,sys.argv[1])", "sys.path[:0]=sys.argv[1:3]")
    result = subprocess.run([getattr(sys, "_base_executable", sys.executable), "-I", "-c", code,
                             str(Path(__file__).resolve().parents[1] / "core"),
                             sysconfig.get_path("purelib")],
                            capture_output=True, timeout=10, check=True)
    assert json.loads(result.stdout) == {"denied": True, "limit": 3 * 1024**3}


def test_measurement_report_never_promotes_missing_or_failed_observations():
    from scripts.ai_runtime_report import evaluate

    report = evaluate({"samples": [], "failures": []})
    assert report["status"] == "BLOCKED"
    assert set(report["gates"].values()) == {"NOT_RUN"}
    report["cancel_load"] = {"seconds": 2.1, "worker_absent": True, "code": "cancelled"}
    assert evaluate(report)["status"] == "FAIL"


def test_native_library_change_invalidates_lifecycle_evidence_and_closes_runner(
    tmp_path, model, monkeypatch,
):
    from provelume.ai_model_store import ModelStore, SelfTestEvidence

    store = ModelStore(tmp_path / "store")
    selection = runtime.native_selection()
    runner = runtime.LocalRuntime(tmp_path / "native")
    evidence = SelfTestEvidence(MODEL_ID, store._binding(model.entry, selection),
                                "PASSED", time.monotonic() + 60)
    store._evidence[MODEL_ID] = evidence
    store._native_runners[MODEL_ID] = runner
    closed = []
    monkeypatch.setattr(runner, "close", lambda: closed.append(True))

    def changed():
        raise ModelError("integrity")

    monkeypatch.setattr(runner, "validate_installation", changed)
    with pytest.raises(ModelError, match="stale"):
        store._admit_evidence(model.entry, selection, evidence)
    assert MODEL_ID not in store._evidence and closed == [True]
    # Restoring library bytes cannot resurrect the old self-test object.
    monkeypatch.setattr(runner, "validate_installation", lambda: None)
    with pytest.raises(ModelError, match="stale"):
        store._admit_evidence(model.entry, selection, evidence)


def test_native_evidence_requires_same_configuration_and_current_admission(tmp_path, model):
    from provelume.ai_model_store import ModelStore, SelfTestEvidence

    store = ModelStore(tmp_path / "store")
    selection = runtime.native_selection()
    evidence = SelfTestEvidence(MODEL_ID, store._binding(model.entry, selection),
                                "PASSED", time.monotonic() + 60)
    store._evidence[MODEL_ID] = evidence
    for changed in (dataclasses.replace(selection, configuration=b"{}"), selection):
        with pytest.raises(ModelError, match="stale"):
            store._admit_evidence(model.entry, changed, evidence)
    store.allowed_ids = ()
    with pytest.raises(ModelError, match="revoked"):
        store._entry(MODEL_ID, selection)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows Job Object only")
def test_windows_job_refuses_descendant_process():
    import sysconfig

    code = '''
import sys,subprocess,json
sys.path[:0]=sys.argv[1:3]
from provelume.ai_runtime_limits import contain
job,limits=contain()
try:
    child=subprocess.Popen([sys.executable,'-I','-c','pass'])
except OSError:
    denied=True
else:
    child.wait(timeout=2)
    denied=False
print(json.dumps({'denied':denied,'processes':limits['processes']}))
'''
    result = subprocess.run([getattr(sys, "_base_executable", sys.executable), "-I", "-c", code,
                             str(Path(__file__).resolve().parents[1] / "core"),
                             sysconfig.get_path("purelib")],
                            capture_output=True, timeout=10, check=True)
    assert json.loads(result.stdout) == {
        "denied": True, "processes": "JobObject:active-process:1"}


@pytest.mark.skipif(sys.platform != "linux", reason="native Linux file descriptor ceiling")
def test_snapshots_release_source_ancestor_descriptors_under_native_limit(tmp_path):
    import hashlib

    directory = tmp_path / "a/b/c/d/e/f/g/h"
    directory.mkdir(parents=True)
    for n in range(8):
        (directory / str(n)).write_bytes(b"synthetic")
    code = '''
import sys,os,hashlib
from pathlib import Path
from contextlib import ExitStack
sys.path.insert(0,sys.argv[1])
from provelume.ai_runtime_limits import contain
from provelume.ai_runtime_worker import pinned_input,sealed_snapshot
contain()
paths=[]
with ExitStack() as stack:
    for path in Path(sys.argv[2]).iterdir():
        with pinned_input(stack,path) as stream:
            paths.append(sealed_snapshot(stack,stream,9,sys.argv[3]))
    assert len(os.listdir('/proc/self/fd')) < 32
    assert all(Path(p).read_bytes()==b'synthetic' for p in paths)
'''
    subprocess.run([sys.executable, "-I", "-c", code,
                    str(Path(__file__).resolve().parents[1] / "core"), str(directory),
                    hashlib.sha256(b"synthetic").hexdigest()], check=True, timeout=10)
