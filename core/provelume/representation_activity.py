from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

from .service import ProvelumeInstance


def attach_representation_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    @app.get("/api/v1/representations/support")
    def api_representation_support(profile_id: str | None = None) -> dict[str, Any]:
        return instance.representation_support(profile_id=profile_id)

    @app.get("/api/v1/representations")
    def api_representations(
        profile_id: str | None = None,
        version_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return instance.representation_read_model(
            profile_id=profile_id,
            version_id=version_id,
            limit=limit,
        )

    @app.get("/api/v1/representations/{representation_id}")
    def api_representation(representation_id: str) -> dict[str, Any]:
        result = instance.get_representation(representation_id)
        if result is None:
            raise HTTPException(status_code=404, detail="representation not found")
        return result

    @app.get("/representations")
    def representations_page(request: Request):
        model = instance.representation_read_model(limit=250)
        return templates.TemplateResponse(
            request=request,
            name="representations.html",
            context=context_factory(request, instance, model=model),
        )
