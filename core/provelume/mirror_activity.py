"""Passive mirror inventory and explicit local staging controls with bounded CSRF forms."""

import hmac
import secrets
from urllib.parse import parse_qs, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .google_activity import _loopback_request
from .mirror_contract import fingerprint, require
from .mirror_jobs import local_preview


def attach_mirror_routes(app, instance, templates, context_factory):
    csrf = secrets.token_urlsafe(32)

    @app.get("/mirrors")
    def page(request: Request):
        try:
            values = context_factory(request, instance)
            engine = instance.mirrors()
            values.update(
                mirrors=engine.view(),
                plan=None,
                manifest=None,
                csrf_token=csrf,
                editable=_loopback_request(request),
                notice=request.query_params.get("notice"),
            )
            plan_id = request.query_params.get("plan")
            if plan_id:
                plan = engine.plan(plan_id)
                values.update(
                    plan={**plan, "plan_sha256": fingerprint(plan)},
                    manifest=engine.snapshots.verify(plan["generation"]),
                )
            return templates.TemplateResponse(
                request=request,
                name="mirrors.html",
                context=values,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        except (ValueError, KeyError, OSError, TypeError):
            raise HTTPException(409, "Mirror inventory unavailable") from None

    def action(fields):
        require(fields.get("confirm") == "yes", "consent_required")
        selected = fields.get("action")
        allowed = {
            "access": {"revision", "enabled", "github", "rsync"},
            "prepare": {"destination_id", "revision"},
            "disable": {"destination_id", "revision"},
            "discard": {"plan_id", "plan_sha256"},
        }
        require(selected in allowed and set(fields) == allowed[selected] | {"action", "confirm"})
        engine = instance.mirrors()
        if selected == "access":
            require(all(fields[key] in {"yes", "no"} for key in ("enabled", "github", "rsync")))
            engine.set_access(
                enabled=fields["enabled"] == "yes",
                github=fields["github"] == "yes",
                rsync=fields["rsync"] == "yes",
                expected_revision=int(fields["revision"]),
                confirmed=True,
            )
            return {"notice": "saved"}
        if selected == "prepare":
            plan = local_preview(
                engine, fields["destination_id"], expected_revision=int(fields["revision"])
            )
            return {"plan": plan["id"]}
        if selected == "disable":
            engine.disable(
                fields["destination_id"], expected_revision=int(fields["revision"]), confirmed=True
            )
        else:
            engine.discard(
                fields["plan_id"], expected_plan_sha256=fields["plan_sha256"], confirmed=True
            )
        return {"notice": "saved"}

    @app.post("/mirrors")
    async def control(request: Request):
        if not _loopback_request(request):
            raise HTTPException(403, "Local mirror controls only")
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "Invalid mirror control form")
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 16384:
                raise HTTPException(413, "Mirror control form too large")
        try:
            fields = parse_qs(
                body.decode(), strict_parsing=True, keep_blank_values=True, max_num_fields=12
            )
            require(all(len(values) == 1 for values in fields.values()))
            fields = {key: values[0] for key, values in fields.items()}
            require(hmac.compare_digest(fields.pop("csrf_token", ""), csrf))
        except ValueError:
            raise HTTPException(403, "Invalid mirror control token") from None
        try:
            result = await run_in_threadpool(action, fields)
        except (ValueError, KeyError, OSError, TypeError):
            result = {"notice": "unavailable"}
        query = urlencode({"lang": context_factory(request, instance)["lang"], **result})
        return RedirectResponse(
            "/mirrors?" + query, status_code=303, headers={"Cache-Control": "no-store"}
        )
