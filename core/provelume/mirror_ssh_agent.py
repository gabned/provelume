"""Closed Ed25519 agent protocol: one user-auth signature bound to the pinned host."""

from __future__ import annotations

import struct
import time

from .mirror_contract import MirrorError, require
from .mirror_ssh_crypto import public_key, sign, verify

MAX_FRAME = 32768
ALGORITHM = b"ssh-ed25519"


def field(value):
    require(type(value) is bytes and len(value) <= MAX_FRAME, "ssh_agent_request")
    return struct.pack(">I", len(value)) + value


def public_blob(public):
    require(type(public) is bytes and len(public) == 32, "ssh_key")
    return field(ALGORITHM) + field(public)


class Wire:
    def __init__(self, value):
        require(type(value) is bytes and len(value) <= MAX_FRAME, "ssh_agent_request")
        self.value, self.offset = value, 0

    def take(self, length):
        require(
            type(length) is int and 0 <= length <= len(self.value) - self.offset,
            "ssh_agent_request",
        )
        selected = self.value[self.offset : self.offset + length]
        self.offset += length
        return selected

    def byte(self):
        return self.take(1)[0]

    def number(self):
        return struct.unpack(">I", self.take(4))[0]

    def string(self, maximum=MAX_FRAME):
        length = self.number()
        require(length <= maximum, "ssh_agent_request")
        return self.take(length)

    def end(self):
        require(self.offset == len(self.value), "ssh_agent_request")


def decode_public(blob):
    wire = Wire(blob)
    require(wire.string(32) == ALGORITHM, "ssh_host_key")
    public = wire.string(32)
    require(len(public) == 32, "ssh_host_key")
    wire.end()
    return public


class AgentProtocol:
    def __init__(self, seed, *, host_public_blob, username, deadline=None):
        require(
            type(username) is str
            and 0 < len(username) <= 100
            and username.isascii()
            and not any(ord(c) < 33 for c in username),
            "ssh_identity",
        )
        self.seed, self.public = seed, public_blob(public_key(seed))
        self.host_public_blob = host_public_blob
        self.host_public = decode_public(host_public_blob)
        self.username = username.encode("ascii")
        self.deadline = min(deadline or float("inf"), time.monotonic() + 30)
        self.session = None
        self.requests, self.signatures, self.closed = 0, 0, False

    def handle(self, payload):
        if self.closed:
            return b"\x05"
        try:
            self.requests += 1
            require(self.requests <= 64 and time.monotonic() <= self.deadline, "ssh_agent_request")
            request = Wire(payload)
            kind = request.byte()
            if kind == 11:  # SSH2_AGENTC_REQUEST_IDENTITIES: public material only.
                request.end()
                return (
                    b"\x0c" + struct.pack(">I", 1) + field(self.public) + field(b"Provelume mirror")
                )
            if kind == 27:
                return self.bind(request)
            require(kind == 13, "ssh_agent_request")
            return self.authenticate(request)
        except (MirrorError, ValueError, struct.error):
            self.closed = True
            return b"\x05"

    def bind(self, request):
        extension = request.string(128)
        if extension != b"session-bind@openssh.com":
            return b"\x1c"  # Unsupported extension, never a fallback signer.
        host = request.string(1024)
        session = request.string(128)
        signature = Wire(request.string(256))
        require(signature.string(32) == ALGORITHM, "ssh_host_key")
        signed = signature.string(64)
        signature.end()
        require(request.byte() == 0, "ssh_agent_forwarding")
        request.end()
        require(
            host == self.host_public_blob
            and len(session) in {32, 64}
            and len(signed) == 64
            and verify(self.host_public, session, signed),
            "ssh_host_key",
        )
        require(self.session is None or self.session == session, "ssh_agent_session")
        self.session = session
        return b"\x06"

    def authenticate(self, request):
        selected, data, flags = request.string(1024), request.string(16384), request.number()
        request.end()
        require(
            self.session is not None
            and self.signatures == 0
            and flags == 0
            and selected == self.public,
            "ssh_agent_session",
        )
        authentication = Wire(data)
        require(
            authentication.string(128) == self.session
            and authentication.byte() == 50
            and authentication.string(100) == self.username
            and authentication.string(64) == b"ssh-connection",
            "ssh_agent_identity",
        )
        method = authentication.string(128)
        require(
            method in {b"publickey", b"publickey-hostbound-v00@openssh.com"}
            and authentication.byte() == 1
            and authentication.string(32) == ALGORITHM
            and authentication.string(1024) == self.public,
            "ssh_agent_identity",
        )
        if method == b"publickey-hostbound-v00@openssh.com":
            require(authentication.string(1024) == self.host_public_blob, "ssh_host_key")
        authentication.end()
        self.signatures += 1
        return b"\x0e" + field(field(ALGORITHM) + field(sign(self.seed, data)))
