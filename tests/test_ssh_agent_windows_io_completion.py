"""Portable Win32 API contract tests; actual private IPC remains in native CI."""

import ctypes
from types import SimpleNamespace

import pytest

from provelume.mirror_contract import MirrorError, require
from provelume.mirror_ssh_agent_server import WindowsPipe


def pipe_fixture(monkeypatch, *, immediate_error=None, expires=False):
    class Operation(ctypes.Structure):
        _fields_ = [("event", ctypes.c_void_p)]

    calls = []
    expired = [False]

    def start(*_args):
        return False

    def wait(*_args):
        if expires:
            expired[0] = True
            return 258
        return 0

    def result(_handle, _operation, count, blocking):
        calls.append("drain" if blocking else "result")
        assert immediate_error is None, "No pending I/O owns this failed operation"
        count._obj.value = 4
        return True

    pipe = WindowsPipe.__new__(WindowsPipe)
    pipe.handle, pipe.overlapped = 101, Operation
    pipe.check = lambda: require(not expired[0], "ssh_agent_deadline")
    pipe.api = SimpleNamespace(
        CreateEventW=lambda *_: 202,
        ReadFile=start,
        WriteFile=start,
        ConnectNamedPipe=start,
        WaitForSingleObject=wait,
        GetOverlappedResult=result,
        CancelIoEx=lambda *_: calls.append("cancel"),
        CloseHandle=lambda event: calls.append(("close", event)),
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: immediate_error or 997, raising=False)
    return pipe, calls


@pytest.mark.parametrize("function,error", [("ReadFile", 109), ("WriteFile", 5), ("connect", 535)])
def test_immediate_pipe_failure_or_already_connected_has_no_pending_result(
    monkeypatch, function, error
):
    pipe, calls = pipe_fixture(monkeypatch, immediate_error=error)
    if function == "connect":
        assert pipe.operation(function) == 0
    else:
        with pytest.raises(MirrorError, match="ssh_agent_pipe"):
            pipe.operation(function)
    assert calls == [("close", 202)]


def test_pending_io_retains_cancellation_and_drain_before_freeing_its_event(monkeypatch):
    pipe, calls = pipe_fixture(monkeypatch)
    assert pipe.operation("ReadFile") == 4
    assert calls == ["result", "cancel", "drain", ("close", 202)]


def test_expired_pending_io_still_cancels_and_drains_before_freeing_its_event(monkeypatch):
    pipe, calls = pipe_fixture(monkeypatch, expires=True)
    with pytest.raises(MirrorError, match="ssh_agent_deadline"):
        pipe.operation("ReadFile")
    assert calls == ["cancel", "drain", ("close", 202)]
