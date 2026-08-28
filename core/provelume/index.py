from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from .derived import materialize_extracted_text
from .domain import as_record
from .extractors import ExtractionError, extractor_for
from .storage import InstanceStore, utc_now

INDEX_SCHEMA = 2


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


def _documents_and_versions(
    store: InstanceStore,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    documents = store.list_canonical("documents")
    current = {
        str(document["id"]): str(document["current_version_id"])
        for document in documents
    }
    return documents, current


def _knowledge_fingerprint(documents: dict[str, str]) -> str:
    pairs = sorted(
        f"{document_id}:{version_id}"
        for document_id, version_id in documents.items()
    )
    return hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest()


def _metadata_path(store: InstanceStore) -> Path:
    return store.paths.indexes / "search.meta.json"


def _database_path(store: InstanceStore) -> Path:
    return store.paths.indexes / "search.sqlite3"


def _valid_metadata(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    documents = value.get("documents")
    return (
        value.get("schema_version") == INDEX_SCHEMA
        and isinstance(value.get("knowledge_fingerprint"), str)
        and isinstance(value.get("built_at"), str)
        and type(value.get("documents_indexed")) is int
        and int(value["documents_indexed"]) >= 0
        and isinstance(documents, dict)
        and all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in documents.items()
        )
    )


def _read_metadata(store: InstanceStore) -> dict[str, Any] | None:
    path = _metadata_path(store)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if _valid_metadata(value) else None


def _write_metadata(
    store: InstanceStore,
    documents: dict[str, str],
    documents_indexed: int,
) -> None:
    store._atomic_json(_metadata_path(store), _metadata(documents, documents_indexed))


def _metadata(
    documents: dict[str, str],
    documents_indexed: int,
) -> dict[str, Any]:
    return {
        "schema_version": INDEX_SCHEMA,
        "knowledge_fingerprint": _knowledge_fingerprint(documents),
        "built_at": utc_now(),
        "documents_indexed": documents_indexed,
        "documents": documents,
    }


def _unused_temporary_path(directory: Path, *, prefix: str, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _install_rebuilt_index(
    store: InstanceStore,
    database_candidate: Path,
    metadata_candidate: Path,
) -> None:
    database = _database_path(store)
    metadata = _metadata_path(store)
    database_backup = _unused_temporary_path(
        store.paths.indexes,
        prefix=".search-previous-",
        suffix=".sqlite3",
    )
    metadata_backup = _unused_temporary_path(
        store.paths.indexes,
        prefix=".search-metadata-previous-",
        suffix=".json",
    )
    database_backed_up = False
    metadata_backed_up = False
    database_installed = False
    metadata_installed = False
    committed = False
    try:
        if database.exists():
            os.replace(database, database_backup)
            database_backed_up = True
        if metadata.exists():
            os.replace(metadata, metadata_backup)
            metadata_backed_up = True
        os.replace(database_candidate, database)
        database_installed = True
        os.replace(metadata_candidate, metadata)
        metadata_installed = True
        committed = True
    except BaseException:
        if metadata_installed:
            metadata.unlink(missing_ok=True)
        if database_installed:
            database.unlink(missing_ok=True)
        if metadata_backed_up:
            os.replace(metadata_backup, metadata)
            metadata_backed_up = False
        if database_backed_up:
            os.replace(database_backup, database)
            database_backed_up = False
        raise
    finally:
        cleanup = (
            (database_backup, committed or not database_backed_up),
            (metadata_backup, committed or not metadata_backed_up),
        )
        for obsolete, safe_to_remove in cleanup:
            if not safe_to_remove:
                continue
            with suppress(OSError):
                obsolete.unlink(missing_ok=True)


def _create_search_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE VIRTUAL TABLE search USING fts5("
        "document_id UNINDEXED, version_id UNINDEXED, source_id UNINDEXED, "
        "media_type UNINDEXED, acquired_at UNINDEXED, title, content)"
    )


def _insert_document(
    connection: sqlite3.Connection,
    store: InstanceStore,
    document: dict[str, Any],
    *,
    recover_missing_derived: bool,
) -> bool:
    version = store.read_canonical("versions", document["current_version_id"])
    if version is None:
        return False
    artifact = _ensure_extracted(
        store,
        version,
        document["locator"],
        recover_missing_derived=recover_missing_derived,
    )
    if artifact is None:
        return False
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
    return True


def _database_count(path: Path) -> int:
    connection = _connection(path)
    try:
        return int(connection.execute("SELECT count(*) FROM search").fetchone()[0])
    finally:
        connection.close()


def rebuild_search_index(
    store: InstanceStore,
    *,
    recover_missing_derived: bool = True,
) -> int:
    store.paths.indexes.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".search-building-",
        suffix=".sqlite3",
        dir=store.paths.indexes,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    temporary_metadata_path = _unused_temporary_path(
        store.paths.indexes,
        prefix=".search-metadata-building-",
        suffix=".json",
    )
    documents, current = _documents_and_versions(store)
    connection: sqlite3.Connection | None = None
    try:
        connection = _connection(temporary_path)
        _create_search_table(connection)
        count = 0
        for document in documents:
            count += int(
                _insert_document(
                    connection,
                    store,
                    document,
                    recover_missing_derived=recover_missing_derived,
                )
            )
        connection.commit()
        connection.close()
        connection = None
        with temporary_path.open("r+b") as handle:
            os.fsync(handle.fileno())
        store._atomic_json(temporary_metadata_path, _metadata(current, count))
        _install_rebuilt_index(store, temporary_path, temporary_metadata_path)
        return count
    finally:
        if connection is not None:
            connection.close()
        temporary_path.unlink(missing_ok=True)
        temporary_metadata_path.unlink(missing_ok=True)


def refresh_search_index(
    store: InstanceStore,
    document_ids: Iterable[str],
    *,
    recover_missing_derived: bool = False,
) -> int:
    selected = {str(document_id) for document_id in document_ids}
    path = _database_path(store)
    metadata = _read_metadata(store)
    documents, current = _documents_and_versions(store)
    if metadata is None or not path.is_file():
        return rebuild_search_index(
            store,
            recover_missing_derived=recover_missing_derived,
        )

    previous = {
        str(key): str(value) for key, value in metadata["documents"].items()
    }
    if metadata["knowledge_fingerprint"] != _knowledge_fingerprint(previous):
        return rebuild_search_index(
            store,
            recover_missing_derived=recover_missing_derived,
        )
    unchanged_previous = {
        key: value for key, value in previous.items() if key not in selected
    }
    unchanged_current = {
        key: value for key, value in current.items() if key not in selected
    }
    if unchanged_previous != unchanged_current:
        return rebuild_search_index(
            store,
            recover_missing_derived=recover_missing_derived,
        )
    try:
        existing_count = _database_count(path)
    except sqlite3.Error:
        return rebuild_search_index(
            store,
            recover_missing_derived=recover_missing_derived,
        )
    if existing_count != int(metadata["documents_indexed"]):
        return rebuild_search_index(
            store,
            recover_missing_derived=recover_missing_derived,
        )
    if not selected and previous == current:
        return existing_count

    by_id = {str(document["id"]): document for document in documents}
    connection = _connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for document_id in sorted(selected):
            connection.execute(
                "DELETE FROM search WHERE document_id = ?",
                (document_id,),
            )
            document = by_id.get(document_id)
            if document is not None:
                _insert_document(
                    connection,
                    store,
                    document,
                    recover_missing_derived=recover_missing_derived,
                )
        count = int(connection.execute("SELECT count(*) FROM search").fetchone()[0])
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        connection.close()
        return rebuild_search_index(
            store,
            recover_missing_derived=recover_missing_derived,
        )
    finally:
        connection.close()

    _write_metadata(store, current, count)
    return count


def index_status(store: InstanceStore) -> str:
    path = _database_path(store)
    if not path.exists() or not _metadata_path(store).exists():
        return "missing"
    metadata = _read_metadata(store)
    if metadata is None:
        return "invalid"
    _documents, current = _documents_and_versions(store)
    if metadata["documents"] != current:
        return "out_of_date"
    if metadata["knowledge_fingerprint"] != _knowledge_fingerprint(current):
        return "invalid"
    try:
        count = _database_count(path)
    except sqlite3.Error:
        return "invalid"
    if count != int(metadata["documents_indexed"]):
        return "invalid"
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
    connection = _connection(_database_path(store))
    try:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
    finally:
        connection.close()
