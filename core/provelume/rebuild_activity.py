from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

from .rebuild import DerivedRebuildManager
from .service import ProvelumeInstance


def attach_rebuild_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    manager = DerivedRebuildManager(instance.store)

    @app.get("/api/v1/rebuild")
    def api_rebuild_summary() -> dict[str, Any]:
        return manager.summary()

    @app.get("/api/v1/rebuild/lock")
    def api_rebuild_lock() -> dict[str, Any]:
        return manager.lock_status()

    @app.get("/api/v1/rebuild/reports")
    def api_rebuild_reports(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return manager.list_reports(limit=limit)

    @app.get("/api/v1/rebuild/reports/{report_id}")
    def api_rebuild_report(report_id: str) -> dict[str, Any]:
        report = manager.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="rebuild report not found")
        return report

    @app.get("/rebuild")
    def rebuild_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="rebuild.html",
            context=context_factory(
                request,
                instance,
                summary=manager.summary(),
                reports=manager.list_reports(limit=100),
            ),
        )

    @app.get("/rebuild/{report_id}")
    def rebuild_report_page(request: Request, report_id: str):
        report = manager.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="rebuild report not found")
        return templates.TemplateResponse(
            request=request,
            name="rebuild_report.html",
            context=context_factory(request, instance, report=report),
        )
