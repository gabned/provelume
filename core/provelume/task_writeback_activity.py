"""Explicit remote-task diff and one confirmation; passive views are local only."""

import hmac
import secrets
from urllib.parse import parse_qs, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .google_activity import _loopback_request
from .productivity_contract import local_instant, require


def attach_task_writeback_routes(app, instance, templates, context_factory):
    csrf = secrets.token_urlsafe(32)

    @app.get("/task-writeback/{object_id}")
    def page(request: Request, object_id: str):
        engine = instance.task_writeback()
        try:
            values = context_factory(request, instance)
            view = engine.view(object_id)
            plan, receipt = None, None
            selected = request.query_params.get("plan")
            if selected:
                receipt = engine.audit(view["source"]["source_id"], selected)
                if receipt is None:
                    plan = engine.load_plan(view["source"]["source_id"], selected)
                    require(plan["object_id"] == object_id, "stale")
            values.update(
                writeback=view,
                plan=plan,
                receipt=receipt,
                csrf_token=csrf,
                editable=_loopback_request(request),
                notice=request.query_params.get("notice"),
            )
            return templates.TemplateResponse(
                request=request,
                name="task_writeback.html",
                context=values,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        except (ValueError, KeyError):
            raise HTTPException(409, "Task write preview is unavailable") from None

    def action(object_id, fields):
        engine = instance.task_writeback()
        require(fields.get("confirm") == "yes", "consent_required")
        selected = fields.get("action")
        allowed = {
            "consent": {"revision", "enabled", "allow_completed", "allow_due"},
            "prepare": {
                "local_sha256",
                "revision",
                "completed",
                "due_kind",
                "day",
                "clock",
                "zone",
            },
            "confirm": {"plan_id", "plan_sha256"},
            "discard": {"plan_id", "plan_sha256"},
            "reconcile": set(),
        }
        require(
            selected in allowed and not (set(fields) - allowed[selected] - {"action", "confirm"})
        )
        if selected == "consent":
            _obj, snapshot = engine.object(object_id)
            require(fields.get("enabled") in {"yes", "no"})
            engine.consent(
                snapshot["source_id"],
                enabled=fields["enabled"] == "yes",
                fields=[key for key in ("completed", "due") if fields.get("allow_" + key) == "yes"],
                expected_revision=int(fields["revision"]),
                confirmed=True,
            )
        elif selected == "prepare":
            requested = {}
            require(fields.get("completed") in {"unchanged", "yes", "no"})
            if fields["completed"] != "unchanged":
                requested["completed"] = fields["completed"] == "yes"
            kind = fields.get("due_kind")
            require(kind in {"unchanged", "none", "date", "instant"})
            if kind != "unchanged":
                requested["due"] = (
                    None
                    if kind == "none"
                    else {"kind": "date", "value": fields["day"], "time_zone": None}
                    if kind == "date"
                    else (local_instant(fields["day"], fields["clock"], fields["zone"]))
                )
            plan = engine.prepare(
                object_id,
                requested,
                expected_local_sha256=fields["local_sha256"],
                expected_consent_revision=int(fields["revision"]),
            )
            return {"plan": plan["id"]}
        elif selected == "reconcile":
            result = engine.reconcile(object_id)
            return {"plan": result["plan_id"], "notice": result["status"]}
        else:
            if selected == "discard":
                engine.discard(
                    object_id, fields["plan_id"], expected_plan_sha256=fields["plan_sha256"]
                )
            else:
                result = engine.confirm(
                    object_id,
                    fields["plan_id"],
                    expected_plan_sha256=fields["plan_sha256"],
                    confirmed=True,
                )
                return {"plan": fields["plan_id"], "notice": result["status"]}
        return {"notice": "saved"}

    @app.post("/task-writeback/{object_id}")
    async def control(request: Request, object_id: str):
        if not _loopback_request(request):
            raise HTTPException(403, "Task write controls require loopback")
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "Unsupported task write request")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, "Task write request too large")
        try:
            values = parse_qs(
                body.decode(), keep_blank_values=True, strict_parsing=True, max_num_fields=14
            )
            require(all(len(value) == 1 for value in values.values()))
            fields = {key: value[0] for key, value in values.items()}
        except ValueError:
            raise HTTPException(400, "Invalid task write request") from None
        if not hmac.compare_digest(fields.pop("csrf_token", ""), csrf):
            raise HTTPException(403, "Invalid task write control token")
        try:
            result = await run_in_threadpool(action, object_id, fields)
        except (ValueError, KeyError, OSError, TypeError):
            result = {"notice": "error"}
        query = urlencode({"lang": context_factory(request, instance)["lang"], **result})
        return RedirectResponse(
            "/task-writeback/" + object_id + "?" + query,
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )
