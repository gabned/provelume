from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api import attach_api
from .build_info import current_build_info
from .i18n import SUPPORTED_LANGUAGES, translator
from .installation import verify_current_installation
from .installation_i18n import installation_translator
from .service import ProvelumeInstance

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
ROOT_AREA_FILTER = "__root__"


def _language(request: Request, instance: ProvelumeInstance) -> str:
    requested = request.query_params.get("lang")
    if requested in SUPPORTED_LANGUAGES:
        return requested
    configured = instance.store.read_config().get("ui", {}).get("language", "en")
    return configured if configured in SUPPORTED_LANGUAGES else "en"


def _context(request: Request, instance: ProvelumeInstance, **values: Any) -> dict[str, Any]:
    language = _language(request, instance)
    return {
        "request": request,
        "instance": instance.instance_summary(),
        "lang": language,
        "t": translator(language),
        "security_t": installation_translator(language),
        **values,
    }


def _installation_context(request: Request, **values: Any) -> dict[str, Any]:
    requested = request.query_params.get("lang")
    language = requested if requested in SUPPORTED_LANGUAGES else "en"
    return {
        "request": request,
        "lang": language,
        "t": translator(language),
        "security_t": installation_translator(language),
        **values,
    }


def create_app(instance_root: Path | str) -> FastAPI:
    instance = ProvelumeInstance(instance_root)
    app = FastAPI(
        title="Provelume Knowledge API",
        version="1.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.provelume = instance
    app.mount("/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static")
    attach_api(app, instance)

    @app.get("/")
    def home(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="home.html",
            context=_context(
                request,
                instance,
                latest=instance.recent_documents(limit=8),
                ingestion_errors=instance.ingestion_errors(limit=8),
                health=instance.knowledge_health(),
            ),
        )

    @app.get("/browse")
    def browse(
        request: Request,
        source_id: str | None = None,
        media_type: str | None = None,
        area: str | None = None,
    ):
        area_filter = "" if area == ROOT_AREA_FILTER else (area or None)
        documents = instance.list_documents(
            source_id=source_id,
            media_type=media_type,
            area=area_filter,
        )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="browse.html",
            context=_context(
                request,
                instance,
                documents=documents,
                sources=instance.list_sources(),
                areas=instance.areas(),
                media_types=instance.media_types(),
                selected_source=source_id,
                selected_media_type=media_type,
                selected_area=area,
                root_area_filter=ROOT_AREA_FILTER,
            ),
        )

    @app.get("/search")
    def search_page(
        request: Request,
        q: str = "",
        source_id: str | None = None,
        media_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ):
        results = []
        if q.strip():
            results = instance.search(
                q.strip(),
                source_id=source_id,
                media_type=media_type,
                date_from=date_from,
                date_to=date_to,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="search.html",
            context=_context(
                request,
                instance,
                q=q,
                results=results,
                sources=instance.list_sources(),
                media_types=instance.media_types(),
                selected_source=source_id,
                selected_media_type=media_type,
                date_from=date_from,
                date_to=date_to,
            ),
        )

    @app.get("/documents/{document_id}")
    def document_page(request: Request, document_id: str):
        document = instance.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="document.html",
            context=_context(
                request,
                instance,
                document=document,
                versions=instance.versions(document_id),
                preview=instance.extracted_text(document_id),
            ),
        )

    @app.get("/documents/{document_id}/provenance")
    def provenance_page(request: Request, document_id: str):
        provenance = instance.provenance(document_id)
        if provenance is None:
            raise HTTPException(status_code=404, detail="document not found")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="provenance.html",
            context=_context(request, instance, provenance=provenance),
        )

    @app.get("/knowledge-health")
    def health_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="knowledge_health.html",
            context=_context(request, instance, health=instance.knowledge_health()),
        )

    @app.get("/security")
    def security_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="security.html",
            context=_context(request, instance, build=current_build_info()),
        )

    @app.get("/security/installation")
    def installation_page(
        request: Request,
        release_bundle: str | None = Query(default=None, max_length=4096),
        expected_manifest_sha256: str | None = Query(default=None, max_length=128),
    ):
        if not release_bundle and not expected_manifest_sha256:
            verification = verify_current_installation()
        else:
            verification = verify_current_installation(
                release_bundle=release_bundle or None,
                expected_manifest_sha256=expected_manifest_sha256 or None,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="installation_verification.html",
            context=_installation_context(
                request,
                verification=verification,
                release_bundle_input=release_bundle or "",
                expected_manifest_sha256_input=expected_manifest_sha256 or "",
            ),
        )

    @app.get("/security/network")
    def network_status_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="network_status.html",
            context=_context(
                request,
                instance,
                network=instance.network_status(),
            ),
        )

    return app
