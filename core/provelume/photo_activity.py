from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response

from .paths import safe_instance_path
from .photo_profiles import PhotoContractError
from .service import ProvelumeInstance


def _raise_http(exc: PhotoContractError) -> None:
    status = 404 if exc.code == "photo_not_found" else 409 if "job_state" in exc.code else 422
    raise HTTPException(
        status_code=status, detail={"error_code": exc.code, "message": str(exc)}
    ) from exc


def attach_photo_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    @app.get("/api/v1/photos/support")
    def api_photo_support() -> dict[str, Any]:
        return instance.photo_support()

    @app.get("/api/v1/photos")
    def api_photos(
        version_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return instance.photo_read_model(version_id=version_id, limit=limit)

    @app.post("/api/v1/photos/jobs/{version_id}", status_code=202)
    def api_queue_photo(version_id: str) -> dict[str, Any]:
        try:
            return instance.queue_photo(version_id)
        except PhotoContractError as exc:
            _raise_http(exc)

    @app.post("/api/v1/photos/jobs/{job_id}/run")
    def api_run_photo(job_id: str) -> dict[str, Any]:
        try:
            return instance.run_photo_job(job_id)
        except PhotoContractError as exc:
            _raise_http(exc)

    @app.get("/api/v1/photos/{representation_id}/preview")
    def api_photo_preview(representation_id: str) -> Response:
        selected = instance.get_photo(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="photo representation not found")
        output = next(
            (
                item
                for item in selected["outputs"]
                if Path(str(item["storage_ref"])).name == "preview.png"
                and item["media_type"] == "image/png"
            ),
            None,
        )
        if output is None:
            raise HTTPException(status_code=404, detail="sanitized preview unavailable")
        try:
            payload = safe_instance_path(instance.root, str(output["storage_ref"])).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="sanitized preview invalid") from exc
        return Response(
            content=payload,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/v1/photos/{representation_id}")
    def api_photo(representation_id: str) -> dict[str, Any]:
        selected = instance.get_photo(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="photo representation not found")
        return selected

    @app.delete("/api/v1/photos/{representation_id}")
    def api_remove_photo(representation_id: str) -> dict[str, Any]:
        try:
            return instance.remove_photo(representation_id)
        except PhotoContractError as exc:
            _raise_http(exc)

    @app.post("/api/v1/photos/{representation_id}/rebuild")
    def api_rebuild_photo(representation_id: str) -> dict[str, Any]:
        try:
            return instance.rebuild_photo(representation_id)
        except PhotoContractError as exc:
            _raise_http(exc)

    @app.get("/photos")
    def photos_page(request: Request):
        model = instance.photo_read_model(limit=250)
        return templates.TemplateResponse(
            request=request,
            name="photos.html",
            context=context_factory(request, instance, model=model),
        )


__all__ = ["attach_photo_routes"]
