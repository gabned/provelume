from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from .service import ProvelumeInstance


def attach_connector_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    @app.get("/connectors")
    def connectors_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="connectors.html",
            context=context_factory(
                request,
                instance,
                connector_inventory=instance.connector_inventory(),
            ),
        )

    @app.get("/connectors/{connector_instance_id}")
    def connector_page(request: Request, connector_instance_id: str):
        connector = instance.get_connector_instance(connector_instance_id)
        if connector is None:
            raise HTTPException(status_code=404, detail="connector instance not found")
        return templates.TemplateResponse(
            request=request,
            name="connector.html",
            context=context_factory(
                request,
                instance,
                connector=connector,
            ),
        )

    @app.get("/connectors/{connector_instance_id}/sources/{source_id}")
    def connector_source_page(
        request: Request,
        connector_instance_id: str,
        source_id: str,
    ):
        connector = instance.get_connector_instance(connector_instance_id)
        source = instance.get_connector_source(connector_instance_id, source_id)
        if connector is None or source is None:
            raise HTTPException(status_code=404, detail="connector Source not found")
        return templates.TemplateResponse(
            request=request,
            name="connector_source.html",
            context=context_factory(
                request,
                instance,
                connector=connector,
                connector_source=source,
                web_acquisitions=instance.list_manual_web_acquisitions(
                    connector_instance_id,
                    source_id,
                    limit=100,
                ),
            ),
        )

    @app.get(
        "/connectors/{connector_instance_id}/sources/{source_id}/acquisitions/"
        "{acquisition_id}"
    )
    def connector_acquisition_page(
        request: Request,
        connector_instance_id: str,
        source_id: str,
        acquisition_id: str,
    ):
        connector = instance.get_connector_instance(connector_instance_id)
        source = instance.get_connector_source(connector_instance_id, source_id)
        acquisition = instance.get_manual_web_acquisition(
            connector_instance_id,
            source_id,
            acquisition_id,
        )
        if connector is None or source is None or acquisition is None:
            raise HTTPException(status_code=404, detail="manual web acquisition not found")
        return templates.TemplateResponse(
            request=request,
            name="connector_acquisition.html",
            context=context_factory(
                request,
                instance,
                connector=connector,
                connector_source=source,
                web_acquisition=acquisition,
            ),
        )
