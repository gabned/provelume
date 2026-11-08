"""Loopback-only explicit feed controls; observation never opens the device vault."""

import hmac
import secrets
from urllib.parse import parse_qs, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .google_activity import _loopback_request
from .productivity_contract import require
from .productivity_jobs import ProductivityJobs

HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def attach_icalendar_routes(app, instance, templates, context_factory):
    csrf = secrets.token_urlsafe(32)

    @app.get("/icalendar")
    def page(request: Request):
        manager = instance.icalendar_feeds()
        sources = [{**source, "policy": manager.host.policy(source["id"])}
                   for source in instance.store.list_canonical("sources")
                   if source.get("kind") == "connector"
                   and source.get("source_kind") == "icalendar"]
        values = context_factory(request, instance)
        values.update(feeds=sources, duplicates=manager.duplicates(),
                      editable=_loopback_request(request), csrf_token=csrf,
                      notice=request.query_params.get("notice"))
        return templates.TemplateResponse(request=request, name="icalendar.html", context=values,
                                          headers=HEADERS)

    def apply(fields):
        manager = instance.icalendar_feeds()
        require(fields.get("confirm") == "yes", "consent_required")
        action, source_id = fields.get("action"), fields.get("source_id")
        allowed = {"add": {"name", "kind", "location", "authorization", "time_zone"},
                   "reconnect": {"source_id", "revision", "kind", "location", "authorization",
                                 "time_zone"},
                   "read": {"source_id", "revision"},
                   "consent": {"source_id", "revision", "mode", "interval"}}
        require(action in allowed and not (set(fields) - allowed[action] - {"action", "confirm"}))
        if action in {"add", "reconnect"}:
            options = {key: fields.get(key) or None for key in ("authorization", "time_zone")}
            options.update(kind=fields.get("kind"), location=fields.get("location"), confirmed=True)
            if action == "add":
                manager.add(name=fields.get("name"), **options)
            else:
                manager.reconnect(source_id, expected_policy_revision=int(fields["revision"]),
                                  **options)
            return
        policy = manager.host.policy(source_id)
        require(policy is not None and policy["revision"] == int(fields["revision"]), "stale")
        if action == "read":
            queued = ProductivityJobs(instance.store).queue(source_id)
            result = instance.scheduler.run_one(job_id=queued["job"]["id"])
            require(result is not None and result["status"] == "succeeded", "incomplete")
        else:
            mode = fields.get("mode")
            interval = int(fields["interval"]) if mode == "scheduled" else None
            from .scheduler_model import schedule_payload

            schedule_payload(mode="interval" if interval is not None else "manual",
                             timezone="UTC", interval_seconds=interval)
            manager.host.consent(source_id, capabilities=["calendar_read"], mode=mode,
                expected_revision=policy["revision"], confirmed=True)
            ProductivityJobs(instance.store).policy(source_id, interval_seconds=interval)

    @app.post("/icalendar")
    async def control(request: Request):
        if not _loopback_request(request):
            raise HTTPException(403, "Feed controls require loopback")
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "Unsupported feed request")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 24 * 1024:
                raise HTTPException(413, "Feed request too large")
        try:
            values = parse_qs(body.decode(), keep_blank_values=True, strict_parsing=True,
                              max_num_fields=12)
            require(all(len(value) == 1 for value in values.values()))
            fields = {key: value[0] for key, value in values.items()}
        except ValueError:
            raise HTTPException(400, "Invalid feed request") from None
        if not hmac.compare_digest(fields.pop("csrf_token", ""), csrf):
            raise HTTPException(403, "Invalid feed control token")
        try:
            await run_in_threadpool(apply, fields)
            notice = "saved"
        except (ValueError, KeyError, TypeError, OSError):
            notice = "error"
        query = urlencode({"lang": context_factory(request, instance)["lang"], "notice": notice})
        return RedirectResponse("/icalendar?" + query, status_code=303, headers=HEADERS)
