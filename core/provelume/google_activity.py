from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .google_contract import GoogleContractError
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance

MAX_GOOGLE_CONTROL_BODY_BYTES = 32 * 1024


def _loopback_request(request: Request) -> bool:
    if request.client is None:
        return False
    if request.client.host == "testclient":
        return True
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def attach_google_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    csrf_token = secrets.token_urlsafe(32)

    def values(
        request: Request,
        *,
        saved: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        editable = _loopback_request(request)
        return context_factory(
            request,
            instance,
            google_instances=instance.list_google_instances(),
            google_sources=instance.list_google_sources(),
            google_jobs=instance.list_google_jobs(limit=100),
            google_gmail=instance.list_google_gmail_observations(limit=100),
            google_drive=instance.list_google_drive_revisions(limit=100),
            editable=editable,
            csrf_token=csrf_token if editable else None,
            saved=saved,
            error=error,
        )

    @app.get("/google")
    def google_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="google.html",
            context=values(request),
        )

    @app.post("/google")
    async def mutate_google(request: Request):
        if not _loopback_request(request):
            raise HTTPException(status_code=403, detail="Google controls require loopback")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="unsupported Google content type")
        body = await request.body()
        if len(body) > MAX_GOOGLE_CONTROL_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Google control request is too large")
        try:
            fields = parse_qs(
                body.decode(),
                keep_blank_values=True,
                max_num_fields=24,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid Google control request") from exc
        if not hmac.compare_digest(fields.get("csrf_token", [""])[0], csrf_token):
            raise HTTPException(status_code=403, detail="invalid Google control token")

        def field(name: str) -> str:
            return fields.get(name, [""])[0]

        action = field("action")
        try:
            if action == "create-instance":
                result = instance.create_google_instance(
                    name=field("name"), account_identity=field("account_identity")
                )
            elif action == "connector-state":
                result = instance.set_google_connector_state(
                    field("connector_instance_id"), enabled=field("state") == "enabled"
                )
            elif action == "authorize":
                result = instance.authorize_google_capability(
                    field("connector_instance_id"),
                    field("capability"),
                    credential_reference={
                        "kind": field("credential_kind"),
                        "name": field("credential_name"),
                    },
                    consent=field("consent") == "yes",
                )
            elif action == "capability-state":
                result = instance.set_google_capability_state(
                    field("connector_instance_id"),
                    field("capability"),
                    state=field("state"),
                )
            elif action == "revoke":
                result = instance.revoke_google_capability(
                    field("connector_instance_id"), field("capability")
                )
            elif action == "create-source":
                selectors = [
                    item.strip() for item in field("selectors").splitlines() if item.strip()
                ]
                result = instance.create_google_source(
                    field("connector_instance_id"),
                    name=field("name"),
                    capability=field("capability"),
                    selection_kind=field("selection_kind"),
                    selectors=selectors,
                )
            elif action == "source-state":
                result = instance.set_google_source_state(field("source_id"), state=field("state"))
            elif action == "source-schedule":
                interval = field("interval_seconds").strip()
                result = instance.configure_google_source_schedule(
                    field("source_id"),
                    mode=field("mode"),
                    interval_seconds=int(interval) if interval else None,
                )
            elif action == "reset-source":
                result = instance.reset_google_source_cursor(field("source_id"))
            elif action == "remove-source":
                result = instance.remove_google_source(field("source_id"))
            elif action == "queue":
                result = instance.queue_google_intake(field("source_id"))
            elif action == "run":
                result = instance.run_google_job(field("job_id"))
            elif action == "cancel":
                result = instance.cancel_google_job(field("job_id"))
            else:
                raise GoogleContractError("google_payload_invalid", "unsupported Google control")
            message = f"{action}:{result.get('id') or result.get('job_id') or 'ok'}"
        except (GoogleContractError, SchedulerError, OSError, ValueError) as exc:
            return templates.TemplateResponse(
                request=request,
                name="google.html",
                status_code=400,
                context=values(request, error=str(exc)),
            )
        return templates.TemplateResponse(
            request=request,
            name="google.html",
            context=values(request, saved=message),
        )


__all__ = ["attach_google_routes"]
