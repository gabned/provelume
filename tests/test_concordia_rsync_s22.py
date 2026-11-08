"""Pinned SSH/rsync reference profile; automatic fixtures never use live credentials."""

import pytest

from provelume.mirror_contract import MirrorError
from provelume.mirror_ssh_crypto import public_key, sign, verify


def test_native_tls_runtime_ed25519_matches_rfc8032_vector_and_rejects_changed_data():
    # Public RFC8032 section7.1 test1; not an account credential.
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    public = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    signature = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
        "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    assert public_key(seed) == public
    assert sign(seed, b"") == signature
    assert verify(public, b"", signature)
    assert not verify(public, b"changed", signature)
    assert not verify(public, b"", bytes([signature[0] ^ 1]) + signature[1:])


@pytest.mark.parametrize("bad", [b"", b"x" * 31, b"x" * 33, "untrusted"])
def test_wrong_key_shape_is_refused_without_native_crypto_use(bad, monkeypatch):
    from provelume import mirror_ssh_crypto

    monkeypatch.setattr(mirror_ssh_crypto, "library", lambda: pytest.fail("native crypto used"))
    with pytest.raises(MirrorError, match="ssh_key"):
        public_key(bad)


def agent_fixture(*, deadline=None):
    import secrets

    from provelume.mirror_ssh_agent import AgentProtocol, field, public_blob

    seed, host_seed, session = (secrets.token_bytes(32) for _ in range(3))
    host = public_blob(public_key(host_seed))
    agent = AgentProtocol(seed, host_public_blob=host, username="synthetic", deadline=deadline)
    signature = field(b"ssh-ed25519") + field(sign(host_seed, session))
    binding = (
        b"\x1b"
        + field(b"session-bind@openssh.com")
        + field(host)
        + field(session)
        + field(signature)
        + b"\0"
    )
    return agent, host_seed, session, binding


def auth_request(
    agent, session, *, username=b"synthetic", method=b"publickey", service=b"ssh-connection"
):
    from provelume.mirror_ssh_agent import field

    data = (
        field(session)
        + b"\x32"
        + field(username)
        + field(service)
        + field(method)
        + b"\x01"
        + field(b"ssh-ed25519")
        + field(agent.public)
    )
    if method == b"publickey-hostbound-v00@openssh.com":
        data += field(agent.host_public_blob)
    return b"\x0d" + field(agent.public) + field(data) + b"\0" * 4, data


@pytest.mark.parametrize("method", [b"publickey", b"publickey-hostbound-v00@openssh.com"])
def test_owned_agent_signs_one_exact_host_bound_user_authentication(method):
    from provelume.mirror_ssh_agent import Wire, decode_public

    agent, _host_seed, session, binding = agent_fixture()
    assert agent.handle(b"\x0b").startswith(b"\x0c\0\0\0\x01")
    assert agent.handle(binding) == b"\x06"
    request, data = auth_request(agent, session, method=method)
    response = Wire(agent.handle(request))
    assert response.byte() == 14
    signature = Wire(response.string(128))
    response.end()
    assert signature.string(32) == b"ssh-ed25519"
    assert verify(decode_public(agent.public), data, signature.string(64))
    signature.end()
    assert agent.signatures == 1
    assert agent.handle(request) == b"\x05"  # No second auth/retry signer.


@pytest.mark.parametrize("wrong", ["unbound", "user", "session", "service", "method", "flags"])
def test_agent_never_signs_a_request_outside_its_predeclared_context(wrong, monkeypatch):
    from provelume import mirror_ssh_agent

    agent, _host_seed, session, binding = agent_fixture()
    if wrong != "unbound":
        assert agent.handle(binding) == b"\x06"
    request, _data = auth_request(
        agent,
        b"x" * 32 if wrong == "session" else session,
        username=b"other" if wrong == "user" else b"synthetic",
        service=b"other" if wrong == "service" else b"ssh-connection",
        method=b"password" if wrong == "method" else b"publickey",
    )
    if wrong == "flags":
        request = request[:-4] + b"\0\0\0\x01"
    monkeypatch.setattr(mirror_ssh_agent, "sign", lambda *_: pytest.fail("unauthorized signing"))
    assert agent.handle(request) == b"\x05"
    assert agent.signatures == 0


@pytest.mark.parametrize("wrong", ["key", "signature", "forwarded"])
def test_agent_refuses_wrong_host_key_signature_and_forwarded_session(wrong):
    agent, _host_seed, _session, binding = agent_fixture()
    if wrong == "key":
        binding = binding[:60] + bytes([binding[60] ^ 1]) + binding[61:]
    elif wrong == "signature":
        binding = binding[:-2] + bytes([binding[-2] ^ 1]) + binding[-1:]
    else:
        binding = binding[:-1] + b"\x01"
    assert agent.handle(binding) == b"\x05" and agent.session is None


def test_agent_expiry_and_malformed_frames_are_closed_without_secret_response():
    agent, _host_seed, _session, binding = agent_fixture(deadline=-1)
    assert agent.handle(binding) == b"\x05"
    for payload in [b"", b"\x0bextra", b"\x0d\xff\xff\xff\xff", b"x" * 32769, b"\x11"]:
        agent, *_ = agent_fixture()
        assert agent.handle(payload) == b"\x05"
        assert agent.signatures == 0


def test_actual_contained_agent_worker_signs_through_private_ipc_and_has_no_key_file():
    import base64
    import os
    import secrets
    import socket
    import struct
    from contextlib import ExitStack
    from pathlib import Path

    from provelume.mirror_ssh_agent import field, public_blob
    from provelume.mirror_ssh_agent_process import AgentWorker

    seed, host_seed, session = (secrets.token_bytes(32) for _ in range(3))
    host = public_blob(public_key(host_seed))
    identity = public_blob(public_key(seed))
    with AgentWorker(seed, host_public_blob=host, username="synthetic") as owned:
        endpoint = owned.endpoint
        root = owned.output.parent

        def read(receive, length):
            data = b""
            while len(data) < length:
                chunk = receive(length - len(data))
                assert chunk
                data += chunk
            return data

        with ExitStack() as resources:
            if os.name == "nt":
                connection = resources.enter_context(open(endpoint, "r+b", buffering=0))
                receive = connection.read

                def send(payload):
                    assert connection.write(payload) == len(payload)

            else:
                connection = resources.enter_context(
                    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                )
                connection.settimeout(2)
                connection.connect(endpoint)
                receive, send = connection.recv, connection.sendall

            def request(payload):
                send(struct.pack(">I", len(payload)) + payload)
                return read(receive, struct.unpack(">I", read(receive, 4))[0])

            signature = field(b"ssh-ed25519") + field(sign(host_seed, session))
            assert (
                request(
                    b"\x1b"
                    + field(b"session-bind@openssh.com")
                    + field(host)
                    + field(session)
                    + field(signature)
                    + b"\0"
                )
                == b"\x06"
            )
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
            assert request(b"\x0d" + field(identity) + field(data) + b"\0" * 4).startswith(b"\x0e")
        for path in root.rglob("*"):
            if path.is_file():
                value = path.read_bytes()
                leaked = seed in value or base64.b64encode(seed) in value
                assert not leaked
    assert owned.report["signatures"] == 1 and owned.report["host_bound"]
    assert (os.name == "nt" or not Path(endpoint).exists()) and not root.exists()
