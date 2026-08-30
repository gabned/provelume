from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .maintenance_model import MaintenanceError
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance

MAX_MAINTENANCE_BODY_BYTES = 8 * 1024


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


def attach_maintenance_routes(
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
        catalog = instance.maintenance_catalog()
        plans: dict[str, dict[str, Any]] = {}
        for action in catalog:
            if not action["available"] or not action["dry_run"]:
                continue
            try:
                plans[str(action["id"])] = instance.plan_maintenance_action(
                    str(action["id"])
                )
            except (MaintenanceError, OSError):
                continue
        maintenance_kinds = {
            str(action["scheduler_job_kind"])
            for action in catalog
            if action["scheduler_job_kind"] is not None
        }
        jobs = [
            job
            for job in instance.list_scheduler_jobs(limit=100)
            if job["job_kind"] in maintenance_kinds
        ]
        sources = instance.folder_sources.list_public()
        source_forms: dict[str, list[dict[str, Any]]] = {}
        for action in catalog:
            if action["scope_kind"] != "source":
                continue
            source_forms[str(action["id"])] = [
                {
                    "source": source,
                    "policies": [
                        policy
                        for policy in action["policies"]
                        if policy["scope"]
                        == {"kind": "source", "id": source["id"]}
                    ],
                }
                for source in sources
            ]
        return context_factory(
            request,
            instance,
            catalog=catalog,
            plans=plans,
            runs=instance.list_maintenance_runs(limit=50),
            source_forms=source_forms,
            source_cursors=instance.list_source_reconciliation_cursors(),
            source_runs=instance.list_source_reconciliation_runs(limit=50),
            resource_status=instance.resource_statistics_status(history_limit=20),
            jobs=jobs,
            editable=editable,
            csrf_token=csrf_token if editable else None,
            saved=saved,
            error=error,
        )

    @app.get("/maintenance")
    def maintenance_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="maintenance.html",
            context=values(request),
        )

    @app.post("/maintenance")
    async def queue_maintenance(request: Request):
        if not _loopback_request(request):
            raise HTTPException(
                status_code=403,
                detail="maintenance can be queued only from the local browser",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(
                status_code=415,
                detail="unsupported maintenance content type",
            )
        body = await request.body()
        if len(body) > MAX_MAINTENANCE_BODY_BYTES:
            raise HTTPException(status_code=413, detail="maintenance request is too large")
        try:
            fields = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=5,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid maintenance request") from exc
        supplied_token = fields.get("csrf_token", [""])[0]
        if not hmac.compare_digest(supplied_token, csrf_token):
            raise HTTPException(status_code=403, detail="invalid maintenance token")
        action_id = fields.get("action_id", [""])[0]
        policy_id = fields.get("policy_id", [""])[0].strip() or None
        source_id = fields.get("source_id", [""])[0].strip() or None
        try:
            queued = instance.queue_maintenance_action(
                action_id,
                request_key=secrets.token_hex(16),
                policy_id=policy_id,
                source_id=source_id,
            )
        except (MaintenanceError, OSError, SchedulerError, ValueError) as exc:
            return templates.TemplateResponse(
                request=request,
                name="maintenance.html",
                status_code=400,
                context=values(request, error=str(exc)),
            )
        return templates.TemplateResponse(
            request=request,
            name="maintenance.html",
            context=values(request, saved=f"queued:{queued['job']['id']}"),
        )


__all__ = ["attach_maintenance_routes"]
