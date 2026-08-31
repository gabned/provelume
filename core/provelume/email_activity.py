from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .email_contract import EMAIL_SOURCE_STATES, EMAIL_SUPPORTED_PROFILES, EmailContractError
from .email_sources import EMAIL_SOURCE_SCHEDULE_MODES, EmailSourceError
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance

MAX_EMAIL_CONTROL_BODY_BYTES = 32 * 1024


def _loopback_request(request: Request) -> bool:
    if request.client is None:
        return False
    if request.client.host == "testclient":
        return True
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def attach_email_routes(
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
        try:
            capability = instance.email_capability(local=False)
        except (EmailContractError, EmailSourceError, OSError):
            capability = {
                "available": False,
                "profiles": [],
                "network_access": "none",
                "attachment_ocr": {
                    "state": "unavailable",
                    "available": False,
                    "reason": "ocr_internal_error",
                    "intake_dependency": False,
                    "execution_started": False,
                },
            }
        return context_factory(
            request,
            instance,
            capability=capability,
            email_profiles=EMAIL_SUPPORTED_PROFILES,
            email_states=EMAIL_SOURCE_STATES,
            email_schedule_modes=EMAIL_SOURCE_SCHEDULE_MODES,
            sources=instance.list_email_sources(local=editable),
            jobs=instance.list_email_jobs(limit=100),
            messages=instance.list_email_messages(limit=100),
            threads=instance.list_email_threads(limit=100),
            attachments=instance.list_email_attachments(limit=100),
            editable=editable,
            csrf_token=csrf_token if editable else None,
            saved=saved,
            error=error,
        )

    @app.get("/email")
    def email_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="email.html",
            context=values(request),
        )

    @app.get("/email/messages/{message_id}")
    def email_message_page(request: Request, message_id: str):
        message = instance.get_email_message(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="email message not found")
        return templates.TemplateResponse(
            request=request,
            name="email_message.html",
            context=context_factory(request, instance, message=message),
        )

    @app.get("/email/threads/{thread_id}")
    def email_thread_page(request: Request, thread_id: str):
        thread = instance.get_email_thread(thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="observed email thread not found")
        return templates.TemplateResponse(
            request=request,
            name="email_thread.html",
            context=context_factory(request, instance, thread=thread),
        )

    @app.get("/email/attachments/{attachment_id}")
    def email_attachment_page(request: Request, attachment_id: str):
        attachment = instance.get_email_attachment(attachment_id)
        if attachment is None:
            raise HTTPException(status_code=404, detail="email attachment not found")
        return templates.TemplateResponse(
            request=request,
            name="email_attachment.html",
            context=context_factory(request, instance, attachment=attachment),
        )

    @app.post("/email")
    async def mutate_email(request: Request):
        if not _loopback_request(request):
            raise HTTPException(
                status_code=403,
                detail="email intake can be controlled only from the local browser",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="unsupported email content type")
        body = await request.body()
        if len(body) > MAX_EMAIL_CONTROL_BODY_BYTES:
            raise HTTPException(status_code=413, detail="email control request is too large")
        try:
            fields = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=16,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid email control request") from exc
        if not hmac.compare_digest(fields.get("csrf_token", [""])[0], csrf_token):
            raise HTTPException(status_code=403, detail="invalid email control token")
        action = fields.get("action", [""])[0]
        try:
            if action == "create-source":
                result = instance.create_email_source(
                    name=fields.get("name", [""])[0],
                    path=fields.get("path", [""])[0],
                    profile=fields.get("profile", [""])[0],
                )
                message = f"created:{result['id']}"
            elif action == "source-state":
                result = instance.set_email_source_state(
                    fields.get("source_id", [""])[0],
                    fields.get("state", [""])[0],
                )
                message = f"state:{result['state']}"
            elif action == "source-schedule":
                interval_text = fields.get("interval_seconds", [""])[0].strip()
                result = instance.configure_email_source_schedule(
                    fields.get("source_id", [""])[0],
                    mode=fields.get("mode", [""])[0],
                    interval_seconds=int(interval_text) if interval_text else None,
                )
                message = f"schedule:{result['schedule']['mode']}"
            elif action == "remove-source":
                result = instance.remove_email_source(fields.get("source_id", [""])[0])
                message = f"removed:{result['id']}"
            elif action == "queue":
                result = instance.queue_email_intake(fields.get("source_id", [""])[0])
                message = f"queued:{result['job']['id']}"
            elif action == "run":
                result = instance.run_email_job(fields.get("job_id", [""])[0])
                if result is None:
                    raise EmailContractError("email_internal_error", "email job not found")
                message = f"job:{result['status']}"
            elif action == "cancel":
                instance.cancel_email_job(fields.get("job_id", [""])[0])
                message = "cancellation-requested"
            elif action == "remove-derived":
                instance.remove_email_derived(fields.get("message_id", [""])[0])
                message = "derived-removed"
            elif action == "rebuild-derived":
                instance.rebuild_email_derived(fields.get("message_id", [""])[0])
                message = "derived-rebuilt"
            else:
                raise EmailContractError(
                    "email_internal_error",
                    "unsupported email control action",
                )
        except (EmailContractError, EmailSourceError, SchedulerError, OSError, ValueError) as exc:
            safe_error = str(exc) if not isinstance(exc, OSError) else "local email I/O failed"
            return templates.TemplateResponse(
                request=request,
                name="email.html",
                status_code=400,
                context=values(request, error=safe_error),
            )
        return templates.TemplateResponse(
            request=request,
            name="email.html",
            context=values(request, saved=message),
        )


__all__ = ["attach_email_routes"]
