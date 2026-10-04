"""Single-attempt pinned HTTP/1.1 transport, exercised only by synthetic fixtures.

No HTTP library/SDK retry, proxy, netrc, redirect, cookies or ambient auth. A
numeric socket address is used after one bounded resolution; TLS uses the original
hostname. Headers are bounded while reading, before a general HTTP parser can
accumulate them. Only identity-encoded Content-Length responses are supported.
"""

from __future__ import annotations

import errno
import json
import re
import select
import socket
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address

from .ai_contract import AiContractError
from .ai_provider import (
    CallInputs,
    CredentialReference,
    Failure,
    ProviderError,
    Transmission,
    accept_candidate,
    admit_address,
    check,
    endpoint,
    wire_request,
)

_DNS_SLOT = threading.BoundedSemaphore(1)
_SECRET_SLOT = threading.BoundedSemaphore(1)
_HEADER = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")


class Cancellation:
    def __init__(self, *, probe=None):
        self._event = threading.Event()
        self._probe = probe

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set() or (self._probe is not None and self._probe())


class _Control:
    def __init__(self, cancel, seconds):
        check(type(cancel) is Cancellation)
        self.cancel = cancel
        self.deadline = time.monotonic() + seconds
        self.transmission = Transmission.NOT_SENT

    def poll(self):
        if self.cancel.cancelled:
            raise ProviderError(Failure.CANCELLED, self.transmission)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderError(Failure.TIMEOUT, self.transmission)
        return min(remaining, 0.05)


@dataclass(frozen=True, slots=True, repr=False)
class SecretLease:
    """External vault response, ephemeral and never serializable as a Contract."""

    reference: CredentialReference
    profile_fingerprint: str
    transport_fingerprint: str
    value: str
    active: bool


def _external(function, slot, control, failure):
    """Bound caller wait and outstanding workers; never continue a timed-out call."""
    control.poll()
    check(slot.acquire(blocking=False), failure)
    done, result = threading.Event(), []

    def work():
        try:
            result.append(function())
        except Exception:
            result.append(None)
        finally:
            slot.release()
            done.set()

    try:
        threading.Thread(target=work, daemon=True, name="ai-provider-lookup").start()
    except Exception:
        # No worker owns the slot when construction/start fails. Preserve the
        # caller's transmission state and expose only the closed failure code.
        slot.release()
        raise ProviderError(failure, control.transmission) from None
    while not done.wait(control.poll()):
        pass
    control.poll()
    check(result and result[0] is not None, failure)
    return result[0]


def _secret(resolver, inputs, profile, control):
    reference = inputs.config.credential
    if reference is None:
        return None
    try:
        lease = _external(
            lambda: resolver(reference, profile.fingerprint, inputs.config.fingerprint),
            _SECRET_SLOT,
            control,
            Failure.CREDENTIAL,
        )
        check(type(lease) is SecretLease and lease.active is True, Failure.CREDENTIAL)
        check(
            lease.reference == reference
            and lease.profile_fingerprint == profile.fingerprint
            and lease.transport_fingerprint == inputs.config.fingerprint,
            Failure.CREDENTIAL,
        )
        check(type(lease.value) is str and 1 <= len(lease.value) <= 2048, Failure.CREDENTIAL)
        check(re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", lease.value) is not None, Failure.CREDENTIAL)
        return lease.value
    except ProviderError:
        raise
    except Exception:
        raise ProviderError(Failure.CREDENTIAL) from None


def _system_resolve(host, port):
    rows = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    check(1 <= len(rows) <= 16, Failure.DNS)
    return tuple(row[4][0] for row in rows)


def _resolve(target, config, resolver, control):
    control.poll()
    try:
        address = ip_address(target.host)
    except ValueError:
        address = None
    if address is not None:
        return admit_address(config, str(address))
    # OS DNS has no portable cancellation. At most one detached DNS worker may
    # survive a timeout; it has no payload/secret/socket-connection capability.
    rows = _external(lambda: resolver(target.host, target.port), _DNS_SLOT, control, Failure.DNS)
    check(type(rows) in (tuple, list) and 1 <= len(rows) <= 16, Failure.DNS)
    addresses = sorted({admit_address(config, raw) for raw in rows})
    check(bool(addresses), Failure.DNS)
    return addresses[0]  # Exactly one connection; no address fallback/retry.


def _wait(sock, control, *, writing=False):
    while True:
        seconds = control.poll()
        read, write, exceptional = select.select(
            [] if writing else [sock], [sock] if writing else [], [sock], seconds
        )
        if exceptional:
            raise ProviderError(Failure.CONNECTION, control.transmission)
        if read or write:
            control.poll()
            return


def _io(sock, control, function, *, writing=False):
    while True:
        control.poll()
        try:
            value = function()
            control.poll()
            return value
        except ssl.SSLWantReadError:
            _wait(sock, control)
        except ssl.SSLWantWriteError:
            _wait(sock, control, writing=True)
        except BlockingIOError:
            _wait(sock, control, writing=writing)


def _tls_context():
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _peer(sock, address, port):
    actual = sock.getpeername()
    check(str(ip_address(actual[0])) == address and actual[1] == port, Failure.DESTINATION)


def _connect(target, address, control):
    family = socket.AF_INET6 if isinstance(ip_address(address), IPv6Address) else socket.AF_INET
    destination = (
        (address, target.port, 0, 0) if family == socket.AF_INET6 else (address, target.port)
    )
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setblocking(False)
        control.poll()
        code = sock.connect_ex(destination)
        pending = {
            0,
            errno.EINPROGRESS,
            errno.EWOULDBLOCK,
            errno.EALREADY,
            getattr(errno, "WSAEWOULDBLOCK", 10035),
        }
        check(code in pending, Failure.CONNECTION)
        _wait(sock, control, writing=True)
        check(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0, Failure.CONNECTION)
        _peer(sock, address, target.port)
        if target.scheme == "https":
            sock = _tls_context().wrap_socket(
                sock, server_hostname=target.host, do_handshake_on_connect=False
            )
            _io(sock, control, sock.do_handshake)
            _peer(sock, address, target.port)
        return sock
    except BaseException:
        sock.close()
        raise


class _Reader:
    def __init__(self, sock, control, limits):
        self.sock, self.control, self.limits = sock, control, limits
        self.header_size = 0

    def read(self, count):
        raw = _io(self.sock, self.control, lambda: self.sock.recv(count))
        check(bool(raw), Failure.TRUNCATED)
        return raw

    def line(self):
        data = bytearray()
        while True:
            # Read only what remains admissible; one sentinel byte detects excess.
            check(
                len(data) < self.limits.line_bytes and self.header_size < self.limits.header_bytes,
                Failure.LIMIT,
            )
            raw = self.read(1)
            self.header_size += 1
            data.extend(raw)
            if raw == b"\n":
                check(data.endswith(b"\r\n"), Failure.INCOMPATIBLE)
                return bytes(data[:-2])

    def response(self):
        status_line = self.line()
        check(
            re.fullmatch(rb"HTTP/1\.[01] [1-5][0-9]{2} [\x20-\x7e]*", status_line) is not None,
            Failure.INCOMPATIBLE,
        )
        status = int(status_line[9:12])
        headers = {}
        while True:
            line = self.line()
            if not line:
                break
            check(len(headers) < self.limits.header_count, Failure.LIMIT)
            name, separator, value = line.partition(b":")
            check(separator and _HEADER.fullmatch(name) is not None, Failure.INCOMPATIBLE)
            check(all(32 <= b <= 126 for b in value), Failure.INCOMPATIBLE)
            name = name.lower()
            check(name not in headers, Failure.INCOMPATIBLE)
            headers[name] = value.strip()
        # No status/body/header/location text is copied to diagnostics.
        if 300 <= status <= 399:
            raise ProviderError(Failure.REDIRECT)
        if status in (401, 403):
            raise ProviderError(Failure.AUTH)
        if status == 429:
            raise ProviderError(Failure.RATE_LIMIT)
        if status >= 500:
            raise ProviderError(Failure.REMOTE)
        check(status == 200, Failure.INCOMPATIBLE)
        check(b"transfer-encoding" not in headers, Failure.INCOMPATIBLE)
        check(headers.get(b"content-encoding", b"identity") == b"identity", Failure.INCOMPATIBLE)
        check(
            headers.get(b"content-type", b"").lower()
            in (b"application/json", b"application/json; charset=utf-8"),
            Failure.INCOMPATIBLE,
        )
        length = headers.get(b"content-length", b"")
        check(re.fullmatch(rb"[1-9][0-9]{0,8}", length) is not None, Failure.INCOMPATIBLE)
        count = int(length)
        check(count <= self.limits.response_bytes, Failure.LIMIT)
        body = bytearray()
        while len(body) < count:
            body.extend(self.read(min(4096, count - len(body))))
        self.control.poll()
        return bytes(body)


def _decode(raw, model, maximum):
    def pairs(items):
        row = {}
        for key, value in items:
            check(key not in row, Failure.INCOMPATIBLE)
            row[key] = value
        return row

    try:
        check(type(raw) is bytes and len(raw) <= maximum, Failure.LIMIT)
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        check(type(value) is dict, Failure.INCOMPATIBLE)
        check(
            set(value)
            <= {
                "id",
                "object",
                "created",
                "model",
                "choices",
                "usage",
                "system_fingerprint",
                "service_tier",
            },
            Failure.INCOMPATIBLE,
        )
        check(
            value.get("object") == "chat.completion" and value.get("model") == model,
            Failure.INCOMPATIBLE,
        )
        check(type(value.get("id")) is str and 1 <= len(value["id"]) <= 256, Failure.INCOMPATIBLE)
        check(type(value.get("created")) is int and value["created"] >= 0, Failure.INCOMPATIBLE)
        choices = value.get("choices")
        check(type(choices) is list and len(choices) == 1, Failure.INCOMPATIBLE)
        choice = choices[0]
        check(
            type(choice) is dict
            and set(choice) <= {"index", "finish_reason", "message", "logprobs"},
            Failure.INCOMPATIBLE,
        )
        check(
            type(choice.get("index")) is int
            and choice["index"] == 0
            and choice.get("finish_reason") == "stop"
            and choice.get("logprobs") is None,
            Failure.INCOMPATIBLE,
        )
        message = choice.get("message")
        check(
            type(message) is dict and set(message) <= {"role", "content", "refusal"},
            Failure.INCOMPATIBLE,
        )
        check(
            message.get("role") == "assistant" and message.get("refusal") is None,
            Failure.INCOMPATIBLE,
        )
        content = message.get("content")
        check(type(content) is str and len(content) <= maximum, Failure.INCOMPATIBLE)
        return content.encode("utf-8", errors="strict")
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise ProviderError(Failure.INCOMPATIBLE) from None


class CheckedCall:
    """One snapshot lineage shared by real/fake adapters; not an execution grant."""

    def __init__(self, current: Callable[[], CallInputs]):
        self.current = current
        self.initial = current()
        check(type(self.initial) is CallInputs)
        self.request, self.profile = self.initial.prepare()
        self.body = wire_request(self.initial)  # Bound before credential lookup/DNS.

    def refresh(self):
        fresh = self.current()
        check(type(fresh) is CallInputs, Failure.POLICY)
        fresh.prepare()
        check(
            fresh.plan == self.initial.plan and fresh.config == self.initial.config, Failure.POLICY
        )
        return fresh

    def accept(self, raw, transmission):
        return accept_candidate(raw, self.refresh(), transmission=transmission)


class ChatJsonAdapter:
    """Internal adapter; no product call site. Dependencies must be explicitly injected."""

    def __init__(self, *, credentials, resolver=_system_resolve):
        self._credentials, self._resolver = credentials, resolver

    def _operate(self, current, cancel, *, diagnostic=False):
        call = CheckedCall(current)
        inputs, config = call.initial, call.initial.config
        control = _Control(cancel, min(config.limits.seconds, call.request.limits.max_seconds))
        sock = None
        try:
            control.poll()
            # Connection diagnostics do not ask for or transmit credentials/content.
            secret = (
                None if diagnostic else _secret(self._credentials, inputs, call.profile, control)
            )
            control.poll()
            target = endpoint(config.endpoint_url)
            header = (
                f"POST /v1/chat/completions HTTP/1.1\r\nHost: {target.authority}\r\n"
                "Content-Type: application/json\r\nAccept: application/json\r\n"
                "Accept-Encoding: identity\r\nConnection: close\r\n"
                f"Content-Length: {len(call.body)}\r\n"
            )
            if secret is not None:
                header += f"Authorization: Bearer {secret}\r\n"
            wire_header = (header + "\r\n").encode("ascii")
            check(len(wire_header) <= config.limits.header_bytes, Failure.LIMIT)
            check(len(wire_header.split(b"\r\n")) - 3 <= config.limits.header_count, Failure.LIMIT)
            check(
                all(
                    len(line) + 2 <= config.limits.line_bytes
                    for line in wire_header.split(b"\r\n")[:-1]
                ),
                Failure.LIMIT,
            )
            call.refresh()
            address = _resolve(target, config, self._resolver, control)
            call.refresh()
            sock = _connect(target, address, control)
            call.refresh()
            control.poll()
            if diagnostic:
                return {
                    "connection": "connected",
                    "destination": config.destination.value,
                    "peer_verified": True,
                    "tls_verified": target.scheme == "https",
                    "authentication": "NOT_RUN",
                    "inference": "NOT_RUN",
                    "product_execution": "governed_job_required",
                }
            # Observe revocation/rotation again at the final pre-send boundary.
            # A changed token is refused; this is not an authentication retry.
            check(
                _secret(self._credentials, inputs, call.profile, control) == secret,
                Failure.CREDENTIAL,
            )
            call.refresh()
            _peer(sock, address, target.port)
            for part in (wire_header, call.body):
                view = memoryview(part)
                while view:
                    control.poll()
                    # Conservatively uncertain even if the first send raises.
                    control.transmission = Transmission.POSSIBLE
                    sent = _io(sock, control, lambda view=view: sock.send(view), writing=True)
                    check(sent > 0, Failure.CONNECTION)
                    view = view[sent:]
            raw = _Reader(sock, control, config.limits).response()
            content = _decode(raw, call.profile.model, config.limits.response_bytes)
            result = call.accept(content, Transmission.RESPONSE)
            control.poll()
            return result
        except ProviderError as error:
            raise ProviderError(error.code, control.transmission) from None
        except ssl.SSLError:
            raise ProviderError(Failure.TLS, control.transmission) from None
        except TimeoutError:
            raise ProviderError(Failure.TIMEOUT, control.transmission) from None
        except (OSError, ValueError, TypeError, AiContractError):
            raise ProviderError(Failure.CONNECTION, control.transmission) from None
        finally:
            if sock is not None:
                sock.close()

    def exchange(self, current, *, cancel):
        return self._operate(current, cancel)

    def diagnose(self, current, *, cancel, requested=False):
        check(requested is True, Failure.DISABLED)
        return self._operate(current, cancel, diagnostic=True)
