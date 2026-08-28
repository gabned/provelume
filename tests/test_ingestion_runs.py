from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

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
