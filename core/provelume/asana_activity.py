"""Loopback Asana connection and explicit Source controls; no vault/network on GET."""

import hmac
import json
import secrets
from urllib.parse import parse_qs, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .asana_connection import AUTHORIZE
from .asana_intake import reset_source
from .google_activity import _loopback_request
from .instance_lifecycle import InstanceLifecycleManager
from .productivity_contract import require
from .productivity_jobs import ProductivityJobs
from .review_decisions import read_json
from .scheduler_model import schedule_payload

HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def attach_asana_routes(app, instance, templates, context_factory, *, redirect_uri):
    csrf = secrets.token_urlsafe(32)

    @app.get("/asana/connect")
    def page(request: Request):
        values = context_factory(request, instance)
        values.update(connection=instance.asana_connection().view(), csrf_token=csrf,
                      callback_uri=redirect_uri,
                      editable=_loopback_request(request),
                      notice=request.query_params.get("notice"))
        return templates.TemplateResponse(request=request, name="asana_connection.html",
                                          context=values, headers=HEADERS)

    def action(fields):
        manager = instance.asana_connection()
        require(fields.get("confirm") == "yes", "consent_required")
        selected, identity = fields.get("action"), fields.get("identity") or None
        allowed = {
            "configure": {"client_json"}, "network": {"enabled"},
            "connect": {"name", "identity"}, "catalogue": {"identity", "workspace"},
            "select": {"identity", "name", "scope", "workspace", "team", "project"},
            "disconnect": {"identity", "revision"}, "revoke": {"identity", "revision"},
            "read": {"source_id", "revision"}, "reset": {"source_id", "revision"},
            "policy": {"source_id", "revision", "mode", "interval"}}
        require(selected in allowed
                and not (set(fields) - allowed[selected] - {"action", "confirm"}))
        if selected == "network":
            require(fields.get("enabled") in {"yes", "no"})
            with InstanceLifecycleManager(instance.store)._hold(purpose="asana-network-consent"):
                config = instance.store.read_config()
                config["network"]["external_access"] = fields["enabled"] == "yes"
                instance.store.write_config(config)
        elif selected == "configure":
            manager.configure(json.loads(fields["client_json"]))
        elif selected == "connect":
            return manager.begin(name=fields.get("name") or "Asana", redirect_uri=redirect_uri,
                                  confirmed=True, identity=identity)
        elif selected == "catalogue":
            manager.catalogue(identity, workspace=fields.get("workspace") or None, confirmed=True)
        elif selected == "select":
            scope = fields.get("scope")
            manager.select_source(identity, name=fields.get("name"), scope=scope,
                workspace=fields.get("workspace"), team=fields.get("team") if scope == "team"
                else None, project=fields.get("project") if scope == "project" else None,
                confirmed=True)
        elif selected in {"disconnect", "revoke"}:
            if selected == "disconnect":
                manager.disconnect(identity, expected_revision=int(fields["revision"]),
                                   confirmed=True)
            else:
                receipt = manager.revoke_remote(identity, expected_revision=int(fields["revision"]),
                                                 confirmed=True)
                return {"notice": "saved" if receipt["remote_revocation"] == "CONFIRMED"
                        else "remote_unknown"}
        else:
            source = fields.get("source_id")
            policy = manager.host.policy(source)
            require(policy is not None and policy["revision"] == int(fields["revision"]), "stale")
            require(manager.host._records(source)[2]["provider"] == "asana", "unsupported")
            if selected == "reset":
                reset_source(manager, source, expected_policy_revision=policy["revision"],
                             confirmed=True)
            elif selected == "policy":
                mode = fields.get("mode")
                interval = int(fields["interval"]) if mode == "scheduled" else None
                schedule_payload(mode="interval" if interval else "manual", timezone="UTC",
                                  interval_seconds=interval)
                manager.host.consent(source, capabilities=["task_read"], mode=mode,
                    expected_revision=policy["revision"], confirmed=True)
                ProductivityJobs(instance.store).policy(source, interval_seconds=interval)
            else:
                queued = ProductivityJobs(instance.store).queue(source)
                result = instance.scheduler.run_one(job_id=queued["job"]["id"])
                require(result is not None and result["status"] == "succeeded", "incomplete")
                receipt = read_json(instance.store,
                    f"state/productivity-providers/asana-runs/{queued['job']['id']}.json")
                return {"notice": "continuation" if receipt["status"] == "continuation_available"
                        else "saved"}
        return {"notice": "saved"}

    @app.post("/asana/connect")
    async def control(request: Request):
        if not _loopback_request(request):
            raise HTTPException(403, "Asana controls require loopback")
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "Unsupported Asana request")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 24 * 1024:
                raise HTTPException(413, "Asana request too large")
        try:
            values = parse_qs(body.decode(), keep_blank_values=True, strict_parsing=True,
                              max_num_fields=14)
            require(all(len(value) == 1 for value in values.values()))
            fields = {key: value[0] for key, value in values.items()}
        except ValueError:
            raise HTTPException(400, "Invalid Asana request") from None
        if not hmac.compare_digest(fields.pop("csrf_token", ""), csrf):
            raise HTTPException(403, "Invalid Asana control token")
        try:
            result = await run_in_threadpool(action, fields)
            if "authorization_uri" in result:
                uri = result["authorization_uri"]
                require(uri.startswith(AUTHORIZE + "?"), "callback")
                return RedirectResponse(uri, status_code=303, headers=HEADERS)
            notice = result["notice"]
        except (ValueError, KeyError, OSError, TypeError):
            notice = "error"
        query = urlencode({"lang": context_factory(request, instance)["lang"], "notice": notice})
        return RedirectResponse("/asana/connect?" + query, status_code=303, headers=HEADERS)

    @app.get("/asana/oauth/callback")
    async def callback(request: Request):
        query = request.scope.get("query_string", b"")
        request.scope["query_string"] = b""
        if not _loopback_request(request):
            raise HTTPException(403, "Asana callback requires loopback")
        try:
            await run_in_threadpool(instance.asana_connection().complete,
                                   query, redirect_uri=redirect_uri)
            notice = "saved"
        except (ValueError, KeyError, OSError, TypeError):
            notice = "error"
        return RedirectResponse("/asana/connect?" + urlencode({"notice": notice}),
                                status_code=303, headers=HEADERS)
