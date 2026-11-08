"""Native qualification errors retain a closed phase without private exception text."""

import json

import pytest

from provelume.mirror_contract import MirrorError
from provelume.mirror_rsync_windows_qualification import (
    WindowsComponentsFailure,
    local_copy_diagnostics,
    qualification_phase,
)


def test_synthetic_native_exit_retains_code_and_hashes_with_fixture_paths_removed(tmp_path):
    from pathlib import Path

    root, directory = Path("C:/synthetic-root"), Path("D:/synthetic-tools")
    stderr = (b"rsync: receiver failed: C:/synthetic-root/output\n"
              b"rsync: fork: Resource temporarily unavailable (11)\n"
              b"rsync error: error in IPC code (code 14)\n")
    detail = local_copy_diagnostics(14, b"", stderr, root=root, directory=directory)
    assert detail["exit_code"] == 14 and detail["stderr_bytes"] == len(stderr)
    assert "Resource temporarily unavailable" in detail["synthetic_stderr_redacted"]
    assert "synthetic-root" not in json.dumps(detail)
    original = MirrorError("ssh_command_failed")
    original.local_copy_evidence = detail
    with (
        pytest.raises(WindowsComponentsFailure) as caught,
        qualification_phase("native_local_copy"),
    ):
        raise original
    assert caught.value.evidence["synthetic_local_copy"] == detail


@pytest.mark.parametrize("kind", [OSError, ValueError, KeyError, TypeError])
def test_native_failure_exposes_phase_and_type_without_exception_message(kind):
    with (
        pytest.raises(WindowsComponentsFailure) as caught,
        qualification_phase("native_version"),
    ):
        raise kind("synthetic-private-path-and-secret")
    assert caught.value.code == "rsync_windows_qualification"
    evidence = caught.value.evidence
    assert evidence["schema"] == "concordia-rsync-windows-components-failure/v1"
    assert evidence["phase"] == "native_version" and evidence["exception"] == kind.__name__
    assert evidence["temporary_role"] == "not_transport_temporary"
    assert all(set(frame) == {"module", "function", "line"} for frame in evidence["frames"])
    assert "private" not in json.dumps(caught.value.evidence)


def test_native_sharing_failure_identifies_temporary_role_without_its_path():
    failure = PermissionError(13, "synthetic-private-error", "/synthetic-private/session.err")
    with (
        pytest.raises(WindowsComponentsFailure) as caught,
        qualification_phase("native_local_copy"),
    ):
        raise failure
    assert caught.value.evidence["temporary_role"] == "stderr"
    assert "private" not in json.dumps(caught.value.evidence)


def test_native_failure_preserves_original_closed_code_and_containment_evidence():
    original = MirrorError("git_containment")
    original.containment_evidence = {"operation": "CreateProcessW", "native_error": 5}
    with (
        pytest.raises(WindowsComponentsFailure) as caught,
        qualification_phase("native_local_copy"),
    ):
        raise original
    assert caught.value.code == "git_containment"
    assert caught.value.evidence["containment"] == original.containment_evidence


def test_windows_cleanup_waits_for_all_descendants_before_releasing_job(monkeypatch):
    import ctypes
    from contextlib import ExitStack

    from provelume import mirror_git_windows as native

    class Kernel:
        observations = 0

        def TerminateJobObject(self, _job, _code):
            return True

        def WaitForSingleObject(self, _process, timeout):
            assert 0 <= timeout <= 2000
            return 0  # Parent already exited; descendants still own output handles.

        def QueryInformationJobObject(self, _job, kind, output, size, _returned):
            assert kind == 1 and size == 48
            self.observations += 1
            ctypes.cast(output, ctypes.POINTER(native.JobAccounting)).contents.active = (
                1 if self.observations < 3 else 0)
            return True

    kernel = Kernel()
    monkeypatch.setattr(native, "libraries", lambda: (kernel,))
    process = native.WindowsGitProcess.__new__(native.WindowsGitProcess)
    process.handle, process.job, process.resources = 1, 2, ExitStack()
    released = []
    process.resources.callback(lambda: released.append(kernel.observations))
    process.close()
    assert released == [3] and process.handle is process.job is None


@pytest.mark.parametrize("code,expires,windows", [(32, False, True), (5, False, True),
                                                 (32, True, True), (32, False, False)])
def test_temporary_cleanup_confirms_removal_within_original_budget(
    monkeypatch, code, expires, windows
):
    from provelume import mirror_ssh_runtime as native

    error = PermissionError(13, "synthetic")
    error.winerror = code

    class Temporary:
        calls = 0

        def unlink(self, *, missing_ok):
            assert missing_ok
            self.calls += 1
            if self.calls < 3:
                raise error

    path, waits = Temporary(), []
    monkeypatch.setattr(native.time, "monotonic", lambda: 1)
    monkeypatch.setattr(native.time, "sleep", waits.append)
    if code == 32 and not expires and windows:
        native._unlink_temporary(path, deadline=2, windows=windows)
        assert path.calls == 3 and waits == [0.01, 0.01]
    else:
        with pytest.raises(PermissionError) as caught:
            native._unlink_temporary(path, deadline=0 if expires else 2, windows=windows)
        assert caught.value is error and path.calls == 1 and waits == []
