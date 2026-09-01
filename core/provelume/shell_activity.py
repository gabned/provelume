from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from .service import ProvelumeInstance
from .shell_settings import (
    DEFAULT_LOCAL_PORT,
    MAX_SETTINGS_REVISION,
    ShellSettingsError,
    ShellSettingsManager,
)

MAX_SHELL_BODY_BYTES = 8 * 1024
MAX_FORM_FIELDS = 12
MAX_ACTIVE_NONCES = 64
NONCE_LIFETIME_SECONDS = 10 * 60
SHELL_FORM_FIELDS = frozenset(
    {
        "csrf_token",
        "mutation_nonce",
        "revision",
        "action",
        "port",
        "tray_enabled",
        "login_startup",
        "theme",
        "language",
    }
)


def _endpoint_display(host: str, port: int) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        authority = host
    else:
        authority = f"[{address}]" if address.version == 6 else str(address)
    return f"http://{authority}:{port}"


def _loopback_request(request: Request) -> bool:
    if request.client is None:
        return False
    if request.client.host == "testclient":
        return True
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


class MutationNonces:
    def __init__(self) -> None:
        self._values: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def issue(self) -> str:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            while len(self._values) >= MAX_ACTIVE_NONCES:
                self._values.popitem(last=False)
            nonce = secrets.token_urlsafe(24)
            self._values[nonce] = now
        return nonce

    def consume(self, supplied: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            created = self._values.pop(supplied, None)
        return created is not None and now - created <= NONCE_LIFETIME_SECONDS

    def _expire(self, now: float) -> None:
        while self._values:
            _nonce, created = next(iter(self._values.items()))
            if now - created <= NONCE_LIFETIME_SECONDS:
                break
            self._values.popitem(last=False)


def attach_shell_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
    manager: ShellSettingsManager,
    *,
    effective_host: str,
    effective_port: int,
) -> None:
    csrf_token = secrets.token_urlsafe(32)
    nonces = MutationNonces()

    def view() -> dict[str, Any]:
        loaded = manager.load()
        result = loaded.settings.public_view(warning=loaded.warning)
        result["service"] = {
            "status": "running",
            "host": effective_host,
            "port": effective_port,
            "display": _endpoint_display(effective_host, effective_port),
            "binding": "loopback_only",
        }
        installed_windows = os.name == "nt" and bool(getattr(sys, "frozen", False))
        result["capabilities"] = {
            "windows_tray": installed_windows,
            "login_startup": installed_windows,
            "theme": ["system", "light", "dark"],
            "preference_transfer": True,
            "authenticode": "unsigned",
            "publisher_authentication": "not_established",
        }
        return result

    def page_context(
        request: Request,
        *,
        saved: bool = False,
        reset: bool = False,
        error_code: str | None = None,
        status_code: int = 200,
    ):
        editable = _loopback_request(request)
        return templates.TemplateResponse(
            request=request,
            name="shell_settings.html",
            status_code=status_code,
            context=context_factory(
                request,
                instance,
                shell=view(),
                editable=editable,
                csrf_token=csrf_token if editable else None,
                mutation_nonce=nonces.issue() if editable else None,
                saved=saved,
                reset=reset,
                error_code=error_code,
            ),
        )

    @app.get("/api/v1/shell")
    def api_shell() -> dict[str, Any]:
        return view()

    @app.get("/settings/shell")
    def shell_settings_page(request: Request):
        status = request.query_params.get("status")
        return page_context(
            request,
            saved=status == "saved",
            reset=status == "reset",
        )

    @app.post("/settings/shell")
    async def save_shell_settings(request: Request):
        if not _loopback_request(request):
            raise HTTPException(
                status_code=403,
                detail="shell settings can be changed only from the local Browser shell",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="unsupported shell settings content type")
        body = await request.body()
        if len(body) > MAX_SHELL_BODY_BYTES:
            raise HTTPException(status_code=413, detail="shell settings request is too large")
        try:
            values = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=MAX_FORM_FIELDS,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid shell settings request") from exc
        if (
            not set(values).issubset(SHELL_FORM_FIELDS)
            or any(len(items) != 1 for items in values.values())
            or not {"csrf_token", "mutation_nonce", "revision", "action"}.issubset(values)
        ):
            raise HTTPException(status_code=400, detail="invalid shell settings fields")
        action = values["action"][0]
        if (
            action not in {"save", "reset-port"}
            or (
                action == "save"
                and not {"port", "theme", "language"}.issubset(values)
            )
            or any(
                values[name][0] != "on"
                for name in ("tray_enabled", "login_startup")
                if name in values
            )
        ):
            raise HTTPException(status_code=400, detail="invalid shell settings fields")
        supplied_token = values.get("csrf_token", [""])[0]
        if not hmac.compare_digest(supplied_token, csrf_token):
            raise HTTPException(status_code=403, detail="invalid shell settings token")
        if not nonces.consume(values.get("mutation_nonce", [""])[0]):
            raise HTTPException(
                status_code=409,
                detail="shell settings request is stale or replayed",
            )
        revision_text = values["revision"][0]
        if (
            not revision_text
            or not revision_text.isascii()
            or not revision_text.isdigit()
            or len(revision_text) > 19
        ):
            raise HTTPException(status_code=400, detail="invalid shell settings revision")
        expected_revision = int(revision_text)
        if expected_revision > MAX_SETTINGS_REVISION:
            raise HTTPException(status_code=400, detail="invalid shell settings revision")
        try:
            if action == "reset-port":
                manager.reset_port(expected_revision=expected_revision)
                reset = True
            elif action == "save":
                current = manager.load().settings
                installed_windows = os.name == "nt" and bool(getattr(sys, "frozen", False))
                manager.configure(
                    port=values.get("port", [str(DEFAULT_LOCAL_PORT)])[0],
                    tray_enabled=values.get("tray_enabled", [""])[0] == "on",
                    login_startup=(
                        values.get("login_startup", [""])[0] == "on"
                        if installed_windows
                        else current.login_startup
                    ),
                    theme=values.get("theme", ["system"])[0],
                    language=values.get("language", ["en"])[0],
                    expected_revision=expected_revision,
                )
                reset = False
            else:
                raise ShellSettingsError("unsupported shell settings action")
        except (OSError, ShellSettingsError, ValueError) as exc:
            code = getattr(exc, "code", "shell_settings_error")
            return page_context(request, error_code=code, status_code=400)
        language = values.get("language", ["en"])[0]
        selected_language = language if language in {"en", "it"} else "en"
        return RedirectResponse(
            url=(
                f"/settings/shell?lang={selected_language}&status="
                f"{'reset' if reset else 'saved'}"
            ),
            status_code=303,
        )
