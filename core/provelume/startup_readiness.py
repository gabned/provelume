"""Private, bounded startup proof for a launcher-owned loopback child.

This is not /health, an installation attestation, or a public Knowledge API.
Only the private stdin bootstrap supplies the ephemeral key.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import hmac
import json
import os
import re
import select
import socket
import struct
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Event
from typing import BinaryIO

ROUTE = "/internal/startup-readiness"
CHALLENGE_HEADER = "X-Provelume-Readiness-Challenge"
CONTRACT = "provelume.startup-readiness"
BOOTSTRAP_LIMIT = 256
RESPONSE_LIMIT = 2048
HEADER_LIMIT = 4096
PROBE_SECONDS = 1.0
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset({"contract", "version", "startup_id", "challenge", "instance_binding",
                     "port", "backend_state", "reason", "diagnostics_state", "proof"})
_REASONS = {"starting": {"initializing"}, "ready": {"operational"},
            "failed": {"configuration_invalid", "integrity_failed", "initialization_failed"}}
_DIAGNOSTICS = {"not_requested", "pending", "complete", "failed", "unavailable"}
ERROR_CODES = frozenset({
    "preparation_timeout", "spawn_failed", "bootstrap_failed", "process_exited",
    "endpoint_occupied", "readiness_timeout", "readiness_contract_unsupported",
    "readiness_response_invalid", "readiness_binding_failed", "startup_configuration_invalid",
    "startup_integrity_failed", "startup_initialization_failed", "cancelled", "stop_unconfirmed",
})


class StartupReadinessError(ValueError):
    def __init__(self, code: str):
        self.code = code if code in ERROR_CODES else "startup_initialization_failed"
        super().__init__(self.code)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _port(value: int) -> str:
    if type(value) is not int or not 1 <= value <= 65535:
        raise StartupReadinessError("startup_configuration_invalid")
    return str(value)


def _frame(*values: str) -> bytes:
    result = bytearray()
    for value in values:
        if not isinstance(value, str):
            raise StartupReadinessError("readiness_response_invalid")
        encoded = value.encode("utf-8")
        if len(encoded) > 4096:
            raise StartupReadinessError("readiness_response_invalid")
        result.extend(struct.pack(">I", len(encoded)))
        result.extend(encoded)
    return bytes(result)


@dataclass(frozen=True, slots=True)
class StartupSecrets:
    startup_id: str = field(repr=False)
    key: bytes = field(repr=False)

    def __post_init__(self):
        if (not isinstance(self.startup_id, str) or not _HEX32.fullmatch(self.startup_id)
                or not isinstance(self.key, bytes) or len(self.key) != 32):
            raise StartupReadinessError("bootstrap_failed")

    def bootstrap_frame(self) -> bytes:
        data = json.dumps({"version": 1, "startup_id": self.startup_id,
                           "key": self.key.hex()}, separators=(",", ":")).encode("utf-8")
        if len(data) > BOOTSTRAP_LIMIT:
            raise StartupReadinessError("bootstrap_failed")
        return struct.pack(">I", len(data)) + data

    def stop_event_name(self) -> str:
        value = hmac.new(self.key, _frame("provelume.startup-stop.v1", self.startup_id),
                         hashlib.sha256).hexdigest()
        return "Local\\Provelume.Startup.Stop." + value

    def instance_binding(self, instance_id: str, root_binding: str, port: int) -> str:
        if (not isinstance(instance_id, str) or not instance_id.startswith("inst_")
                or len(instance_id.encode("utf-8")) > 1024 or "\x00" in instance_id
                or not isinstance(root_binding, str)
                or not re.fullmatch(r"(?:win32\.file-id\.v1:[0-9a-f]{48}"
                                    r"|posix\.file-id\.v1:[0-9a-f]{32})", root_binding)):
            raise StartupReadinessError("startup_configuration_invalid")
        return hmac.new(self.key, _frame("provelume.instance-binding.v1", self.startup_id,
                                        instance_id, root_binding, "127.0.0.1", _port(port)),
                        hashlib.sha256).hexdigest()


def read_bootstrap(stream: BinaryIO) -> StartupSecrets:
    def exact(size):
        result = bytearray()
        while len(result) < size:
            block = stream.read(size - len(result))
            if not block:
                raise StartupReadinessError("bootstrap_failed")
            result.extend(block)
        return bytes(result)

    try:
        size = struct.unpack(">I", exact(4))[0]
        if not 1 <= size <= BOOTSTRAP_LIMIT:
            raise ValueError("bootstrap bound")
        value = json.loads(exact(size).decode("utf-8"), object_pairs_hook=_unique)
        if (stream.read(1) or not isinstance(value, dict)
                or set(value) != {"version", "startup_id", "key"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["key"], str) or not _HEX64.fullmatch(value["key"])):
            raise ValueError("bootstrap schema")
        return StartupSecrets(value["startup_id"], bytes.fromhex(value["key"]))
    except (OSError, ValueError, TypeError, KeyError, struct.error) as exc:
        raise StartupReadinessError("bootstrap_failed") from exc


@contextmanager
def bootstrap_stdin():
    """Read a pipe even in a windowed frozen runtime whose sys.stdin is None.

    The original handle and our duplicate are made noninheritable before a key
    is read. Worker factories retain their explicit DEVNULL stdin boundaries.
    """
    if os.name == "nt":
        import msvcrt
        from ctypes import wintypes as w

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [w.DWORD]
        kernel.GetStdHandle.restype = w.HANDLE
        kernel.SetStdHandle.argtypes = [w.DWORD, w.HANDLE]
        kernel.SetStdHandle.restype = w.BOOL
        kernel.GetCurrentProcess.restype = w.HANDLE
        kernel.SetHandleInformation.argtypes = [w.HANDLE, w.DWORD, w.DWORD]
        kernel.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE,
                                          ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        source = kernel.GetStdHandle(w.DWORD(-10))
        duplicate = w.HANDLE()
        process = kernel.GetCurrentProcess()
        if (not source or source == ctypes.c_void_p(-1).value
                or not kernel.SetHandleInformation(source, 1, 0)
                or not kernel.DuplicateHandle(process, source, process,
                                              ctypes.byref(duplicate), 0, False, 2)):
            raise StartupReadinessError("bootstrap_failed")
        try:
            descriptor = msvcrt.open_osfhandle(duplicate.value, os.O_BINARY | os.O_RDONLY)
        except Exception:
            kernel.CloseHandle(duplicate)
            raise
    else:
        os.set_inheritable(0, False)
        descriptor = os.dup(0)
    try:
        with os.fdopen(descriptor, "rb") as stream:
            yield stream
    finally:
        # A later Windows Popen(stdin=None) duplicates GetStdHandle even when
        # the source handle is noninheritable. Remove this consumed private
        # pipe from that ambient slot before application workers can start.
        if os.name == "nt" and not kernel.SetStdHandle(w.DWORD(-10), None):
            raise StartupReadinessError("bootstrap_failed")


def _proof(secrets: StartupSecrets, value: dict) -> str:
    return hmac.new(secrets.key, _frame(
        "provelume.startup-readiness.proof.v1", value["contract"], str(value["version"]),
        value["startup_id"], value["challenge"], value["instance_binding"], str(value["port"]),
        value["backend_state"], value["reason"], value["diagnostics_state"],
    ), hashlib.sha256).hexdigest()


class ReadinessContext:
    def __init__(self, secrets: StartupSecrets, root_binding: str, port: int):
        _port(port)
        self._secrets = secrets
        self._root_binding = root_binding
        self.port = port
        self._binding: str | None = None
        self._state = ("starting", "initializing", "not_requested")

    def bind_opened_instance(self, instance_id: str) -> None:
        if self._binding is not None:
            raise StartupReadinessError("startup_initialization_failed")
        self._binding = self._secrets.instance_binding(instance_id, self._root_binding, self.port)

    def mark_ready(self) -> None:
        if self._binding is None:
            raise StartupReadinessError("startup_initialization_failed")
        self._state = ("ready", "operational", "not_requested")

    def response(self, challenge: str) -> tuple[int, dict]:
        if (not isinstance(challenge, str) or not _HEX64.fullmatch(challenge)
                or self._binding is None):
            raise StartupReadinessError("readiness_response_invalid")
        state, reason, diagnostics = self._state
        value = {"contract": CONTRACT, "version": 1, "startup_id": self._secrets.startup_id,
                 "challenge": challenge, "instance_binding": self._binding, "port": self.port,
                 "backend_state": state, "reason": reason, "diagnostics_state": diagnostics}
        value["proof"] = _proof(self._secrets, value)
        return (200 if state == "ready" else 503), value


def verify_response(raw: bytes, status: int, *, secrets: StartupSecrets,
                    binding: str, port: int, challenge: str) -> dict:
    try:
        if len(raw) > RESPONSE_LIMIT:
            raise ValueError("response bound")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise ValueError("response schema")
        if type(value["version"]) is not int:
            raise ValueError("version type")
        if value["contract"] != CONTRACT or value["version"] != 1:
            raise StartupReadinessError("readiness_contract_unsupported")
        if (type(value["port"]) is not int or value["port"] != port
                or not all(isinstance(value[k], str) for k in _FIELDS - {"version", "port"})
                or value["backend_state"] not in _REASONS
                or value["reason"] not in _REASONS[value["backend_state"]]
                or value["diagnostics_state"] not in _DIAGNOSTICS
                or status != (200 if value["backend_state"] == "ready" else 503)
                or not all(_HEX64.fullmatch(value[k])
                           for k in ("proof", "challenge", "instance_binding"))
                or not _HEX32.fullmatch(value["startup_id"])):
            raise ValueError("response fields")
        if (value["startup_id"] != secrets.startup_id or value["challenge"] != challenge
                or not hmac.compare_digest(value["instance_binding"], binding)
                or not hmac.compare_digest(value["proof"], _proof(secrets, value))):
            raise StartupReadinessError("readiness_binding_failed")
        return value
    except StartupReadinessError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise StartupReadinessError("readiness_response_invalid") from exc


def probe(*, secrets: StartupSecrets, binding: str, port: int, challenge: str,
          deadline: float, cancelled: Event) -> dict:
    """One direct IPv4 probe with an absolute deadline over all socket I/O.

    Serial select waits are cancellable and do not reset the budget per byte.
    There is no proxy, redirect, DNS, alternate endpoint, or background reader.
    """
    _port(port)
    deadline = min(deadline, time.monotonic() + PROBE_SECONDS)
    if not _HEX64.fullmatch(challenge):
        raise StartupReadinessError("readiness_response_invalid")

    def active():
        if cancelled.is_set():
            raise StartupReadinessError("cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("readiness probe deadline")
        return remaining

    def wait(sock, *, write=False):
        while True:
            remaining = active()
            readable, writable, _ = select.select(
                [] if write else [sock], [sock] if write else [], [], min(remaining, 0.05)
            )
            if writable if write else readable:
                return

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setblocking(False)
        active()
        result = sock.connect_ex(("127.0.0.1", port))
        if result not in {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY,
                          10035, 10036, 10037}:
            raise OSError(result, "readiness connection unavailable")
        wait(sock, write=True)
        error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if error:
            raise OSError(error, "readiness connection unavailable")
        request = (f"GET {ROUTE} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                   f"{CHALLENGE_HEADER}: {challenge}\r\nConnection: close\r\n\r\n").encode("ascii")
        view = memoryview(request)
        while view:
            wait(sock, write=True)
            try:
                sent = sock.send(view)
            except BlockingIOError:
                continue
            if not sent:
                raise OSError("readiness connection closed")
            view = view[sent:]
        data = bytearray()
        while b"\r\n\r\n" not in data:
            wait(sock)
            try:
                block = sock.recv(min(1024, HEADER_LIMIT + 1 - len(data)))
            except BlockingIOError:
                continue
            if not block:
                raise OSError("readiness connection closed")
            data.extend(block)
            if b"\r\n\r\n" not in data and len(data) > HEADER_LIMIT:
                raise StartupReadinessError("readiness_response_invalid")
        headers, body = bytes(data).split(b"\r\n\r\n", 1)
        try:
            lines = headers.decode("ascii").split("\r\n")
            if len(headers) > HEADER_LIMIT or not re.fullmatch(
                r"HTTP/1\.[01] (?:200|503)(?: [\x20-\x7e]*)?", lines[0]
            ):
                raise ValueError("status")
            status = int(lines[0].split(" ")[1])
            parsed = {}
            for line in lines[1:]:
                name, value = line.split(":", 1)
                if not re.fullmatch(r"[A-Za-z0-9-]+", name) or name.lower() in parsed:
                    raise ValueError("header")
                parsed[name.lower()] = value.strip()
            length = parsed.get("content-length", "")
            if (not re.fullmatch(r"0|[1-9][0-9]{0,4}", length)
                    or int(length) > RESPONSE_LIMIT or "transfer-encoding" in parsed
                    or parsed.get("content-type", "").lower()
                    not in {"application/json", "application/json; charset=utf-8"}):
                raise ValueError("body headers")
            length = int(length)
        except (ValueError, UnicodeError) as exc:
            raise StartupReadinessError("readiness_response_invalid") from exc
        while len(body) < length:
            wait(sock)
            try:
                block = sock.recv(length + 1 - len(body))
            except BlockingIOError:
                continue
            if not block:
                raise OSError("readiness connection closed")
            body += block
        if len(body) != length:
            raise StartupReadinessError("readiness_response_invalid")
        value = verify_response(body, status, secrets=secrets, binding=binding,
                                port=port, challenge=challenge)
        active()
        return value
