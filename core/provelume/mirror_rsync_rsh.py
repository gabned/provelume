"""Fixed rsync rsh adapter, inside its parent's native process group/Windows Job."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path

from .maintenance_local_files import open_local_file
from .migration_permissions import private_directory
from .mirror_contract import MAX_MANIFEST_BYTES, parse, require
from .mirror_folder_files import MAX_TARGET_BYTES
from .mirror_rsync_protocol import expected_rsh_arguments, frame, request
from .mirror_ssh_runtime import (
    MAX_COMPONENT_BYTES,
    configuration,
    environment,
    ssh_arguments,
    ssh_environment,
    windows_ssh_component,
)


@contextmanager
def inherited_streams():
    """Use only the byte streams that the contained rsync process supplied."""
    if os.name != "nt":
        yield 0, 1, sys.stderr
        return

    import ctypes
    import msvcrt

    from .ai_windows_api import libraries

    kernel, *_ = libraries()
    process = kernel.GetCurrentProcess()
    with ExitStack() as files:
        streams = []
        for identifier, types, mode in ((-10, {3}, "rb"), (-11, {3}, "wb"),
                                        (-12, {1, 3}, "wb")):
            source = kernel.GetStdHandle(identifier)
            duplicate = ctypes.c_void_p()
            require(
                source and kernel.GetFileType(source) in types
                and kernel.DuplicateHandle(
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
            streams.append(files.enter_context(os.fdopen(descriptor, mode, buffering=0)))
        yield streams[0].fileno(), streams[1].fileno(), streams[2]


def main():
    process = None
    resources = ExitStack()
    try:
        arguments = sys.argv[1:]
        if arguments[:1] == ["--internal-rsync-rsh"]:
            arguments = arguments[1:]
        require(arguments and Path(arguments[0]).is_absolute(), "rsync_rsh_context")
        path = Path(arguments[0])
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
        require(arguments[1:] == expected_rsh_arguments(target), "rsync_rsh_arguments")
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
        incoming, outgoing, errors = resources.enter_context(inherited_streams())
        # Deliberately no start_new_session/CREATE_BREAKAWAY_FROM_JOB: native SSH
        # stays in the rsync invocation's already established group/Job. Its only
        # descendants can be fixed native SSH code; proxies/helpers are disabled.
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
        writer = process.stdin.fileno()

        def write(descriptor, value):
            view = memoryview(value)
            while view:
                require(time.monotonic() < deadline, "deadline")
                count = os.write(descriptor, view)
                require(count > 0, "rsync_stream")
                view = view[count:]

        write(writer, frame(value))
        failures = []

        def pump(source, destination, *, close=False):
            count = 0
            try:
                while data := os.read(source, 65536):
                    count += len(data)
                    require(
                        count <= MAX_TARGET_BYTES and time.monotonic() < deadline,
                        "rsync_stream_limit",
                    )
                    write(destination, data)
            except Exception:
                failures.append(True)
                if process.poll() is None:
                    process.kill()
            finally:
                if close:
                    process.stdin.close()

        # Raw fd operations avoid interpreter buffered-I/O locks. These daemon
        # pumps live only in this contained worker; its parent enforces the same
        # absolute deadline and kills the complete group/Job, including SSH.
        sender = threading.Thread(
            target=pump, args=(incoming, writer), kwargs={"close": True}, daemon=True
        )
        receiver = threading.Thread(
            target=pump, args=(process.stdout.fileno(), outgoing), daemon=True
        )
        sender.start()
        receiver.start()
        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        receiver.join(timeout=max(0.01, min(1, deadline - time.monotonic())))
        require(not receiver.is_alive() and not failures, "rsync_stream")
        return code
    except Exception:
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
