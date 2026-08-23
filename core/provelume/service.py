from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .index import index_status, rebuild_search_index, search_index
from .ingest import ingest_filesystem
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
    ) -> "ProvelumeInstance":
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
    ) -> list[dict[str, Any]]:
        acquisitions = ingest_filesystem(self.store, source_path, source_name=source_name)
        rebuild_search_index(self.store)
        return [
            {
                "id": item.id,
                "source_id": item.source_id,
                "locator": item.locator,
                "observed_at": item.observed_at,
                "content_hash": item.content_hash,
                "outcome": item.outcome,
                "document_id": item.document_id,
                "version_id": item.version_id,
                "error": item.error,
            }
            for item in acquisitions
        ]

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
        acquisitions = [
            item
            for item in self.store.list_canonical("acquisitions")
            if item["document_id"] == document_id
        ]
        ids = {document_id, document["source_id"]}
        ids.update(item["id"] for item in versions)
        ids.update(item["original_id"] for item in versions)
        ids.update(item["id"] for item in acquisitions)
        edges = self.store.list_canonical("provenance") + self.store.list_derived_provenance()
        changed = True
        while changed:
            changed = False
            for edge in edges:
                if edge["from_id"] in ids or edge["to_id"] in ids:
                    before = len(ids)
                    ids.add(edge["from_id"])
                    ids.add(edge["to_id"])
                    changed = changed or len(ids) > before
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
                "external_access": bool(config.get("network", {}).get("external_access", False)),
                "update_checks": bool(config.get("network", {}).get("update_checks", False)),
                "configured_external_providers": 0,
            },
        }

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
