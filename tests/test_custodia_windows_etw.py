"""Exercise recorder ownership and failure retention without a native AI run."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location(
        "custodia_windows_etw", ROOT / "scripts/custodia_windows_etw.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def runtime():
    return SimpleNamespace(loaded=True, _process=SimpleNamespace(pid=81), _request_id="a" * 32)


def test_recorder_does_not_stop_foreign_or_failed_start(tmp_path):
    calls = []

    def refused(command):
        calls.append(command)
        raise RuntimeError("another recorder owns the session")

    capture = module().SchedulerCapture(tmp_path, invoke=refused, snapshot=lambda: [])
    with pytest.raises(RuntimeError, match="another recorder"):
        capture.start(0, runtime())
    capture.stop(runtime())
    assert len(calls) == 1 and calls[0][0] == "-start"
    assert capture.active is None and not capture.sessions


def test_fixed_window_preserves_bytes_identity_and_blocks_repeat(tmp_path):
    calls = []

    def invoke(command):
        calls.append(command)
        if command[0] == "-stop":
            Path(command[1]).write_bytes(b"synthetic trace, not native evidence")

    capture = module().SchedulerCapture(
        tmp_path, invoke=invoke, snapshot=lambda: [{"pid": 81, "tid": 92}])
    capture.start(0, runtime())
    capture.stop(runtime())
    assert [row[0] for row in calls] == ["-start", "-stop"]
    assert capture.sessions[0]["status"] == "OBSERVED"
    assert capture.sessions[0]["worker_pid_before"] == 81
    assert capture.sessions[0]["request"] == "a" * 32
    assert (tmp_path / "scheduler/sessions.json").is_file()
    with pytest.raises(RuntimeError, match="Repeated"):
        capture.start(0, runtime())


def test_stop_failure_is_retained_and_never_called_twice(tmp_path):
    def invoke(command):
        if command[0] == "-stop":
            raise RuntimeError("stop rejected")

    capture = module().SchedulerCapture(tmp_path, invoke=invoke, snapshot=lambda: [])
    capture.start(0, runtime())
    with pytest.raises(RuntimeError, match="stop rejected"):
        capture.stop(runtime())
    assert capture.sessions[0]["status"] == "STOP_FAILED"
    assert capture.active is None
    capture.stop(runtime())
    assert len(capture.sessions) == 1
