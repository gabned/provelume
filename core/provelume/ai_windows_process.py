"""Parent-owned creation-time Job and AppContainer for the installed executable."""

from __future__ import annotations

import ctypes as c
import hashlib
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

from .ai_model_download import checkpoint
from .ai_runtime_limits import check
from .ai_windows_api import (
    SIZE,
    Capabilities,
    D,
    H,
    P,
    ProcessInfo,
    StartupExtended,
    create_job,
    libraries,
    local_app_data,
    no_loopback_exemption,
    verify_job,
    verify_token,
)


def profile_name(executable):
    identity = os.path.normcase(str(Path(executable).absolute())).encode("utf-8")
    return "Provelume.Custodia." + hashlib.sha256(identity).hexdigest()[:32]


class WindowsWorkerProcess:
    def __init__(self):
        # Publish the owner to LocalRuntime before launch, including error cleanup.
        self._resources = ExitStack()
        self._handle = self._job = self._sid = None
        self.pid = None
        self.stdin = self.stdout = None
        self.model_handle = None
        self.proof = None
        self.phase = "runtime-path"
        self.native_code = None

    def start(self, model, runtime_directory, *, environment, deadline, cancel):
        import msvcrt

        from .ai_windows_package import pin_public_package
        from .maintenance_local_files import open_local_file

        check(os.name == "nt" and getattr(sys, "frozen", False), "compatibility")
        executable = Path(sys.executable)
        expected_runtime = Path(sys._MEIPASS) / "provelume/native-ai/windows"
        check(runtime_directory == expected_runtime, "compatibility")
        kernel, advapi, userenv, _ = libraries()
        sid = P()
        name = profile_name(executable)
        self.phase = "profile-create"
        result = userenv.CreateAppContainerProfile(
            name, "Provelume local AI", "Isolated local model worker", None, 0, c.byref(sid))
        self.native_code = result
        check(result in (0, c.c_int32(0x800700B7).value), "compatibility")
        if result != 0:
            check(userenv.DeriveAppContainerSidFromAppContainerName(name, c.byref(sid)) == 0,
                  "compatibility")
        check(sid and advapi.IsValidSid(sid), "compatibility")
        self._sid = sid
        self._resources.callback(advapi.FreeSid, sid)
        self.phase = "loopback-exemptions"
        self.native_code = None
        no_loopback_exemption(sid)
        self.phase = "public-inventory"
        public = pin_public_package(self._resources, executable, sid,
                                    cancel=cancel, deadline=deadline)
        self.phase = "private-model-handle"
        source = self._resources.enter_context(open_local_file(model.path))
        self.phase = "job-create"
        self._job, topology = create_job()
        self._resources.callback(kernel.CloseHandle, self._job)
        checkpoint(cancel, deadline)
        with ExitStack() as creation:
            self.phase = "stdio-handles"
            in_read, in_write = os.pipe()
            creation.callback(os.close, in_read)
            self.stdin = os.fdopen(in_write, "wb", buffering=0)
            self._resources.callback(self.stdin.close)
            out_read, out_write = os.pipe()
            creation.callback(os.close, out_write)
            self.stdout = os.fdopen(out_read, "rb", buffering=0)
            self._resources.callback(self.stdout.close)
            null = creation.enter_context(open(os.devnull, "wb", buffering=0))
            stdio = [msvcrt.get_osfhandle(fd) for fd in (in_read, out_write, null.fileno())]
            for handle in stdio:
                check(kernel.SetHandleInformation(handle, 1, 1), "compatibility")
            inherited_model = H()
            check(kernel.DuplicateHandle(kernel.GetCurrentProcess(),
                                         msvcrt.get_osfhandle(source.fileno()),
                                         kernel.GetCurrentProcess(), c.byref(inherited_model),
                                         0, True, 2), "compatibility")
            creation.callback(kernel.CloseHandle, inherited_model)
            self.model_handle = inherited_model.value
            handles = (H * 4)(*stdio, inherited_model.value)
            jobs = (H * 1)(self._job)
            capabilities = Capabilities(sid, None, 0, 0)
            self.phase = "process-attributes"
            size = SIZE()
            check(not kernel.InitializeProcThreadAttributeList(None, 3, 0, c.byref(size))
                  and c.get_last_error() == 122 and 0 < size.value <= 65536, "compatibility")
            attributes = c.create_string_buffer(size.value)
            check(kernel.InitializeProcThreadAttributeList(attributes, 3, 0, c.byref(size)),
                  "compatibility")
            creation.callback(kernel.DeleteProcThreadAttributeList, attributes)
            for kind, value in ((0x20002, handles), (0x20009, capabilities), (0x2000D, jobs)):
                check(kernel.UpdateProcThreadAttribute(attributes, 0, kind, c.byref(value),
                                                       c.sizeof(value), None, None),
                      "compatibility")
            startup = StartupExtended()
            startup.startup.cb = c.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES.
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = stdio
            startup.attributes = c.cast(attributes, P)
            command = c.create_unicode_buffer(subprocess.list2cmdline(
                [str(executable), "--internal-ai-worker"]))
            # CreateProcessW resolves the AppContainer profile using this field.
            # Omitting it returns ERROR_ENVVAR_NOT_FOUND (203) before child entry.
            # Obtain only this OS-owned location, not the parent's complete env.
            environment = {**environment, "LOCALAPPDATA": local_app_data()}
            check(all("=" not in key and "\0" not in key + value
                      for key, value in environment.items()), "compatibility")
            env = c.create_unicode_buffer("\0".join(
                f"{key}={value}" for key, value in sorted(
                    environment.items(), key=lambda item: item[0].upper())) + "\0\0")
            process = ProcessInfo()
            # Both containment attributes are effective at CREATE time. No assign
            # after launch, no uncontained fallback, no inherited Job handle.
            flags = 0x08000000 | 0x00080000 | 0x00000400 | 0x00000004
            self.phase = "process-create"
            created = kernel.CreateProcessW(str(executable), command, None, None, True, flags,
                                             env, str(executable.parent), c.byref(startup),
                                             c.byref(process))
            # Capture immediately: Python's frozen error import may itself query
            # environment variables and replace the thread-local Win32 error.
            self.native_code = None if created else c.get_last_error()
            check(created, "compatibility")
            self._handle, self.pid = process.process, process.pid
            self._resources.callback(kernel.CloseHandle, self._handle)
            creation.callback(kernel.CloseHandle, process.thread)
            self.phase = "process-verification"
            self.proof = {**verify_token(self._handle, expected_sid=sid),
                          **verify_job(self._handle, self._job), "cpu_topology": topology,
                          **public, "model_access": "inherited-read-only-handle"}
            checkpoint(cancel, deadline)
            self.phase = "process-resume"
            check(kernel.ResumeThread(process.thread) == 1, "compatibility")
            self.phase = "worker-bootstrap"

    def validate_containment(self):
        check(self.poll() is None, "state")
        verify_token(self._handle, expected_sid=self._sid)
        verify_job(self._handle, self._job)
        return dict(self.proof)

    def poll(self):
        if self._handle is None:
            return 0
        kernel, _, _, _ = libraries()
        result = kernel.WaitForSingleObject(self._handle, 0)
        if result == 258:
            return None
        check(result == 0, "state")
        code = D()
        check(kernel.GetExitCodeProcess(self._handle, c.byref(code)), "state")
        return code.value

    def kill(self):
        kernel, _, _, _ = libraries()
        if self._job is not None:
            check(kernel.TerminateJobObject(self._job, 1) or self.poll() is not None, "state")

    def wait(self, timeout=2):
        if self._handle is None:
            return 0
        kernel, _, _, _ = libraries()
        result = kernel.WaitForSingleObject(self._handle, int(timeout * 1000))
        if result == 258:
            raise subprocess.TimeoutExpired("private AI worker", timeout)
        check(result == 0, "state")
        return self.poll()

    def close(self):
        check(self.poll() is not None, "busy")
        self._resources.close()
        self._handle = self._job = self._sid = None
