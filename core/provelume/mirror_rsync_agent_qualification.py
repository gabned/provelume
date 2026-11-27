"""Native OS-vault and contained agent IPC qualification, never an SSH/rsync PASS."""

import base64
import os
import secrets
import socket
import struct
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import patch

from .build_info import current_build_info
from .google_credentials import GoogleCredentialVault
from .migration_permissions import make_private
from .mirror_contract import MirrorError, require
from .mirror_rsync_credentials import RsyncCredentials
from .mirror_ssh_agent import Wire, field, public_blob
from .mirror_ssh_agent_process import AgentWorker
from .mirror_ssh_crypto import public_key, sign, verify
from .mirrors import Mirrors
from .service import ProvelumeInstance


def exchange(owned, *, seed, host_seed, wrong_host=False):
    host = public_blob(public_key(host_seed))
    session = secrets.token_bytes(32)
    with ExitStack() as resources:
        if os.name == "nt":
            connection = resources.enter_context(open(owned.endpoint, "r+b", buffering=0))
            receive = connection.read

            def send(value):
                require(connection.write(value) == len(value), "ssh_agent_pipe")

        else:
            connection = resources.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
            connection.settimeout(2)
            connection.connect(owned.endpoint)
            receive, send = connection.recv, connection.sendall

        def read(length):
            value = b""
            while len(value) < length:
                chunk = receive(length - len(value))
                require(chunk, "ssh_agent_pipe")
                value += chunk
            return value

        def message(value):
            send(struct.pack(">I", len(value)) + value)
            return read(struct.unpack(">I", read(4))[0])

        signed = field(b"ssh-ed25519") + field(sign(host_seed, session))
        response = message(
            b"\x1b"
            + field(b"session-bind@openssh.com")
            + field(host)
            + field(session)
            + field(signed)
            + b"\0"
        )
        if wrong_host:
            require(response == b"\x05", "rsync_credential_qualification")
            return
        require(response == b"\x06", "rsync_credential_qualification")
        identity = public_blob(public_key(seed))
        data = (
            field(session)
            + b"\x32"
            + field(b"synthetic")
            + field(b"ssh-connection")
            + field(b"publickey")
            + b"\x01"
            + field(b"ssh-ed25519")
            + field(identity)
        )
        request = b"\x0d" + field(identity) + field(data) + b"\0" * 4
        reply = Wire(message(request))
        require(reply.byte() == 14, "rsync_credential_qualification")
        signature = Wire(reply.string(128))
        reply.end()
        require(
            signature.string(32) == b"ssh-ed25519"
            and verify(public_key(seed), data, signature.string(64)),
            "rsync_credential_qualification",
        )
        signature.end()
        require(message(request) == b"\x05", "rsync_credential_qualification")


def qualify_agent(root):
    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    make_private(root)
    selected = (
        patch.dict(os.environ, {"LOCALAPPDATA": str(root / "Synthetic Host")})
        if os.name == "nt"
        else nullcontext()
    )
    with selected:
        instance = ProvelumeInstance.initialise(root / "Instance")
        mirrors = Mirrors(
            instance.store,
            vault=GoogleCredentialVault(namespace="mirror", forbidden_root=instance.root),
        )
        mirrors.set_access(
            enabled=True, github=False, rsync=True, expected_revision=0, confirmed=True
        )
        credentials = RsyncCredentials(mirrors)
        issued = credentials.generate(confirmed=True)
        try:
            value = RsyncCredentials(mirrors).read(issued["reference"])
            seed = base64.b64decode(value["seed"], validate=True)
            host_seed = secrets.token_bytes(32)
            host = public_blob(public_key(host_seed))
            with AgentWorker(seed, host_public_blob=host, username="synthetic") as owned:
                work = owned.output.parent
                exchange(owned, seed=seed, host_seed=host_seed)
                leaked = any(
                    seed in path.read_bytes() or value["seed"].encode() in path.read_bytes()
                    for path in work.rglob("*")
                    if path.is_file()
                )
                require(not leaked, "rsync_credential_qualification")
            require(
                owned.report["signatures"] == 1 and owned.report["host_bound"],
                "rsync_credential_qualification",
            )
            rejected = AgentWorker(seed, host_public_blob=host, username="synthetic")
            try:
                with rejected:
                    exchange(
                        rejected, seed=seed, host_seed=secrets.token_bytes(32), wrong_host=True
                    )
            except MirrorError as error:
                require(
                    error.code == "ssh_credentials"
                    and rejected.report is not None
                    and rejected.report["signatures"] == 0
                    and not rejected.report["host_bound"],
                    "rsync_credential_qualification",
                )
            else:
                require(False, "rsync_credential_qualification")
        finally:
            credentials.revoke(issued["reference"], confirmed=True)
        require(mirrors.vault.read(issued["reference"]) is None, "rsync_credential_qualification")
    return {
        "schema": "concordia-rsync-native-agent/v1",
        "result": "PASS",
        "commit": current_build_info().get("commit"),
        "mode": "NATIVE_VAULT_AND_OWNED_AGENT_IPC_ONLY",
        "backend": "NATIVE_CURRENT_USER_DPAPI" if os.name == "nt" else "NATIVE_SECRET_SERVICE",
        "write_reopen_read_delete": "PASS",
        "one_signature": "PASS",
        "wrong_host_refusal": "PASS",
        "private_key_file": False,
        "credential_values_logged": False,
        "driver_external_network_used": False,
        "native_ssh_authentication": "NOT_RUN",
        "native_rsync_transport": "NOT_RUN",
        "s22_acceptance": "NOT_ACCEPTED",
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
