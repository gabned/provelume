"""Bounded native model acquisition over an instrumented HTTPS wire."""

import socket
import ssl
import time
from dataclasses import replace

import pytest
from test_ai_model_download import ADDRESS, Wire, response

from provelume.ai_model_download import ArtifactDownload
from provelume.ai_models import ModelError, ModelRegistry
from provelume.ai_runtime_contract import MODEL_ID


class NativeTLS:
    check_hostname = True
    verify_mode = ssl.CERT_REQUIRED

    def __init__(self):
        self.hosts = []

    def wrap_socket(self, wire, *, server_hostname):
        self.hosts.append(server_hostname)
        return wire


def native_response(data):
    return response(headers=[b"Content-Length: " + str(len(data)).encode(),
                             b"Content-Type: application/octet-stream"], body=data)


def acquire(wires, data, *, cancel=lambda: False, addresses=None):
    calls = []
    tls = NativeTLS()

    def resolve(host, *_args, **_kwargs):
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
                for ip in (addresses or [ADDRESS])]

    remaining = iter(wires)
    transport = ArtifactDownload(resolver=resolve, connector=lambda *_: next(remaining),
                                 tls_context=tls)
    entry = replace(ModelRegistry.packaged().entry(MODEL_ID), package_size=len(data))
    chunks = list(transport.fetch(entry, cancel=cancel, deadline=time.monotonic() + 5))
    return chunks, calls, tls.hosts


def test_native_download_retains_buffered_body_and_follows_only_reviewed_https_cdn():
    data = b"GGUF\x03\0\0\0" + b"public inert bytes" * 10000
    redirect = Wire(response(status=b"HTTP/1.1 302 Found", headers=[
        b"Location: https://cas-bridge.xethub.hf.co/public/model?signature=synthetic",
        b"Set-Cookie: never-forward=this-value",
    ], body=b""))
    wire = Wire(native_response(data))
    chunks, hosts, sni = acquire([redirect, wire], data)
    assert b"".join(chunks) == data
    assert max(map(len, chunks)) <= 65536
    assert len(chunks) < len(data) // 4096
    assert hosts == sni == ["huggingface.co", "cas-bridge.xethub.hf.co"]
    assert all(w.closed for w in (redirect, wire))
    assert b"Accept: application/octet-stream" in redirect.sent[0]
    assert b"Cookie:" not in wire.sent[0] and b"Authorization:" not in wire.sent[0]
    assert wire.sent[0].startswith(b"GET /public/model?signature=synthetic HTTP/1.1\r\n")


@pytest.mark.parametrize("location", [
    "http://huggingface.co/model", "https://unreviewed.example/model",
    "https://huggingface.co.evil.example/model", "https://user@huggingface.co/model",
    "https://huggingface.co:444/model", "https://127.0.0.1/model",
    "https://huggingface.co/model#x", "https://huggingface.co/a/../model",
    "https://huggingface.co/%2e%2e/model", "https://huggingface.co/a\\b",
    "https://huggingface.co/model?" + "x" * 8192,
])
def test_native_redirect_is_refused_before_any_second_connection(location):
    wire = Wire(response(status=b"HTTP/1.1 302 Found",
                         headers=[b"Location: " + location.encode()], body=b""))
    with pytest.raises(ModelError, match="origin|limit"):
        acquire([wire], b"public bytes")
    assert wire.closed and len(wire.sent) == 1


def test_native_redirect_budget_has_no_retry():
    wires = [Wire(response(status=b"HTTP/1.1 307 Temporary Redirect", headers=[
        f"Location: https://huggingface.co/public/{i}".encode()], body=b"")) for i in range(4)]
    with pytest.raises(ModelError, match="limit"):
        acquire(wires, b"public bytes")
    assert all(w.closed and len(w.sent) == 1 for w in wires)


@pytest.mark.parametrize("headers,body", [
    ([b"Content-Length: 1", b"Content-Type: application/octet-stream"], b"x"),
    ([b"Content-Length: 12", b"Content-Type: text/html"], b"public bytes"),
    ([b"Content-Length: 12", b"Content-Type: application/octet-stream",
      b"Transfer-Encoding: chunked"], b"public bytes"),
    ([b"Content-Length: 12", b"Content-Type: application/octet-stream",
      b"Content-Encoding: gzip"], b"public bytes"),
    ([b"Content-Length: 12", b"Content-Type: application/octet-stream"], b"short"),
    ([b"Content-Length: 12", b"Content-Type: application/octet-stream"], b"public bytesEXCESS"),
])
def test_native_wrong_framing_never_publishes_bytes(headers, body):
    wire = Wire(response(headers=headers, body=body))
    with pytest.raises(ModelError):
        acquire([wire], b"public bytes")
    assert wire.closed


def test_native_dns_answers_and_cancel_before_resolution_are_enforced():
    wire = Wire(native_response(b"public bytes"))
    with pytest.raises(ModelError, match="network"):
        acquire([wire], b"public bytes", addresses=[ADDRESS, "127.0.0.1"])
    assert not wire.sent
    with pytest.raises(ModelError, match="cancelled"):
        acquire([], b"public bytes", cancel=lambda: True)
