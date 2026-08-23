from __future__ import annotations

from pathlib import Path
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

    def search(self, query: str, **filters: Any) -> list[dict[str, Any]]:
        return search_index(self.store, query, **filters)

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
