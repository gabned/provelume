"""Frozen worker bootstrap; reached before desktop/Tk imports or service startup."""

import ctypes as c
import io
import os
import sys

from .ai_runtime_limits import check


def main():
    import msvcrt

    from .ai_windows_api import libraries, verify_job, verify_token

    check(getattr(sys, "frozen", False) and sys.argv[1:] == ["--internal-ai-worker"],
          "compatibility")
    kernel, _, _, _ = libraries()
    process = kernel.GetCurrentProcess()
    # Independently inspect our real token and already-assigned Job. The parent
    # checks the system-wide loopback exemption list before resume and every use.
    limits = {**verify_token(process, observe_loopback=False), **verify_job(process)}
    for attribute, identifier, mode in (("stdin", -10, "rb"), ("stdout", -11, "wb"),
                                         ("stderr", -12, "wb")):
        handle = kernel.GetStdHandle(identifier)
        check(handle and handle != c.c_void_p(-1).value
              and kernel.GetFileType(handle) == (2 if attribute == "stderr" else 3),
              "compatibility")
        descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY | (
            os.O_RDONLY if mode == "rb" else os.O_WRONLY))
        binary = os.fdopen(descriptor, mode, buffering=0)
        setattr(sys, attribute, io.TextIOWrapper(binary, encoding="utf-8", write_through=True))
    from .ai_runtime_worker import main as run

    run(containment=(None, limits), inherited_model=True)
