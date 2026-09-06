from __future__ import annotations

import hmac
import secrets
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .google_activity import _loopback_request
from .google_connection_i18n import TEXT, connection_translator
from .google_contract import GoogleAuthorizationError, GoogleContractError
from .google_credentials import GoogleCredentialError
from .google_oauth import GoogleConnectionError
from .instance_lifecycle import InstanceLifecycleError
from .oauth_authorization import OAuthAuthorizationError
from .scheduler_model import SchedulerError

HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
CALLBACK_ERRORS = {
    "google_account_mismatch",
    "google_callback_invalid",
    "google_connection_busy",
    "google_connection_failed",
    "google_consent_cancelled",
    "google_network_disabled",
    "google_reconnect_required",
    "google_scope_mismatch",
    "google_secure_store_unavailable",
}


def attach_google_connection_routes(app, instance, templates, context_factory, *, redirect_uri):
    csrf = secrets.token_urlsafe(32)
    manager = instance.google_connection

    def render(request, *, message=None, error=None, status=200):
        values = context_factory(request, instance)
        editable = _loopback_request(request)
        values.update(
            connection=manager.view(),
            editable=editable,
            csrf_token=csrf if editable else None,
            message=message,
            error=error,
            gt=connection_translator(values["lang"]),
            jobs=instance.list_google_jobs(),
        )
        return templates.TemplateResponse(
            request=request,
            name="google_connection.html",
            context=values,
            status_code=status,
            headers=HEADERS,
        )

    @app.get("/google/connect")
    def page(request: Request):
        notice = request.query_params.get("notice")
        return render(request, error=notice if notice in CALLBACK_ERRORS else None)

    @app.get("/api/v1/google/connection")
    def read_model():
        return JSONResponse(manager.view(), headers=HEADERS)

    @app.get("/google/connect/evidence")
    def evidence(request: Request, expected_head: str):
        if not _loopback_request(request):
            raise HTTPException(403, "Google qualification evidence requires loopback")
        try:
            report = manager.evidence.report(
                expected_head=expected_head, jobs=instance.list_google_jobs(limit=500)
            )
        except ValueError:
            raise HTTPException(
                400, "Google qualification requires exact embedded build identity"
            ) from None
        return JSONResponse(
            report,
            headers={
                **HEADERS,
                "Content-Disposition": 'attachment; filename="google-connection-evidence.json"',
            },
        )

    async def fields(request):
        if not _loopback_request(request):
            raise HTTPException(403, "Google connection requires loopback")
        if request.headers.get("content-type", "").split(";", 1)[0] != (
            "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "unsupported Google connection request")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 24 * 1024:
                raise HTTPException(413, "Google connection request too large")
        try:
            parsed = parse_qs(
                body.decode(), strict_parsing=True, keep_blank_values=True, max_num_fields=10
            )
        except (ValueError, UnicodeError):
            raise HTTPException(400, "invalid Google connection request") from None
        if any(len(value) != 1 for value in parsed.values()):
            raise HTTPException(400, "duplicate Google connection field")
        values = {key: value[0] for key, value in parsed.items()}
        if not hmac.compare_digest(values.pop("csrf_token", ""), csrf):
            raise HTTPException(403, "invalid Google connection token")
        return values

    def action(values):
        selected = values.get("action")
        allowed = {
            "network": {"enabled", "consent"},
            "configure": {"client_json"},
            "connect": {"capability", "consent", "name", "instance_id"},
            "test": {"instance_id", "capability"},
            "disconnect": {"instance_id", "capability"},
            "cancel-consent": {"instance_id", "capability"},
            "revoke-project": {"instance_id", "capability", "consent"},
            "start": {"source_id"},
            "continue": {"source_id"},
            "cancel-job": {"job_id"},
        }
        if selected not in allowed or set(values) - {"action"} - allowed[selected]:
            raise GoogleConnectionError("google_callback_invalid")
        identity = values.get("instance_id") or None
        capability = values.get("capability")
        if selected == "network":
            if values.get("enabled") not in {"yes", "no"}:
                raise GoogleConnectionError("google_callback_invalid")
            return manager.set_network(
                enabled=values["enabled"] == "yes", consent=values.get("consent") == "yes"
            )
        if selected == "configure":
            return manager.configure(values.get("client_json", ""))
        if selected == "connect":
            return manager.begin(
                capability=capability,
                redirect_uri=redirect_uri,
                consent=values.get("consent") == "yes",
                instance_id=identity,
                name=values.get("name") or "Google",
            )
        if selected in {"test", "disconnect", "cancel-consent", "revoke-project"}:
            if selected == "test":
                return manager.test(identity, capability)
            if selected == "disconnect":
                return manager.disconnect(identity, capability)
            if selected == "cancel-consent":
                return manager.cancel(identity, capability)
            return manager.revoke_project(
                identity, capability, consent=values.get("consent") == "yes"
            )
        if selected == "cancel-job":
            instance.cancel_google_job(values.get("job_id"))
            return {"status": "google_cancelled"}
        source_id = values.get("source_id")
        source = instance.google_sources.source_record(source_id)
        manager._network(source["connector_instance_id"])
        capability_state = instance.google_sources.capability_record(
            source["connector_instance_id"], source["capability"]
        )
        if capability_state["state"] != "enabled":
            instance.set_google_capability_state(
                source["connector_instance_id"], source["capability"], state="enabled"
            )
        if source["state"] != "enabled":
            instance.set_google_source_state(source_id, state="enabled")
        instance.google.queue(source_id, guided=True)
        return {"status": "google_queued"}

    def diagnostic(exc):
        if isinstance(exc, InstanceLifecycleError):
            return "google_connection_busy"
        if isinstance(exc, GoogleAuthorizationError):
            return "google_reconnect_required"
        if isinstance(exc, GoogleCredentialError):
            return "google_secure_store_unavailable"
        if isinstance(exc, OAuthAuthorizationError):
            return "google_callback_invalid"
        code = getattr(exc, "code", "google_connection_failed")
        return code if code in TEXT else "google_connection_failed"

    failures = (
        InstanceLifecycleError,
        GoogleConnectionError,
        GoogleCredentialError,
        GoogleContractError,
        OAuthAuthorizationError,
        SchedulerError,
        OSError,
        ValueError,
    )

    @app.post("/google/connect")
    async def control(request: Request):
        values = await fields(request)
        try:
            result = await run_in_threadpool(action, values)
            if "authorization_uri" in result:
                return RedirectResponse(
                    result["authorization_uri"], status_code=303, headers=HEADERS
                )
            return render(request, message=result["status"])
        except failures as exc:
            return render(request, error=diagnostic(exc), status=400)

    @app.get("/google/oauth/callback")
    async def callback(request: Request):
        query = request.scope.get("query_string", b"")
        request.scope["query_string"] = b""
        if not _loopback_request(request):
            raise HTTPException(403, "Google callback requires loopback")
        # Redirect immediately to a clean URL after processing; never echo callback content.
        try:
            await run_in_threadpool(manager.complete, query, redirect_uri=redirect_uri)
        except failures as exc:
            code = diagnostic(exc)
            notice = code if code in CALLBACK_ERRORS else "google_callback_invalid"
            return RedirectResponse(
                f"/google/connect?notice={notice}", status_code=303, headers=HEADERS
            )
        return RedirectResponse("/google/connect", status_code=303, headers=HEADERS)
