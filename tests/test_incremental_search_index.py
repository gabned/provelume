from __future__ import annotations

import json
from pathlib import Path

import pytest

from provelume import index as index_module
from provelume.inbox import InboxManager
from provelume.index import INDEX_SCHEMA, index_status, rebuild_search_index
from provelume.service import ProvelumeInstance


def _instance_with_two_documents(tmp_path: Path) -> tuple[ProvelumeInstance, Path]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "alpha.txt").write_text(
        "alpha durable traceability baseline\n",
        encoding="utf-8",
    )
    (source / "beta.txt").write_text(
        "beta portable knowledge baseline\n",
        encoding="utf-8",
    )
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source, source_name="Synthetic source")
    return instance, source


def _metadata(instance: ProvelumeInstance) -> dict[str, object]:
    return json.loads(
        (instance.store.paths.indexes / "search.meta.json").read_text(
            encoding="utf-8"
        )
    )


def test_ingestion_refresh_reads_only_changed_document_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, source = _instance_with_two_documents(tmp_path)
    original_documents = {
        document["title"]: document for document in instance.list_documents()
    }
    original_version_ids = {
        document["current_version"]["id"] for document in original_documents.values()
    }
    reads: list[str] = []
    read_derived_text = instance.store.read_derived_text

    def tracked_read(artifact: dict[str, object]) -> str:
        reads.append(str(artifact["version_id"]))
        return read_derived_text(artifact)

    monkeypatch.setattr(instance.store, "read_derived_text", tracked_read)
    (source / "gamma.txt").write_text(
        "gamma incremental indexing evidence\n",
        encoding="utf-8",
    )

    result = instance.ingest_run(source)
    changed = {
        acquisition["document_id"]
        for acquisition in result["acquisitions"]
        if acquisition["outcome"] != "unchanged"
    }
    gamma = next(
        document
        for document in instance.list_documents()
        if document["title"] == "gamma.txt"
    )

    assert changed == {gamma["id"]}
    assert reads == [gamma["current_version"]["id"]]
    assert original_version_ids.isdisjoint(reads)
    assert instance.search("durable traceability")[0]["title"] == "alpha.txt"
    assert instance.search("incremental indexing")[0]["title"] == "gamma.txt"
    assert index_status(instance.store) == "ready"

    metadata = _metadata(instance)
    assert metadata["schema_version"] == INDEX_SCHEMA
    assert metadata["documents_indexed"] == 3
    assert metadata["documents"] == {
        document["id"]: document["current_version"]["id"]
        for document in instance.list_documents()
    }


def test_changed_version_replaces_only_its_search_row(tmp_path: Path) -> None:
    instance, source = _instance_with_two_documents(tmp_path)
    alpha = next(
        document
        for document in instance.list_documents()
        if document["title"] == "alpha.txt"
    )
    (source / "alpha.txt").write_text(
        "alpha replacement vocabulary\n",
        encoding="utf-8",
    )

    instance.ingest_run(source)

    refreshed = instance.get_document(alpha["id"])
    assert refreshed is not None
    assert refreshed["current_version"]["id"] != alpha["current_version"]["id"]
    assert instance.search("replacement vocabulary")[0]["document_id"] == alpha["id"]
    assert instance.search("durable traceability") == []
    assert instance.search("portable knowledge")[0]["title"] == "beta.txt"


def test_legacy_index_metadata_is_rebuilt_transparently(tmp_path: Path) -> None:
    instance, _source = _instance_with_two_documents(tmp_path)
    metadata_path = instance.store.paths.indexes / "search.meta.json"
    metadata = _metadata(instance)
    metadata["schema_version"] = 1
    metadata.pop("documents", None)
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert index_status(instance.store) == "invalid"
    assert instance.search("portable knowledge")[0]["title"] == "beta.txt"
    rebuilt = _metadata(instance)
    assert rebuilt["schema_version"] == INDEX_SCHEMA
    assert index_status(instance.store) == "ready"


def test_failed_full_rebuild_preserves_previous_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source = _instance_with_two_documents(tmp_path)
    database_path = instance.store.paths.indexes / "search.sqlite3"
    metadata_path = instance.store.paths.indexes / "search.meta.json"
    database_before = database_path.read_bytes()
    metadata_before = metadata_path.read_bytes()

    def fail_read(_artifact: dict[str, object]) -> str:
        raise RuntimeError("synthetic derived read failure")

    monkeypatch.setattr(instance.store, "read_derived_text", fail_read)
    with pytest.raises(RuntimeError, match="synthetic derived read failure"):
        rebuild_search_index(instance.store)

    assert database_path.read_bytes() == database_before
    assert metadata_path.read_bytes() == metadata_before
    assert not list(instance.store.paths.indexes.glob(".search-building-*.sqlite3"))


def test_failed_metadata_install_restores_previous_index_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source = _instance_with_two_documents(tmp_path)
    database_path = instance.store.paths.indexes / "search.sqlite3"
    metadata_path = instance.store.paths.indexes / "search.meta.json"
    database_before = database_path.read_bytes()
    metadata_before = metadata_path.read_bytes()
    replace = index_module.os.replace

    def fail_metadata_install(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            source_path.name.startswith(".search-metadata-building-")
            and destination_path == metadata_path
        ):
            raise OSError("synthetic metadata install failure")
        replace(source, destination)

    monkeypatch.setattr(index_module.os, "replace", fail_metadata_install)
    with pytest.raises(OSError, match="synthetic metadata install failure"):
        rebuild_search_index(instance.store)

    assert database_path.read_bytes() == database_before
    assert metadata_path.read_bytes() == metadata_before
    assert index_status(instance.store) == "ready"
    assert instance.search("durable traceability")[0]["title"] == "alpha.txt"
    assert not list(instance.store.paths.indexes.glob(".search-*-building-*"))
    assert not list(instance.store.paths.indexes.glob(".search-previous-*"))
    assert not list(instance.store.paths.indexes.glob(".search-metadata-previous-*"))


def test_failed_inbox_extraction_refreshes_only_its_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _source = _instance_with_two_documents(tmp_path)
    reads: list[str] = []
    read_derived_text = instance.store.read_derived_text

    def tracked_read(artifact: dict[str, object]) -> str:
        reads.append(str(artifact["version_id"]))
        return read_derived_text(artifact)

    monkeypatch.setattr(instance.store, "read_derived_text", tracked_read)
    broken = tmp_path / "broken.txt"
    broken.write_bytes(b"\xff\xfe")

    result = InboxManager(instance.store).submit(broken)

    assert result["submission"]["status"] == "failed"
    assert result["acquisitions"] == []
    failed = next(
        acquisition
        for acquisition in instance.store.list_canonical("acquisitions")
        if acquisition["outcome"] == "extraction_failed"
    )
    assert failed["outcome"] == "extraction_failed"
    assert reads == []
    assert index_status(instance.store) == "ready"
    assert instance.search("portable knowledge")[0]["title"] == "beta.txt"
