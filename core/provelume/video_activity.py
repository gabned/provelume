from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response

from .paths import safe_instance_path
from .service import ProvelumeInstance

_JSON_OUTPUTS = {"subtitles.json", "timeline.json", "transcript.json", "video.json"}


def attach_video_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    @app.get("/api/v1/video/support")
    def api_video_support() -> dict[str, Any]:
        return instance.video_support()

    @app.get("/api/v1/video")
    def api_video(
        version_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return instance.video_read_model(version_id=version_id, limit=limit)

    @app.get("/api/v1/video/{representation_id}/outputs/{output_name}")
    def api_video_output(representation_id: str, output_name: str) -> Response:
        if output_name not in _JSON_OUTPUTS:
            raise HTTPException(status_code=404, detail="video output not found")
        selected = instance.get_video(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="video representation not found")
        output = next(
            (
                item
                for item in selected["outputs"]
                if Path(str(item["storage_ref"])).name == output_name
                and item["media_type"] == "application/json"
            ),
            None,
        )
        if output is None:
            raise HTTPException(status_code=404, detail="video output not found")
        try:
            payload = safe_instance_path(instance.root, str(output["storage_ref"])).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="video output invalid") from exc
        if (
            len(payload) != output["size_bytes"]
            or hashlib.sha256(payload).hexdigest() != output["sha256"]
        ):
            raise HTTPException(status_code=409, detail="video output invalid")
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/v1/video/{representation_id}")
    def api_video_profile(representation_id: str) -> dict[str, Any]:
        selected = instance.get_video(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="video representation not found")
        return selected

    @app.get("/video")
    def video_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="video.html",
            context=context_factory(request, instance, model=instance.video_read_model(limit=250)),
        )


__all__ = ["attach_video_routes"]
