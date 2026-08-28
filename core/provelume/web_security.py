from __future__ import annotations

import ipaddress

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
        response.headers["Cache-Control"] = "no-store"
        return response
