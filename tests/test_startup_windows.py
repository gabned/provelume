from __future__ import annotations

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
    control = OwnedWindowsControl(material.stop_event_name())
    marker = tmp_path / "synthetic-ready.txt"
    script = (
        "import pathlib,subprocess,sys,time;sys.stdin.buffer.read(1);"
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "close_fds=True);pathlib.Path(sys.argv[1]).write_text('ready');time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(marker)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        control.assign(process)
        process.stdin.write(b"x")
        process.stdin.close()
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert marker.is_file()
        assert control.process_count() == 2
        control.terminate()
        process.wait(timeout=2)
        deadline = time.monotonic() + 2
        while not control.empty() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert control.empty()
    finally:
        with suppress(OSError):
            control.terminate()
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=2)
        process.stdin.close()
        control.close()


def test_windows_private_stop_signal_requests_cooperative_server_exit():
    from provelume.startup_windows import ChildStopSignal, OwnedWindowsControl

    material = StartupSecrets("cd" * 16, os.urandom(32))
    name = material.stop_event_name()
    control = OwnedWindowsControl(name)
    signal = ChildStopSignal(name)

    class Server:
        should_exit = False

        def run(self):
            deadline = time.monotonic() + 2
            while not self.should_exit and time.monotonic() < deadline:
                time.sleep(0.025)
            assert self.should_exit

    try:
        control.request_stop()
        assert signal.run(Server())
        assert control.empty()
    finally:
        signal.close()
        control.close()
