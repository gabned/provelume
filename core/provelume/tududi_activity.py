"""Loopback Tududi explicit controls. GET never loads credentials or contacts a server."""

import hmac
import json
import secrets
from urllib.parse import parse_qs, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .google_activity import _loopback_request
from .instance_lifecycle import InstanceLifecycleManager
from .productivity_contract import require
from .productivity_jobs import ProductivityJobs
from .review_decisions import read_json
from .scheduler_model import schedule_payload
from .tududi_intake import reset_source


def attach_tududi_routes(app, instance, templates, context_factory):
    csrf = secrets.token_urlsafe(32)

    @app.get("/tududi/connect")
    def page(request: Request):
        values = context_factory(request, instance)
        values.update(
            connection=instance.tududi_connection().view(),
            csrf_token=csrf,
            editable=_loopback_request(request),
            notice=request.query_params.get("notice"),
        )
        return templates.TemplateResponse(
            request=request,
            name="tududi_connection.html",
            context=values,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    def action(fields):
        manager = instance.tududi_connection()
        require(fields.get("confirm") == "yes", "consent_required")
        selected, identity = fields.get("action"), fields.get("identity") or None
        allowed = {
            "network": {"enabled"},
            "connect": {"configuration", "name", "identity", "revision"},
            "catalogue": {"identity"},
            "select": {"identity", "name", "scope", "remote_id"},
            "disconnect": {"identity", "revision"},
            "read": {"source_id", "revision"},
            "reset": {"source_id", "revision"},
            "policy": {"source_id", "revision", "mode", "interval"},
        }
        require(
            selected in allowed and not (set(fields) - allowed[selected] - {"action", "confirm"})
        )
        if selected == "network":
            require(fields.get("enabled") in {"yes", "no"})
            with InstanceLifecycleManager(instance.store)._hold(purpose="tududi-network-consent"):
                config = instance.store.read_config()
                config["network"]["external_access"] = fields["enabled"] == "yes"
                instance.store.write_config(config)
        elif selected == "connect":
            manager.connect(
                json.loads(fields["configuration"]),
                name=fields.get("name"),
                identity=identity,
                expected_revision=int(fields.get("revision") or 0),
                confirmed=True,
            )
        elif selected == "catalogue":
            manager.catalogue(identity, confirmed=True)
        elif selected == "select":
            manager.select_source(
                identity,
                name=fields.get("name"),
                scope=fields.get("scope"),
                remote_id=fields.get("remote_id") or None,
                confirmed=True,
            )
        elif selected == "disconnect":
            manager.disconnect(identity, expected_revision=int(fields["revision"]), confirmed=True)
        else:
            source = fields.get("source_id")
            policy = manager.host.policy(source)
            require(policy is not None and policy["revision"] == int(fields["revision"]), "stale")
            require(manager.host._records(source)[2]["provider"] == "tududi", "unsupported")
            if selected == "reset":
                reset_source(
                    manager, source, expected_policy_revision=policy["revision"], confirmed=True
                )
            elif selected == "policy":
                mode = fields.get("mode")
                interval = int(fields["interval"]) if mode == "scheduled" else None
                schedule_payload(
                    mode="interval" if interval else "manual",
                    timezone="UTC",
                    interval_seconds=interval,
                )
                manager.host.consent(
                    source,
                    capabilities=["task_read"],
                    mode=mode,
                    expected_revision=policy["revision"],
                    confirmed=True,
                )
                ProductivityJobs(instance.store).policy(source, interval_seconds=interval)
            else:
                queued = ProductivityJobs(instance.store).queue(source)
                result = instance.scheduler.run_one(job_id=queued["job"]["id"])
                require(result is not None and result["status"] == "succeeded", "incomplete")
                receipt = read_json(
                    instance.store,
                    f"state/productivity-providers/tududi-runs/{queued['job']['id']}.json",
                )
                return "continuation" if receipt["status"] == "continuation_available" else "saved"
        return "saved"

    @app.post("/tududi/connect")
    async def control(request: Request):
        if not _loopback_request(request):
            raise HTTPException(403, "Tududi controls require loopback")
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "Unsupported Tududi request")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 24 * 1024:
                raise HTTPException(413, "Tududi request too large")
        try:
            values = parse_qs(
                body.decode(), keep_blank_values=True, strict_parsing=True, max_num_fields=14
            )
            require(all(len(value) == 1 for value in values.values()))
            fields = {key: value[0] for key, value in values.items()}
        except ValueError:
            raise HTTPException(400, "Invalid Tududi request") from None
        if not hmac.compare_digest(fields.pop("csrf_token", ""), csrf):
            raise HTTPException(403, "Invalid Tududi control token")
        try:
            notice = await run_in_threadpool(action, fields)
        except (ValueError, KeyError, OSError, TypeError) as error:
            notice = "unsupported" if getattr(error, "code", None) == "unsupported" else "error"
        query = urlencode({"lang": context_factory(request, instance)["lang"], "notice": notice})
        return RedirectResponse(
            "/tududi/connect?" + query, status_code=303, headers={"Cache-Control": "no-store"}
        )
