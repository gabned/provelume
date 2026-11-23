"""WinSock adapter ownership and unchanged binary stream paths."""

import ctypes
import socket
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace

import pytest

from provelume import mirror_rsync_rsh as rsh
from provelume.mirror_contract import MirrorError


@pytest.mark.parametrize("duplicate_fails", [False, True])
def test_windows_socket_does_not_close_borrowed_stream(monkeypatch, duplicate_fails):
    events = []
    duplicate = SimpleNamespace(setblocking=lambda mode: events.append(("blocking", mode)))
    handle = 17

    def share(pid):
        assert pid == rsh.os.getpid()
        events.append("share")
        return b"synthetic-protocol-information"

    borrowed = SimpleNamespace(share=share, detach=lambda: events.append("detach"))

    @contextmanager
    def fromshare(record):
        assert record == b"synthetic-protocol-information"
        if duplicate_fails:
            raise OSError("duplicate failed")
        try:
            yield duplicate
        finally:
            events.append("close owned duplicate")

    def wrap(*, fileno):
        assert fileno == handle
        return borrowed

    monkeypatch.setattr(rsh.socket, "socket", wrap)
    monkeypatch.setattr(rsh.socket, "fromshare", fromshare, raising=False)
    with ExitStack() as files:
        if duplicate_fails:
            with pytest.raises(OSError, match="duplicate failed"):
                rsh.duplicate_windows_socket(files, handle)
        else:
            assert rsh.duplicate_windows_socket(files, handle) is duplicate
        expected = (
            ["share", "detach"] if duplicate_fails else ["share", ("blocking", False), "detach"]
        )
        assert events == expected
    assert events == (expected if duplicate_fails else [*expected, "close owned duplicate"])


def test_winsock_recv_and_send_preserve_binary_bytes_and_existing_deadline():
    blob = b"\x00\x1a\r\n\xff"
    left, right = socket.socketpair()
    with left, right:
        deadline = rsh.time.monotonic() + 2
        send = rsh.socket_io(left, deadline, sending=True)
        recv = rsh.socket_io(right, deadline, sending=False)
        assert send(blob) == len(blob) and recv(len(blob)) == blob
        expired = rsh.socket_io(right, rsh.time.monotonic() - 1, sending=False)
        with pytest.raises(MirrorError, match="deadline"):
            expired(len(blob))


def test_posix_adapter_routes_standard_fds_without_socket_admission(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(rsh.os, "name", "posix")
        patch.setattr(rsh.os, "read", lambda fd, count: (fd, count))
        patch.setattr(rsh.os, "write", lambda fd, data: (fd, data))
        with rsh.inherited_streams({}, {}, 1) as (read, write, errors):
            assert read(64) == (0, 64) and write(b"binary") == (1, b"binary")
            assert errors is rsh.sys.stderr


def test_windows_non_socket_standard_pipes_keep_crt_binary_path(monkeypatch):
    import sys

    from provelume import ai_windows_api

    def duplicate(_source_process, source, _destination_process, output, *_options):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = source + 100
        return True

    kernel = SimpleNamespace(
        GetCurrentProcess=lambda: 1000,
        GetStdHandle=lambda identifier: -identifier,
        GetFileType=lambda source: 1 if source == 12 else 3,
        DuplicateHandle=duplicate,
    )
    opened = []

    @contextmanager
    def open_binary(descriptor, mode, *, buffering):
        opened.append((descriptor, mode, buffering))
        yield SimpleNamespace(fileno=lambda: descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(rsh.os, "name", "nt")
        patch.setattr(rsh.os, "O_BINARY", 0x8000, raising=False)
        patch.setattr(rsh.os, "fdopen", open_binary)
        patch.setattr(rsh.os, "read", lambda fd, count: (fd, count))
        patch.setattr(rsh.os, "write", lambda fd, data: (fd, data))
        patch.setattr(ai_windows_api, "libraries", lambda: (kernel,))
        patch.setattr(rsh, "socket_kind", lambda _source: "NOT_SOCKET")
        patch.setitem(sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=lambda h, _mode: h))
        kinds, checks = {}, {}
        with rsh.inherited_streams(kinds, checks, 1) as (read, write, errors):
            assert read(64) == (110, 64) and write(b"binary") == (111, b"binary")
            assert errors.fileno() == 112
        assert kinds == {"stdin": "PIPE", "stdout": "PIPE", "stderr": "DISK"}
        assert checks == {"stdin": "NOT_SOCKET", "stdout": "NOT_SOCKET"}
    assert opened == [(110, "rb", 0), (111, "wb", 0), (112, "wb", 0)]
