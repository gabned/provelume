"""Explicit artifact GET transport. No inference protocol, proxy, auth or discovery."""

from __future__ import annotations

import queue
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

from .ai_models import ModelEntry, ModelError, artifact_url, check
from .web_transport import _open_pinned_socket, _public_ip

_DNS_SLOT = threading.BoundedSemaphore(1)
CHUNK = 4096
MAX_HEADER_BYTES = 16 * 1024
MAX_HEADERS = 32


def checkpoint(cancel: Callable[[], bool], deadline: float):
    check(not cancel(), "cancelled")
    check(time.monotonic() < deadline, "timeout")


def _resolve(host: str, deadline: float, cancel, resolver) -> tuple[str, ...]:
    checkpoint(cancel, deadline)
    check(_DNS_SLOT.acquire(blocking=False), "busy")
    result = queue.Queue(maxsize=1)

    def worker():
        try:
            result.put(resolver(host, 443, type=socket.SOCK_STREAM))
        except Exception:
            result.put(None)
        finally:
            _DNS_SLOT.release()

    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception:
        _DNS_SLOT.release()
        raise ModelError("network") from None
    while True:
        checkpoint(cancel, deadline)
        try:
            rows = result.get(timeout=min(0.02, max(0.001, deadline - time.monotonic())))
            break
        except queue.Empty:
            continue
    check(type(rows) in (list, tuple) and 1 <= len(rows) <= 16, "network")
    try:
        addresses = tuple(dict.fromkeys(_public_ip(row[4][0]) for row in rows))
        check(bool(addresses), "network")
        return addresses
    except Exception:
        raise ModelError("network") from None


class ArtifactDownload:
    """Governed HTTPS acquisition; ZIPs never redirect, native routes are closed."""

    def __init__(self, *, resolver=None, connector=None, tls_context=None):
        # Internal host/test seams. Product callers use the defaults.
        self._resolver = resolver or socket.getaddrinfo
        self._connector = connector or _open_pinned_socket
        self._tls_context = tls_context

    def fetch(self, entry: ModelEntry, *, cancel, deadline: float) -> Iterator[bytes]:
        if entry.native:
            from .ai_model_download_native import fetch_native

            yield from fetch_native(self, entry, cancel=cancel, deadline=deadline)
            return
        parts = urlsplit(artifact_url(entry.url))
        checkpoint(cancel, deadline)
        addresses = _resolve(parts.hostname, deadline, cancel, self._resolver)
        plain = secured = None
        try:
            checkpoint(cancel, deadline)
            plain = self._connector(addresses[0], 443, min(2, deadline - time.monotonic()))
            check(plain.getpeername()[:2] == (addresses[0], 443), "network")
            context = self._tls_context or ssl.create_default_context()
            check(context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED, "network")
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            secured = context.wrap_socket(plain, server_hostname=parts.hostname)
            check(secured.getpeername()[:2] == (addresses[0], 443), "network")
            checkpoint(cancel, deadline)
            secured.settimeout(min(2, deadline - time.monotonic()))
            secured.sendall((
                f"GET {parts.path or '/'} HTTP/1.1\r\nHost: {parts.hostname}\r\n"
                "Accept: application/zip\r\nAccept-Encoding: identity\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii"))

            def read(amount):
                checkpoint(cancel, deadline)
                secured.settimeout(min(2, deadline - time.monotonic()))
                data = secured.recv(amount)
                checkpoint(cancel, deadline)
                return data

            header = bytearray()
            while not header.endswith(b"\r\n\r\n"):
                check(len(header) < MAX_HEADER_BYTES, "limit")
                part = read(1)
                check(bool(part), "network")
                header.extend(part)
            lines = bytes(header[:-4]).decode("ascii").split("\r\n")
            check(lines[0] == "HTTP/1.1 200 OK", "network")
            check(len(lines) - 1 <= MAX_HEADERS, "limit")
            headers = {}
            for line in lines[1:]:
                check(":" in line and not line.startswith((" ", "\t")), "network")
                name, value = line.split(":", 1)
                name = name.lower()
                check(name not in headers and name and name.isascii(), "network")
                check(all(32 <= ord(c) < 127 for c in value), "network")
                headers[name] = value.strip()
            check(headers.get("content-length") == str(entry.package_size), "integrity")
            check(headers.get("content-type") == "application/zip", "package")
            check("transfer-encoding" not in headers, "network")
            check(headers.get("content-encoding", "identity") == "identity", "network")
            total = 0
            while total < entry.package_size:
                chunk = read(min(CHUNK, entry.package_size - total))
                check(bool(chunk), "integrity")
                total += len(chunk)
                yield chunk
        except ModelError:
            raise
        except TimeoutError:
            raise ModelError("timeout") from None
        except Exception:
            raise ModelError("network") from None
        finally:
            if secured is not None:
                secured.close()
            if plain is not None:
                plain.close()
