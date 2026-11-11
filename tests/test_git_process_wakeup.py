import subprocess
from types import SimpleNamespace

import pytest

from provelume import mirror_git_runtime as runtime
from provelume import mirror_git_windows as windows
from provelume.mirror_contract import MirrorError


@pytest.mark.parametrize("oversized", [False, True])
def test_short_lived_git_wakes_early_and_still_checks_final_output(
    tmp_path, monkeypatch, oversized
):
    session = runtime.GitSession(tmp_path)
    waits = []

    class Child:
        pid = 1073741824
        returncode = None

        def __init__(self, output):
            self.output = output
            self.polls = 0

        def poll(self):
            self.polls += 1
            if self.polls > 1:
                self.returncode = 0
            return self.returncode

        def wait(self, *, timeout):
            waits.append(timeout)
            self.output.write(b"Synthetic bounded Git output\n" * (10 if oversized else 1))
            self.output.flush()
            self.returncode = 0
            return 0

        def close(self):
            pass

    popen = runtime.subprocess.Popen

    def start(command, **options):
        if options.get("cwd") != tmp_path:
            return popen(command, **options)
        return Child(options.get("output", options.get("stdout")))

    monkeypatch.setattr(runtime.subprocess, "Popen", start)
    monkeypatch.setattr(windows, "WindowsGitProcess", start)
    kill = getattr(runtime.os, "killpg", None)

    def kill_group(pid, signal):
        if pid != Child.pid and kill is not None:
            return kill(pid, signal)

    monkeypatch.setattr(runtime.os, "killpg", kill_group, raising=False)
    monkeypatch.setattr(
        runtime,
        "time",
        SimpleNamespace(
            monotonic=runtime.time.monotonic,
            sleep=lambda _: pytest.fail(
                "The exited child must wake the monitor before a fixed idle sleep"
            ),
        ),
    )
    if oversized:
        with pytest.raises(MirrorError, match="git_output_limit"):
            session.run(["--version"], payload_limit=64)
    else:
        assert session.run(["--version"], payload_limit=64) == (
            0,
            b"Synthetic bounded Git output\n",
        )
    assert waits == [0.01] and session.commands == 1
    assert not list(tmp_path.glob("*.out")) and not list(tmp_path.glob("*.err"))


@pytest.mark.parametrize("status", [0, 258, 0xFFFFFFFF])
def test_contained_windows_wait_handles_exit_timeout_and_native_failure(monkeypatch, status):
    calls = []
    kernel = SimpleNamespace(
        WaitForSingleObject=lambda handle, milliseconds: (
            calls.append((handle, milliseconds)) or status
        )
    )
    monkeypatch.setattr(windows, "libraries", lambda: (kernel, None, None, None))
    child = windows.WindowsGitProcess.__new__(windows.WindowsGitProcess)
    child.handle = 101
    child.poll = lambda: 7
    if status == 0:
        assert child.wait(timeout=0.01) == 7
    elif status == 258:
        with pytest.raises(subprocess.TimeoutExpired) as error:
            child.wait(timeout=0.01)
        assert error.value.cmd == "contained-git" and error.value.timeout == 0.01
    else:
        with pytest.raises(MirrorError, match="git_containment"):
            child.wait(timeout=0.01)
    assert calls == [(101, 10)]


@pytest.mark.parametrize("timeout", [-1, float("inf"), True])
def test_contained_wait_refuses_invalid_or_unbounded_duration(timeout):
    child = windows.WindowsGitProcess.__new__(windows.WindowsGitProcess)
    child.handle = 101
    with pytest.raises(MirrorError, match="git_containment"):
        child.wait(timeout=timeout)
