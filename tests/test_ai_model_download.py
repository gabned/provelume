from __future__ import annotations

import socket
import ssl
import time

import pytest
from ai_model_fixtures import package

from provelume import ai_model_download as download
from provelume.ai_model_download import ArtifactDownload
from provelume.ai_models import ModelError, ModelRegistry, artifact_url

ADDRESS = "8.8.8.8"


def resolver(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ADDRESS, 443))]


class Wire:
    def __init__(self, data, *, peer=(ADDRESS, 443)):
        self.data = bytearray(data)
        self.peer = peer
        self.sent = []
        self.closed = False

    def getpeername(self):
        return self.peer

    def settimeout(self, value):
        assert 0 < value <= 2

    def sendall(self, raw):
        self.sent.append(raw)

    def recv(self, amount):
        raw = bytes(self.data[:amount])
        del self.data[:amount]
        return raw

    def close(self):
        self.closed = True


class TLS:
    check_hostname = True
    verify_mode = ssl.CERT_REQUIRED

    def wrap_socket(self, wire, *, server_hostname):
        assert server_hostname == "fixtures.invalid"
        return wire


def response(*, status=b"HTTP/1.1 200 OK", headers=None, body=None):
    raw = package() if body is None else body
    if headers is None:
        headers = [b"Content-Length: " + str(len(package())).encode(),
                   b"Content-Type: application/zip"]
    return status + b"\r\n" + b"\r\n".join(headers) + b"\r\n\r\n" + raw


def fetch(wire, **kwargs):
    adapter = ArtifactDownload(resolver=resolver,
                               connector=lambda *_: wire, tls_context=TLS())
    for key, value in kwargs.items():
        setattr(adapter, "_" + key, value)
    return b"".join(adapter.fetch(ModelRegistry.packaged().entry("fixture.model-v1"),
                                  cancel=lambda: False, deadline=time.monotonic() + 5))


def test_real_get_framing_and_ambient_environment_ignored(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://synthetic-secret@invalid")
    monkeypatch.setenv("NETRC", "synthetic-missing")
    wire = Wire(response())
    assert fetch(wire) == package()
    assert wire.closed
    assert wire.sent == [
        b"GET /custodia/model-v1.zip HTTP/1.1\r\nHost: fixtures.invalid\r\n"
        b"Accept: application/zip\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n"
    ]


@pytest.mark.parametrize("status", [b"HTTP/1.1 301 Moved Permanently", b"HTTP/1.1 302 Found",
                                    b"HTTP/1.1 307 Temporary Redirect", b"HTTP/1.1 401 No",
                                    b"HTTP/1.1 206 Partial Content", b"HTTP/2 200 OK"])
def test_redirect_and_non_200_refused_without_second_request(status):
    wire = Wire(response(status=status))
    with pytest.raises(ModelError):
        fetch(wire)
    assert len(wire.sent) == 1 and wire.closed


@pytest.mark.parametrize("headers", [
    [], [b"Content-Length: 999999999", b"Content-Type: application/zip"],
    [b"Content-Length: 1", b"Content-Length: 1"],
    [b" Transfer-Encoding: chunked"], [b"Invalid"], [b"X: " + b"x" * 17000],
    [b"X-" + str(i).encode() + b": x" for i in range(33)],
    [b"Content-Length: " + str(len(package())).encode(), b"Content-Type: text/html"],
    [b"Content-Length: " + str(len(package())).encode(), b"Content-Type: application/zip",
     b"Content-Encoding: gzip"],
    [b"Content-Length: " + str(len(package())).encode(), b"Content-Type: application/zip",
     b"Transfer-Encoding: chunked"],
])
def test_header_framing_encoding_and_accumulation_limits(headers):
    wire = Wire(response(headers=headers))
    with pytest.raises(ModelError):
        fetch(wire)
    assert wire.closed


@pytest.mark.parametrize("url", ["http://fixtures.invalid/a", "https://u:p@fixtures.invalid/a",
                                 "https://fixtures.invalid:444/a", "https://fixtures.invalid/a#x",
                                 "https://fixtures.invalid/a?token=secret", "https://x/%2e%2e/a",
                                 "https://x/../a", "file:///a", "https://x\\y/a"])
def test_url_closed_matrix(url):
    with pytest.raises(ModelError):
        artifact_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.2", "169.254.169.254", "::1",
                                     "::ffff:127.0.0.1", "fe80::1", "fc00::1"])
def test_all_dns_answers_checked_before_connect(address):
    wire = Wire(response())
    rows = resolver() + [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    with pytest.raises(ModelError):
        fetch(wire, resolver=lambda *_args, **_kwargs: rows)
    assert wire.sent == []


def test_peer_port_mismatch_and_insecure_tls_refused():
    for peer in (("1.1.1.1", 443), (ADDRESS, 444)):
        wire = Wire(response(), peer=peer)
        with pytest.raises(ModelError):
            fetch(wire)
        assert wire.sent == [] and wire.closed
    tls = TLS()
    tls.check_hostname = False
    wire = Wire(response())
    with pytest.raises(ModelError):
        fetch(wire, tls_context=tls)
    assert wire.sent == []


def test_truncation_timeout_cancellation_and_no_retry():
    wire = Wire(response(body=package()[:30]))
    with pytest.raises(ModelError, match="integrity"):
        fetch(wire)
    assert len(wire.sent) == 1
    calls = []

    def timeout(*_):
        calls.append(1)
        raise TimeoutError("SYNTHETIC_SECRET")

    with pytest.raises(ModelError, match="timeout") as error:
        fetch(Wire(response()), connector=timeout)
    assert len(calls) == 1 and "SYNTHETIC_SECRET" not in str(error.value)
    adapter = ArtifactDownload(resolver=lambda *_args, **_kwargs: calls.append(2))
    entry = ModelRegistry.packaged().entry("fixture.model-v1")
    with pytest.raises(ModelError, match="cancelled"):
        list(adapter.fetch(entry, cancel=lambda: True, deadline=time.monotonic() + 5))
    with pytest.raises(ModelError, match="timeout"):
        list(adapter.fetch(entry, cancel=lambda: False, deadline=time.monotonic() - 1))
    assert calls == [1]


@pytest.mark.parametrize("where", ["constructor", "start"])
def test_dns_worker_start_failure_releases_slot_without_retry(monkeypatch, where):
    calls = []
    original = download.threading.Thread

    def broken(*_args, **_kwargs):
        if where == "constructor":
            raise RuntimeError("worker unavailable")

        class Worker:
            def start(self):
                raise RuntimeError("worker unavailable")

        return Worker()

    monkeypatch.setattr(download.threading, "Thread", broken)
    with pytest.raises(ModelError, match="network"):
        fetch(Wire(response()), resolver=lambda *_args, **_kwargs: calls.append(1))
    assert not calls
    monkeypatch.setattr(download.threading, "Thread", original)
    assert fetch(Wire(response())) == package()
