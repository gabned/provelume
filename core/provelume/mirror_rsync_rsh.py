"""Fixed rsync rsh adapter, inside its parent's native process group/Windows Job."""

from __future__ import annotations

import hashlib
import os
import select
import socket
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager, suppress
from functools import partial
from pathlib import Path

from .maintenance_local_files import open_local_file
from .migration_permissions import private_directory
from .mirror_contract import MAX_MANIFEST_BYTES, MirrorError, parse, require
from .mirror_folder_files import MAX_TARGET_BYTES
from .mirror_rsync_protocol import RSH_FAILURE_PREFIX, expected_rsh_arguments, frame, request
from .mirror_ssh_runtime import (
    MAX_COMPONENT_BYTES,
    configuration,
    environment,
    ssh_arguments,
    ssh_environment,
    windows_ssh_component,
)


def socket_kind(handle):
    """Inspect the admitted raw handle without owning or reconfiguring it."""
    import ctypes

    try:
        winsock = ctypes.WinDLL("ws2_32")
        kind = ctypes.c_int()
        size = ctypes.c_int(ctypes.sizeof(kind))
        get_type = winsock.getsockopt
        get_type.argtypes = [
            ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
        ]
        get_type.restype = ctypes.c_int
        if get_type(handle, socket.SOL_SOCKET, socket.SO_TYPE, ctypes.byref(kind),
                    ctypes.byref(size)) == 0:
            return "STREAM_SOCKET" if kind.value == socket.SOCK_STREAM else "OTHER_SOCKET"
        if winsock.WSAGetLastError() == 10038:  # WSAENOTSOCK
            return "NOT_SOCKET"
    except (AttributeError, OSError, ValueError):
        pass
    return "UNAVAILABLE"


def duplicate_windows_socket(files, handle):
    # MSYS gives the adapter an inherited WinSock SOCKET under FILE_TYPE_PIPE.
    # Use a WinSock duplicate owned by this adapter, never a CRT file descriptor
    # or DuplicateHandle for the original socket.
    borrowed = socket.socket(fileno=handle)
    try:
        owned = files.enter_context(socket.fromshare(borrowed.share(os.getpid())))
        owned.setblocking(False)
        return owned
    finally:
        borrowed.detach()


def socket_io(endpoint, deadline, *, sending):
    operation = endpoint.send if sending else endpoint.recv
    readers, writers = ([], [endpoint]) if sending else ([endpoint], [])

    def transfer(value):
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "deadline")
            readable, writable, _ = select.select(readers, writers, [], remaining)
            require(readable or writable, "deadline")
            try:
                return operation(value)
            except BlockingIOError:
                continue

    return transfer


@contextmanager
def inherited_streams(observed, sockets, deadline):
    """Use only the byte streams that the contained rsync process supplied."""
    if os.name != "nt":
        yield partial(os.read, 0), partial(os.write, 1), sys.stderr
        return

    import ctypes
    import msvcrt

    from .ai_windows_api import libraries

    kernel, *_ = libraries()
    process = kernel.GetCurrentProcess()
    standard = []
    kind_names = {0: "UNKNOWN", 1: "DISK", 2: "CHAR", 3: "PIPE"}
    for name, identifier, types, mode in (
        ("stdin", -10, {3}, "rb"), ("stdout", -11, {3}, "wb"), ("stderr", -12, {1, 3}, "wb")
    ):
        source = kernel.GetStdHandle(identifier)
        kind = kernel.GetFileType(source) if source else None
        observed[name] = "ABSENT" if kind is None else kind_names.get(kind, "OTHER")
        if kind == 3 and name != "stderr":
            sockets[name] = socket_kind(source)
        standard.append((name, source, kind, types, mode))
    with ExitStack() as files:
        streams = []
        for name, source, kind, types, mode in standard:
            require(source and kind in types, "rsync_stream")
            if sockets.get(name) == "STREAM_SOCKET":
                endpoint = duplicate_windows_socket(files, source)
                streams.append(socket_io(endpoint, deadline, sending=(name == "stdout")))
                continue
            duplicate = ctypes.c_void_p()
            require(
                kernel.DuplicateHandle(
                    process, source, process, ctypes.byref(duplicate), 0, False, 2
                ),
                "rsync_stream",
            )
            access = os.O_RDONLY if mode == "rb" else os.O_WRONLY
            try:
                descriptor = msvcrt.open_osfhandle(duplicate.value, os.O_BINARY | access)
            except BaseException:
                kernel.CloseHandle(duplicate)
                raise
            stream = files.enter_context(os.fdopen(descriptor, mode, buffering=0))
            if name == "stderr":
                streams.append(stream)
            else:
                operation = os.read if name == "stdin" else os.write
                streams.append(partial(operation, stream.fileno()))
        yield tuple(streams)


def error_kind(error):
    for attribute, kind in (("winerror", "WIN32"), ("errno", "ERRNO")):
        value = getattr(error, attribute, None)
        if type(value) is int and 0 <= value <= 0xFFFFFFFF:
            return kind, value
    if isinstance(error, subprocess.TimeoutExpired):
        return "TIMEOUT", 0
    if isinstance(error, MirrorError):
        return "MIRROR", 0
    return ("NONE" if error is None else "OTHER"), 0


def child_status(process):
    if process is not None:
        with suppress(OSError):
            value = process.poll()
            if value is None:
                return "RUNNING"
            if type(value) is int and 0 <= value <= 0xFFFFFFFF:
                return value
    return "UNOBSERVED"


def emit_failure(phase, stdio, sockets, argc, mismatch, *, error=None, child="UNOBSERVED"):
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes as w

    kind, native = error_kind(error)
    fields = [phase, *(stdio.get(name, "UNOBSERVED") for name in ("stdin", "stdout", "stderr")),
              *(sockets.get(name, "UNAVAILABLE") for name in ("stdin", "stdout")),
              str(argc), str(mismatch), kind, str(native), str(child)]
    record = RSH_FAILURE_PREFIX + " ".join(fields).encode("ascii") + b"\n"
    try:
        # The frozen GUI can have sys.stderr=None. Use only its inherited
        # handle, and emit a fixed-enum record without any command data.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes, kernel.GetStdHandle.restype = [w.DWORD], w.HANDLE
        kernel.GetFileType.argtypes, kernel.GetFileType.restype = [w.HANDLE], w.DWORD
        kernel.WriteFile.argtypes = [
            w.HANDLE, ctypes.c_char_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p
        ]
        kernel.WriteFile.restype = w.BOOL
        handle = kernel.GetStdHandle(w.DWORD(-12))
        if handle and kernel.GetFileType(handle) in {1, 3}:
            kernel.WriteFile(handle, record, len(record), ctypes.byref(w.DWORD()), None)
    except (OSError, ValueError, AttributeError):
        pass


def main():
    process = None
    resources = ExitStack()
    phase, stdio, sockets, argc, mismatch = "CONTEXT_PATH", {}, {}, 0, -1
    failures = []
    try:
        arguments = sys.argv[1:]
        if arguments[:1] == ["--internal-rsync-rsh"]:
            arguments = arguments[1:]
        argc = max(0, min(len(arguments) - 1, 99))
        require(arguments and Path(arguments[0]).is_absolute(), "rsync_rsh_context")
        path = Path(arguments[0])
        phase = "CONTEXT_READ"
        private_directory(path.parent)
        with open_local_file(path) as stream:
            context = parse(stream.read(MAX_MANIFEST_BYTES + 1))
        require(
            set(context) == {"schema", "target", "ssh", "agent", "request", "deadline"}
            and context["schema"] == "provelume-rsync-rsh/v1",
            "rsync_rsh_context",
        )
        target = configuration(context["target"])
        value = request(context["request"])
        phase = "ARGV"
        expected = expected_rsh_arguments(target)
        if arguments[1:] != expected:
            mismatch = next(
                (index for index, (actual, wanted) in enumerate(
                    zip(arguments[1:], expected, strict=False)
                )
                 if actual != wanted),
                min(argc, len(expected)),
            )
            require(False, "rsync_rsh_arguments")
        phase = "REQUEST"
        require(
            value["action"] in {"receive", "resume"}
            and value["namespace"] == target["namespace"]
            and value["configuration_sha256"] == target["configuration_sha256"]
            and value["bandwidth_kib"] == target["bandwidth_kib"],
            "rsync_rsh_context",
        )
        deadline = context["deadline"]
        require(
            type(deadline) in {int, float} and time.monotonic() < deadline <= time.monotonic() + 30,
            "deadline",
        )
        phase = "COMPONENT"
        component = context["ssh"]
        require(
            type(component) is dict and set(component) == {"path", "version", "sha256"},
            "rsync_rsh_context",
        )
        binary = Path(component["path"])
        if os.name == "nt":
            pinned = resources.enter_context(windows_ssh_component(binary))
            require(component == pinned, "ssh_profile_not_qualified")
        else:
            require(
                binary.is_absolute()
                and binary.stat().st_size <= MAX_COMPONENT_BYTES
                and hashlib.sha256(binary.read_bytes()).hexdigest() == component["sha256"],
                "ssh_profile_not_qualified",
            )
        agent = context["agent"]
        phase = "STDIO"
        incoming, outgoing, errors = resources.enter_context(
            inherited_streams(stdio, sockets, deadline)
        )
        # Deliberately no start_new_session/CREATE_BREAKAWAY_FROM_JOB: native SSH
        # stays in the rsync invocation's already established group/Job. Its only
        # descendants can be fixed native SSH code; proxies/helpers are disabled.
        phase = "SSH_LAUNCH"
        process = subprocess.Popen(
            ssh_arguments(str(binary), target, path.parent, agent),
            cwd=path.parent,
            env=ssh_environment(environment(path.parent), agent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        phase = "FRAME_WRITE"
        child_write = partial(os.write, process.stdin.fileno())
        child_read = partial(os.read, process.stdout.fileno())

        def write(send, value):
            view = memoryview(value)
            while view:
                require(time.monotonic() < deadline, "deadline")
                count = send(view)
                require(count > 0, "rsync_stream")
                view = view[count:]

        write(child_write, frame(value))

        def pump(read, send, *, close=False):
            count = 0
            read_phase, write_phase = (
                ("PUMP_INPUT_READ", "PUMP_CHILD_WRITE")
                if close else ("PUMP_CHILD_READ", "PUMP_OUTPUT_WRITE")
            )
            try:
                while True:
                    failed_phase = read_phase
                    data = read(65536)
                    if not data:
                        break
                    count += len(data)
                    require(
                        count <= MAX_TARGET_BYTES and time.monotonic() < deadline,
                        "rsync_stream_limit",
                    )
                    failed_phase = write_phase
                    write(send, data)
            except Exception as error:
                child = child_status(process)
                failures.append((failed_phase, error, child))
                if child == "RUNNING":
                    process.kill()
            finally:
                if close:
                    process.stdin.close()

        # Raw fd operations avoid interpreter buffered-I/O locks. These daemon
        # pumps live only in this contained worker; its parent enforces the same
        # absolute deadline and kills the complete group/Job, including SSH.
        sender = threading.Thread(
            target=pump, args=(incoming, child_write), kwargs={"close": True}, daemon=True
        )
        receiver = threading.Thread(
            target=pump, args=(child_read, outgoing), daemon=True
        )
        phase = "PUMP_START"
        sender.start()
        receiver.start()
        phase = "CHILD_WAIT"
        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        phase = "PUMP_DRAIN"
        receiver.join(timeout=max(0.01, min(1, deadline - time.monotonic())))
        require(not receiver.is_alive() and not failures, "rsync_stream")
        if code:
            emit_failure("SSH_EXIT", stdio, sockets, argc, mismatch, child=child_status(process))
        return code
    except Exception as raised:
        if failures:
            phase, failure, child = failures[0]
        else:
            failure, child = raised, child_status(process)
        emit_failure(phase, stdio, sockets, argc, mismatch, error=failure, child=child)
        return 2
    finally:
        try:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=1)
        finally:
            resources.close()


if __name__ == "__main__":
    raise SystemExit(main())
