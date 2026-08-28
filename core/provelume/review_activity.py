from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

from .assurance import OriginalAssuranceManager
from .duplicates import DuplicateCaseManager
from .service import ProvelumeInstance


def attach_review_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    duplicates = DuplicateCaseManager(instance.store)
    assurance = OriginalAssuranceManager(instance.store)

    @app.get("/api/v1/duplicates")
    def api_duplicates(
        kind: str | None = Query(default=None, pattern="^(exact|probable)$"),
        current: bool | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return duplicates.list_cases(kind=kind, current=current, limit=limit)

    @app.get("/api/v1/duplicates/{case_id}")
    def api_duplicate(case_id: str) -> dict[str, Any]:
        record = duplicates.get_case(case_id)
        if record is None:
            raise HTTPException(status_code=404, detail="duplicate case not found")
        return record

    @app.get("/api/v1/assurance")
    def api_assurance() -> dict[str, Any]:
        latest = assurance.latest()
        return {
            "schema_version": 1,
            "status": latest["status"] if latest else "not_run",
            "latest": latest,
        }

    @app.get("/api/v1/assurance/reports")
    def api_assurance_reports(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return assurance.list_reports(limit=limit)

    @app.get("/api/v1/assurance/reports/{report_id}")
    def api_assurance_report(report_id: str) -> dict[str, Any]:
        record = assurance.get_report(report_id)
        if record is None:
            raise HTTPException(status_code=404, detail="assurance report not found")
        return record

    @app.get("/duplicates")
    def duplicates_page(
        request: Request,
        kind: str | None = None,
        current: str | None = "true",
    ):
        current_filter: bool | None
        if current == "true":
            current_filter = True
        elif current == "false":
            current_filter = False
        else:
            current_filter = None
        if kind not in {None, "", "exact", "probable"}:
            kind = None
        return templates.TemplateResponse(
            request=request,
            name="duplicates.html",
            context=context_factory(
                request,
                instance,
                cases=duplicates.list_cases(
                    kind=kind or None,
                    current=current_filter,
                    limit=250,
                ),
                selected_kind=kind or "",
                selected_current=current or "",
            ),
        )

    @app.get("/duplicates/{case_id}")
    def duplicate_page(request: Request, case_id: str):
        record = duplicates.get_case(case_id)
        if record is None:
            raise HTTPException(status_code=404, detail="duplicate case not found")
        return templates.TemplateResponse(
            request=request,
            name="duplicate.html",
            context=context_factory(request, instance, duplicate=record),
        )

    @app.get("/assurance")
    def assurance_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="assurance.html",
            context=context_factory(
                request,
                instance,
                latest=assurance.latest(),
                reports=assurance.list_reports(limit=100),
            ),
        )

    @app.get("/assurance/{report_id}")
    def assurance_report_page(request: Request, report_id: str):
        record = assurance.get_report(report_id)
        if record is None:
            raise HTTPException(status_code=404, detail="assurance report not found")
        return templates.TemplateResponse(
            request=request,
            name="assurance_report.html",
            context=context_factory(request, instance, report=record),
        )
