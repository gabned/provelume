from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .action_center import ActionCenter
from .action_center_model import ActionCenterError, ActionCenterUnavailable
from .notification_preferences import NotificationPreferences, NotificationPreferencesError
from .notifications import NotificationError, NotificationService
from .service import ProvelumeInstance
from .shell_activity import MutationNonces, _loopback_request
from .shell_settings import ShellSettingsError

MAX_ACTION_FORM_BYTES = 8 * 1024


def action_reason(item: dict[str, Any], translate: Callable[[str], str]) -> str:
    key = "action.reason." + str(item["proposal"]["reason"])
    text = translate(key)
    return text if text != key else translate("action.reason.queue." + item["queue"])


def item_url(item: dict[str, Any], language: str | None = None) -> str:
    values = {"instance_id": item["instance_id"], "revision": item["revision"]}
    if language:
        values["lang"] = language
    return f"/attention/items/{item['id']}?{urlencode(values)}"


def attach_action_center_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
    center: ActionCenter,
) -> None:
    token = secrets.token_urlsafe(32)
    nonces = MutationNonces()

    def page(request: Request, template: str, *, status_code: int = 200, **values):
        context = context_factory(request, instance, **values)
        editable = _loopback_request(request)
        translate = context["t"]

        def reason(item):
            return action_reason(item, translate)

        def label(prefix, name, fallback):
            key = prefix + str(name)
            text = translate(key)
            return text if text != key else translate(fallback)

        def domain_links(item):
            links = []
            for link in item["domain_links"]:
                href = link.get("href", link.get("url", ""))
                parsed = urlsplit(href)
                if (
                    not href.startswith("/")
                    or href.startswith("//")
                    or parsed.scheme
                    or parsed.netloc
                ):
                    continue
                if "\\" in href or any(ord(character) < 32 for character in href):
                    continue
                links.append(
                    {
                        "href": href
                        + ("&" if "?" in href else "?")
                        + urlencode({"lang": context["lang"]}),
                        "label": label(
                            "action.link.",
                            link.get("label", link.get("kind", "")),
                            "action.open_evidence",
                        ),
                    }
                )
            return links

        context.update(
            editable=editable,
            csrf_token=token if editable else None,
            mutation_nonce=nonces.issue() if editable else None,
            request_id=secrets.token_hex(16) if editable else None,
            action_item_url=lambda item: item_url(item, context["lang"]),
            action_reason=reason,
            action_label=label,
            action_domain_links=domain_links,
        )
        return templates.TemplateResponse(
            request=request,
            name=template,
            context=context,
            status_code=status_code,
        )

    async def fields(request: Request, required: set[str], optional: set[str] | None = None):
        if not _loopback_request(request):
            raise HTTPException(403, "Action Center writes require the authorized local browser")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip()
            != "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "unsupported Action Center form type")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_ACTION_FORM_BYTES:
                raise HTTPException(413, "Action Center form is too large")
            body.extend(chunk)
        common = {"csrf_token", "mutation_nonce", "request_id", "instance_id"}
        required = required | common
        try:
            data = parse_qs(
                body.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=20
            )
        except (UnicodeError, ValueError) as exc:
            raise HTTPException(400, "invalid Action Center form") from exc
        if (
            not required.issubset(data)
            or set(data) - required - (optional or set())
            or any(len(v) != 1 for v in data.values())
        ):
            raise HTTPException(400, "invalid Action Center fields")
        values = {k: v[0] for k, v in data.items()}
        if not hmac.compare_digest(values["csrf_token"].encode(), token.encode()):
            raise HTTPException(403, "invalid Action Center form token")
        if not nonces.consume(values["mutation_nonce"]):
            raise HTTPException(409, "Action Center form is expired or replayed")
        if values["instance_id"] != center.authority()["instance_id"]:
            raise HTTPException(409, "Action Center Instance changed")
        return values

    def number(value: str) -> int:
        if not value.isascii() or not value.isdigit() or len(value) > 19:
            raise HTTPException(400, "invalid Action Center revision")
        return int(value)

    @app.exception_handler(ActionCenterUnavailable)
    async def unavailable(request: Request, exc: ActionCenterUnavailable):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.code}, status_code=503)
        return page(
            request, "cura/action_error.html", status_code=503, error="evidence_unavailable"
        )

    @app.get("/api/v1/action-center")
    def api_action_center(
        queue: str | None = None,
        state: str = "awaiting_review",
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        try:
            return center.snapshot(queue=queue, state=state, limit=limit, offset=offset)
        except ActionCenterError as exc:
            raise HTTPException(400, exc.code) from exc

    @app.get("/api/v1/action-center/authority")
    def api_action_authority():
        return center.authority()

    @app.get("/api/v1/action-center/items/{item_id}")
    def api_action_item(item_id: str):
        item = center.get_item(item_id)
        if item is None:
            raise HTTPException(404, "Action Center item not found")
        return item

    @app.get("/attention")
    def attention_page(
        request: Request,
        queue: str | None = None,
        state: str = "awaiting_review",
        offset: int = Query(default=0, ge=0),
    ):
        try:
            snapshot = center.snapshot(queue=queue or None, state=state, limit=50, offset=offset)
        except ActionCenterError as exc:
            raise HTTPException(400, exc.code) from exc
        if (
            request.query_params.get("instance_id", snapshot["instance_id"])
            != snapshot["instance_id"]
        ):
            return page(request, "cura/action_error.html", status_code=409, error="wrong_instance")
        return page(
            request,
            "cura/attention.html",
            attention=snapshot,
            selected_queue=queue or "",
            selected_state=state,
            page_url=lambda selected: (
                "/attention?"
                + urlencode(
                    {
                        "queue": queue or "",
                        "state": state,
                        "offset": selected,
                        "lang": context_factory(request, instance)["lang"],
                    }
                )
            ),
        )

    @app.get("/attention/items/{item_id}")
    def attention_item(request: Request, item_id: str):
        item = center.get_item(item_id)
        if item is None:
            raise HTTPException(404, "Action Center item not found")
        if request.query_params.get("instance_id", item["instance_id"]) != item["instance_id"]:
            return page(request, "cura/action_error.html", status_code=409, error="wrong_instance")
        stale = request.query_params.get("revision", item["revision"]) != item["revision"]
        return page(
            request,
            "cura/action_item.html",
            item=item,
            stale=stale,
            saved=request.query_params.get("saved") == "true",
            error=None,
        )

    @app.post("/attention/items/{item_id}/decision")
    async def attention_decision(request: Request, item_id: str):
        values = await fields(
            request, {"expected_revision", "authority_revision", "action", "confirmed"}
        )
        if values["confirmed"] != "on":
            raise HTTPException(400, "explicit review confirmation is required")
        try:
            center.decide(
                item_id,
                expected_revision=values["expected_revision"],
                action=values["action"],
                request_id=values["request_id"],
                expected_authority_revision=number(values["authority_revision"]),
                principal="local_browser",
            )
        except ActionCenterError as exc:
            item = center.get_item(item_id)
            if item is None:
                return page(request, "cura/action_error.html", status_code=409, error="write_error")
            return page(
                request,
                "cura/action_item.html",
                status_code=409,
                item=item,
                error=exc.code,
                saved=False,
                stale=True,
            )
        item = center.get_item(item_id)
        target = (
            item_url(item, context_factory(request, instance)["lang"]) if item else "/attention"
        )
        return RedirectResponse(
            target + ("&" if "?" in target else "?") + "saved=true", status_code=303
        )

    @app.get("/attention/authority")
    def attention_authority(request: Request):
        return page(
            request,
            "cura/action_authority.html",
            authority=center.authority(),
            error=None,
            sources=instance.list_sources(),
        )

    @app.post("/attention/authority")
    async def action_authority(request: Request):
        values = await fields(request, {"queue", "mode", "revision", "scope", "confirmed"})
        if values["confirmed"] != "on":
            raise HTTPException(400, "explicit scope confirmation is required")
        scope_kind, separator, scope_id = values["scope"].partition(":")
        if not separator:
            raise HTTPException(400, "explicit Action Center scope is required")
        try:
            center.set_authority(
                values["queue"],
                values["mode"],
                expected_revision=number(values["revision"]),
                request_id=values["request_id"],
                scope={"kind": scope_kind, "id": scope_id},
                principal="local_browser",
            )
        except ActionCenterError as exc:
            return page(
                request,
                "cura/action_authority.html",
                status_code=409,
                authority=center.authority(),
                error=exc.code,
                sources=instance.list_sources(),
            )
        return RedirectResponse(
            "/attention/authority?"
            + urlencode({"lang": context_factory(request, instance)["lang"]}),
            status_code=303,
        )

    def notification_view(request: Request, offset: int = 0):
        loaded = getattr(request.state, "shell_settings_snapshot", None)
        if loaded is None:
            loaded = app.state.shell_settings_manager.load()
            request.state.shell_settings_snapshot = loaded
        snapshot = center.snapshot(limit=100, offset=offset)
        notifications = NotificationService(instance.store.paths.root, snapshot["instance_id"])
        return {
            **notifications.preview(snapshot, loaded),
            "offset": offset,
            "limit": 100,
            "observed_count": snapshot["observed_count"],
        }

    @app.get("/api/v1/action-center/notifications")
    def api_action_notifications(request: Request, offset: int = Query(default=0, ge=0, le=10000)):
        return notification_view(request, offset)

    @app.get("/attention/notifications")
    def action_notifications(request: Request, offset: int = Query(default=0, ge=0, le=10000)):
        notification = notification_view(request, offset)
        if (
            request.query_params.get("instance_id", notification["instance_id"])
            != notification["instance_id"]
        ):
            return page(request, "cura/action_error.html", status_code=409, error="wrong_instance")
        stale = (
            request.query_params.get("batch_id", notification["batch_id"])
            != notification["batch_id"]
        )
        return page(
            request,
            "cura/action_notifications.html",
            notification=notification,
            stale=stale,
            error=None,
        )

    @app.post("/attention/notifications/acknowledge")
    async def acknowledge_notifications(request: Request):
        values = await fields(
            request, {"batch_id", "journal_revision", "settings_revision", "offset"}
        )
        offset = number(values["offset"])
        if offset > 10000:
            raise HTTPException(400, "notification page is outside the supported range")
        loaded = app.state.shell_settings_manager.load()
        snapshot = center.snapshot(limit=100, offset=offset)
        notifications = NotificationService(instance.store.paths.root, snapshot["instance_id"])
        try:
            notifications.acknowledge(
                snapshot,
                loaded,
                batch_id=values["batch_id"],
                expected_revision=number(values["journal_revision"]),
                expected_settings_revision=number(values["settings_revision"]),
            )
        except NotificationError as exc:
            return page(
                request,
                "cura/action_notifications.html",
                status_code=409,
                notification={
                    **notifications.preview(snapshot, loaded),
                    "offset": offset,
                    "limit": 100,
                    "observed_count": snapshot["observed_count"],
                },
                error=exc.code,
                stale=True,
            )
        return RedirectResponse(
            "/attention/notifications?"
            + urlencode({"lang": context_factory(request, instance)["lang"], "offset": offset}),
            status_code=303,
        )

    @app.get("/settings/notifications")
    def notification_settings(request: Request):
        return page(
            request,
            "cura/notification_settings.html",
            notification=notification_view(request),
            error=None,
        )

    @app.post("/settings/notifications")
    async def save_notification_settings(request: Request):
        values = await fields(
            request,
            {"revision", "quiet_start", "quiet_end", "timezone", "aggregation_seconds"},
            {"in_app", "quiet_enabled"},
        )
        if any(values.get(key, "on") != "on" for key in ("in_app", "quiet_enabled")):
            raise HTTPException(400, "invalid notification switch")
        manager = app.state.shell_settings_manager
        # Channels not yet supported cannot be activated through this form.
        # Preserve existing outward choices for later adapters and preference transfer.
        previous = manager.load().settings.notifications
        preferences = NotificationPreferences(
            in_app="in_app" in values,
            host_desktop=previous.host_desktop,
            browser=previous.browser,
            pwa=previous.pwa,
            quiet_enabled="quiet_enabled" in values,
            quiet_start=values["quiet_start"],
            quiet_end=values["quiet_end"],
            timezone=values["timezone"],
            aggregation_seconds=number(values["aggregation_seconds"]),
        )
        try:
            manager.configure_notifications(
                preferences, expected_revision=number(values["revision"]), source="local_browser"
            )
        except (NotificationPreferencesError, ShellSettingsError) as exc:
            return page(
                request,
                "cura/notification_settings.html",
                status_code=409,
                notification=notification_view(request),
                error=getattr(exc, "code", "invalid_preferences"),
            )
        return RedirectResponse(
            "/settings/notifications?"
            + urlencode({"lang": context_factory(request, instance)["lang"]}),
            status_code=303,
        )

    @app.get("/settings/notifications/history")
    def notification_history(request: Request):
        return page(
            request,
            "cura/notification_history.html",
            notification=notification_view(request),
            error=None,
        )

    @app.post("/settings/notifications/history")
    async def reset_notification_history(request: Request):
        values = await fields(
            request, {"journal_revision", "settings_revision", "confirm_redelivery"}
        )
        if values["confirm_redelivery"] != "on":
            raise HTTPException(400, "explicit notification redelivery confirmation is required")
        snapshot = center.snapshot(limit=100)
        service = NotificationService(instance.store.paths.root, snapshot["instance_id"])
        loaded = app.state.shell_settings_manager.load()
        try:
            service.reset_acknowledgements(
                loaded,
                expected_revision=number(values["journal_revision"]),
                expected_settings_revision=number(values["settings_revision"]),
                confirm_redelivery=True,
            )
        except NotificationError as exc:
            return page(
                request,
                "cura/notification_history.html",
                status_code=409,
                notification=service.preview(snapshot, loaded),
                error=exc.code,
            )
        return RedirectResponse(
            "/attention/notifications?"
            + urlencode({"lang": context_factory(request, instance)["lang"]}),
            status_code=303,
        )
