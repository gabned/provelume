from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .hierarchy import HierarchyManager
from .index import (
    index_status,
    rebuild_search_index,
    search_index,
)
from .ingest import (
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    IngestionLimitError,
    retry_ingestion_run,
    run_ingestion_filesystem,
)
from .ingestion_runs import IngestionLedger
from .instance_lifecycle import InstanceLifecycleManager
from .library_projection import (
    DEFAULT_MAX_LIBRARY_DOCUMENTS,
    LibraryProjectionManager,
)
from .markdown_viewer import MAX_VIEWER_MARKDOWN_CHARS, DocumentContentReader
from .network_status import declared_network_status
from .paths import UnsafePathError
from .portable_transfer import PortableInstanceTransfer
from .retention import DocumentRetentionManager
from .retention_model import DISPOSITION_FILTERS, effective_dispositions
from .storage import InstanceStore


class ProvelumeInstance:
    def __init__(self, root: Path | str):
        self.store = InstanceStore.open(root)
        self.retention = DocumentRetentionManager(self.store)
        preparation = self.store._open_preparation or {}
        self.retention_recovery = preparation.get("retention_recovery")
        self.hierarchy = HierarchyManager(self.store)
        self.library = LibraryProjectionManager(self.store)
        self.content = DocumentContentReader(self.store)

    @classmethod
    def initialise(
        cls,
        root: Path | str,
        *,
        name: str = "Provelume Instance",
    ) -> ProvelumeInstance:
        InstanceStore.initialise(root, name=name)
        return cls(root)

    @property
    def root(self) -> Path:
        return self.store.paths.root

    def ingest(
        self,
        source_path: Path | str,
        *,
        source_name: str | None = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> list[dict[str, Any]]:
        result = self.ingest_run(
            source_path,
            source_name=source_name,
            max_file_bytes=max_file_bytes,
            max_files=max_files,
        )
        run = result["run"]
        if run["status"] == "failed" and not result["items"]:
            error = str(run.get("error") or "filesystem Source ingestion failed")
            if run.get("error_code") == "unsafe_path":
                raise UnsafePathError(error)
            if run.get("error_code") == "ingestion_limit":
                raise IngestionLimitError(error)
        return list(result["acquisitions"])

    def ingest_run(
        self,
        source_path: Path | str,
        *,
        source_name: str | None = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> dict[str, Any]:
        result = run_ingestion_filesystem(
            self.store,
            source_path,
            source_name=source_name,
            max_file_bytes=max_file_bytes,
            max_files=max_files,
        )
        return result.as_dict()

    def retry_ingestion(self, run_id: str) -> dict[str, Any]:
        result = retry_ingestion_run(self.store, run_id)
        return result.as_dict()

    def list_ingestion_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return IngestionLedger(self.store).list_runs(limit=limit)

    def get_ingestion_run(self, run_id: str) -> dict[str, Any] | None:
        return IngestionLedger(self.store).run_detail(run_id)

    def rebuild_index(self) -> int:
        return rebuild_search_index(self.store)

    def validate_instance(self, *, deep: bool = True) -> dict[str, Any]:
        return InstanceLifecycleManager(self.store).validate(deep=deep)

    def backup(
        self,
        *,
        destination: Path | str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]:
        return InstanceLifecycleManager(self.store).backup(
            destination=destination,
            reason=reason,
        )

    def restore(self, archive: Path | str) -> dict[str, Any]:
        return InstanceLifecycleManager(self.store).restore(archive)

    def export_portable(
        self,
        destination: Path | str,
        *,
        derived_state: str = "rebuild",
    ) -> dict[str, Any]:
        return PortableInstanceTransfer(self.store).export(
            destination,
            derived_state=derived_state,
        )

    def import_portable(self, archive: Path | str) -> dict[str, Any]:
        return PortableInstanceTransfer(self.store).import_bundle(archive)

    def rebuild_library(
        self,
        *,
        max_documents: int = DEFAULT_MAX_LIBRARY_DOCUMENTS,
    ) -> dict[str, Any]:
        return self.library.rebuild(max_documents=max_documents)

    def library_status(self) -> dict[str, Any]:
        return self.library.status()

    @staticmethod
    def _date_floor(value: str | None) -> str | None:
        if value and len(value) == 10:
            return f"{value}T00:00:00+00:00"
        return value

    @staticmethod
    def _date_ceiling(value: str | None) -> str | None:
        if value and len(value) == 10:
            return f"{value}T23:59:59.999999+00:00"
        return value

    def search(self, query: str, **filters: Any) -> list[dict[str, Any]]:
        filters["date_from"] = self._date_floor(filters.get("date_from"))
        filters["date_to"] = self._date_ceiling(filters.get("date_to"))
        return search_index(self.store, query, **filters)

    def list_sources(self) -> list[dict[str, Any]]:
        documents = self.store.list_canonical("documents")
        result = []
        for source in self.store.list_canonical("sources"):
            source_path = self.store.source_path(source["id"])
            result.append(
                {
                    **source,
                    "document_count": sum(
                        1 for document in documents if document["source_id"] == source["id"]
                    ),
                    "available": bool(source_path and source_path.exists()),
                }
            )
        return sorted(result, key=lambda item: item["name"].casefold())

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        source = self.store.read_canonical("sources", source_id)
        if source is None:
            return None
        source_path = self.store.source_path(source_id)
        return {
            **source,
            "available": bool(source_path and source_path.exists()),
            "document_count": sum(
                1
                for document in self.store.list_canonical("documents")
                if document["source_id"] == source_id
            ),
        }

    @staticmethod
    def _area(locator: str) -> str:
        parts = PurePosixPath(locator).parts
        return parts[0] if len(parts) > 1 else ""

    def _document_view(
        self,
        document: dict[str, Any],
        *,
        classification: dict[str, Any] | None = None,
        disposition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        version = self.store.read_canonical("versions", document["current_version_id"])
        source = self.store.read_canonical("sources", document["source_id"])
        return {
            **document,
            "area": self._area(document["locator"]),
            "source_name": source["name"] if source else document["source_id"],
            "current_version": version,
            "classification": classification,
            "disposition": disposition or self.retention.get(str(document["id"])),
        }

    def list_documents(
        self,
        *,
        source_id: str | None = None,
        media_type: str | None = None,
        area: str | None = None,
        hierarchy_id: str | None = None,
        include_descendants: bool = True,
        date_from: str | None = None,
        date_to: str | None = None,
        disposition: str = "active",
    ) -> list[dict[str, Any]]:
        if disposition not in DISPOSITION_FILTERS:
            raise ValueError("unsupported disposition filter")
        date_from = self._date_floor(date_from)
        date_to = self._date_ceiling(date_to)
        classified_document_ids = (
            self.hierarchy.document_ids_for_node(
                hierarchy_id,
                include_descendants=include_descendants,
            )
            if hierarchy_id
            else None
        )
        classification_views = self.hierarchy.classification_views()
        dispositions = effective_dispositions(self.store)
        result = []
        for document in self.store.list_canonical("documents"):
            selected_disposition = dispositions.get(str(document["id"]))
            if selected_disposition is None:
                continue
            if (
                disposition != "all"
                and selected_disposition["status"] != disposition
            ):
                continue
            if source_id and document["source_id"] != source_id:
                continue
            if media_type and document["media_type"] != media_type:
                continue
            if (
                classified_document_ids is not None
                and document["id"] not in classified_document_ids
            ):
                continue
            view = self._document_view(
                document,
                classification=classification_views.get(document["id"]),
                disposition=selected_disposition,
            )
            if area is not None and view["area"] != area:
                continue
            acquired_at = (view["current_version"] or {}).get("acquired_at", "")
            if date_from and acquired_at < date_from:
                continue
            if date_to and acquired_at > date_to:
                continue
            result.append(view)
        return sorted(
            result,
            key=lambda item: (
                (item["current_version"] or {}).get("acquired_at", ""),
                item["id"],
            ),
            reverse=True,
        )

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        document = self.store.read_canonical("documents", document_id)
        return (
            self._document_view(
                document,
                classification=self.hierarchy.get_classification(document_id),
            )
            if document
            else None
        )

    def hierarchy_tree(self) -> dict[str, Any]:
        return self.hierarchy.tree()

    def list_hierarchy_nodes(self) -> list[dict[str, Any]]:
        return self.hierarchy.list_nodes()

    def get_hierarchy_node(self, node_id: str) -> dict[str, Any] | None:
        return self.hierarchy.get_node(node_id)

    def create_hierarchy_node(
        self,
        kind: str,
        name: str,
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        return self.hierarchy.create_node(kind, name, parent_id=parent_id)

    def rename_hierarchy_node(self, node_id: str, name: str) -> dict[str, Any]:
        return self.hierarchy.rename_node(node_id, name)

    def move_hierarchy_node(
        self,
        node_id: str,
        parent_id: str | None,
    ) -> dict[str, Any]:
        return self.hierarchy.move_node(node_id, parent_id)

    def classify_document(
        self,
        document_id: str,
        primary_node_id: str,
        *,
        secondary_node_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        return self.hierarchy.classify_document(
            document_id,
            primary_node_id,
            secondary_node_ids=secondary_node_ids,
        )

    def document_classification(self, document_id: str) -> dict[str, Any] | None:
        return self.hierarchy.get_classification(document_id)

    def document_disposition(self, document_id: str) -> dict[str, Any] | None:
        return self.retention.get(document_id)

    def archive_document(self, document_id: str) -> dict[str, Any]:
        return self.retention.archive(document_id)

    def unarchive_document(self, document_id: str) -> dict[str, Any]:
        return self.retention.unarchive(document_id)

    def remove_document_from_library(self, document_id: str) -> dict[str, Any]:
        return self.retention.remove_from_library(document_id)

    def restore_document_to_library(self, document_id: str) -> dict[str, Any]:
        return self.retention.restore_to_library(document_id)

    def trash_document(self, document_id: str) -> dict[str, Any]:
        return self.retention.trash(document_id)

    def restore_document_from_trash(self, document_id: str) -> dict[str, Any]:
        return self.retention.restore_from_trash(document_id)

    def purge_document_preview(self, document_id: str) -> dict[str, Any]:
        return self.retention.purge_preview(document_id)

    def purge_document(
        self,
        document_id: str,
        confirmation_token: str,
        *,
        acknowledge_boundaries: bool = False,
    ) -> dict[str, Any]:
        return self.retention.purge(
            document_id,
            confirmation_token,
            acknowledge_boundaries=acknowledge_boundaries,
        )

    def current_version(self, document_id: str) -> dict[str, Any] | None:
        document = self.store.read_canonical("documents", document_id)
        if document is None:
            return None
        return self.store.read_canonical("versions", document["current_version_id"])

    def versions(self, document_id: str) -> list[dict[str, Any]]:
        return list(reversed(self.store.versions_for_document(document_id)))

    def extracted_text(self, document_id: str, *, max_chars: int = 30000) -> str | None:
        version = self.current_version(document_id)
        if version is None:
            return None
        artifact = self.store.derived_artifact_for_version(version["id"])
        if artifact is None:
            return None
        text = self.store.read_derived_text(artifact)
        return text[:max_chars]

    def document_content(
        self,
        document_id: str,
        *,
        max_chars: int = MAX_VIEWER_MARKDOWN_CHARS,
    ) -> dict[str, Any] | None:
        return self.content.get(document_id, max_chars=max_chars)

    def document_original(self, document_id: str) -> dict[str, Any] | None:
        return self.content.verified_original(document_id)

    def provenance(self, document_id: str) -> dict[str, Any] | None:
        document = self.get_document(document_id)
        if document is None:
            return None
        versions = self.store.versions_for_document(document_id)
        version_ids = {item["id"] for item in versions}
        acquisitions = [
            item
            for item in self.store.list_canonical("acquisitions")
            if item["document_id"] == document_id
        ]
        derived_artifacts = [
            item
            for item in self.store.list_derived_artifacts()
            if item["version_id"] in version_ids
        ]
        ids = {document_id, document["source_id"]}
        ids.update(version_ids)
        ids.update(item["original_id"] for item in versions)
        ids.update(item["id"] for item in acquisitions)
        ids.update(item["id"] for item in derived_artifacts)
        edges = self.store.list_canonical("provenance") + self.store.list_derived_provenance()
        selected = [
            edge
            for edge in edges
            if edge["from_id"] in ids and edge["to_id"] in ids
        ]
        selected.extend(
            edge
            for edge in edges
            if edge.get("from_kind") == "document"
            and edge.get("from_id") == document_id
            and edge.get("to_kind") == "hierarchy_node"
            and edge.get("relation")
            in {"classified_primary_as", "classified_secondary_as"}
            and edge not in selected
        )
        return {
            "document": document,
            "versions": list(reversed(versions)),
            "acquisitions": sorted(
                acquisitions,
                key=lambda item: item["observed_at"],
                reverse=True,
            ),
            "edges": sorted(
                selected,
                key=lambda item: (item["created_at"], item["id"]),
            ),
        }

    def recent_documents(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_documents()[:limit]

    def ingestion_errors(self, *, limit: int = 10) -> list[dict[str, Any]]:
        errors = [
            item
            for item in self.store.list_canonical("acquisitions")
            if item.get("error") or item["outcome"] == "extraction_failed"
        ]
        return sorted(errors, key=lambda item: item["observed_at"], reverse=True)[:limit]

    def areas(self) -> list[str]:
        return sorted(
            {self._area(item["locator"]) for item in self.list_documents(disposition="all")}
        )

    def media_types(self) -> list[str]:
        return sorted(
            {item["media_type"] for item in self.list_documents(disposition="all")}
        )

    def instance_summary(self) -> dict[str, Any]:
        config = self.store.read_config()
        manifest = self.store.read_manifest()
        network = config.get("network")
        if not isinstance(network, Mapping):
            network = {}
        documents = self.store.list_canonical("documents")
        hierarchy_nodes = self.store.list_canonical("hierarchy")
        classifications = self.store.list_canonical("classifications")
        dispositions = self.retention.list(status="all")
        health = self.knowledge_health()
        return {
            "id": config["instance"]["id"],
            "name": config["instance"]["name"],
            "schema_version": config["schema_version"],
            "manifest_schema_version": manifest["schema_version"],
            "created_at": config["instance"]["created_at"],
            "derived_state": dict(manifest["derived_state"]),
            "migrations_applied": len(manifest["migrations"]),
            "lifecycle_recoveries": len(
                list(self.store.paths.lifecycle_recovery_receipts.glob("*.json"))
            ),
            "sources": len(self.store.list_canonical("sources")),
            "documents": len(documents),
            "versions": len(self.store.list_canonical("versions")),
            "hierarchy_nodes": len(hierarchy_nodes),
            "classifications": len(classifications),
            "archived_documents": sum(
                item["status"] == "archived" for item in dispositions
            ),
            "trashed_documents": sum(
                item["status"] == "trashed" for item in dispositions
            ),
            "library_excluded_documents": sum(
                not item["projected"] and item["status"] != "trashed"
                for item in dispositions
            ),
            "index_status": health["index_status"],
            "knowledge_status": health["status"],
            "network": {
                "external_access": bool(network.get("external_access", False)),
                "update_checks": bool(network.get("update_checks", False)),
                "configured_external_providers": 0,
            },
        }

    def network_status(self) -> dict[str, Any]:
        return declared_network_status(self.store.read_config())

    def knowledge_health(self) -> dict[str, Any]:
        documents = self.store.list_canonical("documents")
        acquisitions = self.store.list_canonical("acquisitions")
        sources = self.store.list_canonical("sources")
        problems: list[dict[str, str]] = []
        for acquisition in acquisitions:
            if acquisition["outcome"] == "extraction_failed":
                problems.append(
                    {
                        "code": "extraction_failed",
                        "severity": "warning",
                        "message": f"Text extraction failed for {acquisition['locator']}.",
                    }
                )
        for source in sources:
            source_path = self.store.source_path(source["id"])
            if source_path is None or not source_path.exists():
                problems.append(
                    {
                        "code": "source_missing",
                        "severity": "warning",
                        "message": (
                            f"Source {source['name']} is not currently readable at its "
                            "configured path."
                        ),
                    }
                )
        hashes: dict[str, list[str]] = {}
        for document in documents:
            version = self.store.read_canonical("versions", document["current_version_id"])
            if version:
                hashes.setdefault(version["content_hash"], []).append(document["id"])
                if self.store.derived_artifact_for_version(version["id"]) is None:
                    problems.append(
                        {
                            "code": "derived_missing",
                            "severity": "warning",
                            "message": (
                                f"Derived text is missing for {document['title']} and can be "
                                "rebuilt."
                            ),
                        }
                    )
        for ids in hashes.values():
            if len(ids) > 1:
                problems.append(
                    {
                        "code": "duplicate_content",
                        "severity": "info",
                        "message": (
                            f"The same current content is referenced by {len(ids)} documents."
                        ),
                    }
                )
        status = index_status(self.store)
        if status != "ready":
            problems.append(
                {
                    "code": f"index_{status}",
                    "severity": "warning",
                    "message": (
                        "The search index is missing or out of date and can be rebuilt safely."
                    ),
                }
            )
        return {
            "status": "healthy" if not problems else "attention",
            "index_status": status,
            "problems": problems,
        }
