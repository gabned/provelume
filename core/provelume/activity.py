from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

from .bundle_activity import attach_bundle_routes
from .component_inventory_activity import attach_component_inventory_routes
from .configured_inbox import InboxManager
from .connector_activity import attach_connector_routes
from .folder_settings_activity import attach_folder_settings_routes
from .operations import OperationLedger
from .rebuild_activity import attach_rebuild_routes
from .representation_activity import attach_representation_routes
from .review_activity import attach_review_routes
from .service import ProvelumeInstance


def attach_activity_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    operations = OperationLedger(instance.store)
    inbox = InboxManager(instance.store)

    @app.get("/api/v1/operations")
    def api_operations(
        kind: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return operations.list(kind=kind, status=status, limit=limit)

    @app.get("/api/v1/operations/{operation_id}")
    def api_operation(operation_id: str) -> dict[str, Any]:
        record = operations.get(operation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return record

    @app.get("/api/v1/inbox")
    def api_inbox() -> dict[str, Any]:
        return inbox.summary()

    @app.get("/api/v1/inbox/submissions")
    def api_inbox_submissions(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return inbox.list_submissions(limit=limit)

    @app.get("/api/v1/inbox/submissions/{submission_id}")
    def api_inbox_submission(submission_id: str) -> dict[str, Any]:
        record = inbox.get_submission(submission_id)
        if record is None:
            raise HTTPException(status_code=404, detail="inbox submission not found")
        return record

    @app.get("/operations")
    def operations_page(
        request: Request,
        kind: str | None = None,
        status: str | None = None,
    ):
        return templates.TemplateResponse(
            request=request,
            name="operations.html",
            context=context_factory(
                request,
                instance,
                operations=operations.list(kind=kind, status=status, limit=250),
                kinds=operations.kinds(),
                selected_kind=kind,
                selected_status=status,
            ),
        )

    @app.get("/operations/{operation_id}")
    def operation_page(request: Request, operation_id: str):
        record = operations.get(operation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return templates.TemplateResponse(
            request=request,
            name="operation.html",
            context=context_factory(request, instance, operation=record),
        )

    @app.get("/inbox")
    def inbox_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="inbox.html",
            context=context_factory(
                request,
                instance,
                inbox=inbox.summary(),
                submissions=inbox.list_submissions(limit=100),
            ),
        )

    attach_folder_settings_routes(app, instance, templates, context_factory)
    attach_connector_routes(app, instance, templates, context_factory)
    attach_bundle_routes(app, instance, templates, context_factory)
    attach_representation_routes(app, instance, templates, context_factory)
    attach_component_inventory_routes(app, instance, templates, context_factory)
    attach_review_routes(app, instance, templates, context_factory)
    attach_rebuild_routes(app, instance, templates, context_factory)
