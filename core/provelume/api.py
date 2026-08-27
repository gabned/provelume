from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse

from . import __version__
from .about import current_about
from .build_info import current_build_info
from .paths import safe_instance_path
from .service import ProvelumeInstance

CLIENT_INSTALLATION_EVIDENCE_PARAMETERS = frozenset(
    {"release_bundle", "expected_manifest_sha256"}
)


def _not_found(kind: str, object_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} not found: {object_id}")


def reject_client_installation_evidence(request: Request) -> None:
    if CLIENT_INSTALLATION_EVIDENCE_PARAMETERS.intersection(request.query_params):
        raise HTTPException(
            status_code=400,
            detail=(
                "Release evidence is configured only by the local operator when the "
                "server starts. HTTP clients cannot supply server-local paths or hashes."
            ),
        )


def build_api(instance: ProvelumeInstance) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/build-info")
    def get_build_info() -> dict[str, Any]:
        return current_build_info()

    @router.get("/about")
    def get_about() -> dict[str, Any]:
        return current_about()

    @router.get("/instance")
    def get_instance() -> dict[str, Any]:
        return instance.instance_summary()

    @router.get("/sources")
    def get_sources() -> list[dict[str, Any]]:
        return instance.list_sources()

    @router.get("/sources/{source_id}")
    def get_source(source_id: str) -> dict[str, Any]:
        source = instance.get_source(source_id)
        if source is None:
            raise _not_found("source", source_id)
        return source

    @router.get("/documents")
    def get_documents(
        source_id: str | None = None,
        media_type: str | None = None,
        area: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        return instance.list_documents(
            source_id=source_id,
            media_type=media_type,
            area=area,
            date_from=date_from,
            date_to=date_to,
        )

    @router.get("/documents/{document_id}")
    def get_document(document_id: str) -> dict[str, Any]:
        document = instance.get_document(document_id)
        if document is None:
            raise _not_found("document", document_id)
        return document

    @router.get("/documents/{document_id}/versions")
    def get_versions(document_id: str) -> list[dict[str, Any]]:
        if instance.get_document(document_id) is None:
            raise _not_found("document", document_id)
        return instance.versions(document_id)

    @router.get("/documents/{document_id}/provenance")
    def get_provenance(document_id: str) -> dict[str, Any]:
        result = instance.provenance(document_id)
        if result is None:
            raise _not_found("document", document_id)
        return result

    @router.get("/documents/{document_id}/original")
    def get_original(document_id: str) -> FileResponse:
        document = instance.get_document(document_id)
        if document is None:
            raise _not_found("document", document_id)
        version = instance.current_version(document_id)
        if version is None:
            raise _not_found("version", document["current_version_id"])
        original = instance.store.read_canonical("originals", version["original_id"])
        if original is None:
            raise _not_found("original", version["original_id"])
        path = safe_instance_path(instance.root, original["storage_ref"])
        return FileResponse(path, media_type=document["media_type"], filename=document["title"])

    @router.get("/search")
    def search(
        q: str = Query(min_length=1, max_length=500),
        source_id: str | None = None,
        media_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {
            "query": q,
            "results": instance.search(
                q,
                source_id=source_id,
                media_type=media_type,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            ),
        }

    @router.get("/knowledge-health")
    def get_knowledge_health() -> dict[str, Any]:
        return instance.knowledge_health()

    @router.get("/security/network")
    def get_network_status() -> dict[str, Any]:
        return instance.network_status()

    return router


def attach_api(
    app: FastAPI,
    instance: ProvelumeInstance,
    *,
    installation_verification: dict[str, Any],
) -> None:
    @app.get("/health")
    def health() -> dict[str, Any]:
        summary = instance.instance_summary()
        build = current_build_info()
        return {
            "ok": True,
            "version": __version__,
            "build_identity_status": build["identity_status"],
            "official_build_metadata": build["official"],
            "instance_id": summary["id"],
            "index_status": summary["index_status"],
        }

    app.include_router(build_api(instance))

    @app.get("/api/v1/security/installation")
    def get_installation_verification(request: Request) -> dict[str, Any]:
        reject_client_installation_evidence(request)
        return installation_verification
