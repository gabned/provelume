from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import provelume.ingest as ingest_module
from provelume.cli import main
from provelume.extractors import ExtractionError, ExtractionResult
from provelume.ingestion_runs import (
    IngestionItemRecord,
    IngestionLedger,
    IngestionRunRecord,
)
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def test_mixed_run_is_durable_and_retries_only_failed_items(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "good.txt").write_text("durable valid work\n", encoding="utf-8")
    oversized = source / "oversized.txt"
    oversized.write_text("x" * 100, encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    first = instance.ingest_run(source, max_file_bytes=32)

    assert first["run"]["status"] == "completed_with_errors"
    assert first["run"]["completed_items"] == 1
    assert first["run"]["failed_items"] == 1
    assert len(first["acquisitions"]) == 1
    failed = next(item for item in first["items"] if item["status"] == "failed")
    assert failed["locator"] == "oversized.txt"
    assert failed["error_code"] == "file_too_large"
    assert str(tmp_path) not in failed["error"]
    assert instance.search("durable")[0]["title"] == "good.txt"

    restarted = ProvelumeInstance(tmp_path / "instance")
    run_id = first["run"]["id"]
    assert restarted.list_ingestion_runs()[0]["id"] == run_id
    assert restarted.get_ingestion_run(run_id) == {
        "run": first["run"],
        "items": first["items"],
    }

    oversized.write_text("retry recovered\n", encoding="utf-8")
    retried = restarted.retry_ingestion(run_id)

    assert retried["run"]["status"] == "completed"
    assert retried["run"]["retry_of_run_id"] == run_id
    assert len(retried["items"]) == 1
    assert retried["items"][0]["locator"] == "oversized.txt"
    assert retried["items"][0]["attempt"] == 2
    assert retried["items"][0]["retry_of_item_id"] == failed["id"]
    assert retried["items"][0]["outcome"] == "created"
    assert restarted.search("recovered")[0]["title"] == "oversized.txt"


def test_extraction_failure_recovers_without_replacing_original_or_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("recover preserved bytes\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    class FlakyExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, data: bytes) -> ExtractionResult:
            self.calls += 1
            if self.calls == 1:
                raise ExtractionError("synthetic transient extraction failure")
            return ExtractionResult(
                text=data.decode("utf-8"),
                generator="synthetic.flaky",
                generator_version="1",
            )

    extractor = FlakyExtractor()
    monkeypatch.setattr("provelume.ingest.extractor_for", lambda _path: extractor)

    first = instance.ingest_run(source)
    document = instance.store.list_canonical("documents")[0]
    original_id = instance.store.list_canonical("originals")[0]["id"]
    version_id = document["current_version_id"]

    assert first["run"]["status"] == "failed"
    assert first["items"][0]["outcome"] == "extraction_failed"
    assert extractor.calls == 1
    assert instance.store.derived_artifact_for_version(version_id) is None

    retried = instance.retry_ingestion(first["run"]["id"])

    assert retried["run"]["status"] == "completed"
    assert retried["items"][0]["outcome"] == "extraction_recovered"
    assert extractor.calls == 2
    assert len(instance.store.list_canonical("originals")) == 1
    assert instance.store.list_canonical("originals")[0]["id"] == original_id
    assert len(instance.store.versions_for_document(document["id"])) == 1
    assert instance.store.versions_for_document(document["id"])[0]["id"] == version_id
    assert len(instance.store.list_canonical("acquisitions")) == 2
    assert instance.search("preserved")[0]["document_id"] == document["id"]


def test_interrupted_item_retry_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("idempotent retry\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    first = instance.ingest_run(source)
    ledger = IngestionLedger(instance.store)

    interrupted_run = replace(
        IngestionRunRecord(**first["run"]),
        status="running",
        completed_at=None,
        completed_items=0,
    )
    interrupted_item = replace(
        IngestionItemRecord(**first["items"][0]),
        status="running",
        completed_at=None,
        acquisition_id=None,
        outcome=None,
    )
    ledger.write_run(interrupted_run)
    ledger.write_item(interrupted_item)

    retried = instance.retry_ingestion(interrupted_run.id)

    assert retried["run"]["status"] == "completed"
    assert retried["items"][0]["outcome"] == "unchanged"
    assert retried["items"][0]["attempt"] == 2
    assert len(instance.store.list_canonical("originals")) == 1
    assert len(instance.store.list_canonical("versions")) == 1
    assert len(instance.store.list_canonical("acquisitions")) == 2


def test_interrupted_after_document_write_recovers_missing_extraction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("recover after interruption\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    original_materialize = ingest_module.materialize_extracted_text

    def interrupt_materialization(*_args, **_kwargs):
        raise RuntimeError("synthetic interruption before derived commit")

    monkeypatch.setattr(
        ingest_module,
        "materialize_extracted_text",
        interrupt_materialization,
    )

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        instance.ingest_run(source)

    interrupted = instance.list_ingestion_runs()[0]
    detail = instance.get_ingestion_run(interrupted["id"])
    assert interrupted["status"] == "running"
    assert detail is not None
    assert detail["items"][0]["status"] == "running"
    document = instance.store.list_canonical("documents")[0]
    version_id = document["current_version_id"]
    assert instance.store.derived_artifact_for_version(version_id) is None

    monkeypatch.setattr(
        ingest_module,
        "materialize_extracted_text",
        original_materialize,
    )
    retried = instance.retry_ingestion(interrupted["id"])

    assert retried["run"]["status"] == "completed"
    assert retried["items"][0]["outcome"] == "extraction_recovered"
    assert instance.store.derived_artifact_for_version(version_id) is not None
    assert instance.search("interruption")[0]["document_id"] == document["id"]


def test_partial_version_is_reconciled_without_orphan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("reconcile partial version\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    original_write_document = instance.store.write_document

    def interrupt_document_write(_document) -> None:
        raise RuntimeError("synthetic interruption after Version commit")

    monkeypatch.setattr(
        instance.store,
        "write_document",
        interrupt_document_write,
    )

    with pytest.raises(RuntimeError, match="after Version commit"):
        instance.ingest_run(source)

    interrupted = instance.list_ingestion_runs()[0]
    partial_versions = instance.store.list_canonical("versions")
    assert interrupted["status"] == "running"
    assert instance.store.list_canonical("documents") == []
    assert len(partial_versions) == 1

    monkeypatch.setattr(
        instance.store,
        "write_document",
        original_write_document,
    )
    retried = instance.retry_ingestion(interrupted["id"])

    documents = instance.store.list_canonical("documents")
    versions = instance.store.list_canonical("versions")
    assert retried["run"]["status"] == "completed"
    assert retried["items"][0]["outcome"] == "created"
    assert len(documents) == 1
    assert len(versions) == 1
    assert versions[0]["id"] == partial_versions[0]["id"]
    assert versions[0]["document_id"] == documents[0]["id"]
    assert documents[0]["current_version_id"] == versions[0]["id"]


def test_missing_configured_source_creates_failed_run(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("configured source\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    completed = instance.ingest_run(source)
    shutil.rmtree(source)

    failed = instance.ingest_run(source)

    assert completed["run"]["status"] == "completed"
    assert failed["run"]["status"] == "failed"
    assert failed["run"]["source_id"] == completed["run"]["source_id"]
    assert failed["run"]["error_code"] == "input_missing"
    assert failed["run"]["item_count"] == 0
    assert failed["items"] == []
    assert instance.list_ingestion_runs()[0]["id"] == failed["run"]["id"]


def test_missing_retry_input_fails_without_mutating_knowledge(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    blocked = source / "blocked.txt"
    blocked.write_text("x" * 100, encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    first = instance.ingest_run(source, max_file_bytes=10)
    before = {
        kind: instance.store.list_canonical(kind)
        for kind in ("originals", "documents", "versions", "acquisitions")
    }
    blocked.unlink()

    retried = instance.retry_ingestion(first["run"]["id"])

    assert retried["run"]["status"] == "failed"
    assert retried["items"][0]["error_code"] == "input_missing"
    assert str(tmp_path) not in retried["items"][0]["error"]
    assert {
        kind: instance.store.list_canonical(kind)
        for kind in ("originals", "documents", "versions", "acquisitions")
    } == before


def test_cli_and_read_only_api_expose_ingestion_runs(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("operator-visible run\n", encoding="utf-8")
    instance_root = tmp_path / "instance"
    assert main(["init", str(instance_root)]) == 0
    capsys.readouterr()

    assert main(["ingest", str(instance_root), str(source)]) == 0
    ingested = json.loads(capsys.readouterr().out)
    run_id = ingested["run"]["id"]

    assert main(["ingestion-runs", str(instance_root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == run_id
    assert main(["ingestion-run", str(instance_root), run_id]) == 0
    assert json.loads(capsys.readouterr().out)["run"]["id"] == run_id

    client = TestClient(create_app(instance_root))
    listed = client.get("/api/v1/ingestion/runs")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == run_id
    detail = client.get(f"/api/v1/ingestion/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["items"][0]["locator"] == "note.txt"
    assert client.post(f"/api/v1/ingestion/runs/{run_id}").status_code == 405
