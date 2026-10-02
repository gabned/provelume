"""Local preference previews; temporary plans are not job or knowledge state."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import Response

from .cura_shell import script_integrity
from .shell_activity import _loopback_request
from .shell_preferences import (
    PREFERENCE_FIELDS,
    apply_preferences,
    parse_preferences,
    preference_bytes,
    preference_digest,
    preference_display,
    preference_payload,
    reset_preview,
)
from .shell_settings import MAX_SETTINGS_REVISION, ShellSettingsError, ShellSettingsStale


class PreferencePlans:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.rows = OrderedDict()
        self.lock = threading.Lock()

    def put(self, value):
        with self.lock:
            now = self.clock()
            self.rows = OrderedDict((k, v) for k, v in self.rows.items() if now - v[0] <= 600)
            if len(self.rows) >= 64:
                raise ValueError("preference preview capacity reached")
            key = secrets.token_urlsafe(24)
            self.rows[key] = (now, value)
            return key

    def take(self, key):
        with self.lock:
            row = self.rows.pop(key, None)
        if row is None or self.clock() - row[0] > 600:
            raise ValueError("preference preview expired or already used")
        return row[1]


def attach_preference_routes(app, instance, templates, context_factory, manager, csrf, nonces):
    plans = PreferencePlans()

    def local(request):
        if not _loopback_request(request):
            raise HTTPException(403, "host preferences require the local browser")

    def page(request, *, plan=None, plan_key=None, undo_key=None, saved=False, error=False):
        loaded = manager.load()
        context = context_factory(request, instance)
        language = context["lang"]
        # Use the existing exact-script CSP binding on this current-interface page
        # as well; never enable arbitrary same-origin or inline document scripts.
        integrity = script_integrity()
        request.state.cura_script_integrity = integrity
        context.update(
            preferences=preference_payload(loaded.settings),
            revision=loaded.settings.revision,
            first_run=loaded.settings.revision == 0,
            csrf_token=csrf,
            mutation_nonce=nonces.issue(),
            plan=plan,
            plan_key=plan_key,
            undo_key=undo_key,
            saved=saved,
            error=error,
            cura_script_integrity=integrity,
            preference_display=lambda key, value: preference_display(key, value, language),
        )
        return templates.TemplateResponse(
            request=request,
            name="shell_preferences.html",
            status_code=400 if error else 200,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            context=context,
        )

    @app.get("/settings/preferences")
    def preference_page(request: Request):
        local(request)
        return page(request)

    @app.get("/settings/preferences/export")
    def export(request: Request):
        local(request)
        return Response(
            preference_bytes(preference_payload(manager.load().settings)),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="provelume-preferences.json"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/settings/preferences")
    async def preference_action(request: Request):
        local(request)
        if (
            request.headers.get("content-type", "").split(";", 1)[0]
            != "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "unsupported preference content type")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 128 * 1024:
                raise HTTPException(413, "preference request exceeds limit")
        try:
            fields = parse_qs(
                body.decode("utf-8"), keep_blank_values=True, max_num_fields=8, strict_parsing=True
            )
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(400, "invalid preference form") from exc
        required = {"csrf_token", "mutation_nonce", "revision", "action"}
        if not required <= set(fields) or any(len(v) != 1 for v in fields.values()):
            raise HTTPException(400, "invalid preference form fields")
        fields = {k: v[0] for k, v in fields.items()}
        actions = {
            "preview-reset": {"scope"},
            "preview-import": {"preferences_json"},
            "confirm": {"plan_key"},
            "undo": {"plan_key"},
        }
        if fields["action"] not in actions or set(fields) != required | actions[fields["action"]]:
            raise HTTPException(400, "unsupported preference action")
        if not hmac.compare_digest(fields["csrf_token"].encode(), csrf.encode()):
            raise HTTPException(403, "invalid preference token")
        revision = fields["revision"]
        if (
            not revision.isascii()
            or not revision.isdigit()
            or len(revision) > 19
            or int(revision) > MAX_SETTINGS_REVISION
        ):
            raise HTTPException(400, "invalid preference revision")
        if not nonces.consume(fields["mutation_nonce"]):
            raise HTTPException(409, "preference request expired or replayed")
        try:
            current = manager.load().settings
            if current.revision != int(revision):
                raise ShellSettingsStale("preferences changed")
            before = preference_payload(current)
            action = fields["action"]
            if action.startswith("preview-"):
                after = (
                    reset_preview(current, fields["scope"])["after"]
                    if action == "preview-reset"
                    else parse_preferences(fields["preferences_json"].encode(), current=current)
                )
                plan = {
                    "kind": "confirm",
                    "before": before,
                    "after": after,
                    "revision": current.revision,
                    "changed_fields": sorted(k for k in PREFERENCE_FIELDS if before[k] != after[k]),
                }
                key = plans.put(plan)
                return page(request, plan=plan, plan_key=key)
            plan = plans.take(fields["plan_key"])
            if plan["kind"] != action or plan["revision"] != current.revision:
                raise ShellSettingsStale("preference plan no longer matches")
            committed = apply_preferences(
                manager,
                plan["after"],
                expected_revision=current.revision,
                expected_digest=preference_digest(plan["before"]),
            )
            request.state.shell_settings_snapshot = manager.load()
            undo_key = None
            if action == "confirm":
                undo_key = plans.put(
                    {
                        "kind": "undo",
                        "before": preference_payload(committed),
                        "after": plan["before"],
                        "revision": committed.revision,
                    }
                )
            return page(request, undo_key=undo_key, saved=True)
        except (OSError, ValueError, ShellSettingsError):
            return page(request, error=True)
