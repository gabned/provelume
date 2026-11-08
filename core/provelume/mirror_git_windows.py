"""Creation-time Windows Job for optional Git; no uncontained launch fallback."""

from __future__ import annotations

import ctypes as c
import os
import subprocess
from contextlib import ExitStack

from .ai_windows_api import (
    SIZE,
    D,
    H,
    JobExtended,
    P,
    ProcessInfo,
    StartupExtended,
    libraries,
)
from .mirror_contract import MirrorError, require


def require_native(result, operation):
    if not result:
        error = MirrorError("git_containment")
        error.containment_evidence = {
            "schema": "provelume-windows-process-failure/v1",
            "operation": operation,
            "native_error": c.get_last_error(),
        }
        raise error


class WindowsGitProcess:
    def __init__(self, command, *, cwd, environment, incoming, output, errors):
        import msvcrt

        require(os.name == "nt", "git_containment")
        self.pid, self.handle, self.job = None, None, None
        self.returncode = None
        self.resources = ExitStack()
        kernel, _advapi, _userenv, _ip = libraries()
        try:
            self.job = kernel.CreateJobObjectW(None, None)
            require_native(bool(self.job), "CreateJobObjectW")
            self.resources.callback(kernel.CloseHandle, self.job)
            limits = JobExtended()
            limits.basic.flags = 0x2000 | 0x8  # Kill on close; at most 16 descendants.
            limits.basic.active = 16
            require_native(
                kernel.SetInformationJobObject(self.job, 9, c.byref(limits), c.sizeof(limits)),
                "SetInformationJobObject",
            )
            with ExitStack() as startup_resources:
                stdio = [msvcrt.get_osfhandle(file.fileno()) for file in (incoming, output, errors)]
                inherited = list(dict.fromkeys(stdio))
                for handle in inherited:
                    require_native(
                        kernel.SetHandleInformation(handle, 1, 1), "SetHandleInformation"
                    )
                    startup_resources.callback(kernel.SetHandleInformation, handle, 1, 0)
                handles, jobs = (H * len(inherited))(*inherited), (H * 1)(self.job)
                size = SIZE()
                require_native(
                    not kernel.InitializeProcThreadAttributeList(None, 2, 0, c.byref(size))
                    and c.get_last_error() == 122
                    and 0 < size.value <= 65536,
                    "InitializeProcThreadAttributeList.size",
                )
                attributes = c.create_string_buffer(size.value)
                require_native(
                    kernel.InitializeProcThreadAttributeList(attributes, 2, 0, c.byref(size)),
                    "InitializeProcThreadAttributeList",
                )
                startup_resources.callback(kernel.DeleteProcThreadAttributeList, attributes)
                for kind, value in ((0x20002, handles), (0x2000D, jobs)):
                    require_native(
                        kernel.UpdateProcThreadAttribute(
                            attributes, 0, kind, c.byref(value), c.sizeof(value), None, None
                        ),
                        "UpdateProcThreadAttribute." + ("handles" if kind == 0x20002 else "jobs"),
                    )
                startup = StartupExtended()
                startup.startup.cb = c.sizeof(startup)
                startup.startup.flags = 0x100
                startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = stdio
                startup.attributes = c.cast(attributes, P)
                environment = {key.upper(): value for key, value in environment.items()}
                require(
                    all(
                        key and "=" not in key and "\0" not in key + value
                        for key, value in environment.items()
                    ),
                    "git_containment",
                )
                block = c.create_unicode_buffer(
                    "\0".join(key + "=" + value for key, value in sorted(environment.items()))
                    + "\0\0"
                )
                line = c.create_unicode_buffer(subprocess.list2cmdline(command))
                process = ProcessInfo()
                flags = 0x08000000 | 0x00080000 | 0x00000400 | 0x00000004
                require_native(
                    kernel.CreateProcessW(
                        command[0],
                        line,
                        None,
                        None,
                        True,
                        flags,
                        block,
                        str(cwd),
                        c.byref(startup),
                        c.byref(process),
                    ),
                    "CreateProcessW",
                )
                self.handle, self.pid = process.process, process.pid
                self.resources.callback(kernel.CloseHandle, self.handle)
                startup_resources.callback(kernel.CloseHandle, process.thread)
                member = c.c_int32()
                require_native(
                    kernel.IsProcessInJob(self.handle, self.job, c.byref(member)) and member.value,
                    "IsProcessInJob",
                )
                require_native(kernel.ResumeThread(process.thread) == 1, "ResumeThread")
        except BaseException as error:
            try:
                self.close()
            except MirrorError as cleanup:
                cleanup.containment_evidence = {
                    **getattr(error, "containment_evidence", {}),
                    "cleanup": "STOP_NOT_CONFIRMED",
                }
                raise cleanup from error
            raise

    def poll(self):
        if self.handle is None:
            return self.returncode
        kernel, *_ = libraries()
        code = D()
        require(kernel.GetExitCodeProcess(self.handle, c.byref(code)), "git_containment")
        if code.value == 259:
            return None
        self.returncode = int(code.value)
        return self.returncode

    def close(self):
        kernel, *_ = libraries()
        try:
            if self.job:
                # Closing a Job also terminates descendants after a parent has exited.
                require(kernel.TerminateJobObject(self.job, 1), "git_containment")
            if self.handle:
                require(kernel.WaitForSingleObject(self.handle, 2000) == 0, "git_containment")
        except (OSError, ValueError):
            raise MirrorError("git_containment") from None
        finally:
            self.resources.close()
            self.handle = self.job = None
