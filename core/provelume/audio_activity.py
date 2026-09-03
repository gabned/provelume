from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response

from .audio_profiles import AudioContractError
from .paths import safe_instance_path
from .service import ProvelumeInstance


def _raise_http(exc: AudioContractError) -> None:
    status = 404 if exc.code == "audio_not_found" else 409 if "job_state" in exc.code else 422
    raise HTTPException(
        status_code=status,
        detail={"error_code": exc.code, "message": str(exc)},
    ) from exc


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

    @app.post("/api/v1/audio/jobs/{version_id}", status_code=202)
    def api_queue_audio(
        version_id: str,
        language: str = "auto",
        threads: int = Query(default=2, ge=1, le=16),
    ) -> dict[str, Any]:
        try:
            return instance.queue_audio(version_id, language=language, threads=threads)
        except AudioContractError as exc:
            _raise_http(exc)

    @app.post("/api/v1/audio/jobs/{job_id}/run")
    def api_run_audio(job_id: str) -> dict[str, Any]:
        try:
            return instance.run_audio_job(job_id)
        except AudioContractError as exc:
            _raise_http(exc)

    @app.post("/api/v1/audio/jobs/{job_id}/cancel")
    def api_cancel_audio(job_id: str) -> dict[str, Any]:
        try:
            return instance.cancel_audio_job(job_id)
        except AudioContractError as exc:
            _raise_http(exc)

    @app.post("/api/v1/audio/jobs/{job_id}/retry")
    def api_retry_audio(job_id: str) -> dict[str, Any]:
        try:
            return instance.retry_audio_job(job_id)
        except AudioContractError as exc:
            _raise_http(exc)

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

    @app.delete("/api/v1/audio/{representation_id}")
    def api_remove_audio(representation_id: str) -> dict[str, Any]:
        try:
            return instance.remove_audio(representation_id)
        except AudioContractError as exc:
            _raise_http(exc)

    @app.post("/api/v1/audio/{representation_id}/rebuild")
    def api_rebuild_audio(representation_id: str) -> dict[str, Any]:
        try:
            return instance.rebuild_audio(representation_id)
        except AudioContractError as exc:
            _raise_http(exc)

    @app.get("/audio")
    def audio_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="audio.html",
            context=context_factory(request, instance, model=instance.audio_read_model(limit=250)),
        )


__all__ = ["attach_audio_routes"]
