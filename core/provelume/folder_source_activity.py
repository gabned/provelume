from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .folder_source_model import FolderSourceError
from .scheduler import schedule_payload
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance

MAX_SOURCE_BODY_BYTES = 24 * 1024


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


def attach_folder_source_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    csrf_token = secrets.token_urlsafe(32)

    def values(request: Request, *, saved: str | None = None, error: str | None = None):
        editable = _loopback_request(request)
        sources = instance.folder_sources.list_public()
        if editable:
            sources = [instance.folder_sources.local_view(str(source["id"])) for source in sources]
        return context_factory(
            request,
            instance,
            sources=sources,
            editable=editable,
            csrf_token=csrf_token if editable else None,
            saved=saved,
            error=error,
        )

    @app.get("/api/v1/folder-sources")
    def api_folder_sources() -> list[dict[str, Any]]:
        return instance.folder_sources.list_public()

    @app.get("/sources")
    def folder_sources_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="folder_sources.html",
            context=values(request),
        )

    @app.post("/sources")
    async def mutate_folder_sources(request: Request):
        if not _loopback_request(request):
            raise HTTPException(
                status_code=403,
                detail="folder Sources can be changed only from the local browser",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="unsupported Source content type")
        body = await request.body()
        if len(body) > MAX_SOURCE_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Source request is too large")
        try:
            fields = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=18,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid Source request") from exc
        supplied_token = fields.get("csrf_token", [""])[0]
        if not hmac.compare_digest(supplied_token, csrf_token):
            raise HTTPException(status_code=403, detail="invalid Source token")
        action = fields.get("action", [""])[0]
        try:
            if action == "register":
                watch_text = fields.get("watch_interval_seconds", [""])[0].strip()
                schedule = (
                    schedule_payload(
                        mode="interval",
                        timezone=fields.get("timezone", ["UTC"])[0],
                        interval_seconds=int(watch_text),
                        missed_run_policy="coalesce",
                    )
                    if watch_text
                    else schedule_payload(
                        mode="manual",
                        timezone=fields.get("timezone", ["UTC"])[0],
                    )
                )
                result = instance.register_folder_source(
                    fields.get("path", [""])[0],
                    name=fields.get("name", [""])[0],
                    source_class=fields.get("source_class", ["local"])[0],
                    lifecycle_state=fields.get("state", ["enabled"])[0],
                    quiescence_seconds=int(fields.get("quiescence_seconds", ["5"])[0]),
                    stable_observations=int(fields.get("stable_observations", ["2"])[0]),
                    schedule=schedule,
                )
                message = f"registered:{result['id']}"
            else:
                source_id = fields.get("source_id", [""])[0]
                if action in {"enabled", "paused"}:
                    instance.set_folder_source_state(source_id, action)
                    message = f"state:{source_id}:{action}"
                elif action == "observe":
                    instance.observe_folder_source(source_id)
                    message = f"observed:{source_id}"
                elif action == "refresh":
                    queued = instance.queue_folder_source_refresh(
                        source_id,
                        request_key=secrets.token_hex(16),
                    )
                    message = f"queued:{queued['job']['id']}"
                else:
                    raise FolderSourceError("unsupported folder Source action")
        except (FolderSourceError, OSError, SchedulerError, ValueError) as exc:
            return templates.TemplateResponse(
                request=request,
                name="folder_sources.html",
                status_code=400,
                context=values(request, error=str(exc)),
            )
        return templates.TemplateResponse(
            request=request,
            name="folder_sources.html",
            context=values(request, saved=message),
        )


__all__ = ["attach_folder_source_routes"]
