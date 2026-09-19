from __future__ import annotations

import ipaddress
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from time import monotonic
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .maintenance_model import MaintenanceBusyError, MaintenanceError
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance

MAX_MAINTENANCE_BODY_BYTES = 8 * 1024
MAX_REVIEWED_PAGES = 32
MAX_REVIEWED_SELECTIONS = 256
REVIEW_SECONDS = 10 * 60


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
    reviewed: OrderedDict[str, tuple[float, dict[tuple[str, str | None], dict[str, Any]]]] = (
        OrderedDict()
    )
    review_lock = threading.Lock()

    def prune_reviews(now: float):
        for token, (created_at, _selections) in list(reviewed.items()):
            if now - created_at >= REVIEW_SECONDS:
                del reviewed[token]

    def retain_review(selections):
        token = secrets.token_urlsafe(32)
        with review_lock:
            now = monotonic()
            prune_reviews(now)
            while len(reviewed) >= MAX_REVIEWED_PAGES:
                reviewed.popitem(last=False)
            reviewed[token] = (now, selections)
        return token

    def values(
        request: Request,
        *,
        saved: str | None = None,
        error: str | None = None,
        issue_preview: bool = True,
    ) -> dict[str, Any]:
        editable = _loopback_request(request)
        catalog = instance.maintenance_catalog()
        plans: dict[str, dict[str, Any]] = {}
        selections: dict[tuple[str, str | None], dict[str, Any]] = {}
        preview_count = 0
        preview_limited = False

        def preview(action, source_id, policies):
            nonlocal preview_count, preview_limited
            if not issue_preview or not action["available"]:
                return None
            if preview_count >= MAX_REVIEWED_SELECTIONS:
                preview_limited = True
                return None
            preview_count += 1
            parameters = {"source_id": source_id} if source_id is not None else {}
            try:
                # Read-only planning: GET does not acquire/create lifecycle lock state.
                plan = instance.maintenance.plan_action(str(action["id"]), parameters=parameters)
            except (MaintenanceError, SchedulerError, OSError, ValueError):
                return None
            if plan.get("ready") is True:
                selections[(str(action["id"]), source_id)] = {
                    "parameters": parameters,
                    "plan_revision": plan["plan_revision"],
                    "policies": {str(policy["id"]) for policy in policies},
                }
            return plan

        for action in catalog:
            if action["scope_kind"] != "source":
                plans[str(action["id"])] = preview(action, None, action["policies"])
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
            source_forms[str(action["id"])] = []
            for source in sources:
                policies = [
                    policy
                    for policy in action["policies"]
                    if policy["scope"] == {"kind": "source", "id": source["id"]}
                ]
                source_forms[str(action["id"])].append(
                    {
                        "source": source,
                        "policies": policies,
                        "plan": preview(action, str(source["id"]), policies),
                    }
                )
        csrf_token = (
            retain_review(selections) if editable and issue_preview and selections else None
        )
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
            csrf_token=csrf_token,
            preview_limited=preview_limited,
            review_required=editable and not issue_preview,
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
                max_num_fields=4,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid maintenance request") from exc
        if not set(fields) <= {"csrf_token", "action_id", "policy_id", "source_id"} or any(
            len(value) != 1 for value in fields.values()
        ):
            raise HTTPException(status_code=400, detail="invalid maintenance request")
        supplied_token = fields.get("csrf_token", [""])[0]
        with review_lock:
            prune_reviews(monotonic())
            retained = reviewed.pop(supplied_token, None)
        if retained is None:
            return templates.TemplateResponse(
                request=request,
                name="maintenance.html",
                status_code=403,
                context=values(request, error="maintenance.review.expired", issue_preview=False),
            )
        action_id = fields.get("action_id", [""])[0]
        policy_id = fields.get("policy_id", [""])[0].strip() or None
        source_id = fields.get("source_id", [""])[0].strip() or None
        selected = retained[1].get((action_id, source_id))
        if selected is None or (
            policy_id not in selected["policies"]
            if policy_id is not None
            else bool(selected["policies"])
        ):
            return templates.TemplateResponse(
                request=request,
                name="maintenance.html",
                status_code=400,
                context=values(request, error="maintenance.review.missing", issue_preview=False),
            )
        try:
            queued = instance.queue_maintenance_action(
                action_id,
                request_key="legacy-maintenance-" + supplied_token,
                policy_id=policy_id,
                source_id=source_id,
                parameters=selected["parameters"],
                expected_plan_revision=selected["plan_revision"],
            )
        except MaintenanceBusyError:
            return templates.TemplateResponse(
                request=request,
                name="maintenance.html",
                status_code=409,
                context=values(request, error="maintenance.review.busy", issue_preview=False),
            )
        except (MaintenanceError, OSError, SchedulerError, ValueError):
            return templates.TemplateResponse(
                request=request,
                name="maintenance.html",
                status_code=400,
                context=values(request, error="maintenance.review.changed", issue_preview=False),
            )
        return templates.TemplateResponse(
            request=request,
            name="maintenance.html",
            context=values(request, saved=f"queued:{queued['job']['id']}", issue_preview=False),
        )


__all__ = ["attach_maintenance_routes"]
