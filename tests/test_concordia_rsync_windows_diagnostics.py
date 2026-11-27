"""Native qualification errors retain a closed phase without private exception text."""

import json
from hashlib import sha256

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


def test_windows_ssh_gets_private_programdata_not_ambient_config_or_auth(monkeypatch, tmp_path):
    from provelume import mirror_ssh_runtime as native

    monkeypatch.setenv("PROGRAMDATA", "unapproved-host-config")
    monkeypatch.setenv("SSH_AUTH_SOCK", "unapproved-host-agent")
    monkeypatch.setenv("USERPROFILE", "unapproved-host-profile")
    with monkeypatch.context() as windows:
        windows.setattr(native.os, "name", "nt")
        selected = native.environment(tmp_path)
    assert selected["PROGRAMDATA"] == selected["USERPROFILE"] == str(tmp_path)
    assert "SSH_AUTH_SOCK" not in selected
    assert "unapproved" not in json.dumps(selected)


def test_windows_ssh_passes_only_its_unchanged_owned_pipe_to_openssh(monkeypatch):
    from provelume import mirror_ssh_runtime as native

    endpoint = r"\\.\pipe\Provelume-Mirror-Auth-" + "a" * 32
    base = {"PATH": "synthetic"}
    with monkeypatch.context() as windows:
        windows.setattr(native.os, "name", "nt")
        assert native.ssh_environment(base, endpoint) == {**base, "SSH_AUTH_SOCK": endpoint}
        for other in (r"\\.\pipe\openssh-ssh-agent", endpoint.replace("\\", "/")):
            with pytest.raises(MirrorError, match="ssh_agent_containment"):
                native.ssh_environment(base, other)
    assert "SSH_AUTH_SOCK" not in base


@pytest.fixture
def windows_native_session(monkeypatch, tmp_path):
    import os
    from types import SimpleNamespace

    from provelume import mirror_ssh_runtime as native

    for name in ("OPENSSL_CONF", "OPENSSL_CONF_INCLUDE", "OPENSSL_MODULES"):
        monkeypatch.setenv(name, "synthetic-ambient")
    monkeypatch.setattr(
        native, "os", SimpleNamespace(name="nt", environ=os.environ, devnull=os.devnull)
    )
    return native.NativeSession(tmp_path)


def test_windows_rsync_launches_hold_one_config_through_job_cleanup(
    monkeypatch, tmp_path, windows_native_session
):
    from contextlib import contextmanager

    from provelume import mirror_git_windows, mirror_rsync_windows

    actual_guard = mirror_rsync_windows.pinned_openssl_configuration
    held = set()
    launched = []

    @contextmanager
    def observed_guard(path):
        with actual_guard(path) as selected:
            held.add(path)
            try:
                yield selected
            finally:
                held.remove(path)

    class Child:
        returncode = 0

        def __init__(self, arguments, *, cwd, environment, **_stdio):
            launched.append(arguments)
            assert cwd == tmp_path
            if arguments[0].endswith("rsync.exe"):
                configuration = environment["OPENSSL_CONF"]
                assert configuration.startswith("./")
                assert environment["OPENSSL_MODULES"] == configuration
                self.configuration = cwd / configuration
                assert held == {self.configuration}
                assert self.configuration.read_bytes() == mirror_rsync_windows.OPENSSL_CONFIGURATION
                assert not self.configuration.is_dir()
                assert "OPENSSL_CONF_INCLUDE" not in environment
            else:
                self.configuration = None
                assert not held
                assert all(not key.startswith("OPENSSL_") for key in environment)

        def poll(self):
            return self.returncode

        def close(self, *, deadline):
            assert deadline > 0
            if self.configuration is not None:
                assert held == {self.configuration} and self.configuration.is_file()

    monkeypatch.setattr(mirror_rsync_windows, "pinned_openssl_configuration", observed_guard)
    monkeypatch.setattr(mirror_git_windows, "WindowsGitProcess", Child)
    sender, ssh = (str(tmp_path / name) for name in ("rsync.exe", "ssh.exe"))
    invocations = [
        [sender, "--version"],
        [sender, "--checksum", "./Input with space/", "./Output with space/"],
        [sender, "--checksum", "./payload/", "synthetic@host:generation"],
        [ssh, "-V"],
    ]
    for command in invocations:
        assert windows_native_session.run(command) == (0, b"", b"")
        assert not held and not list(tmp_path.iterdir())
    assert launched == invocations
    assert all(not key.startswith("OPENSSL_") for key in windows_native_session.environment)


@pytest.mark.parametrize("damage", ["missing", "changed", "provider-directory"])
def test_windows_rsync_refuses_unverified_configuration_before_child(
    monkeypatch, tmp_path, windows_native_session, damage
):
    from contextlib import contextmanager

    from provelume import mirror_git_windows, mirror_rsync_windows

    actual_guard = mirror_rsync_windows.pinned_openssl_configuration

    @contextmanager
    def changed_guard(path):
        if damage != "changed":
            path.unlink()
        else:
            path.write_bytes(b"different synthetic config")
        if damage == "provider-directory":
            path.mkdir()
            marker = path / "inert.txt"
            marker.write_text("No provider binary")
            try:
                with actual_guard(path) as selected:
                    yield selected
            finally:
                marker.unlink()
                path.rmdir()
        else:
            with actual_guard(path) as selected:
                yield selected

    monkeypatch.setattr(mirror_rsync_windows, "pinned_openssl_configuration", changed_guard)
    monkeypatch.setattr(
        mirror_git_windows,
        "WindowsGitProcess",
        lambda *args, **kwargs: pytest.fail("child launched"),
    )
    with pytest.raises(MirrorError, match="rsync_profile_not_qualified"):
        windows_native_session.run([str(tmp_path / "rsync.exe"), "--version"])
    assert not list(tmp_path.iterdir())


def test_windows_ssh_requires_exact_paired_files_before_component_use(tmp_path, monkeypatch):
    from provelume import mirror_ssh_runtime as native

    binaries = {"ssh.exe": b"pinned synthetic executable", "libcrypto.dll": b"pinned synthetic DLL"}
    for name, content in binaries.items():
        (tmp_path / name).write_bytes(content)
    monkeypatch.setattr(
        native, "WINDOWS_SSH_FILES",
        {name: (len(content), sha256(content).hexdigest()) for name, content in binaries.items()},
    )
    selected = tmp_path / "ssh.exe"
    with native.windows_ssh_component(selected) as proof:
        assert proof["path"] == str(selected)
        assert proof["sha256"] == sha256(binaries["ssh.exe"]).hexdigest()
    (tmp_path / "other.dll").write_bytes(b"unexpected")
    with (
        pytest.raises(MirrorError, match="ssh_profile_not_qualified"),
        native.windows_ssh_component(selected),
    ):
        pytest.fail("extra DLL admitted")
    (tmp_path / "other.dll").unlink()
    (tmp_path / "libcrypto.dll").write_bytes(b"?")
    with (
        pytest.raises(MirrorError, match="ssh_profile_not_qualified"),
        native.windows_ssh_component(selected),
    ):
        pytest.fail("changed DLL admitted")


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
