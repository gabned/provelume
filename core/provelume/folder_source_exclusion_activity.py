from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .folder_source_exclusion_i18n import exclusion_message
from .folder_source_exclusions import propose_change
from .folder_source_model import FolderSourceError
from .service import ProvelumeInstance
from .source_exclusions import KINDS, ExclusionError


def attach_exclusion_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable,
    source_fields: Callable,
    loopback: Callable,
    csrf_token: str,
) -> None:
    def current(source_id: str):
        try:
            return instance.folder_source_exclusions(source_id)
        except (FolderSourceError, ExclusionError) as exc:
            raise HTTPException(status_code=404, detail="Folder Source is unavailable") from exc

    def page(request: Request, source_id: str, *, preview=None, form=None, error=None, saved=False):
        view = current(source_id)
        return context_factory(
            request,
            instance,
            source=instance.folder_sources.public_view(source_id),
            policy=view["policy"],
            preview=preview,
            form=form or {},
            error=error,
            saved=saved,
            kinds=KINDS,
            editable=loopback(request),
            csrf_token=csrf_token if loopback(request) else None,
        )

    async def selected_fields(request: Request):
        raw = await source_fields(request)
        allowed = {
            "csrf_token",
            "action",
            "revision",
            "operation",
            "enabled",
            "rule_id",
            "kind",
            "pattern",
            "rule_action",
            "rule_enabled",
            "preview_fingerprint",
        }
        if set(raw) - allowed:
            raise HTTPException(status_code=400, detail="Unsupported exclusion field")
        return {key: items[0] for key, items in raw.items() if key != "csrf_token"}

    @app.get("/api/v1/folder-sources/{source_id}/exclusions")
    def exclusions_api(source_id: str):
        return current(source_id)

    @app.post("/api/v1/folder-sources/{source_id}/exclusions/preview")
    async def preview_api(source_id: str, request: Request):
        fields = await selected_fields(request)
        if fields.get("action", "preview") != "preview":
            raise HTTPException(status_code=400, detail="This endpoint only previews rules")
        try:
            proposed = propose_change(current(source_id)["policy"], fields)
            return await run_in_threadpool(
                instance.preview_folder_source_exclusions, source_id, proposed
            )
        except ExclusionError as exc:
            language = context_factory(request, instance)["lang"]
            raise HTTPException(
                status_code=400,
                detail={
                    "diagnostic_code": exc.code,
                    "message": exclusion_message(exc.code, language),
                },
            ) from exc

    @app.get("/sources/{source_id}/exclusions")
    def exclusions_page(source_id: str, request: Request):
        return templates.TemplateResponse(
            request=request, name="folder_source_exclusions.html", context=page(request, source_id)
        )

    @app.post("/sources/{source_id}/exclusions")
    async def change_exclusions(source_id: str, request: Request):
        fields = await selected_fields(request)
        try:
            proposed = propose_change(current(source_id)["policy"], fields)
            action = fields.get("action")
            if action == "preview":
                preview = await run_in_threadpool(
                    instance.preview_folder_source_exclusions, source_id, proposed
                )
                context = page(request, source_id, preview=preview, form=fields)
            elif action == "apply":
                await run_in_threadpool(
                    instance.apply_folder_source_exclusions,
                    source_id,
                    proposed,
                    preview_fingerprint=fields.get("preview_fingerprint", ""),
                )
                context = page(request, source_id, saved=True)
            else:
                raise ExclusionError("Unsupported exclusion action.")
        except ExclusionError as exc:
            context = page(request, source_id, form=fields)
            context["error"] = exclusion_message(exc.code, context["lang"])
            return templates.TemplateResponse(
                request=request,
                name="folder_source_exclusions.html",
                context=context,
                status_code=400,
            )
        return templates.TemplateResponse(
            request=request, name="folder_source_exclusions.html", context=context
        )
