from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from provelume.assurance import OriginalAssuranceManager
from provelume.cli import main
from provelume.duplicates import DuplicateCaseManager
from provelume.operations import OperationLedger
from provelume.paths import safe_instance_path
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _canonical_snapshot(instance: ProvelumeInstance) -> str:
    value = {
        kind: instance.store.list_canonical(kind)
        for kind in (
            "sources",
            "acquisitions",
            "originals",
            "documents",
            "versions",
            "provenance",
        )
    }
    return json.dumps(value, sort_keys=True)


def _seed_duplicates(tmp_path: Path) -> ProvelumeInstance:
    exact = tmp_path / "exact"
    exact.mkdir()
    shared = "Identical retained original bytes.\n"
    (exact / "copy-a.txt").write_text(shared, encoding="utf-8")
    (exact / "copy-b.txt").write_text(shared, encoding="utf-8")

    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "quarterly-report.txt").write_text(
        (
            "Quarterly strategy plan includes finance delivery operations risks "
            "and milestones.\n"
        ),
        encoding="utf-8",
    )
    (right / "quarterly-report.txt").write_text(
        (
            "Quarterly strategy plan includes finance delivery operations risks "
            "and milestones revised.\n"
        ),
        encoding="utf-8",
    )

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    assert instance.ingest_run(exact)["run"]["status"] == "completed"
    assert instance.ingest_run(left)["run"]["status"] == "completed"
    assert instance.ingest_run(right)["run"]["status"] == "completed"
    return instance


def test_duplicate_scan_preserves_documents_occurrences_and_originals(
    tmp_path: Path,
) -> None:
    instance = _seed_duplicates(tmp_path)
    before = _canonical_snapshot(instance)
    original_bytes = {
        item["id"]: instance.store.original_bytes(item["id"])
        for item in instance.store.list_canonical("originals")
    }

    result = DuplicateCaseManager(instance.store).scan()

    assert result["operation"]["status"] == "completed"
    assert len(result["exact"]) == 1
    assert len(result["probable"]) == 1
    exact = result["exact"][0]
    probable = result["probable"][0]
    assert exact["automatic_action"] == "none"
    assert exact["rule"] == "same_current_content_hash"
    assert len(exact["documents"]) == 2
    assert sum(item["acquisition_count"] for item in exact["documents"]) == 2
    assert probable["automatic_action"] == "none"
    assert probable["evidence"]["different_content_hashes"] is True
    assert probable["confidence"] >= 0.5
    assert _canonical_snapshot(instance) == before
    assert {
        original_id: instance.store.original_bytes(original_id)
        for original_id in original_bytes
    } == original_bytes

    versions = {
        item["id"]: item for item in instance.store.list_canonical("versions")
    }
    exact_originals = {
        versions[item["version_id"]]["original_id"] for item in exact["documents"]
    }
    assert len(exact_originals) == 1

    operation = OperationLedger(instance.store).get(result["operation"]["id"])
    assert operation is not None
    assert operation["kind"] == "duplicate.scan"
    assert operation["metrics"]["exact_cases"] == 1
    assert operation["metrics"]["probable_cases"] == 1


def test_duplicate_case_becomes_historical_without_automatic_mutation(
    tmp_path: Path,
) -> None:
    instance = _seed_duplicates(tmp_path)
    manager = DuplicateCaseManager(instance.store)
    first = manager.scan()
    exact_id = first["exact"][0]["id"]
    changed = tmp_path / "exact" / "copy-b.txt"
    changed.write_text("A later distinct version.\n", encoding="utf-8")
    assert instance.ingest_run(tmp_path / "exact")["run"]["status"] == "completed"

    second = manager.scan()

    assert second["exact"] == []
    previous = manager.get_case(exact_id)
    assert previous is not None
    assert previous["current"] is False
    assert previous["status"] == "not_current"
    assert previous["automatic_action"] == "none"
    documents = instance.store.list_canonical("documents")
    acquisitions = instance.store.list_canonical("acquisitions")
    assert len(documents) == 4
    assert len(acquisitions) == 6


def test_original_assurance_verifies_shared_bytes_without_repair(
    tmp_path: Path,
) -> None:
    instance = _seed_duplicates(tmp_path)
    before = _canonical_snapshot(instance)

    report = OriginalAssuranceManager(instance.store).check()

    assert report["status"] == "healthy"
    assert report["automatic_repair"] == "none"
    assert report["findings"] == []
    assert report["metrics"]["shared_originals"] == 1
    assert report["metrics"]["originals_verified"] == 3
    assert _canonical_snapshot(instance) == before
    operation = OperationLedger(instance.store).get(report["operation_id"])
    assert operation is not None
    assert operation["kind"] == "assurance.originals"
    assert operation["status"] == "completed"


def test_original_assurance_reports_tampering_without_replacing_bytes(
    tmp_path: Path,
) -> None:
    instance = _seed_duplicates(tmp_path)
    original = instance.store.list_canonical("originals")[0]
    path = safe_instance_path(instance.root, original["storage_ref"])
    path.write_bytes(b"tampered")

    report = OriginalAssuranceManager(instance.store).check()

    assert report["status"] == "attention"
    assert report["automatic_repair"] == "none"
    assert any(
        item["code"] == "original_hash_mismatch"
        for item in report["findings"]
    )
    assert path.read_bytes() == b"tampered"


def test_duplicate_and_assurance_reads_are_side_effect_free(tmp_path: Path) -> None:
    instance_root = tmp_path / "instance"
    ProvelumeInstance.initialise(instance_root)
    client = TestClient(create_app(instance_root))

    assert client.get("/api/v1/duplicates").json() == []
    assert client.get("/api/v1/assurance").json()["status"] == "not_run"
    assert client.get("/duplicates").status_code == 200
    assert client.get("/assurance").status_code == 200
    assert client.post("/api/v1/duplicates").status_code == 405
    assert client.post("/api/v1/assurance").status_code == 405
    assert not (instance_root / "state" / "duplicates").exists()
    assert not (instance_root / "state" / "assurance").exists()


def test_invalid_duplicate_case_is_skipped(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = DuplicateCaseManager(instance.store)
    manager.cases.mkdir(parents=True)
    invalid = manager.cases / f"dup_{'0' * 32}.json"
    invalid.write_text("{}\n", encoding="utf-8")

    assert manager.list_cases() == []
    assert manager.get_case(invalid.stem) is None
    client = TestClient(create_app(instance.root))
    assert client.get("/duplicates").status_code == 200


def test_duplicate_assurance_api_browser_and_cli(tmp_path: Path, capsys) -> None:
    instance = _seed_duplicates(tmp_path)
    instance_root = instance.root

    assert main(["duplicate-scan", str(instance_root)]) == 0
    scan = json.loads(capsys.readouterr().out)
    case_id = scan["exact"][0]["id"]
    assert main(["duplicates", str(instance_root)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert case_id in {item["id"] for item in listed}
    assert main(["duplicate", str(instance_root), case_id]) == 0
    assert json.loads(capsys.readouterr().out)["automatic_action"] == "none"

    assert main(["assurance-check", str(instance_root)]) == 0
    report = json.loads(capsys.readouterr().out)
    report_id = report["id"]
    assert main(["assurance-report", str(instance_root), report_id]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "healthy"

    client = TestClient(create_app(instance_root))
    assert client.get(f"/api/v1/duplicates/{case_id}").status_code == 200
    assert client.get(f"/duplicates/{case_id}").status_code == 200
    assert client.get(
        f"/api/v1/assurance/reports/{report_id}"
    ).status_code == 200
    assert client.get(f"/assurance/{report_id}").status_code == 200
    operations = client.get("/api/v1/operations").json()
    assert {item["kind"] for item in operations} >= {
        "duplicate.scan",
        "assurance.originals",
    }
