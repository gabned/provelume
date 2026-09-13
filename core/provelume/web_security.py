from __future__ import annotations

import ipaddress
import re

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse

LOCAL_HOSTNAMES = frozenset({"localhost", "testserver"})
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; "
    "manifest-src 'self'; media-src 'self'; object-src 'none'; script-src 'none'; "
    "style-src 'self'; worker-src 'none'"
)
# Browsers apply form-action to the redirects following a form submission too.
# Only the explicit Google connection page may navigate to Google's consent host.
GOOGLE_CONNECTION_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace(
    "form-action 'self';", "form-action 'self' https://accounts.google.com;"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": (
        "browsing-topics=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Permitted-Cross-Domain-Policies": "none",
}


def loopback_host(value: str) -> str:
    """Return a normalized explicit loopback bind target or fail closed."""

    selected = value.strip()
    if selected.casefold() == "localhost":
        return "localhost"
    try:
        address = ipaddress.ip_address(selected)
    except ValueError as exc:
        raise ValueError(
            "host must be localhost or an explicit loopback IP address"
        ) from exc
    if not address.is_loopback:
        raise ValueError("non-loopback serving requires a separate authenticated contract")
    return str(address)


def _host_without_port(value: str) -> str | None:
    selected = value.strip()
    if not selected:
        return None
    if selected.startswith("["):
        closing = selected.find("]")
        if closing < 0:
            return None
        host = selected[1:closing]
        remainder = selected[closing + 1 :]
        if remainder and (
            not remainder.startswith(":") or not remainder[1:].isdigit()
        ):
            return None
        return host
    if selected.count(":") == 1:
        host, port = selected.rsplit(":", 1)
        if not host or not port.isdigit():
            return None
        return host
    if ":" in selected:
        try:
            ipaddress.ip_address(selected)
        except ValueError:
            return None
    return selected


def trusted_request_host(value: str) -> bool:
    host = _host_without_port(value)
    if host is None:
        return False
    if host.casefold() in LOCAL_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class LocalWebSecurityMiddleware(BaseHTTPMiddleware):
    """Enforce the local Host boundary and attach private-response headers."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not trusted_request_host(request.headers.get("host", "")):
            response: Response = PlainTextResponse(
                "Invalid local Host header.",
                status_code=400,
            )
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if (
            trusted_request_host(request.headers.get("host", ""))
            and request.url.path == "/google/connect"
            and response.status_code in {200, 303}
        ):
            response.headers["Content-Security-Policy"] = GOOGLE_CONNECTION_SECURITY_POLICY
        integrity = getattr(request.state, "cura_script_integrity", None)
        if (
            trusted_request_host(request.headers.get("host", ""))
            and response.headers.get("content-type", "").startswith("text/html")
            and isinstance(integrity, str)
            and re.fullmatch(r"sha256-[A-Za-z0-9+/]{43}=", integrity)
        ):
            # Only the fixed, integrity-bound first-party enhancement is executable.
            # The renderer and policy use one request-local preference snapshot.
            policy = response.headers["Content-Security-Policy"]
            response.headers["Content-Security-Policy"] = policy.replace(
                "script-src 'none'", f"script-src '{integrity}'",
            )
        response.headers["Cache-Control"] = "no-store"
        return response
