from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.bundles import DocumentBundleManager
from provelume.cli import main
from provelume.index import index_status
from provelume.locks import (
    InstanceLockLease,
    InstanceLockManager,
    InstanceLockOwnershipError,
    InstanceLockUnavailable,
)
from provelume.operations import OperationLedger
from provelume.paths import safe_instance_path
from provelume.rebuild import DerivedRebuildManager, RebuildLimitError
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _seed_instance(tmp_path: Path) -> ProvelumeInstance:
    source = tmp_path / "source"
    source.mkdir()
    shared = "Deterministic rebuild evidence.\n"
    (source / "first.txt").write_text(shared, encoding="utf-8")
    (source / "second.txt").write_text(shared, encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    assert instance.ingest_run(source)["run"]["status"] == "completed"
    return instance


def test_instance_lock_is_exclusive_and_owner_checked(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = InstanceLockManager(instance.store)
    assert manager.inspect("derived-rebuild") is None
    assert not (instance.root / "state" / "locks").exists()

    lease = manager.acquire("derived-rebuild", purpose="synthetic rebuild")

    assert manager.inspect("derived-rebuild") == {
        "schema_version": 1,
        "name": "derived-rebuild",
        "held": True,
        "status": "held",
        "purpose": "synthetic rebuild",
        "acquired_at": lease.acquired_at,
    }
    with pytest.raises(InstanceLockUnavailable):
        manager.acquire("derived-rebuild", purpose="competing rebuild")
    wrong = InstanceLockLease(
        schema_version=lease.schema_version,
        name=lease.name,
        token="lock_" + "0" * 32,
        purpose=lease.purpose,
        acquired_at=lease.acquired_at,
    )
    with pytest.raises(InstanceLockOwnershipError):
        manager.release(wrong)
    assert manager.inspect("derived-rebuild")["held"] is True

    manager.release(lease)

    assert manager.inspect("derived-rebuild") is None


def test_incremental_and_full_rebuilds_agree_without_canonical_mutation(
    tmp_path: Path,
) -> None:
    instance = _seed_instance(tmp_path)
    canonical_before = instance.store.knowledge_fingerprint()

    report = DerivedRebuildManager(instance.store).run("agreement")

    assert report["status"] == "completed"
    assert report["mode"] == "agreement"
    assert report["agreement"] is True
    assert report["canonical_before"] == canonical_before
    assert report["canonical_after"] == canonical_before
    assert report["canonical_mutation"] == "none"
    assert len(report["passes"]) == 2
    assert report["final_snapshot"]["counts"]["documents"] == 2
    assert report["final_snapshot"]["counts"]["valid_bundles"] == 2
    assert index_status(instance.store) == "ready"
    assert len(DocumentBundleManager(instance.store).list()) == 2

    operation = OperationLedger(instance.store).get(report["operation_id"])
    assert operation is not None
    assert operation["status"] == "completed"
    codes = [event["code"] for event in operation["events"]]
    assert codes[0] == "rebuild.lock_acquired"
    assert "rebuild.index_committed" in codes
    assert "rebuild.duplicates_refreshed" in codes
    assert "rebuild.library_committed" in codes
    assert "rebuild.agreement_checked" in codes
    assert report["final_snapshot"]["counts"]["library_ready"] is True
    assert DerivedRebuildManager(instance.store).lock_status()["held"] is False


def test_incremental_rebuild_recovers_tampered_bundle_and_missing_index(
    tmp_path: Path,
) -> None:
    instance = _seed_instance(tmp_path)
    manager = DerivedRebuildManager(instance.store)
    initial = manager.run("full")
    assert initial["status"] == "completed"
    document = instance.store.list_canonical("documents")[0]
    bundle = DocumentBundleManager(instance.store).for_document(document["id"])
    assert bundle is not None
    markdown_ref = bundle["manifest"]["markdown"]["storage_ref"]
    markdown_path = safe_instance_path(instance.root, markdown_ref)
    markdown_path.write_text("tampered derived text\n", encoding="utf-8")
    (instance.store.paths.indexes / "search.sqlite3").unlink()

    recovered = manager.run("incremental")

    assert recovered["status"] == "completed"
    assert recovered["metrics"]["bundles_recovered"] == 1
    assert recovered["metrics"]["index_rebuilds"] == 1
    rebuilt = DocumentBundleManager(instance.store).for_document(document["id"])
    assert rebuilt is not None
    rebuilt_path = safe_instance_path(
        instance.root,
        rebuilt["manifest"]["markdown"]["storage_ref"],
    )
    assert rebuilt_path.read_text(encoding="utf-8") != "tampered derived text\n"
    assert index_status(instance.store) == "ready"


def test_rebuild_limit_fails_without_canonical_mutation_and_releases_lock(
    tmp_path: Path,
) -> None:
    instance = _seed_instance(tmp_path)
    manager = DerivedRebuildManager(instance.store)
    canonical_before = instance.store.knowledge_fingerprint()

    with pytest.raises(RebuildLimitError):
        manager.run("incremental", max_documents=1)

    assert instance.store.knowledge_fingerprint() == canonical_before
    assert manager.lock_status()["held"] is False
    assert manager.list_reports() == []
    failed = OperationLedger(instance.store).list(
        kind="rebuild.derived",
        status="failed",
    )
    assert len(failed) == 1
    assert failed[0]["error_code"] == "derived_rebuild_failed"


def test_rebuild_reads_are_side_effect_free(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    ProvelumeInstance.initialise(instance_root)
    client = TestClient(create_app(instance_root))

    summary = client.get("/api/v1/rebuild")
    assert summary.status_code == 200
    assert summary.json()["status"] == "not_run"
    assert client.get("/api/v1/rebuild/lock").json()["held"] is False
    assert client.get("/api/v1/rebuild/reports").json() == []
    assert client.get("/rebuild").status_code == 200
    assert client.post("/api/v1/rebuild").status_code == 405
    assert not (instance_root / "state" / "rebuild").exists()
    assert not (instance_root / "state" / "locks").exists()


def test_rebuild_cli_api_browser_and_operation_log(tmp_path: Path, capsys) -> None:
    instance = _seed_instance(tmp_path)
    instance_root = instance.root

    assert main(
        [
            "rebuild-derived",
            str(instance_root),
            "--mode",
            "agreement",
        ]
    ) == 0
    report = json.loads(capsys.readouterr().out)
    report_id = report["id"]
    assert main(["rebuild-reports", str(instance_root)]) == 0
    assert report_id in {
        item["id"] for item in json.loads(capsys.readouterr().out)
    }
    assert main(["rebuild-report", str(instance_root), report_id]) == 0
    assert json.loads(capsys.readouterr().out)["agreement"] is True
    assert main(["rebuild-lock", str(instance_root)]) == 0
    assert json.loads(capsys.readouterr().out)["held"] is False

    client = TestClient(create_app(instance_root))
    assert client.get(f"/api/v1/rebuild/reports/{report_id}").status_code == 200
    detail = client.get(f"/rebuild/{report_id}")
    assert detail.status_code == 200
    assert "rebuild.agreement_checked" in client.get(
        f"/operations/{report['operation_id']}"
    ).text
