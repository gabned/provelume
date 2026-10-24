from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import socket
import struct
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from provelume import startup_process as process_module
from provelume import startup_readiness as protocol
from provelume.desktop import STRINGS, DesktopShell, _command_for_backend
from provelume.maintenance_local_files import MaintenanceTargetError, open_local_directory
from provelume.service import ProvelumeInstance
from provelume.shell_settings import LauncherSettings, ShellSettingsManager, settings_path
from provelume.startup_process import ManagedStartup
from provelume.web import create_app

SECRETS = protocol.StartupSecrets("12" * 16, bytes(range(32)))
CHALLENGE = "34" * 32
ROOT_BINDING = "posix.file-id.v1:" + "56" * 16


def context(port=44851):
    value = protocol.ReadinessContext(SECRETS, ROOT_BINDING, port)
    value.bind_opened_instance("inst_synthetic")
    return value


def verify(raw, status=200, *, challenge=CHALLENGE):
    return protocol.verify_response(
        raw,
        status,
        secrets=SECRETS,
        binding=SECRETS.instance_binding("inst_synthetic", ROOT_BINDING, 44851),
        port=44851,
        challenge=challenge,
    )


def test_bootstrap_stream_is_bounded_chunked_and_content_free_in_repr():
    class Chunked(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(1, size))

    frame = SECRETS.bootstrap_frame()
    assert len(frame) <= 260
    assert protocol.read_bootstrap(Chunked(frame)) == SECRETS
    assert SECRETS.key.hex() not in repr(SECRETS)
    assert SECRETS.startup_id not in repr(SECRETS)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\0\0",
        struct.pack(">I", 0),
        struct.pack(">I", 257),
        struct.pack(">I", 1) + b"{",
        SECRETS.bootstrap_frame() + b"x",
        json.dumps({"version": True, "startup_id": "12" * 16, "key": "00" * 32}).encode(),
        b'{"version":1,"version":1,"startup_id":"' + b"12" * 16 + b'","key":"' + b"00" * 32 + b'"}',
        json.dumps(
            {"version": 1, "startup_id": "12" * 16, "key": "00" * 32, "extra": "not permitted"}
        ).encode(),
        '{"version":1}'.encode("utf-16"),
    ],
)
def test_bootstrap_rejects_truncation_extra_data_duplicate_keys_and_non_utf8(data):
    if data.startswith((b"{", b"\xff\xfe")):
        data = struct.pack(">I", len(data)) + data
    with pytest.raises(protocol.StartupReadinessError, match="bootstrap_failed"):
        protocol.read_bootstrap(io.BytesIO(data))


def test_proof_uses_the_specified_framing_not_json_order_or_path_strings():
    value = context()
    value.mark_ready()
    status, body = value.response(CHALLENGE)
    fields = [
        "provelume.startup-readiness.proof.v1",
        protocol.CONTRACT,
        "1",
        SECRETS.startup_id,
        CHALLENGE,
        body["instance_binding"],
        "44851",
        "ready",
        "operational",
        "not_requested",
    ]
    reference = b"".join(len(x.encode()).to_bytes(4, "big") + x.encode() for x in fields)
    assert body["proof"] == hmac.new(SECRETS.key, reference, hashlib.sha256).hexdigest()
    raw = json.dumps(dict(reversed(list(body.items()))), indent=2).encode()
    assert verify(raw, status)["backend_state"] == "ready"
    assert b"inst_synthetic" not in raw and ROOT_BINDING.encode() not in raw
    assert SECRETS.key.hex().encode() not in raw
    assert (
        SECRETS.instance_binding("inst_synthetic", ROOT_BINDING, 44852) != body["instance_binding"]
    )
    with pytest.raises(protocol.StartupReadinessError, match="readiness_binding_failed"):
        verify(raw, challenge="78" * 32)


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("version", True),
        ("version", 1.0),
        ("version", 2),
        ("port", True),
        ("port", 44852),
        ("startup_id", "99" * 16),
        ("challenge", "99" * 32),
        ("instance_binding", "99" * 32),
        ("proof", "99" * 32),
        ("diagnostics_state", "invented"),
        ("backend_state", "invented"),
        ("reason", ""),
        ("extra", "not permitted"),
    ],
)
def test_response_schema_identity_and_signed_states_fail_closed(key, bad):
    c = context()
    c.mark_ready()
    _, body = c.response(CHALLENGE)
    body[key] = bad
    with pytest.raises(protocol.StartupReadinessError):
        verify(json.dumps(body).encode())


def test_response_duplicate_keys_oversize_non_utf8_and_wrong_status_are_rejected():
    c = context()
    c.mark_ready()
    _, body = c.response(CHALLENGE)
    raw = json.dumps(body).encode()
    for data, status in [
        (raw[:-1] + b',"version":1}', 200),
        (b" " * 2049, 200),
        (json.dumps(body).encode("utf-16"), 200),
        (raw, 503),
    ]:
        with pytest.raises(protocol.StartupReadinessError):
            verify(data, status)
    status, body = context().response(CHALLENGE)
    assert status == 503
    assert verify(json.dumps(body).encode(), status)["backend_state"] == "starting"


@contextmanager
def responder(handler):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(3)
        port = server.getsockname()[1]
        errors = []

        def serve():
            try:
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(2)
                    request = bytearray()
                    while b"\r\n\r\n" not in request:
                        block = conn.recv(4096)
                        if not block:
                            return
                        request.extend(block)
                    handler(conn, bytes(request), port)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                pass
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield port
        finally:
            thread.join(timeout=3)
            assert not thread.is_alive() and not errors


def test_probe_uses_direct_challenge_route_and_verifies_a_complete_response(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://invalid.invalid:1")

    def respond(conn, request, port):
        assert request.startswith(b"GET /internal/startup-readiness HTTP/1.1\r\n")
        assert (protocol.CHALLENGE_HEADER + ": " + CHALLENGE).encode() in request
        assert SECRETS.key.hex().encode() not in request
        ctx = context(port)
        ctx.mark_ready()
        _, body = ctx.response(CHALLENGE)
        raw = json.dumps(body).encode()
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(raw)).encode()
            + b"\r\n\r\n"
            + raw
        )

    with responder(respond) as port:
        value = protocol.probe(
            secrets=SECRETS,
            binding=SECRETS.instance_binding("inst_synthetic", ROOT_BINDING, port),
            port=port,
            challenge=CHALLENGE,
            deadline=time.monotonic() + 1,
            cancelled=threading.Event(),
        )
        assert value["backend_state"] == "ready"


@pytest.mark.parametrize(
    "reply",
    [
        b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1\r\nContent-Length: 0\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\n\r\nok",
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2049\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n",
    ],
)
def test_probe_refuses_redirects_generic_200_and_unbounded_or_ambiguous_bodies(reply):
    with (
        responder(lambda conn, *_: conn.sendall(reply)) as port,
        pytest.raises(protocol.StartupReadinessError),
    ):
        protocol.probe(
            secrets=SECRETS,
            binding="00" * 32,
            port=port,
            challenge=CHALLENGE,
            deadline=time.monotonic() + 1,
            cancelled=threading.Event(),
        )


def test_probe_absolute_deadline_does_not_restart_for_slow_drip_bytes():
    def drip(conn, *_):
        for _ in range(10):
            conn.sendall(b"H")
            time.sleep(0.04)

    with responder(drip) as port:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            protocol.probe(
                secrets=SECRETS,
                binding="00" * 32,
                port=port,
                challenge=CHALLENGE,
                deadline=start + 0.12,
                cancelled=threading.Event(),
            )
        assert time.monotonic() - start < 0.8


def test_opened_directory_identity_is_physical_and_replacement_is_refused(tmp_path):
    root = tmp_path / "Instance"
    root.mkdir()
    with open_local_directory(root) as (_, first):
        with open_local_directory(root) as (_, second):
            assert first == second
        assert first.startswith("win32.file-id.v1:" if os.name == "nt" else "posix.file-id.v1:")
        if os.name == "nt":
            with pytest.raises(OSError):
                root.rename(tmp_path / "moved")
    root.rename(tmp_path / "moved")
    root.mkdir()
    with open_local_directory(root) as (_, replacement):
        assert first != replacement


def test_directory_binding_rejects_a_file_and_reparse_alias(tmp_path):
    regular = tmp_path / "not-a-directory"
    regular.write_text("synthetic")
    with pytest.raises(MaintenanceTargetError), open_local_directory(regular):
        pytest.fail("file accepted as directory")
    root = tmp_path / "Instance"
    root.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("host cannot create synthetic reparse/symlink fixture")
    with pytest.raises(MaintenanceTargetError), open_local_directory(alias):
        pytest.fail("reparse alias accepted")


@pytest.mark.skipif(os.name == "nt", reason="POSIX replacement detection; Windows denies rename")
def test_posix_root_swap_is_reported_on_guard_release(tmp_path):
    root = tmp_path / "Instance"
    root.mkdir()
    with pytest.raises(MaintenanceTargetError), open_local_directory(root):
        root.rename(tmp_path / "moved")
        root.mkdir()


def test_private_route_is_absent_without_bootstrap_and_never_calls_deep_health(
    tmp_path, monkeypatch
):
    root = tmp_path / "Instance"
    ProvelumeInstance.initialise(root)
    normal = create_app(root, shell_settings_file=tmp_path / "settings.json")
    with TestClient(normal) as client:
        assert client.get(protocol.ROUTE).status_code == 404
    with open_local_directory(root) as (_, identity):
        ctx = protocol.ReadinessContext(SECRETS, identity, 44851)
        app = create_app(
            root, shell_settings_file=tmp_path / "settings.json", effective_port=44851, _startup=ctx
        )
    instance = app.state.provelume

    def deep_summary():
        raise RuntimeError("deep summary called")

    def deep_health():
        raise RuntimeError("deep health called")

    monkeypatch.setattr(instance, "instance_summary", deep_summary)
    monkeypatch.setattr(instance, "knowledge_health", deep_health)
    with TestClient(app) as client:
        reply = client.get(protocol.ROUTE, headers={protocol.CHALLENGE_HEADER: CHALLENGE})
        assert reply.status_code == 200 and reply.json()["diagnostics_state"] == "not_requested"
        assert client.get(protocol.ROUTE).status_code == 400
        assert (
            client.get(
                protocol.ROUTE + "?x=1", headers={protocol.CHALLENGE_HEADER: CHALLENGE}
            ).status_code
            == 400
        )
        assert client.post(protocol.ROUTE).status_code == 405
        for url in ["/search", "/search?q=%20%20", "/about"]:
            response = client.get(url)
            assert response.status_code == 200
        with pytest.raises(RuntimeError, match="deep summary called"):
            client.get("/health")


def test_invalid_installation_cannot_become_private_ready(tmp_path, monkeypatch):
    import provelume.web as web

    monkeypatch.setattr(
        web, "verify_current_installation", lambda: {"status": "modified_installation"}
    )
    monkeypatch.setattr(
        web, "ProvelumeInstance", lambda *_: pytest.fail("opened after integrity fail")
    )
    with pytest.raises(protocol.StartupReadinessError, match="startup_integrity_failed"):
        create_app(tmp_path / "must-not-open", effective_port=44851, _startup=context())


@pytest.mark.parametrize("status", ["verification_unavailable", "not_run", None])
def test_frozen_private_startup_requires_verified_package_before_instance_open(
    tmp_path, monkeypatch, status
):
    import provelume.web as web

    monkeypatch.setattr(web.sys, "frozen", True, raising=False)
    monkeypatch.setattr(web, "verify_current_installation", lambda: {"status": status})
    monkeypatch.setattr(
        web, "ProvelumeInstance", lambda *_: pytest.fail("opened without package integrity")
    )
    with pytest.raises(protocol.StartupReadinessError, match="startup_integrity_failed"):
        create_app(tmp_path / "must-not-open", effective_port=44851, _startup=context())


def test_real_source_child_bootstrap_readiness_cancellation_and_cleanup(tmp_path, monkeypatch):
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    else:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "Instance"
    ProvelumeInstance.initialise(root)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    manager = ShellSettingsManager(
        settings_path(),
        LauncherSettings(instance_path=str(root), endpoint_port=port, last_good_port=port),
    )
    manager.save(manager.load().settings)
    startup = ManagedStartup(root, manager, _command_for_backend)
    startup.start()
    deadline = time.monotonic() + 25
    try:
        while startup.phase != "RUNNING" and not startup.done.is_set():
            assert time.monotonic() < deadline, startup.diagnostic_snapshot()
            time.sleep(0.025)
        assert startup.phase == "RUNNING", startup.diagnostic_snapshot()
        assert startup.process.poll() is None and startup.probes <= 240
    finally:
        startup.request_stop()
        assert startup.done.wait(8), startup.diagnostic_snapshot()
    assert startup.process.poll() is not None
    assert startup.phase == "STOPPED"
    assert "operational" in {x["code"] for x in startup.diagnostic_snapshot()}


class Value:
    def set(self, value):
        self.value = value


class Button:
    def configure(self, **values):
        self.state = values["state"]


def test_shell_refuses_to_forget_an_unowned_live_process_and_blocks_retry(monkeypatch):
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: pytest.fail("unowned terminate"))
    shell = DesktopShell.__new__(DesktopShell)
    shell._startup = None
    shell.server = process
    shell.server_ready = True
    shell.server_port = 44851
    shell.closed = False
    shell.text = STRINGS["en"]
    shell.status = Value()
    shell.open_button = Button()
    shell.stop_button = Button()
    shell.stop_server()
    assert shell.server is process and not shell.server_ready
    assert shell.status.value == STRINGS["en"]["startup_stop_unconfirmed"]
    assert shell.open_button.state == "disabled"
    monkeypatch.setattr(
        process_module.subprocess, "Popen", lambda *_a, **_k: pytest.fail("new child")
    )
    shell.restart_server()
    assert shell.server is process
