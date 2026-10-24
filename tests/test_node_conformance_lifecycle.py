"""Real owned-handle regression for the shared Node conformance launcher."""

import os
import subprocess
import threading
from pathlib import Path

from test_capture_shell_contract import node


def test_completed_node_does_not_wait_for_a_parent_owned_stdout_writer(monkeypatch):
    original = subprocess.Popen._get_handles
    held = []
    lock = threading.Lock()
    observations = {"duplicated": 0, "released_by_fallback": False}

    def release(*, fallback=False):
        with lock:
            observations["released_by_fallback"] |= fallback
            while held:
                handle = held.pop()
                if os.name == "nt":
                    import _winapi

                    _winapi.CloseHandle(handle)
                else:
                    os.close(handle)

    def duplicate_stdout(process, stdin, stdout, stderr):
        handles = original(process, stdin, stdout, stderr)
        executable = Path(process.args[0]).name.lower()
        if executable in {"node", "node.exe"}:
            # Keep an additional, noninheritable writer in the owning parent.
            # Apply the same fault to pipe-backed and file-backed transports.
            if os.name == "nt":
                import _winapi

                owner = _winapi.GetCurrentProcess()
                duplicate = _winapi.DuplicateHandle(
                    owner, int(handles[3]), owner, 0, False,
                    _winapi.DUPLICATE_SAME_ACCESS,
                )
            else:
                duplicate = os.dup(handles[3])
            with lock:
                held.append(duplicate)
                observations["duplicated"] += 1
        return handles

    monkeypatch.setattr(subprocess.Popen, "_get_handles", duplicate_stdout)
    # Failure cleanup is finite even for the old Windows communicate() path.
    fallback = threading.Timer(35, lambda: release(fallback=True))
    fallback.daemon = True
    fallback.start()
    try:
        result = node("console.log(JSON.stringify({complete:true}));")
        assert result == {"complete": True}
        assert observations["duplicated"] == 1
        assert observations["released_by_fallback"] is False
        with lock:
            assert len(held) == 1
    finally:
        fallback.cancel()
        release()
        fallback.join(timeout=1)
    assert not held
    assert not fallback.is_alive()
