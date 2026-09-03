from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response

from .paths import safe_instance_path
from .service import ProvelumeInstance


def attach_audio_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    @app.get("/api/v1/audio/support")
    def api_audio_support() -> dict[str, Any]:
        return instance.audio_support()

    @app.get("/api/v1/audio")
    def api_audio(
        version_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return instance.audio_read_model(version_id=version_id, limit=limit)

    @app.get("/api/v1/audio/{representation_id}/outputs/{output_name}")
    def api_audio_output(representation_id: str, output_name: str) -> Response:
        if output_name not in {"time-map.json", "transcript.json", "waveform.json"}:
            raise HTTPException(status_code=404, detail="audio output not found")
        selected = instance.get_audio(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="audio representation not found")
        output = next(
            (
                item
                for item in selected["outputs"]
                if Path(str(item["storage_ref"])).name == output_name
            ),
            None,
        )
        if output is None:
            raise HTTPException(status_code=404, detail="audio output not found")
        try:
            payload = safe_instance_path(instance.root, str(output["storage_ref"])).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="audio output invalid") from exc
        if (
            len(payload) != output["size_bytes"]
            or hashlib.sha256(payload).hexdigest() != output["sha256"]
        ):
            raise HTTPException(status_code=409, detail="audio output invalid")
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/v1/audio/{representation_id}")
    def api_audio_profile(representation_id: str) -> dict[str, Any]:
        selected = instance.get_audio(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="audio representation not found")
        return selected

    @app.get("/audio")
    def audio_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="audio.html",
            context=context_factory(request, instance, model=instance.audio_read_model(limit=250)),
        )


__all__ = ["attach_audio_routes"]
