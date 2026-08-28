from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .index import (
    index_status,
    rebuild_search_index,
    refresh_search_index,
    search_index,
)
from .ingest import (
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    IngestionLimitError,
    IngestionRunResult,
    retry_ingestion_run,
    run_ingestion_filesystem,
)
from .ingestion_runs import IngestionLedger
from .network_status import declared_network_status
from .paths import UnsafePathError
from .storage import InstanceStore


class ProvelumeInstance:
    def __init__(self, root: Path | str):
        self.store = InstanceStore(root)
        self.store.validate()

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
        self._refresh_after_ingestion(result)
        return result.as_dict()

    def _refresh_after_ingestion(self, result: IngestionRunResult) -> None:
        refresh_search_index(
            self.store,
            (
                acquisition.document_id
                for acquisition in result.acquisitions
                if acquisition.outcome != "unchanged"
            ),
            recover_missing_derived=False,
        )

    def retry_ingestion(self, run_id: str) -> dict[str, Any]:
        result = retry_ingestion_run(self.store, run_id)
        self._refresh_after_ingestion(result)
        return result.as_dict()

    def list_ingestion_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return IngestionLedger(self.store).list_runs(limit=limit)

    def get_ingestion_run(self, run_id: str) -> dict[str, Any] | None:
        return IngestionLedger(self.store).run_detail(run_id)

    def rebuild_index(self) -> int:
        return rebuild_search_index(self.store)

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

    def _document_view(self, document: dict[str, Any]) -> dict[str, Any]:
        version = self.store.read_canonical("versions", document["current_version_id"])
        source = self.store.read_canonical("sources", document["source_id"])
        return {
            **document,
            "area": self._area(document["locator"]),
            "source_name": source["name"] if source else document["source_id"],
            "current_version": version,
        }

    def list_documents(
        self,
        *,
        source_id: str | None = None,
        media_type: str | None = None,
        area: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        date_from = self._date_floor(date_from)
        date_to = self._date_ceiling(date_to)
        result = []
        for document in self.store.list_canonical("documents"):
            if source_id and document["source_id"] != source_id:
                continue
            if media_type and document["media_type"] != media_type:
                continue
            view = self._document_view(document)
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
            key=lambda item: (item["current_version"] or {}).get("acquired_at", ""),
            reverse=True,
        )

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        document = self.store.read_canonical("documents", document_id)
        return self._document_view(document) if document else None

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
        return {
            "document": document,
            "versions": list(reversed(versions)),
            "acquisitions": sorted(
                acquisitions,
                key=lambda item: item["observed_at"],
                reverse=True,
            ),
            "edges": sorted(selected, key=lambda item: item["created_at"]),
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
            {self._area(item["locator"]) for item in self.store.list_canonical("documents")}
        )

    def media_types(self) -> list[str]:
        return sorted({item["media_type"] for item in self.store.list_canonical("documents")})

    def instance_summary(self) -> dict[str, Any]:
        config = self.store.read_config()
        network = config.get("network")
        if not isinstance(network, Mapping):
            network = {}
        documents = self.store.list_canonical("documents")
        health = self.knowledge_health()
        return {
            "id": config["instance"]["id"],
            "name": config["instance"]["name"],
            "schema_version": config["schema_version"],
            "created_at": config["instance"]["created_at"],
            "sources": len(self.store.list_canonical("sources")),
            "documents": len(documents),
            "versions": len(self.store.list_canonical("versions")),
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
