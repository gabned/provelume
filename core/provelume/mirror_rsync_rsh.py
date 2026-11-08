"""Fixed rsync rsh adapter, inside its parent's native process group/Windows Job."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

from .maintenance_local_files import open_local_file
from .migration_permissions import private_directory
from .mirror_contract import MAX_MANIFEST_BYTES, parse, require
from .mirror_folder_files import MAX_TARGET_BYTES
from .mirror_rsync_protocol import expected_rsh_arguments, frame, request
from .mirror_ssh_runtime import configuration, environment, ssh_arguments


def main():
    process = None
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
        require(
            binary.is_absolute()
            and binary.stat().st_size <= 16 * 1024 * 1024
            and hashlib.sha256(binary.read_bytes()).hexdigest() == component["sha256"],
            "ssh_profile_not_qualified",
        )
        # Deliberately no start_new_session/CREATE_BREAKAWAY_FROM_JOB: native SSH
        # stays in the rsync invocation's already established group/Job. Its only
        # descendants can be fixed native SSH code; proxies/helpers are disabled.
        process = subprocess.Popen(
            ssh_arguments(str(binary), target, path.parent, context["agent"]),
            cwd=path.parent,
            env=environment(path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            close_fds=True,
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
            target=pump, args=(0, writer), kwargs={"close": True}, daemon=True
        )
        receiver = threading.Thread(target=pump, args=(process.stdout.fileno(), 1), daemon=True)
        sender.start()
        receiver.start()
        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        receiver.join(timeout=max(0.01, min(1, deadline - time.monotonic())))
        require(not receiver.is_alive() and not failures, "rsync_stream")
        return code
    except Exception:
        return 2
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
