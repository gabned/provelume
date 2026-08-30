from __future__ import annotations

import hmac
import ipaddress
import secrets
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request

from .ocr_contract import OCR_MODES, OcrContractError, OcrUnavailableError
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance

MAX_OCR_BODY_BYTES = 16 * 1024


def _loopback_request(request: Request) -> bool:
    if request.client is None:
        return False
    if request.client.host == "testclient":
        return True
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def _csv(value: str) -> tuple[str, ...]:
    return tuple(sorted({item.strip() for item in value.split(",") if item.strip()}))


def _pages(value: str) -> tuple[int, ...]:
    try:
        return tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    except ValueError as exc:
        raise OcrContractError(
            "ocr_invalid_selection", "Selected OCR pages must be integers"
        ) from exc


def attach_ocr_routes(
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
        editable = _loopback_request(request)
        settings = instance.ocr.configured_settings()
        try:
            capability = instance.ocr_capability()
        except (OcrContractError, OcrUnavailableError, OSError):
            capability = {
                "state": "adapter-unavailable",
                "available": False,
                "adapter": None,
                "renderer": None,
                "limits": settings.limits.as_record(),
            }
        return context_factory(
            request,
            instance,
            ocr_settings=settings.as_record(),
            ocr_modes=OCR_MODES,
            capability=capability,
            jobs=instance.list_ocr_jobs(limit=100),
            bundles=instance.list_ocr_bundles(),
            editable=editable,
            csrf_token=csrf_token if editable else None,
            saved=saved,
            error=error,
        )

    @app.get("/ocr")
    def ocr_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="ocr.html",
            context=values(request),
        )

    @app.post("/ocr")
    async def mutate_ocr(request: Request):
        if not _loopback_request(request):
            raise HTTPException(
                status_code=403, detail="OCR can be controlled only from the local browser"
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="unsupported OCR content type")
        body = await request.body()
        if len(body) > MAX_OCR_BODY_BYTES:
            raise HTTPException(status_code=413, detail="OCR request is too large")
        try:
            fields = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=16,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid OCR request") from exc
        if not hmac.compare_digest(
            fields.get("csrf_token", [""])[0], csrf_token
        ):
            raise HTTPException(status_code=403, detail="invalid OCR token")
        action = fields.get("action", [""])[0]
        try:
            if action == "configure":
                current = instance.ocr.configured_settings()
                languages = _csv(fields.get("languages", [""])[0])
                settings = replace(
                    current,
                    mode=fields.get("mode", [""])[0],
                    languages=languages or current.languages,
                    engine_executable=fields.get("engine_executable", [""])[0],
                    tessdata_path=(
                        fields.get("tessdata_path", [""])[0].strip() or None
                    ),
                    render_dpi=int(fields.get("render_dpi", ["300"])[0]),
                )
                instance.configure_ocr(settings)
                message = "configured"
            elif action == "queue":
                queued = instance.queue_ocr(
                    fields.get("version_id", [""])[0],
                    mode=fields.get("mode", [""])[0],
                    languages=_csv(fields.get("languages", [""])[0]) or None,
                    pages=_pages(fields.get("pages", [""])[0]),
                )
                message = (
                    f"queued:{queued['job']['id']}"
                    if queued.get("scheduled")
                    else f"skipped:{queued['reason']}"
                )
            elif action == "cancel":
                instance.cancel_ocr_job(fields.get("job_id", [""])[0])
                message = "cancellation-requested"
            elif action == "remove":
                instance.remove_ocr(fields.get("version_id", [""])[0])
                message = "removed"
            elif action == "rebuild":
                result = instance.rebuild_ocr(fields.get("version_id", [""])[0])
                message = f"queued:{result['queued']['job']['id']}"
            else:
                raise OcrContractError(
                    "ocr_contract_violation", "Unsupported OCR control action"
                )
        except (
            OcrContractError,
            OcrUnavailableError,
            SchedulerError,
            OSError,
            ValueError,
        ) as exc:
            return templates.TemplateResponse(
                request=request,
                name="ocr.html",
                status_code=400,
                context=values(request, error=str(exc)),
            )
        return templates.TemplateResponse(
            request=request,
            name="ocr.html",
            context=values(request, saved=message),
        )


__all__ = ["attach_ocr_routes"]
