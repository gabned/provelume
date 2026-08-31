from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from . import __version__
from .about import current_about
from .build_info import current_build_info
from .maintenance_model import MaintenanceError, MaintenanceNotFoundError
from .markdown_viewer import DocumentContentError
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

    @router.get("/connectors")
    def get_connectors() -> dict[str, Any]:
        return instance.connector_inventory()

    @router.get("/connectors/definitions/{definition_id}")
    def get_connector_definition(definition_id: str) -> dict[str, Any]:
        result = instance.get_connector_definition(definition_id)
        if result is None:
            raise _not_found("connector definition", definition_id)
        return result

    @router.get("/connectors/{connector_instance_id}")
    def get_connector_instance(connector_instance_id: str) -> dict[str, Any]:
        result = instance.get_connector_instance(connector_instance_id)
        if result is None:
            raise _not_found("connector instance", connector_instance_id)
        return result

    @router.get("/connectors/{connector_instance_id}/sources/{source_id}")
    def get_connector_source(
        connector_instance_id: str,
        source_id: str,
    ) -> dict[str, Any]:
        result = instance.get_connector_source(connector_instance_id, source_id)
        if result is None:
            raise _not_found("connector Source", source_id)
        return result

    @router.get(
        "/connectors/{connector_instance_id}/sources/{source_id}/acquisitions"
    )
    def get_manual_web_acquisitions(
        connector_instance_id: str,
        source_id: str,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        if instance.get_connector_source(connector_instance_id, source_id) is None:
            raise _not_found("connector Source", source_id)
        return instance.list_manual_web_acquisitions(
            connector_instance_id,
            source_id,
            limit=limit,
        )

    @router.get(
        "/connectors/{connector_instance_id}/sources/{source_id}/acquisitions/"
        "{acquisition_id}"
    )
    def get_manual_web_acquisition(
        connector_instance_id: str,
        source_id: str,
        acquisition_id: str,
    ) -> dict[str, Any]:
        result = instance.get_manual_web_acquisition(
            connector_instance_id,
            source_id,
            acquisition_id,
        )
        if result is None:
            raise _not_found("manual web acquisition", acquisition_id)
        return result

    @router.get("/sources")
    def get_sources() -> list[dict[str, Any]]:
        return instance.list_sources()

    @router.get("/sources/{source_id}")
    def get_source(source_id: str) -> dict[str, Any]:
        source = instance.get_source(source_id)
        if source is None:
            raise _not_found("source", source_id)
        return source

    @router.get("/ingestion/runs")
    def get_ingestion_runs(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return instance.list_ingestion_runs(limit=limit)

    @router.get("/ingestion/runs/{run_id}")
    def get_ingestion_run(run_id: str) -> dict[str, Any]:
        result = instance.get_ingestion_run(run_id)
        if result is None:
            raise _not_found("ingestion run", run_id)
        return result

    @router.get("/scheduler")
    def get_scheduler_status() -> dict[str, Any]:
        return instance.scheduler_status()

    @router.get("/scheduler/policies")
    def get_scheduler_policies() -> list[dict[str, Any]]:
        return instance.list_schedule_policies()

    @router.get("/scheduler/policies/{policy_id}")
    def get_scheduler_policy(policy_id: str) -> dict[str, Any]:
        result = instance.get_schedule_policy(policy_id)
        if result is None:
            raise _not_found("scheduler policy", policy_id)
        return result

    @router.get("/scheduler/jobs")
    def get_scheduler_jobs(
        status: str | None = Query(
            default=None,
            pattern="^(queued|running|retry_wait|succeeded|failed|manual_intervention|cancelled)$",
        ),
        policy_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_scheduler_jobs(
            status=status,
            policy_id=policy_id,
            limit=limit,
        )

    @router.get("/scheduler/jobs/{job_id}")
    def get_scheduler_job(job_id: str) -> dict[str, Any]:
        result = instance.get_scheduler_job(job_id)
        if result is None:
            raise _not_found("scheduler job", job_id)
        return result

    @router.get("/scheduler/receipts")
    def get_scheduler_receipts(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_scheduler_receipts(limit=limit)

    @router.get("/ocr/capability")
    def get_ocr_capability() -> dict[str, Any]:
        return instance.ocr_capability()

    @router.get("/ocr/jobs")
    def get_ocr_jobs(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_ocr_jobs(limit=limit)

    @router.get("/ocr/jobs/{job_id}")
    def get_ocr_job(job_id: str) -> dict[str, Any]:
        result = instance.get_ocr_job(job_id)
        if result is None:
            raise _not_found("OCR job", job_id)
        return result

    @router.get("/ocr/bundles")
    def get_ocr_bundles(version_id: str | None = None) -> list[dict[str, Any]]:
        return instance.list_ocr_bundles(version_id)

    @router.get("/email/capability")
    def get_email_capability(source_id: str | None = None) -> dict[str, Any]:
        return instance.email_capability(source_id, local=False)

    @router.get("/email/sources")
    def get_email_sources(
        include_removed: bool = True,
    ) -> list[dict[str, Any]]:
        return instance.list_email_sources(
            local=False,
            include_removed=include_removed,
        )

    @router.get("/email/sources/{source_id}")
    def get_email_source(source_id: str) -> dict[str, Any]:
        result = instance.get_email_source(source_id, local=False)
        if result is None:
            raise _not_found("email Source", source_id)
        return result

    @router.get("/email/jobs")
    def get_email_jobs(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_email_jobs(limit=limit)

    @router.get("/email/jobs/{job_id}")
    def get_email_job(job_id: str) -> dict[str, Any]:
        result = instance.get_email_job(job_id)
        if result is None:
            raise _not_found("email job", job_id)
        return result

    @router.get("/email/messages")
    def get_email_messages(
        source_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_email_messages(source_id=source_id, limit=limit)

    @router.get("/email/messages/{message_id}")
    def get_email_message(message_id: str) -> dict[str, Any]:
        result = instance.get_email_message(message_id)
        if result is None:
            raise _not_found("email message", message_id)
        return result

    @router.get("/email/threads")
    def get_email_threads(
        source_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_email_threads(source_id=source_id, limit=limit)

    @router.get("/email/threads/{thread_id}")
    def get_email_thread(thread_id: str) -> dict[str, Any]:
        result = instance.get_email_thread(thread_id)
        if result is None:
            raise _not_found("observed email thread", thread_id)
        return result

    @router.get("/email/attachments")
    def get_email_attachments(
        message_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_email_attachments(message_id=message_id, limit=limit)

    @router.get("/email/attachments/{attachment_id}")
    def get_email_attachment(attachment_id: str) -> dict[str, Any]:
        result = instance.get_email_attachment(attachment_id)
        if result is None:
            raise _not_found("email attachment", attachment_id)
        return result

    @router.get("/maintenance")
    def get_maintenance_catalog() -> list[dict[str, Any]]:
        return instance.maintenance_catalog()

    @router.get("/maintenance/actions/{action_id}")
    def get_maintenance_action(action_id: str) -> dict[str, Any]:
        try:
            return instance.get_maintenance_action(action_id)
        except MaintenanceNotFoundError as exc:
            raise _not_found("maintenance action", action_id) from exc

    @router.get("/maintenance/plans/{action_id}")
    def get_maintenance_plan(action_id: str) -> dict[str, Any]:
        try:
            return instance.plan_maintenance_action(action_id)
        except MaintenanceNotFoundError as exc:
            raise _not_found("maintenance action", action_id) from exc
        except MaintenanceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/maintenance/runs")
    def get_maintenance_runs(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_maintenance_runs(limit=limit)

    @router.get("/maintenance/runs/{run_id}")
    def get_maintenance_run(run_id: str) -> dict[str, Any]:
        result = instance.get_maintenance_run(run_id)
        if result is None:
            raise _not_found("maintenance reindex run", run_id)
        return result

    @router.get("/maintenance/source-cursors")
    def get_source_reconciliation_cursors() -> list[dict[str, Any]]:
        return instance.list_source_reconciliation_cursors()

    @router.get("/maintenance/source-cursors/{source_id}")
    def get_source_reconciliation_cursor(source_id: str) -> dict[str, Any]:
        if not instance.folder_sources.is_managed(source_id):
            raise _not_found("Source reconciliation cursor", source_id)
        return instance.get_source_reconciliation_cursor(source_id)

    @router.get("/maintenance/source-runs")
    def get_source_reconciliation_runs(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_source_reconciliation_runs(limit=limit)

    @router.get("/maintenance/source-runs/{run_id}")
    def get_source_reconciliation_run(run_id: str) -> dict[str, Any]:
        result = instance.get_source_reconciliation_run(run_id)
        if result is None:
            raise _not_found("Source reconciliation run", run_id)
        return result

    @router.get("/maintenance/resource-statistics")
    def get_resource_statistics(
        history_limit: int = Query(default=30, ge=1, le=500),
    ) -> dict[str, Any]:
        return instance.resource_statistics_status(history_limit=history_limit)

    @router.get("/maintenance/resource-statistics/snapshots")
    def get_resource_snapshots(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return instance.list_resource_snapshots(limit=limit)

    @router.get("/maintenance/resource-statistics/snapshots/{snapshot_id}")
    def get_resource_snapshot(snapshot_id: str) -> dict[str, Any]:
        result = instance.get_resource_snapshot(snapshot_id)
        if result is None:
            raise _not_found("resource snapshot", snapshot_id)
        return result

    @router.get("/hierarchy")
    def get_hierarchy() -> dict[str, Any]:
        return instance.hierarchy_tree()

    @router.get("/hierarchy/{node_id}")
    def get_hierarchy_node(node_id: str) -> dict[str, Any]:
        node = instance.get_hierarchy_node(node_id)
        if node is None:
            raise _not_found("hierarchy node", node_id)
        return node

    @router.get("/library")
    def get_library_status() -> dict[str, Any]:
        return instance.library_status()

    @router.get("/documents")
    def get_documents(
        source_id: str | None = None,
        media_type: str | None = None,
        area: str | None = None,
        hierarchy_id: str | None = None,
        include_descendants: bool = True,
        date_from: str | None = None,
        date_to: str | None = None,
        disposition: str = Query(
            default="active",
            pattern="^(active|archived|trashed|all)$",
        ),
    ) -> list[dict[str, Any]]:
        if hierarchy_id and instance.get_hierarchy_node(hierarchy_id) is None:
            raise _not_found("hierarchy node", hierarchy_id)
        return instance.list_documents(
            source_id=source_id,
            media_type=media_type,
            area=area,
            hierarchy_id=hierarchy_id,
            include_descendants=include_descendants,
            date_from=date_from,
            date_to=date_to,
            disposition=disposition,
        )

    @router.get("/documents/{document_id}")
    def get_document(document_id: str) -> dict[str, Any]:
        document = instance.get_document(document_id)
        if document is None:
            raise _not_found("document", document_id)
        return document

    @router.get("/documents/{document_id}/classification")
    def get_document_classification(document_id: str) -> dict[str, Any]:
        if instance.get_document(document_id) is None:
            raise _not_found("document", document_id)
        return {
            "document_id": document_id,
            "classification": instance.document_classification(document_id),
        }

    @router.get("/documents/{document_id}/disposition")
    def get_document_disposition(document_id: str) -> dict[str, Any]:
        disposition = instance.document_disposition(document_id)
        if disposition is None:
            raise _not_found("document", document_id)
        return disposition

    @router.get("/documents/{document_id}/content")
    def get_document_content(
        document_id: str,
        mode: str = Query(default="raw", pattern="^(raw|original)$"),
    ) -> PlainTextResponse:
        try:
            content = instance.document_content(document_id)
        except DocumentContentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if content is None:
            raise _not_found("document", document_id)
        value = content["markdown"] if mode == "raw" else content["original_text"]
        if value is None:
            raise HTTPException(
                status_code=415,
                detail=f"{mode} text representation is unavailable",
            )
        return PlainTextResponse(
            value,
            headers={
                "Content-Disposition": "inline",
                "X-Provelume-Content-Source": str(content["source"]),
            },
        )

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
    def get_original(document_id: str) -> Response:
        try:
            verified = instance.document_original(document_id)
        except DocumentContentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if verified is None:
            raise _not_found("document", document_id)
        document = verified["document"]
        version = verified["version"]
        original = verified["original"]
        filename = quote(str(document["title"]), safe="") or "original"
        return Response(
            content=verified["data"],
            media_type=str(version["media_type"]),
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "X-Provelume-Original-SHA256": str(original["sha256"]),
            },
        )

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
