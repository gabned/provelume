from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from .bundle_reader import DocumentBundleReader
from .paths import safe_instance_path
from .service import ProvelumeInstance


def attach_bundle_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    bundles = DocumentBundleReader(instance.store)

    @app.get("/api/v1/bundles")
    def api_bundles(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return bundles.list(limit=limit)

    @app.get("/api/v1/bundles/{version_id}")
    def api_bundle(version_id: str) -> dict[str, Any]:
        record = bundles.get(version_id)
        if record is None:
            raise HTTPException(status_code=404, detail="document bundle not found")
        return record

    @app.get("/api/v1/bundles/{version_id}/markdown")
    def api_bundle_markdown(version_id: str) -> PlainTextResponse:
        markdown = bundles.read_markdown(version_id)
        if markdown is None:
            raise HTTPException(status_code=404, detail="bundle Markdown not found")
        return PlainTextResponse(markdown, media_type="text/markdown")

    @app.get("/api/v1/bundles/{version_id}/page-map")
    def api_bundle_page_map(version_id: str) -> dict[str, Any]:
        page_map = bundles.read_page_map(version_id)
        if page_map is None:
            raise HTTPException(status_code=404, detail="bundle page map not found")
        return page_map

    @app.get("/api/v1/bundles/{version_id}/assets/{asset_id}")
    def api_bundle_asset(version_id: str, asset_id: str) -> FileResponse:
        record = bundles.get(version_id)
        if record is None:
            raise HTTPException(status_code=404, detail="document bundle not found")
        asset = next(
            (
                item
                for item in record["manifest"].get("assets", [])
                if item.get("id") == asset_id
            ),
            None,
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="bundle asset not found")
        try:
            path = safe_instance_path(instance.root, asset["storage_ref"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="bundle asset not found") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="bundle asset not found")
        return FileResponse(
            path,
            media_type=asset.get("media_type") or "application/octet-stream",
            filename=asset.get("filename") or asset_id,
        )

    @app.get("/api/v1/documents/{document_id}/bundle")
    def api_document_bundle(document_id: str) -> dict[str, Any]:
        if instance.get_document(document_id) is None:
            raise HTTPException(status_code=404, detail="document not found")
        record = bundles.for_document(document_id)
        if record is None:
            raise HTTPException(status_code=404, detail="document bundle not found")
        return record

    @app.get("/bundles")
    def bundles_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="bundles.html",
            context=context_factory(
                request,
                instance,
                bundles=bundles.list(limit=250),
            ),
        )

    @app.get("/bundles/{version_id}")
    def bundle_page(request: Request, version_id: str):
        record = bundles.get(version_id)
        markdown = bundles.read_markdown(version_id)
        page_map = bundles.read_page_map(version_id)
        if record is None or markdown is None or page_map is None:
            raise HTTPException(status_code=404, detail="document bundle not found")
        document = instance.get_document(record["manifest"]["document_id"])
        return templates.TemplateResponse(
            request=request,
            name="bundle.html",
            context=context_factory(
                request,
                instance,
                bundle=record,
                document=document,
                markdown=markdown,
                page_map=page_map,
            ),
        )
