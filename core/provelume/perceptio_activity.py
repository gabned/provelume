from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

from .perceptio import PerceptioError
from .service import ProvelumeInstance


def attach_perceptio_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    @app.get("/api/v1/perceptio")
    def api_perceptio(
        version_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return instance.perceptio_read_model(version_id=version_id, limit=limit)
        except PerceptioError as exc:
            raise HTTPException(status_code=400, detail=exc.code) from exc

    @app.get("/api/v1/perceptio/representations/{representation_id}/anchors/{anchor_id}")
    def api_perceptio_anchor(representation_id: str, anchor_id: str) -> dict[str, Any]:
        selected = instance.get_perceptio_anchor(representation_id, anchor_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="Perceptio anchor not found")
        return selected

    @app.get("/api/v1/perceptio/representations/{representation_id}")
    def api_perceptio_representation(representation_id: str) -> dict[str, Any]:
        selected = instance.get_perceptio_representation(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="Perceptio representation not found")
        return selected

    @app.get("/perceptio")
    def perceptio_page(request: Request):
        model = instance.perceptio_read_model(limit=250)
        return templates.TemplateResponse(
            request=request,
            name="perceptio.html",
            context=context_factory(request, instance, model=model),
        )


__all__ = ["attach_perceptio_routes"]
