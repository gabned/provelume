"""Raw model transfer on the closed, reviewed acquisition route (ADR 0052)."""

from __future__ import annotations

import re
import ssl
import time
from urllib.parse import unquote, urlsplit

from .ai_model_download import MAX_HEADER_BYTES, MAX_HEADERS, _resolve, checkpoint
from .ai_models import ModelError, artifact_url, check

CHUNK = 64 * 1024
MAX_REDIRECTS = 3
MODEL_HOSTS = frozenset({
    "huggingface.co", "cdn-lfs.huggingface.co", "cdn-lfs-us-1.hf.co",
    "cas-bridge.xethub.hf.co", "us.aws.cdn.hf.co",
})
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9a-z-]+\Z")


def redirect_url(value):
    # Signed CDN query strings are transient transport input. Never persist/log them.
    check(type(value) is str and 0 < len(value) <= 8192, "limit")
    check(value.isascii() and all(32 < ord(ch) < 127 for ch in value), "origin")
    check("\\" not in value, "origin")
    try:
        parts = urlsplit(value)
        check(parts.scheme == "https" and parts.hostname in MODEL_HOSTS, "origin")
        check(not parts.username and not parts.password and not parts.fragment, "origin")
        check(parts.netloc in (parts.hostname, parts.hostname + ":443"), "origin")
        check(parts.port in (None, 443), "origin")
        decoded = unquote(parts.path, errors="strict")
        check("\\" not in decoded and all(ord(ch) >= 32 for ch in decoded), "origin")
        check(all(p not in (".", "..") for p in decoded.split("/")), "origin")
        return parts
    except ModelError:
        raise
    except Exception:
        raise ModelError("origin") from None


def fetch_native(transport, entry, *, cancel, deadline):
    parts = redirect_url(artifact_url(entry.url))
    for redirects in range(MAX_REDIRECTS + 1):
        checkpoint(cancel, deadline)
        addresses = _resolve(parts.hostname, deadline, cancel, transport._resolver)
        plain = secured = None
        try:
            checkpoint(cancel, deadline)
            plain = transport._connector(addresses[0], 443, min(2, deadline - time.monotonic()))
            check(plain.getpeername()[:2] == (addresses[0], 443), "network")
            context = transport._tls_context or ssl.create_default_context()
            check(context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED, "network")
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            secured = context.wrap_socket(plain, server_hostname=parts.hostname)
            check(secured.getpeername()[:2] == (addresses[0], 443), "network")
            checkpoint(cancel, deadline)
            secured.settimeout(min(2, deadline - time.monotonic()))
            target = (parts.path or "/") + ("?" + parts.query if parts.query else "")
            secured.sendall((f"GET {target} HTTP/1.1\r\nHost: {parts.hostname}\r\n"
                            "Accept: application/octet-stream\r\nAccept-Encoding: identity\r\n"
                            "Connection: close\r\n\r\n").encode("ascii"))

            def read(amount, secured=secured):
                checkpoint(cancel, deadline)
                secured.settimeout(min(2, deadline - time.monotonic()))
                data = secured.recv(amount)
                checkpoint(cancel, deadline)
                return data

            buffered = bytearray()
            while (end := buffered.find(b"\r\n\r\n")) < 0:
                check(len(buffered) < MAX_HEADER_BYTES, "limit")
                block = read(min(4096, MAX_HEADER_BYTES - len(buffered)))
                check(bool(block), "network")
                buffered.extend(block)
            check(end + 4 <= MAX_HEADER_BYTES, "limit")
            lines = bytes(buffered[:end]).decode("ascii").split("\r\n")
            check(re.fullmatch(r"HTTP/1\.1 (200|301|302|303|307|308) [ -~]{1,100}",
                               lines[0]) is not None, "network")
            status = int(lines[0].split(" ")[1])
            check(len(lines) - 1 <= MAX_HEADERS, "limit")
            headers = {}
            for line in lines[1:]:
                check(":" in line and not line.startswith((" ", "\t")), "network")
                name, value = line.split(":", 1)
                name = name.lower()
                check(_HEADER_NAME.fullmatch(name) is not None and name not in headers, "network")
                check(all(32 <= ord(ch) < 127 for ch in value), "network")
                headers[name] = value.strip()
            check("transfer-encoding" not in headers, "network")
            check(headers.get("content-encoding", "identity") == "identity", "network")
            if status != 200:
                check(redirects < MAX_REDIRECTS, "limit")
                parts = redirect_url(headers.get("location"))
                continue
            check(headers.get("content-length") == str(entry.package_size), "integrity")
            check(headers.get("content-type") == "application/octet-stream", "package")
            pending = bytes(buffered[end + 4:])
            total = 0
            while total < entry.package_size:
                block = pending or read(min(CHUNK, entry.package_size - total + 1))
                pending = b""
                check(bool(block) and total + len(block) <= entry.package_size, "integrity")
                total += len(block)
                yield block
            checkpoint(cancel, deadline)
            return
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
