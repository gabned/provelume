"""Owned worker: private key arrives only via stdin, never an argv/env/file value."""

import base64
import os
import sys
import time
from pathlib import Path

from .mirror_contract import parse, raw, require
from .mirror_ssh_agent import AgentProtocol
from .mirror_ssh_agent_diagnostics import emit
from .mirror_ssh_agent_server import OwnedAgent


def publish(path, value, *, deadline=None):
    # Keep the parent's existing one-second completion window and the original
    # protocol deadline. Windows readers may briefly deny deletion of the
    # prepared metadata file; retry only that rename, never the signing request.
    end = min(time.monotonic() + 1, deadline if deadline is not None else float("inf"))
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(raw(value))
        stream.flush()
        os.fsync(stream.fileno())
    retrying = False
    while True:
        if retrying:
            require(time.monotonic() < end, "ssh_agent_deadline")
        try:
            os.replace(temporary, path)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {32, 33} or time.monotonic() >= end:
                raise
            retrying = True
            time.sleep(min(0.01, max(0, end - time.monotonic())))


def main():
    phase = "REQUEST"
    emit(phase)
    try:
        arguments = sys.argv[1:]
        if arguments[:1] == ["--internal-rsync-agent-worker"]:
            arguments = arguments[1:]
        require(len(arguments) == 1, "ssh_agent_request")
        output = Path(arguments[0])
        require(
            output.is_absolute() and not output.exists() and not output.is_symlink(),
            "ssh_agent_request",
        )
        incoming = sys.stdin.buffer.read(4097)
        require(len(incoming) <= 4096, "ssh_agent_request")
        value = parse(incoming)
        require(
            set(value) == {"schema", "seed", "host_key", "username", "seconds"}
            and value["schema"] == "provelume-ssh-agent/v1"
            and type(value["seconds"]) in {int, float}
            and 0 < value["seconds"] <= 30,
            "ssh_agent_request",
        )
        seed = base64.b64decode(value["seed"], validate=True)
        host = base64.b64decode(value["host_key"], validate=True)
        protocol = AgentProtocol(
            seed,
            host_public_blob=host,
            username=value["username"],
            deadline=time.monotonic() + value["seconds"],
        )
        phase = "START_AGENT"
        emit(phase)
        with OwnedAgent(protocol) as owned:
            phase = "PUBLISH_READY"
            emit(phase)
            publish(
                output,
                {
                    "schema": "provelume-ssh-agent-ready/v1",
                    "pid": os.getpid(),
                    "endpoint": owned.endpoint,
                },
                deadline=protocol.deadline,
            )
            phase = "SESSION"
            emit(phase)
            while owned.worker.is_alive() and time.monotonic() < protocol.deadline:
                time.sleep(0.05)
            phase = "STOP_AGENT"
            emit(phase)
        phase = "PUBLISH_COMPLETION"
        emit(phase)
        publish(
            output.with_name(output.name + ".done"),
            {
                "schema": "provelume-ssh-agent-result/v1",
                "outcome": owned.outcome,
                "signatures": protocol.signatures,
                "requests": protocol.requests,
                "host_bound": protocol.session is not None,
                "private_key_logged": False,
            },
            deadline=protocol.deadline,
        )
        phase = "COMPLETE"
        emit(phase)
        return 0 if protocol.signatures == 1 else 2
    except Exception as error:
        emit(phase, error)
        # Never render a backend exception, request body, seed or auth signature.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
