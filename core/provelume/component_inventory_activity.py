from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request

from .service import ProvelumeInstance


def attach_component_inventory_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    @app.get("/api/v1/components")
    def api_component_inventory() -> dict[str, Any]:
        return instance.component_inventory()

    @app.get("/components")
    def component_inventory_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="components.html",
            context=context_factory(request, instance, inventory=instance.component_inventory()),
        )
