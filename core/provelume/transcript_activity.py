from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .connectors import ConnectorError
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance
from .transcript_contract import (
    TRANSCRIPT_SELECTION_KINDS,
    TRANSCRIPT_SOURCE_SCHEDULE_MODES,
    TRANSCRIPT_SOURCE_STATES,
    TRANSCRIPT_SUPPORTED_PROFILES,
    TranscriptContractError,
)

MAX_TRANSCRIPT_CONTROL_BODY_BYTES = 48 * 1024


def _loopback(request: Request) -> bool:
    if request.client is None:
        return False
    if request.client.host == "testclient":
        return True
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def attach_transcript_routes(
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
        editable = _loopback(request)
        return context_factory(
            request,
            instance,
            capability=instance.transcript_capability(local=False),
            transcript_profiles=TRANSCRIPT_SUPPORTED_PROFILES,
            transcript_selection_kinds=TRANSCRIPT_SELECTION_KINDS,
            transcript_states=TRANSCRIPT_SOURCE_STATES,
            transcript_schedule_modes=TRANSCRIPT_SOURCE_SCHEDULE_MODES,
            sources=instance.list_transcript_sources(local=editable),
            checkpoints={
                item["id"]: instance.transcript_source_checkpoint(str(item["id"]))
                for item in instance.list_transcript_sources(local=False)
            },
            jobs=instance.list_transcript_jobs(limit=100),
            revisions=instance.list_transcript_revisions(limit=100),
            editable=editable,
            csrf_token=csrf_token if editable else None,
            saved=saved,
            error=error,
        )

    @app.get("/transcripts")
    def transcript_page(request: Request):
        return templates.TemplateResponse(
            request=request, name="transcripts.html", context=values(request)
        )

    @app.get("/transcripts/revisions/{revision_id}")
    def transcript_revision_page(request: Request, revision_id: str):
        revision = instance.get_transcript_revision(revision_id, include_content=True)
        if revision is None:
            raise HTTPException(status_code=404, detail="transcript revision not found")
        return templates.TemplateResponse(
            request=request,
            name="transcript_revision.html",
            context=context_factory(request, instance, revision=revision),
        )

    @app.post("/transcripts")
    async def mutate_transcript(request: Request):
        if not _loopback(request):
            raise HTTPException(
                status_code=403,
                detail="transcript intake can be controlled only from the local browser",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="unsupported transcript content type")
        body = await request.body()
        if len(body) > MAX_TRANSCRIPT_CONTROL_BODY_BYTES:
            raise HTTPException(status_code=413, detail="transcript control request is too large")
        try:
            fields = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=20,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="invalid transcript control request"
            ) from exc
        if not hmac.compare_digest(fields.get("csrf_token", [""])[0], csrf_token):
            raise HTTPException(status_code=403, detail="invalid transcript control token")
        action = fields.get("action", [""])[0]
        try:
            if action == "create-source":
                result = instance.create_transcript_source(
                    name=fields.get("name", [""])[0],
                    path=fields.get("path", [""])[0],
                    profile=fields.get("profile", [""])[0],
                    selection_kind=fields.get("selection_kind", [""])[0],
                )
                message = f"created:{result['id']}"
            elif action == "source-state":
                result = instance.set_transcript_source_state(
                    fields.get("source_id", [""])[0], fields.get("state", [""])[0]
                )
                message = f"state:{result['state']}"
            elif action == "reconfigure-source":
                result = instance.reconfigure_transcript_source(
                    fields.get("source_id", [""])[0],
                    path=fields.get("path", [""])[0],
                    profile=fields.get("profile", [""])[0],
                    selection_kind=fields.get("selection_kind", [""])[0],
                )
                message = f"reconfigured:{result['id']}"
            elif action == "source-schedule":
                interval = fields.get("interval_seconds", [""])[0].strip()
                result = instance.configure_transcript_source_schedule(
                    fields.get("source_id", [""])[0],
                    mode=fields.get("mode", [""])[0],
                    interval_seconds=int(interval) if interval else None,
                )
                message = f"schedule:{result['schedule']['mode']}"
            elif action == "remove-source":
                result = instance.remove_transcript_source(fields.get("source_id", [""])[0])
                message = f"removed:{result['id']}"
            elif action == "resync":
                result = instance.reset_transcript_source_cursor(
                    fields.get("source_id", [""])[0]
                )
                message = f"resync:{result['cursor_revision']}"
            elif action == "queue":
                result = instance.queue_transcript_intake(fields.get("source_id", [""])[0])
                message = f"queued:{result['job']['id']}"
            elif action == "run":
                result = instance.run_transcript_job(fields.get("job_id", [""])[0])
                if result is None:
                    raise TranscriptContractError(
                        "transcript_internal_error", "transcript job was not found"
                    )
                message = f"job:{result['status']}"
            elif action == "retry":
                result = instance.retry_transcript_job(fields.get("job_id", [""])[0])
                message = f"retry:{result['job']['id']}"
            elif action == "cancel":
                result = instance.cancel_transcript_job(fields.get("job_id", [""])[0])
                message = f"cancel:{result['status']}"
            elif action == "remove-derived":
                instance.remove_transcript_derived(fields.get("revision_id", [""])[0])
                message = "derived-removed"
            elif action == "rebuild-derived":
                instance.rebuild_transcript_derived(fields.get("revision_id", [""])[0])
                message = "derived-rebuilt"
            else:
                raise TranscriptContractError(
                    "transcript_internal_error", "unsupported transcript control action"
                )
        except (
            TranscriptContractError,
            ConnectorError,
            SchedulerError,
            OSError,
            ValueError,
        ) as exc:
            safe = str(exc) if not isinstance(exc, OSError) else "local transcript I/O failed"
            return templates.TemplateResponse(
                request=request,
                name="transcripts.html",
                status_code=400,
                context=values(request, error=safe),
            )
        return templates.TemplateResponse(
            request=request,
            name="transcripts.html",
            context=values(request, saved=message),
        )


__all__ = ["attach_transcript_routes"]
