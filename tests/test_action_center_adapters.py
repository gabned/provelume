from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import provelume.action_center_adapters as adapters
from provelume.duplicates import DuplicateCaseManager, DuplicateScanStaleError
from provelume.extractors import ExtractionError, ExtractionResult
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.suffix != ".oslock"
    }


def _items(store: InstanceStore, queue: str) -> list[dict]:
    return [row for row in adapters.collect_proposals(store)["items"] if row["queue"] == queue]


def _instance(tmp_path: Path, *, contents: tuple[str, ...] = ("one",)):
    source = tmp_path / "source"
    source.mkdir()
    for position, content in enumerate(contents):
        (source / f"note-{position}.txt").write_text(content, encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    result = instance.ingest_run(source)
    return instance, source, result


def test_empty_snapshot_is_pure_and_explicit_about_all_eight_contributions(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    before = _snapshot(store.paths.root)
    result = adapters.collect_proposals(store)
    assert result["items"] == []
    assert tuple(result["queues"]) == adapters.QUEUES
    assert all(row["complete"] and row["matched_count"] == 0 for row in result["queues"].values())
    assert _snapshot(store.paths.root) == before
    assert not (store.paths.state / "locks").exists()


def test_visible_unclassified_and_recorded_trash_use_real_lineage_without_domain_actions(tmp_path):
    instance, _, _ = _instance(tmp_path, contents=("one", "two"))
    documents = instance.store.list_canonical("documents")
    instance.trash_document(documents[0]["id"])
    before = _snapshot(instance.store.paths.root)
    placement = _items(instance.store, "classification")
    trash = _items(instance.store, "retention")
    assert len(placement) == len(trash) == 1
    assert placement[0]["proposal"]["kind"] == "needs_manual_placement"
    assert trash[0]["proposal"]["kind"] == "review_recoverable_trash"
    assert placement[0]["evidence"]["document_id"] != trash[0]["evidence"]["document_id"]
    for row in (*placement, *trash):
        assert row["allowed_actions"] == []
        assert row["proposal"]["confidence"] is None and row["proposal"]["choices"] == []
        assert row["evidence"]["original_bytes_verified"] is False
        assert row["evidence"]["acquisition_ids"]
        assert (
            row["evidence"]["content_hash"]
            == instance.store.read_canonical("originals", row["evidence"]["original_id"])["sha256"]
        )
    assert _snapshot(instance.store.paths.root) == before


@pytest.mark.parametrize("bad", [b"{", b"[]", b'{"id":null}', b'{"id":"x","n":NaN}'])
def test_corrupt_record_is_unknown_never_exact_zero(tmp_path, bad):
    store = InstanceStore.initialise(tmp_path / "instance")
    directory = store.paths.state / "duplicates" / "cases"
    directory.mkdir(parents=True)
    (directory / ("dup_" + "a" * 32 + ".json")).write_bytes(bad)
    result = adapters.collect_proposals(store)
    for queue in ("exact_duplicate", "probable_duplicate"):
        observation = result["queues"][queue]
        assert not observation["complete"]
        assert observation["matched_count"] is None
        assert observation["count_relation"] == "unknown"


def test_unreadable_inventory_and_bounded_read_are_partial(tmp_path, monkeypatch):
    instance, _, _ = _instance(tmp_path, contents=("one", "two", "three"))
    original = adapters._Reader._bytes

    def denied(self, path):
        if path.parent.name == "documents":
            raise PermissionError("synthetic unreadable record")
        return original(self, path)

    monkeypatch.setattr(adapters._Reader, "_bytes", denied)
    result = adapters.collect_proposals(instance.store)
    assert result["queues"]["classification"]["matched_count"] is None
    assert not _items(instance.store, "classification")
    monkeypatch.setattr(adapters._Reader, "_bytes", original)
    monkeypatch.setattr(adapters, "MAX_RECORDS_PER_DIRECTORY", 1)
    result = adapters.collect_proposals(instance.store)
    assert result["queues"]["classification"]["matched_count"] is None
    assert "record_count_bound" in result["queues"]["classification"]["reason"]


def test_snapshot_race_is_reported_and_cannot_offer_complete_evidence(tmp_path, monkeypatch):
    instance, _, _ = _instance(tmp_path)
    original = adapters._Reader.verify

    def changed(self):
        document = next(iter(instance.store.paths.canonical_dir("documents").glob("*.json")))
        value = json.loads(document.read_bytes())
        value["title"] = "changed during bounded read"
        document.write_text(json.dumps(value), encoding="utf-8")
        return original(self)

    monkeypatch.setattr(adapters._Reader, "verify", changed)
    result = adapters.collect_proposals(instance.store)
    assert result["queues"]["classification"]["snapshot_changed"]
    assert result["queues"]["classification"]["matched_count"] is None


def test_duplicate_projection_preserves_current_binding_and_ignores_scan_clocks(tmp_path):
    instance, source, _ = _instance(
        tmp_path, contents=("same retained bytes", "same retained bytes")
    )
    manager = DuplicateCaseManager(instance.store)
    scan = manager.scan()
    row = _items(instance.store, "exact_duplicate")[0]
    assert row["producer_id"] == scan["exact"][0]["id"]
    assert row["proposal"]["confidence"] == 1
    assert row["allowed_actions"] == ["reject_proposal"]
    before = _snapshot(instance.store.paths.root)
    assert _items(instance.store, "exact_duplicate")[0]["input_revision"] == row["input_revision"]
    assert _snapshot(instance.store.paths.root) == before
    manager.scan()
    assert _items(instance.store, "exact_duplicate")[0]["input_revision"] == row["input_revision"]
    (source / "note-0.txt").write_text("new current version", encoding="utf-8")
    instance.ingest_run(source)
    result = adapters.collect_proposals(instance.store)
    assert not [item for item in result["items"] if item["queue"] == "exact_duplicate"]
    assert "producer_input_stale" in result["queues"]["exact_duplicate"]["reason"]
    manager.scan()
    historical = _items(instance.store, "exact_duplicate")[0]
    assert historical["producer_current"] is False
    assert historical["allowed_actions"] == []


def test_probable_case_uses_recorded_component_evidence(tmp_path):
    from test_duplicate_assurance import _seed_duplicates

    instance = _seed_duplicates(tmp_path)
    scan = DuplicateCaseManager(instance.store).scan()
    candidate = _items(instance.store, "probable_duplicate")[0]
    assert candidate["proposal"]["confidence"] == scan["probable"][0]["confidence"]
    assert candidate["evidence"]["evidence"] == scan["probable"][0]["evidence"]
    assert len({row["content_hash"] for row in candidate["evidence"]["lineage"]}) == 2


@pytest.mark.parametrize("change", [{"text_similarity": 0.1}, {"compared_text_tokens": 0}])
def test_probable_rule_requires_its_recorded_evidence_thresholds(tmp_path, change):
    from test_duplicate_assurance import _seed_duplicates

    instance = _seed_duplicates(tmp_path)
    manager = DuplicateCaseManager(instance.store)
    case = manager.scan()["probable"][0]
    case["evidence"].update(change)
    instance.store._atomic_json(manager.cases / (case["id"] + ".json"), case)
    result = adapters.collect_proposals(instance.store)
    assert not [row for row in result["items"] if row["queue"] == "probable_duplicate"]
    assert result["queues"]["probable_duplicate"]["matched_count"] is None
    assert "duplicate_rule_invalid" in result["queues"]["probable_duplicate"]["reason"]


def test_retry_chain_counts_current_problem_once_and_preserves_exact_attempts(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    selected = source / "large.txt"
    selected.write_text("x" * 100, encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    first = instance.ingest_run(source, max_file_bytes=32)
    assert len(_items(instance.store, "intake")) == 1
    second = instance.retry_ingestion(first["run"]["id"])
    current = _items(instance.store, "intake")
    assert len(current) == 1
    assert [row["id"] for row in current[0]["evidence"]["attempts"]] == [
        first["items"][0]["id"],
        second["items"][0]["id"],
    ]
    selected.write_text("recovered", encoding="utf-8")
    instance.retry_ingestion(second["run"]["id"])
    assert _items(instance.store, "intake") == []


def test_extraction_failure_has_one_primary_queue_and_successful_retry_recovers(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("retained bytes", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    class Extractor:
        failing = True

        def extract(self, data):
            if self.failing:
                raise ExtractionError("synthetic failure")
            return ExtractionResult(
                text=data.decode(), generator="synthetic", generator_version="1"
            )

    extractor = Extractor()
    monkeypatch.setattr("provelume.ingest.extractor_for", lambda _: extractor)
    failed = instance.ingest_run(source)
    result = adapters.collect_proposals(instance.store)
    assert result["queues"]["intake"]["matched_count"] == 0
    assert result["queues"]["extraction_error"]["matched_count"] == 1
    candidate = _items(instance.store, "extraction_error")[0]
    assert candidate["evidence"]["acquisition_id"] == failed["items"][0]["acquisition_id"]
    extractor.failing = False
    instance.retry_ingestion(failed["run"]["id"])
    assert _items(instance.store, "extraction_error") == []


def test_absent_derived_output_is_not_an_extraction_failure(tmp_path):
    instance, _, _ = _instance(tmp_path)
    for path in instance.store.paths.derived_artifacts.glob("*.json"):
        path.unlink()
    assert _items(instance.store, "extraction_error") == []


def test_ocr_failed_attempt_is_bound_to_version_and_recovers_in_same_job(tmp_path):
    from test_ocr_execution import _fixture

    instance, manager, _, _, version_id = _fixture(tmp_path, fail_page_once=1)
    queued = manager.queue(version_id, mode="forced")
    first = instance.scheduler.run_one(
        job_id=queued["job"]["id"],
        now=datetime.fromisoformat(queued["job"]["eligible_at"]).astimezone(UTC),
    )
    assert first["status"] == "retry_wait"
    candidate = _items(instance.store, "extraction_error")[0]
    assert candidate["evidence"]["version_id"] == version_id
    assert candidate["evidence"]["job_id"] == first["id"]
    assert candidate["evidence"]["attempt"] == 1
    assert candidate["proposal"]["reason"] == "ocr_adapter_failure"
    retry_at = datetime.fromisoformat(first["retry_not_before"])
    instance.scheduler.recover(now=retry_at)
    assert instance.scheduler.run_one(job_id=first["id"], now=retry_at)["status"] == "succeeded"
    assert _items(instance.store, "extraction_error") == []


def test_transcript_failed_parse_is_explicit_source_snapshot_evidence(tmp_path):
    from test_transcript_jobs import _enabled, _run

    instance, _, source_id = _enabled(tmp_path, b"1\n00:00:02,000 --> 00:00:01,000\ninvalid\n")
    queued, _ = _run(instance, source_id)
    candidate = _items(instance.store, "extraction_error")[0]
    assert candidate["proposal"]["reason"] == "transcript_timestamp_invalid"
    assert candidate["evidence"]["source_id"] == source_id
    assert candidate["evidence"]["job_id"] == queued["job"]["id"]
    assert candidate["evidence"]["snapshot_sha256"]


def test_unobserved_source_is_unknown_and_never_reported_as_missing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.register_folder_source(source, name="Synthetic source")
    result = adapters.collect_proposals(instance.store)
    assert not _items(instance.store, "source_change")
    assert "source_not_observed" in result["queues"]["source_change"]["reason"]


def test_reconciliation_plan_owns_source_count_and_rejects_stale_canonical_input(
    tmp_path, monkeypatch
):
    from test_source_reconciliation import _registered_instance, _run_reconciliation

    from provelume.source_reconciliation import SourceReconciliationManager

    # Preserve the real writer exception in fixture diagnostics; scheduler's
    # public local_io code intentionally omits private filesystem paths.
    execute = SourceReconciliationManager.execute

    def diagnose_io(self, *args, **kwargs):
        try:
            return execute(self, *args, **kwargs)
        except OSError as exc:
            raise AssertionError(f"synthetic reconciliation fixture I/O: {exc!r}") from exc

    monkeypatch.setattr(SourceReconciliationManager, "execute", diagnose_io)
    instance, source, source_id = _registered_instance(tmp_path, {"one.txt": b"original"})
    (source / "one.txt").write_bytes(b"changed content")
    (source / "two.txt").write_bytes(b"new content")
    instance.observe_folder_source(source_id)
    result = _run_reconciliation(instance, source_id, request_key="adapter-plan")
    assert result["job"]["status"] == "succeeded", result["job"]
    before = _snapshot(instance.store.paths.root)
    candidates = _items(instance.store, "source_change")
    assert len(candidates) == 2
    assert {item["proposal"]["reason"] for item in candidates} == {"changed", "untracked"}
    assert all(item["evidence"]["source_id"] == source_id for item in candidates)
    assert _snapshot(instance.store.paths.root) == before
    instance.ingest_run(source)
    result = adapters.collect_proposals(instance.store)
    assert not [item for item in result["items"] if item["queue"] == "source_change"]
    assert "reconciliation_invalid_or_stale" in result["queues"]["source_change"]["reason"]


def test_duplicate_writer_guard_excludes_another_process_before_operation_write(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    manager = DuplicateCaseManager(store)
    script = (
        "import sys; from provelume.storage import InstanceStore; "
        "from provelume.duplicates import DuplicateCaseManager, DuplicateCaseBusyError; "
        "manager=DuplicateCaseManager(InstanceStore(sys.argv[1])); "
        "\ntry: manager.scan()\nexcept DuplicateCaseBusyError: sys.exit(73)\n"
    )
    with manager.hold_cases():
        before = _snapshot(store.paths.root)
        result = subprocess.run(
            [sys.executable, "-c", script, str(store.paths.root)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 73, result.stderr
        assert _snapshot(store.paths.root) == before
    assert manager.scan()["operation"]["status"] == "completed"


def test_scan_can_run_under_lifecycle_without_reacquiring_it(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    with InstanceLifecycleManager(store)._hold(purpose="synthetic-scheduler-outer"):
        assert DuplicateCaseManager(store).scan()["operation"]["status"] == "completed"


def test_scan_rejects_participants_changed_before_case_write(tmp_path, monkeypatch):
    instance, _, _ = _instance(tmp_path, contents=("same", "same"))
    manager = DuplicateCaseManager(instance.store)
    original = manager._case_record

    def change_canonical(**kwargs):
        record = original(**kwargs)
        participant = record["documents"][0]
        document = instance.store.read_canonical("documents", participant["document_id"])
        document["current_version_id"] = "ver_" + "f" * 32
        instance.store._atomic_json(
            instance.store.paths.canonical_dir("documents") / (document["id"] + ".json"), document
        )
        return record

    monkeypatch.setattr(manager, "_case_record", change_canonical)
    with pytest.raises(DuplicateScanStaleError):
        manager.scan()
    assert manager.list_cases() == []
    assert manager.operations.list(kind="duplicate.scan")[0]["status"] == "failed"


def test_snapshot_byte_budget_stops_before_reading_an_extra_record(tmp_path, monkeypatch):
    instance, _, _ = _instance(tmp_path)
    monkeypatch.setattr(adapters, "MAX_SNAPSHOT_BYTES", 1)
    reader = adapters._Reader(instance.store)
    path = next(instance.store.paths.canonical_dir("documents").glob("*.json"))
    assert reader.record(path, ("classification",)) is None
    assert reader.bytes_read == 0
    assert reader.reasons["classification"] == {"snapshot_byte_bound"}


def test_new_corrupt_submission_does_not_fall_back_to_legacy_as_current(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    identifier = "inbox_" + "a" * 32
    legacy = store.paths.root / "inbox" / "submissions"
    current = store.paths.state / "inbox" / "submissions"
    legacy.mkdir(parents=True)
    current.mkdir(parents=True)
    (legacy / (identifier + ".json")).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": identifier,
                "status": "failed",
                "ingestion_run_id": None,
            }
        ),
        encoding="utf-8",
    )
    (current / (identifier + ".json")).write_text("{", encoding="utf-8")
    result = adapters.collect_proposals(store)
    assert not result["items"]
    assert result["queues"]["intake"]["matched_count"] is None


def test_canonical_lineage_rejects_an_original_with_another_entity_id_type(tmp_path):
    instance, _, _ = _instance(tmp_path)
    store = instance.store
    original = store.list_canonical("originals")[0]
    (store.paths.canonical_dir("originals") / (original["id"] + ".json")).unlink()
    original["id"] = "doc_" + "f" * 32
    store._atomic_json(
        store.paths.canonical_dir("originals") / (original["id"] + ".json"), original
    )
    version = store.list_canonical("versions")[0]
    version["original_id"] = original["id"]
    store._atomic_json(store.paths.canonical_dir("versions") / (version["id"] + ".json"), version)
    result = adapters.collect_proposals(store)
    assert not result["items"]
    assert result["queues"]["classification"]["matched_count"] is None
    assert "record_identity_invalid" in result["queues"]["classification"]["reason"]


def test_two_ocr_recipes_remain_distinct_and_new_success_recovers_only_same_recipe(tmp_path):
    from test_ocr_execution import _fixture

    instance, manager, _, adapter, version_id = _fixture(tmp_path, fail_page_once=1)

    def run(languages, nonce):
        queued = manager.queue(version_id, mode="forced", languages=languages, rebuild_nonce=nonce)
        job = instance.scheduler.run_one(
            job_id=queued["job"]["id"],
            now=datetime.fromisoformat(queued["job"]["eligible_at"]).astimezone(UTC),
        )
        return job

    first = run(("eng",), "recipe-eng-first")
    adapter.failed_once = False
    second = run(("ita",), "recipe-ita-first")
    assert first["status"] == second["status"] == "retry_wait"
    candidates = _items(instance.store, "extraction_error")
    assert len(candidates) == 2
    assert len({row["evidence"]["derivation_key"] for row in candidates}) == 2
    adapter.failed_once = True
    recovered = run(("eng",), "recipe-eng-recovery")
    assert recovered["status"] == "succeeded"
    remaining = _items(instance.store, "extraction_error")
    assert len(remaining) == 1
    assert remaining[0]["evidence"]["job_id"] == second["id"]
