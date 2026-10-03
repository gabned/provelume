"""Synthetic-only S03 harness and disposable loopback fixture, never installed."""

import json
import socket
import threading
from contextlib import contextmanager
from dataclasses import replace

from ai_context_fakes import candidate, context_case, context_plan

from provelume.ai_context import preview_context
from provelume.ai_contract import Assurance, Locality, digest
from provelume.ai_provider import (
    CallInputs,
    CredentialReference,
    Destination,
    ProviderConfig,
    Transmission,
)
from provelume.ai_provider_http import CheckedCall, SecretLease
from provelume.representations import canonical_json_bytes

SYNTHETIC_SECRET = "synthetic-only-token"


def provider_case(url="http://127.0.0.1:44859/v1/chat/completions", *, config=None):
    config = config or ProviderConfig(
        url, Destination.MANAGED, CredentialReference("system_keyring", "synthetic.ai")
    )
    source, selections, current, gateway = context_case()
    profile = replace(
        gateway["profiles"][0], provider="synthetic_compatible", route_revision=config.fingerprint
    )
    evidence = replace(gateway["evidence"][0], profile_fingerprint=profile.fingerprint)
    if config.destination in (Destination.LAN, Destination.REMOTE):
        evidence = replace(evidence, locality=Locality.REMOTE, assurance=Assurance.REMOTE)
    elif config.destination == Destination.UNKNOWN:
        evidence = replace(evidence, locality=Locality.UNKNOWN, assurance=Assurance.UNQUALIFIED)
    gateway.update(
        profiles=(profile, gateway["profiles"][1]), evidence=(evidence, gateway["evidence"][1])
    )
    preview = preview_context(source, selections, **current)
    plan = context_plan(preview, source, selections, current, gateway)
    return CallInputs(
        plan, preview, source, selections, current, gateway["profiles"], gateway["evidence"], config
    )


class SyntheticVault:
    def __init__(self):
        self.calls = 0
        self.active = True

    def __call__(self, reference, profile, transport):
        self.calls += 1
        return SecretLease(reference, profile, transport, SYNTHETIC_SECRET, self.active)


class SyntheticAdapter:
    """Same checked operation/result contract; no DNS, vault or socket dependency."""

    def exchange(self, current, *, cancel):
        from provelume.ai_provider_http import _Control

        call = CheckedCall(current)
        _Control(cancel, call.request.limits.max_seconds).poll()
        return call.accept(candidate(call.initial.preview), Transmission.NOT_SENT)


def completion(inputs, *, content=None, **changes):
    return canonical_json_bytes(
        {
            "id": "synthetic-response",
            "object": "chat.completion",
            "created": 1,
            "model": inputs.profiles[0].model,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": (
                            candidate(inputs.preview) if content is None else content
                        ).decode(),
                    },
                }
            ],
            **changes,
        }
    )


def response(body, *, status=200, headers=()):
    fields = [("Content-Type", "application/json"), ("Content-Length", str(len(body))), *headers]
    return (
        f"HTTP/1.1 {status} Synthetic\r\n" + "".join(f"{k}: {v}\r\n" for k, v in fields) + "\r\n"
    ).encode() + body


@contextmanager
def local_server(handler, *, ipv6=False):
    """An owned ephemeral HTTP fixture, never an existing provider/LAN service."""
    server = socket.socket(socket.AF_INET6 if ipv6 else socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("::1" if ipv6 else "127.0.0.1", 0))
    server.listen(4)
    server.settimeout(0.05)
    stopped = threading.Event()
    requests, connections, failures = [], [], []

    def serve():
        while not stopped.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                connections.append(True)
                conn.settimeout(2)
                try:
                    data = b""
                    while b"\r\n\r\n" not in data and len(data) < 16384:
                        chunk = conn.recv(1)
                        if not chunk:
                            break
                        data += chunk
                    if not data:  # Connection-only diagnostic deliberately sends no HTTP.
                        continue
                    header, _, body = data.partition(b"\r\n\r\n")
                    headers = dict(line.split(b": ", 1) for line in header.split(b"\r\n")[1:])
                    length = int(headers[b"Content-Length"])
                    while len(body) < length:
                        chunk = conn.recv(length - len(body))
                        if not chunk:
                            break
                        body += chunk
                    requests.append((header, json.loads(body)))
                    output = handler(requests[-1])
                    if output:
                        conn.sendall(output)
                except (OSError, ValueError, KeyError) as error:
                    failures.append(type(error).__name__)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    host = "[::1]" if ipv6 else "127.0.0.1"
    try:
        yield {
            "url": f"http://{host}:{server.getsockname()[1]}/v1/chat/completions",
            "requests": requests,
            "connections": connections,
            "failures": failures,
        }
    finally:
        stopped.set()
        server.close()
        thread.join(3)
        assert not thread.is_alive()


def changed_rules(inputs, **changes):
    current = {
        **inputs.current,
        "rules": (
            replace(inputs.current["rules"][0], revision=digest("changed"), **changes),
            *inputs.current["rules"][1:],
        ),
    }
    return replace(inputs, current=current)
