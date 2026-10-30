from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from contextlib import suppress

import pytest

from provelume.startup_readiness import StartupSecrets

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows event and Job contract")


def test_windows_job_owns_descendants_and_escalation_leaves_no_process(tmp_path):
    from provelume.startup_windows import OwnedWindowsControl

    material = StartupSecrets("ab" * 16, os.urandom(32))
    control = OwnedWindowsControl()
    marker = tmp_path / "synthetic-ready.txt"
    grandchild = (
        "import os,pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));"
        "time.sleep(60)"
    )
    script = (
        "import subprocess,sys,time;sys.stdin.buffer.read(1);"
        "subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "close_fds=True);time.sleep(60)"
    )
    process = None
    try:
        control.prepare(material.stop_event_name())
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(marker), grandchild],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        control.assign(process)
        process.stdin.write(b"x")
        process.stdin.close()
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert marker.is_file()
        # Windows venv redirectors may add a third process. Verify the actual
        # acknowledged grandchild against this exact Job, not a fixed count.
        assert control.process_count() >= 2
        from ctypes import wintypes as w

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
        kernel.IsProcessInJob.restype = w.BOOL
        kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, int(marker.read_text()))
        assert handle
        try:
            member = w.BOOL()
            assert kernel.IsProcessInJob(handle, control._job, ctypes.byref(member))
            assert member.value
        finally:
            assert kernel.CloseHandle(handle)
        control.terminate()
        process.wait(timeout=2)
        deadline = time.monotonic() + 2
        while not control.empty() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert control.empty()
    finally:
        with suppress(OSError):
            control.terminate()
        if process is not None:
            with suppress(OSError, subprocess.TimeoutExpired):
                process.wait(timeout=2)
            process.stdin.close()
        control.close()


def test_windows_private_stop_signal_requests_cooperative_server_exit():
    from provelume.startup_windows import ChildStopSignal, OwnedWindowsControl

    material = StartupSecrets("cd" * 16, os.urandom(32))
    name = material.stop_event_name()
    control = OwnedWindowsControl()
    signal = None

    class Server:
        should_exit = False

        def run(self):
            deadline = time.monotonic() + 2
            while not self.should_exit and time.monotonic() < deadline:
                time.sleep(0.025)
            assert self.should_exit

    try:
        control.prepare(name)
        signal = ChildStopSignal(name)
        control.request_stop()
        assert signal.run(Server())
        assert control.empty()
    finally:
        if signal is not None:
            signal.close()
        control.close()
