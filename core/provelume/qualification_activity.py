from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .qualification_contract import (
    CORRECTION_FIELDS,
    DECISION_ACTIONS,
    FINDING_TYPES,
    WORKFLOW_STATES,
    QualificationError,
)
from .service import ProvelumeInstance

MAX_QUALIFICATION_CONTROL_BODY_BYTES = 48 * 1024


def _loopback(request: Request) -> bool:
    if request.client is None:
        return False
    if request.client.host == "testclient":
        return True
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def _payload(action: str, fields: dict[str, list[str]]) -> dict[str, Any]:
    if action == "defer":
        return {"until": fields.get("until", [""])[0]}
    if action in {"declare-distinct", "add-relation"}:
        value: dict[str, Any] = {"object_ids": fields.get("object_id", [])}
        if action == "add-relation":
            value["relation_type"] = fields.get("relation_type", [""])[0]
        return value
    if action == "correct-observation":
        return {
            "field": fields.get("field", [""])[0],
            "value": fields.get("value", [""])[0],
        }
    if action == "supersede":
        return {"supersedes_decision_id": fields.get("target_decision_id", [""])[0]}
    if action in {"withdraw", "revert"}:
        return {"target_decision_id": fields.get("target_decision_id", [""])[0]}
    return {}


def attach_qualification_routes(
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
        sources = [
            {
                "id": item["id"],
                "kind": item.get("kind"),
                "source_kind": item.get("source_kind"),
                "lifecycle_state": item.get("lifecycle_state"),
            }
            for item in instance.store.list_canonical("sources")
            if item.get("lifecycle_state") != "removed"
        ]
        selected_source = request.query_params.get("source_id") or None
        selected_type = request.query_params.get("finding_type") or None
        selected_state = request.query_params.get("workflow_state") or None
        try:
            findings = instance.list_qualification_findings(
                source_id=selected_source,
                finding_type=selected_type,
                workflow_state=selected_state,
                limit=200,
            )
        except QualificationError:
            findings = []
            error = error or "qualification_invalid_filter"
        return context_factory(
            request,
            instance,
            matrix=instance.qualification_matrix(),
            qualification_limits=instance.qualification_limits(),
            sources=sources,
            checkpoints={
                item["id"]: instance.qualification_source_checkpoint(str(item["id"]))
                for item in sources
            },
            jobs=instance.list_qualification_jobs(limit=100),
            findings=findings,
            finding_types=FINDING_TYPES,
            workflow_states=WORKFLOW_STATES,
            selected_source=selected_source,
            selected_type=selected_type,
            selected_state=selected_state,
            editable=editable,
            csrf_token=csrf_token if editable else None,
            saved=saved,
            error=error,
        )

    @app.get("/qualification")
    def qualification_page(request: Request):
        return templates.TemplateResponse(
            request=request, name="qualification.html", context=values(request)
        )

    @app.get("/qualification/findings/{finding_id}")
    def qualification_finding_page(request: Request, finding_id: str):
        try:
            finding = instance.get_qualification_finding(finding_id)
        except QualificationError as exc:
            raise HTTPException(status_code=404, detail=exc.code) from exc
        if finding is None:
            raise HTTPException(status_code=404, detail="qualification finding not found")
        return templates.TemplateResponse(
            request=request,
            name="qualification_finding.html",
            context=context_factory(
                request,
                instance,
                finding=finding,
                decision_actions=DECISION_ACTIONS,
                correction_fields=CORRECTION_FIELDS,
                editable=_loopback(request),
                csrf_token=csrf_token if _loopback(request) else None,
            ),
        )

    @app.post("/qualification")
    async def mutate_qualification(request: Request):
        if not _loopback(request):
            raise HTTPException(
                status_code=403,
                detail="qualification can be controlled only from the local browser",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="unsupported qualification content type")
        body = await request.body()
        if len(body) > MAX_QUALIFICATION_CONTROL_BODY_BYTES:
            raise HTTPException(status_code=413, detail="qualification control is too large")
        try:
            fields = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=40,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid qualification control") from exc
        if not hmac.compare_digest(fields.get("csrf_token", [""])[0], csrf_token):
            raise HTTPException(status_code=403, detail="invalid qualification control token")
        action = fields.get("action", [""])[0]
        try:
            if action == "queue":
                result = instance.queue_qualification(fields.get("source_id", []))
                message = f"queued:{result['job']['id']}"
            elif action == "run":
                result = instance.run_qualification(fields.get("job_id", [""])[0])
                message = f"job:{result['status']}"
            elif action == "retry":
                result = instance.retry_qualification(fields.get("job_id", [""])[0])
                message = f"retry:{result['job']['id']}"
            elif action == "cancel":
                result = instance.cancel_qualification(fields.get("job_id", [""])[0])
                message = f"cancel:{result['status']}"
            elif action == "rebuild":
                result = instance.rebuild_qualification(fields.get("job_id", [""])[0])
                message = f"rebuild:{result['job']['id']}"
            elif action == "resync":
                result = instance.reset_qualification_source(fields.get("source_id", [""])[0])
                message = f"resync:{result['revision']}"
            elif action == "decide":
                decision_action = fields.get("decision_action", [""])[0]
                result = instance.decide_qualification_finding(
                    fields.get("finding_id", [""])[0],
                    action=decision_action,
                    actor_id=fields.get("actor_id", [""])[0],
                    reason=fields.get("reason", [""])[0],
                    expected_revision=int(fields.get("expected_revision", [""])[0]),
                    payload=_payload(decision_action, fields),
                )
                message = f"decision:{result['id']}"
            else:
                raise QualificationError(
                    "qualification_invalid_decision", "unsupported qualification action"
                )
        except (QualificationError, OSError, ValueError) as exc:
            safe = getattr(exc, "code", "qualification_local_io_failed")
            return templates.TemplateResponse(
                request=request,
                name="qualification.html",
                status_code=400,
                context=values(request, error=safe),
            )
        return templates.TemplateResponse(
            request=request,
            name="qualification.html",
            context=values(request, saved=message),
        )


__all__ = ["attach_qualification_routes"]
