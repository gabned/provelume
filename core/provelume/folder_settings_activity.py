from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .folder_settings import FolderSettingsError, FolderSettingsManager
from .service import ProvelumeInstance

MAX_SETTINGS_BODY_BYTES = 16 * 1024


def _loopback_request(request: Request) -> bool:
    if request.client is None:
        return False
    host = request.client.host
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def attach_folder_settings_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    manager = FolderSettingsManager(instance.store)
    csrf_token = secrets.token_urlsafe(32)

    @app.get("/api/v1/settings/folders")
    def api_folder_settings() -> dict[str, Any]:
        return manager.public_view()

    @app.get("/settings")
    def folder_settings_page(request: Request):
        editable = _loopback_request(request)
        settings = manager.local_view() if editable else manager.public_view()
        return templates.TemplateResponse(
            request=request,
            name="folder_settings.html",
            context=context_factory(
                request,
                instance,
                settings=settings,
                editable=editable,
                csrf_token=csrf_token if editable else None,
                saved=False,
                error=None,
            ),
        )

    @app.post("/settings/folders")
    async def save_folder_settings(request: Request):
        if not _loopback_request(request):
            raise HTTPException(
                status_code=403,
                detail="folder settings can be changed only from the local browser",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="unsupported settings content type")
        body = await request.body()
        if len(body) > MAX_SETTINGS_BODY_BYTES:
            raise HTTPException(status_code=413, detail="settings request is too large")
        try:
            values = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=8,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid settings request") from exc

        supplied_token = values.get("csrf_token", [""])[0]
        if not hmac.compare_digest(supplied_token, csrf_token):
            raise HTTPException(status_code=403, detail="invalid settings token")
        name = values.get("name", [""])[0]
        drop_path = values.get("drop_path", [""])[0]
        managed_path = values.get("managed_path", [""])[0]
        language = values.get("lang", ["en"])[0]
        try:
            manager.configure(
                name=name,
                drop_path=drop_path,
                managed_path=managed_path,
            )
        except (OSError, FolderSettingsError, ValueError) as exc:
            return templates.TemplateResponse(
                request=request,
                name="folder_settings.html",
                status_code=400,
                context=context_factory(
                    request,
                    instance,
                    settings=manager.local_view(),
                    editable=True,
                    csrf_token=csrf_token,
                    saved=False,
                    error=str(exc),
                ),
            )
        response = templates.TemplateResponse(
            request=request,
            name="folder_settings.html",
            context=context_factory(
                request,
                instance,
                settings=manager.local_view(),
                editable=True,
                csrf_token=csrf_token,
                saved=True,
                error=None,
            ),
        )
        response.headers["Content-Language"] = language if language in {"en", "it"} else "en"
        return response
