from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .about import current_about
from .activity import attach_activity_routes
from .api import attach_api, reject_client_installation_evidence
from .build_info import current_build_info
from .i18n import SUPPORTED_LANGUAGES, translator
from .installation import verify_current_installation
from .installation_i18n import installation_translator
from .markdown_viewer import DocumentContentError, safe_markdown_html
from .retention_model import DISPOSITION_FILTERS
from .scheduler_model import SchedulerBusyError, SchedulerError
from .service import ProvelumeInstance
from .web_security import LocalWebSecurityMiddleware

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
ROOT_AREA_FILTER = "__root__"


def _language(request: Request, instance: ProvelumeInstance) -> str:
    requested = request.query_params.get("lang")
    if requested in SUPPORTED_LANGUAGES:
        return requested
    configured = instance.store.read_config().get("ui", {}).get("language", "en")
    return configured if configured in SUPPORTED_LANGUAGES else "en"


def _language_url(request: Request, language: str) -> str:
    query = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != "lang"
    ]
    query.append(("lang", language))
    return f"{request.url.path}?{urlencode(query, doseq=True)}"


def _navigation(
    language: str,
    current_path: str,
    t: Callable[[str], str],
    security_t: Callable[[str], str],
) -> list[dict[str, Any]]:
    return [
        {
            "href": f"/?lang={language}",
            "label": t("nav.home"),
            "current": current_path == "/",
        },
        {
            "href": f"/browse?lang={language}",
            "label": t("nav.browse"),
            "current": (
                current_path == "/browse" or current_path.startswith("/documents/")
            ),
        },
        {
            "href": f"/search?lang={language}",
            "label": t("nav.search"),
            "current": current_path == "/search",
        },
        {
            "href": f"/inbox?lang={language}",
            "label": t("nav.inbox"),
            "current": current_path.startswith("/inbox"),
        },
        {
            "href": f"/connectors?lang={language}",
            "label": t("nav.connectors"),
            "current": current_path.startswith("/connectors"),
        },
        {
            "href": f"/bundles?lang={language}",
            "label": t("nav.bundles"),
            "current": current_path.startswith("/bundles"),
        },
        {
            "href": f"/duplicates?lang={language}",
            "label": t("nav.duplicates"),
            "current": current_path.startswith("/duplicates"),
        },
        {
            "href": f"/assurance?lang={language}",
            "label": t("nav.assurance"),
            "current": current_path.startswith("/assurance"),
        },
        {
            "href": f"/rebuild?lang={language}",
            "label": t("nav.rebuild"),
            "current": current_path.startswith("/rebuild"),
        },
        {
            "href": f"/operations?lang={language}",
            "label": t("nav.operations"),
            "current": current_path.startswith("/operations"),
        },
        {
            "href": f"/scheduler?lang={language}",
            "label": t("nav.scheduler"),
            "current": current_path.startswith("/scheduler"),
        },
        {
            "href": f"/settings?lang={language}",
            "label": t("nav.settings"),
            "current": current_path.startswith("/settings"),
        },
        {
            "href": f"/knowledge-health?lang={language}",
            "label": t("nav.health"),
            "current": current_path == "/knowledge-health",
        },
        {
            "href": f"/security/installation?lang={language}",
            "label": security_t("nav.verify_installation"),
            "current": current_path == "/security/installation",
        },
        {
            "href": f"/security/network?lang={language}",
            "label": t("nav.network"),
            "current": current_path == "/security/network",
        },
        {
            "href": f"/security?lang={language}",
            "label": t("nav.security"),
            "current": current_path == "/security",
        },
        {
            "href": f"/about?lang={language}",
            "label": t("nav.about"),
            "current": current_path == "/about",
        },
    ]


def _base_context(request: Request, language: str) -> dict[str, Any]:
    t = translator(language)
    security_t = installation_translator(language)
    return {
        "request": request,
        "lang": language,
        "t": t,
        "security_t": security_t,
        "navigation": _navigation(language, request.url.path, t, security_t),
        "language_urls": {
            selected: _language_url(request, selected)
            for selected in sorted(SUPPORTED_LANGUAGES)
        },
    }


def _context(request: Request, instance: ProvelumeInstance, **values: Any) -> dict[str, Any]:
    language = _language(request, instance)
    return {
        **_base_context(request, language),
        "instance": instance.instance_summary(),
        **values,
    }


def _installation_context(request: Request, **values: Any) -> dict[str, Any]:
    requested = request.query_params.get("lang")
    language = requested if requested in SUPPORTED_LANGUAGES else "en"
    return {**_base_context(request, language), **values}


def create_app(
    instance_root: Path | str,
    *,
    release_bundle: Path | str | None = None,
    expected_manifest_sha256: str | None = None,
) -> FastAPI:
    if isinstance(release_bundle, str) and not release_bundle.strip():
        release_bundle = None
    if isinstance(expected_manifest_sha256, str):
        expected_manifest_sha256 = expected_manifest_sha256.strip() or None
    release_evidence_configured = (
        release_bundle is not None or expected_manifest_sha256 is not None
    )
    if release_evidence_configured:
        installation_verification = verify_current_installation(
            release_bundle=release_bundle,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    else:
        installation_verification = verify_current_installation()

    instance = ProvelumeInstance(instance_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        app.state.scheduler_runtime_error = None

        async def scheduler_worker() -> None:
            while not stop.is_set():
                try:
                    await asyncio.to_thread(instance.run_scheduler_cycle, max_jobs=1)
                    app.state.scheduler_runtime_error = None
                except SchedulerBusyError:
                    app.state.scheduler_runtime_error = "scheduler_busy"
                except SchedulerError:
                    app.state.scheduler_runtime_error = "scheduler_state_invalid"
                except Exception:
                    app.state.scheduler_runtime_error = "scheduler_cycle_failed"
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except TimeoutError:
                    continue

        worker = asyncio.create_task(scheduler_worker())
        try:
            yield
        finally:
            stop.set()
            with suppress(asyncio.CancelledError):
                await worker

    app = FastAPI(
        title="Provelume Knowledge API",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(LocalWebSecurityMiddleware)
    app.state.provelume = instance
    app.state.scheduler_runtime_error = None
    app.state.installation_verification = installation_verification
    app.state.release_evidence_configured = release_evidence_configured
    app.mount("/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static")
    attach_api(
        app,
        instance,
        installation_verification=installation_verification,
    )
    attach_activity_routes(app, instance, TEMPLATES, _context)

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
        hierarchy_id: str | None = None,
        disposition: str = "active",
    ):
        if disposition not in DISPOSITION_FILTERS:
            raise HTTPException(status_code=400, detail="unsupported disposition filter")
        selected_hierarchy_node = None
        if hierarchy_id:
            selected_hierarchy_node = instance.get_hierarchy_node(hierarchy_id)
            if selected_hierarchy_node is None:
                raise HTTPException(status_code=404, detail="hierarchy node not found")
        area_filter = "" if area == ROOT_AREA_FILTER else (area or None)
        documents = instance.list_documents(
            source_id=source_id,
            media_type=media_type,
            area=area_filter,
            hierarchy_id=hierarchy_id,
            disposition=disposition,
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
                hierarchy_nodes=instance.list_hierarchy_nodes(),
                media_types=instance.media_types(),
                selected_source=source_id,
                selected_media_type=media_type,
                selected_area=area,
                selected_hierarchy=hierarchy_id,
                selected_hierarchy_node=selected_hierarchy_node,
                selected_disposition=disposition,
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
    def document_page(
        request: Request,
        document_id: str,
        mode: str = "rendered",
    ):
        if mode not in {"rendered", "raw", "original"}:
            raise HTTPException(status_code=400, detail="unsupported Viewer mode")
        document = instance.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        try:
            content = instance.document_content(document_id)
        except DocumentContentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        viewer_text = None
        rendered = None
        if content is not None:
            viewer_text = (
                content["original_text"]
                if mode == "original"
                else content["markdown"]
            )
            if mode == "rendered" and content["markdown"] is not None:
                rendered = safe_markdown_html(content["markdown"])
        return TEMPLATES.TemplateResponse(
            request=request,
            name="document.html",
            context=_context(
                request,
                instance,
                document=document,
                versions=instance.versions(document_id),
                content=content,
                viewer_mode=mode,
                viewer_text=viewer_text,
                rendered=rendered,
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

    @app.get("/scheduler")
    def scheduler_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="scheduler.html",
            context=_context(
                request,
                instance,
                scheduler=instance.scheduler_status(),
                policies=instance.list_schedule_policies(),
                jobs=instance.list_scheduler_jobs(limit=100),
                receipts=instance.list_scheduler_receipts(limit=50),
                recovery=instance.scheduler_recovery,
                runtime_error=request.app.state.scheduler_runtime_error,
            ),
        )

    @app.get("/security")
    def security_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="security.html",
            context=_context(request, instance, build=current_build_info()),
        )

    @app.get("/about")
    def about_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="about.html",
            context=_context(request, instance, about=current_about()),
        )

    @app.get("/security/installation")
    def installation_page(request: Request):
        reject_client_installation_evidence(request)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="installation_verification.html",
            context=_installation_context(
                request,
                verification=installation_verification,
                release_evidence_configured=release_evidence_configured,
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
