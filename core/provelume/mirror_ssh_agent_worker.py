"""Owned worker: private key arrives only via stdin, never an argv/env/file value."""

import base64
import os
import sys
import time
from pathlib import Path

from .mirror_contract import parse, raw, require
from .mirror_ssh_agent import AgentProtocol
from .mirror_ssh_agent_server import OwnedAgent


def publish(path, value):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(raw(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
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
        with OwnedAgent(protocol) as owned:
            publish(
                output,
                {
                    "schema": "provelume-ssh-agent-ready/v1",
                    "pid": os.getpid(),
                    "endpoint": owned.endpoint,
                },
            )
            while owned.worker.is_alive() and time.monotonic() < protocol.deadline:
                time.sleep(0.05)
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
        )
        return 0 if protocol.signatures == 1 else 2
    except Exception:
        # Never render a backend exception, request body, seed or auth signature.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
