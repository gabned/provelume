from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .derived import materialize_extracted_text
from .domain import as_record
from .extractors import ExtractionError, extractor_for
from .storage import InstanceStore, utc_now

INDEX_SCHEMA = 1


def _connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _literal_fts_query(query: str) -> str | None:
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        return None
    return " ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _ensure_extracted(
    store: InstanceStore,
    version: dict[str, Any],
    locator: str,
    *,
    recover_missing_derived: bool,
) -> dict[str, Any] | None:
    artifact = store.derived_artifact_for_version(version["id"])
    if artifact is not None:
        return artifact
    if not recover_missing_derived:
        return None
    original = store.read_canonical("originals", version["original_id"])
    if original is None:
        return None
    extractor = extractor_for(Path(locator))
    if extractor is None:
        return None
    data = store.original_bytes(original["id"])
    try:
        result = extractor.extract(data)
    except ExtractionError:
        return None
    return as_record(materialize_extracted_text(store, version["id"], result))


def rebuild_search_index(
    store: InstanceStore,
    *,
    recover_missing_derived: bool = True,
) -> int:
    store.paths.indexes.mkdir(parents=True, exist_ok=True)
    path = store.paths.indexes / "search.sqlite3"
    if path.exists():
        path.unlink()
    connection = _connection(path)
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE search USING fts5("
            "document_id UNINDEXED, version_id UNINDEXED, source_id UNINDEXED, "
            "media_type UNINDEXED, acquired_at UNINDEXED, title, content)"
        )
        count = 0
        for document in store.list_canonical("documents"):
            version = store.read_canonical("versions", document["current_version_id"])
            if version is None:
                continue
            artifact = _ensure_extracted(
                store,
                version,
                document["locator"],
                recover_missing_derived=recover_missing_derived,
            )
            if artifact is None:
                continue
            text = store.read_derived_text(artifact)
            connection.execute(
                "INSERT INTO search("
                "document_id, version_id, source_id, media_type, acquired_at, title, content"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    document["id"],
                    version["id"],
                    document["source_id"],
                    document["media_type"],
                    version["acquired_at"],
                    document["title"],
                    text,
                ),
            )
            count += 1
        connection.commit()
    finally:
        connection.close()
    metadata = {
        "schema_version": INDEX_SCHEMA,
        "knowledge_fingerprint": store.knowledge_fingerprint(),
        "built_at": utc_now(),
        "documents_indexed": count,
    }
    (store.paths.indexes / "search.meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return count


def index_status(store: InstanceStore) -> str:
    path = store.paths.indexes / "search.sqlite3"
    meta = store.paths.indexes / "search.meta.json"
    if not path.exists() or not meta.exists():
        return "missing"
    try:
        metadata = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"
    if metadata.get("knowledge_fingerprint") != store.knowledge_fingerprint():
        return "out_of_date"
    return "ready"


def search_index(
    store: InstanceStore,
    query: str,
    *,
    source_id: str | None = None,
    media_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    fts_query = _literal_fts_query(query)
    if fts_query is None:
        return []
    if index_status(store) != "ready":
        rebuild_search_index(store)
    clauses = ["search MATCH ?"]
    parameters: list[object] = [fts_query]
    if source_id:
        clauses.append("source_id = ?")
        parameters.append(source_id)
    if media_type:
        clauses.append("media_type = ?")
        parameters.append(media_type)
    if date_from:
        clauses.append("acquired_at >= ?")
        parameters.append(date_from)
    if date_to:
        clauses.append("acquired_at <= ?")
        parameters.append(date_to)
    parameters.append(max(1, min(limit, 200)))
    sql = (
        "SELECT document_id, version_id, source_id, media_type, acquired_at, title, "
        "snippet(search, 6, '«', '»', '…', 24) AS snippet "
        f"FROM search WHERE {' AND '.join(clauses)} ORDER BY rank LIMIT ?"
    )
    connection = _connection(store.paths.indexes / "search.sqlite3")
    try:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
    finally:
        connection.close()
