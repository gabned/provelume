"""Finite native Linux receiver: no threads blocked on an SSH channel or child pipe."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from contextlib import suppress
from uuid import uuid4

from .mirror_contract import require
from .mirror_folder_files import MAX_TARGET_BYTES, MAX_TARGET_FILES
from .mirror_ssh_runtime import MAX_COMMAND_SECONDS, MAX_DIAGNOSTIC_BYTES, environment
from .ocr_process import _terminate_process_tree


def receive(arguments, *, tree, stage, incoming, outgoing, work, outcome):
    require(
        os.name == "posix" and os.uname().sysname == "Linux", "rsync_server_profile_not_qualified"
    )
    deadline = min(tree.deadline, time.monotonic() + MAX_COMMAND_SECONDS)
    errors = work / (uuid4().hex + ".err")
    process = None
    input_blocking, output_blocking = os.get_blocking(incoming), os.get_blocking(outgoing)
    try:
        with errors.open("xb") as stderr:
            process = subprocess.Popen(
                arguments,
                cwd=tree.root,
                env=environment(work),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
                umask=0o077,
            )
            reader, writer = process.stdout.fileno(), process.stdin.fileno()
            for descriptor in (incoming, outgoing, reader, writer):
                os.set_blocking(descriptor, False)
            send, reply = bytearray(), bytearray()
            source_end = receiver_end = False
            sent = returned = 0
            next_storage_check = 0
            while not receiver_end or reply or process.poll() is None:
                tree.check()
                require(time.monotonic() < deadline, "deadline")
                require(errors.stat().st_size <= MAX_DIAGNOSTIC_BYTES, "rsync_output_limit")
                if time.monotonic() >= next_storage_check:
                    files = tree.files(stage)
                    require(
                        len(files) <= MAX_TARGET_FILES
                        and sum(size for _, size in files) <= MAX_TARGET_BYTES,
                        "rsync_storage_limit",
                    )
                    next_storage_check = time.monotonic() + 0.25
                if source_end and not send and not process.stdin.closed:
                    process.stdin.close()
                with selectors.DefaultSelector() as selected:
                    if not source_end and len(send) < 65536 and not process.stdin.closed:
                        selected.register(incoming, selectors.EVENT_READ, "source")
                    if send and not process.stdin.closed:
                        selected.register(writer, selectors.EVENT_WRITE, "send")
                    if not receiver_end and len(reply) < 65536:
                        selected.register(reader, selectors.EVENT_READ, "receive")
                    if reply:
                        selected.register(outgoing, selectors.EVENT_WRITE, "reply")
                    for key, _event in selected.select(0.05):
                        try:
                            if key.data == "source":
                                data = os.read(incoming, 65536 - len(send))
                                source_end = not data
                                sent += len(data)
                                require(sent <= MAX_TARGET_BYTES, "rsync_stream_limit")
                                send.extend(data)
                            elif key.data == "send":
                                del send[: os.write(writer, send)]
                            elif key.data == "receive":
                                data = os.read(reader, 65536 - len(reply))
                                receiver_end = not data
                                returned += len(data)
                                require(returned <= MAX_TARGET_BYTES, "rsync_stream_limit")
                                reply.extend(data)
                            else:
                                del reply[: os.write(outgoing, reply)]
                        except BlockingIOError:
                            pass
            return {
                "returncode": process.returncode,
                "received_wire_bytes": sent,
                "sent_wire_bytes": returned,
                "native_child_stopped": True,
            }
    finally:
        if process is not None:
            if process.poll() is None:
                _terminate_process_tree(process)
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        outcome["native_child_stopped"] = process is None or process.poll() is not None
        require(outcome["native_child_stopped"], "rsync_child_outcome_unknown")
        os.set_blocking(incoming, input_blocking)
        os.set_blocking(outgoing, output_blocking)
        errors.unlink(missing_ok=True)
