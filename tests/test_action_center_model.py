from __future__ import annotations

import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from types import ModuleType

import pytest

from provelume.action_center import ActionCenter
from provelume.action_center_model import (
    QUEUES,
    ActionCenterBusy,
    ActionCenterConflict,
    ActionCenterDenied,
    ActionCenterError,
    ActionCenterStale,
    ActionCenterUnavailable,
    digest,
    make_proposal,
    queue_observation,
)
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore


def files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def candidate(queue="extraction_error", producer="job_one", *, evidence=None):
    return make_proposal(
        queue,
        producer,
        proposal={
            "kind": "extraction_error",
            "reason": "extraction_failed",
            "confidence": None,
            "impact": "records_inspection_only",
            "reversible": False,
            "choices": [],
        },
        evidence=evidence or {"job_id": producer, "attempt": 1},
        allowed_actions=["reject_proposal"] if "duplicate" in queue else ["acknowledge_evidence"],
    )


@pytest.fixture
def center(tmp_path, monkeypatch):
    store = InstanceStore.initialise(tmp_path / "instance")
    collection = {
        "items": [candidate()],
        "queues": {queue: queue_observation(queue) for queue in QUEUES},
    }
    adapter = ModuleType("provelume.action_center_adapters")
    adapter.collect_proposals = lambda store: copy.deepcopy(collection)
    monkeypatch.setitem(sys.modules, adapter.__name__, adapter)
    return ActionCenter(store), collection


def test_pure_read_and_page_independent_identity_counts(center, monkeypatch):
    manager, collection = center
    collection["items"] = [candidate(producer=f"job_{index}") for index in range(3)]
    before = files(manager.store.paths.root.parent)

    def forbidden(*args, **kwargs):
        pytest.fail("a read acquired a mutation lock")

    monkeypatch.setattr(InstanceLifecycleManager, "_hold", forbidden)
    first = manager.snapshot(limit=1)
    second = manager.snapshot(limit=1, offset=1)
    assert first["complete"] and first["count_relation"] == "exact"
    assert first["total"] == first["observed_count"] == 3
    assert len(first["items"]) == 1 and first["revision"] == second["revision"]
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert manager.get_item(first["items"][0]["id"]) == first["items"][0]
    assert manager.authority()["revision"] == 0
    assert files(manager.store.paths.root.parent) == before
    assert not manager.root.exists()


def test_revision_does_not_follow_presentation_or_poll_time():
    semantic = {"version_id": "ver_exact", "sha256": "1" * 64, "error_code": "failed"}
    first = make_proposal(
        "intake", "run_one", proposal={"title": "English"}, evidence={}, revision_inputs=semantic
    )
    second = make_proposal(
        "intake",
        "run_one",
        proposal={"title": "Italiano"},
        evidence={"observed_at": "later"},
        revision_inputs=semantic,
    )
    assert first["input_revision"] == second["input_revision"]
    assert (
        make_proposal(
            "intake",
            "run_one",
            proposal={},
            evidence={},
            revision_inputs={**semantic, "sha256": "2" * 64},
        )["input_revision"]
        != first["input_revision"]
    )


def test_incomplete_observation_cannot_authorize_or_claim_total(center):
    manager, collection = center
    collection["queues"]["extraction_error"] = queue_observation(
        "extraction_error", status="partial", observed_count=1, reason="record_bound", bound=500
    )
    view = manager.snapshot()
    assert not view["complete"] and view["total"] is None
    assert view["observed_count"] == 1 and not view["items"][0]["allowed_actions"]
    item = view["items"][0]
    with pytest.raises(ActionCenterUnavailable):
        manager.decide(item["id"], item["revision"], "acknowledge_evidence", "incomplete", 0)
    assert not manager.path.exists()
    with pytest.raises(ActionCenterError):
        queue_observation("intake", status="partial", count_relation="exact")


def test_acknowledgement_persists_inspection_and_exact_replay(center):
    manager, collection = center
    item = manager.snapshot()["items"][0]
    canonical_before = files(manager.store.paths.canonical_dir("documents"))
    first = manager.decide(item["id"], item["revision"], "acknowledge_evidence", "inspect_one", 0)
    receipt = first["receipt"]
    assert receipt["review_state"] == "accepted"
    assert receipt["impact"] == "records_inspection_only" and receipt["canonical_mutation"] is False
    assert manager.snapshot()["total"] == 0
    assert manager.get_item(item["id"])["review_state"] == "accepted"
    restarted = ActionCenter(manager.store)
    same = restarted.decide(item["id"], item["revision"], "acknowledge_evidence", "inspect_one", 0)
    assert same["replayed"] and same["receipt"] == receipt
    assert len(json.loads(manager.path.read_bytes())["receipts"]) == 1
    assert collection["items"][0]["evidence"]["attempt"] == 1
    assert files(manager.store.paths.canonical_dir("documents")) == canonical_before
    with pytest.raises(ActionCenterConflict):
        manager.decide(item["id"], item["revision"], "reject_proposal", "inspect_one", 0)
    with pytest.raises(ActionCenterConflict):
        manager.decide(item["id"], item["revision"], "acknowledge_evidence", "another_request", 0)


def test_upstream_revision_supersedes_receipt_without_erasing_it(center):
    manager, collection = center
    old = manager.snapshot()["items"][0]
    manager.decide(old["id"], old["revision"], "acknowledge_evidence", "old_attempt", 0)
    collection["items"] = [candidate(evidence={"job_id": "job_one", "attempt": 2})]
    current = manager.get_item(old["id"])
    assert current["id"] == old["id"] and current["revision"] != old["revision"]
    assert current["review_state"] == "awaiting_review"
    assert current["history"][0]["superseded"]
    before = manager.path.read_bytes()
    with pytest.raises(ActionCenterStale):
        manager.decide(old["id"], old["revision"], "acknowledge_evidence", "stale", 0)
    assert manager.path.read_bytes() == before


def test_authority_revision_scope_and_unsupported_autonomy(center):
    manager, _ = center
    item = manager.snapshot()["items"][0]
    result = manager.set_authority("extraction_error", "proposal-only", 0, "authority_one")
    assert result["authority"]["revision"] == 1
    assert manager.get_item(item["id"])["allowed_actions"] == []
    with pytest.raises(ActionCenterStale):
        manager.decide(item["id"], item["revision"], "acknowledge_evidence", "old_authority", 0)
    with pytest.raises(ActionCenterDenied):
        manager.decide(item["id"], item["revision"], "acknowledge_evidence", "denied", 1)
    before = manager.path.read_bytes()
    with pytest.raises(ActionCenterDenied):
        manager.set_authority("extraction_error", "controlled-automatic", 1, "automatic")
    with pytest.raises(ActionCenterDenied):
        manager.set_authority(
            "intake", "disabled", 1, "foreign", {"kind": "instance", "id": "inst_" + "f" * 32}
        )
    assert manager.path.read_bytes() == before
    assert manager.set_authority("extraction_error", "proposal-only", 0, "authority_one")[
        "replayed"
    ]


def test_no_intake_rejection_or_domain_effect_can_be_invented(center):
    manager, collection = center
    collection["items"] = [candidate(queue="intake")]
    item = manager.snapshot()["items"][0]
    with pytest.raises(ActionCenterDenied):
        manager.decide(item["id"], item["revision"], "reject_proposal", "reject_intake", 0)
    with pytest.raises(ActionCenterDenied):
        manager.decide(item["id"], item["revision"], "merge_documents", "merge", 0)
    assert not manager.path.exists()


def test_duplicate_decision_recollects_after_real_guard_boundary(center, monkeypatch):
    from provelume.duplicates import DuplicateCaseManager

    manager, collection = center
    collection["items"] = [candidate(queue="exact_duplicate", producer="dup_one")]
    item = manager.snapshot()["items"][0]

    @contextmanager
    def changed_before_guard(self):
        collection["items"] = [
            candidate(
                queue="exact_duplicate", producer="dup_one", evidence={"members": ["changed"]}
            )
        ]
        yield

    monkeypatch.setattr(DuplicateCaseManager, "hold_cases", changed_before_guard, raising=False)
    with pytest.raises(ActionCenterStale):
        manager.decide(item["id"], item["revision"], "reject_proposal", "changed_case", 0)
    assert not manager.path.exists()


def test_two_concurrent_decisions_cannot_both_commit(center):
    manager, _ = center
    item = manager.snapshot()["items"][0]
    barrier = Barrier(2)

    def attempt(index):
        barrier.wait()
        try:
            return manager.decide(
                item["id"], item["revision"], "acknowledge_evidence", f"race_{index}", 0
            )
        except (ActionCenterBusy, ActionCenterConflict) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [0, 1]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert len(json.loads(manager.path.read_bytes())["receipts"]) == 1


def test_atomic_write_failure_never_commits_acceptance(center, monkeypatch):
    manager, _ = center
    item = manager.snapshot()["items"][0]

    def fail(*args, **kwargs):
        raise OSError("synthetic disk write failure")

    monkeypatch.setattr(manager.store, "_atomic_json", fail)
    with pytest.raises(ActionCenterUnavailable):
        manager.decide(item["id"], item["revision"], "acknowledge_evidence", "write_failure", 0)
    assert not manager.path.exists()
    assert manager.get_item(item["id"])["review_state"] == "awaiting_review"


def test_corrupt_state_is_degraded_not_empty_success(center):
    manager, _ = center
    manager.root.mkdir()
    manager.path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
    before = manager.path.read_bytes()
    view = manager.snapshot()
    assert not view["complete"] and view["total"] is None
    assert all(value["status"] == "invalid" for value in view["queues"].values())
    with pytest.raises(ActionCenterUnavailable):
        manager.authority()
    assert manager.path.read_bytes() == before


def test_manual_version_proposal_exact_lineage_restart_and_supersession(center, tmp_path):
    manager, collection = center
    collection["items"] = []
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("first exact input\n", encoding="utf-8")
    (source / "b.txt").write_text("second exact input\n", encoding="utf-8")
    instance = ProvelumeInstance(manager.store.paths.root)
    instance.ingest_run(source)
    documents = instance.store.list_canonical("documents")
    versions = [
        instance.store.read_canonical("versions", document["current_version_id"])
        for document in documents
    ]
    alternatives = [
        {
            "version_id": version["id"],
            "original_id": version["original_id"],
            "sha256": version["content_hash"],
        }
        for version in versions
    ]
    target = documents[0]
    before = files(instance.store.paths.canonical_dir("documents"))
    originals = files(instance.store.paths.originals)
    result = manager.propose_version_conflict(
        target["id"],
        target["current_version_id"],
        alternatives,
        "competing_versions",
        "proposal_one",
        0,
    )
    restarted = ActionCenter(manager.store)
    item = restarted.get_item(result["item_id"])
    assert item["queue"] == "version_conflict" and item["review_state"] == "awaiting_review"
    assert item["proposal"]["confidence"] is None and item["allowed_actions"] == ["reject_proposal"]
    assert files(instance.store.paths.canonical_dir("documents")) == before
    assert files(instance.store.paths.originals) == originals
    assert restarted.propose_version_conflict(
        target["id"],
        target["current_version_id"],
        alternatives,
        "competing_versions",
        "proposal_one",
        0,
    )["replayed"]
    with pytest.raises(ActionCenterError):
        manager.propose_version_conflict(
            target["id"],
            target["current_version_id"],
            [alternatives[0]] * 2,
            "competing_versions",
            "invalid_alternatives",
            0,
        )
    (source / target["locator"]).write_text("a genuinely new current input\n", encoding="utf-8")
    instance.ingest_run(source)
    assert manager.get_item(result["item_id"])["review_state"] == "superseded"
    assert not manager.get_item(result["item_id"])["allowed_actions"]


@pytest.mark.parametrize(
    "queue,state,limit,offset",
    [
        ("unknown", "all", 100, 0),
        (None, "completed", 100, 0),
        (None, "all", True, 0),
        (None, "all", 501, 0),
        (None, "all", 100, -1),
    ],
)
def test_closed_query_bounds(center, queue, state, limit, offset):
    manager, _ = center
    with pytest.raises(ActionCenterError):
        manager.snapshot(queue, state, limit, offset)


def test_model_rejects_non_json_or_external_links():
    with pytest.raises(ActionCenterError):
        make_proposal("intake", "run", proposal={}, evidence={"confidence": float("nan")})
    with pytest.raises(ActionCenterError):
        make_proposal(
            "intake", "run", proposal={}, evidence={}, domain_links=[{"href": "//outside.test"}]
        )
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


def test_retained_decision_detail_survives_missing_producer(center):
    manager, collection = center
    item = manager.snapshot()["items"][0]
    receipt = manager.decide(item["id"], item["revision"], "acknowledge_evidence", "retained", 0)[
        "receipt"
    ]
    collection["items"] = []
    historical = manager.get_item(item["id"])
    assert historical["review_state"] == "accepted" and not historical["producer_available"]
    assert historical["proposal"]["reason"] == "producer_unavailable"
    assert historical["history"][0]["id"] == receipt["id"]
    assert manager.snapshot(state="accepted")["total"] == 1
    assert manager.snapshot()["total"] == 0 and historical["allowed_actions"] == []


def test_receipt_cannot_claim_an_unperformed_domain_effect(center):
    manager, _ = center
    item = manager.snapshot()["items"][0]
    manager.decide(item["id"], item["revision"], "acknowledge_evidence", "tamper", 0)
    state = json.loads(manager.path.read_bytes())
    state["receipts"]["tamper"]["impact"] = "extraction_fixed"
    manager.path.write_text(json.dumps(state), encoding="utf-8")
    assert not manager.snapshot()["complete"]
    with pytest.raises(ActionCenterUnavailable):
        manager.authority()


def test_real_producers_share_snapshot_detail_and_guarded_rejection(tmp_path):
    from provelume.duplicates import DuplicateCaseManager

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = tmp_path / "source"
    source.mkdir()
    for name in ("one.txt", "two.txt"):
        (source / name).write_text("same exact synthetic input\n", encoding="utf-8")
    (source / "large.txt").write_text("x" * 200, encoding="utf-8")
    run = instance.ingest_run(source, max_file_bytes=64)
    assert run["run"]["status"] == "completed_with_errors"
    DuplicateCaseManager(instance.store).scan()
    manager = ActionCenter(instance.store)
    before = files(instance.store.paths.root)
    view = manager.snapshot()
    assert set(view["queues"]) == set(QUEUES)
    assert view["queues"]["classification"]["count"] == 2
    assert view["queues"]["exact_duplicate"]["count"] == 1
    assert view["queues"]["intake"]["observed_count"] >= 1
    duplicate = next(item for item in view["items"] if item["queue"] == "exact_duplicate")
    assert manager.get_item(duplicate["id"])["revision"] == duplicate["revision"]
    assert files(instance.store.paths.root) == before
    knowledge = files(instance.store.paths.canonical_dir("documents").parent)
    original = files(instance.store.paths.originals)
    result = manager.decide(
        duplicate["id"], duplicate["revision"], "reject_proposal", "real_reject", 0
    )
    assert result["receipt"]["review_state"] == "rejected"
    assert result["receipt"]["impact"] == "rejects_proposal_only"
    assert files(instance.store.paths.canonical_dir("documents").parent) == knowledge
    assert files(instance.store.paths.originals) == original
    assert manager.snapshot(queue="exact_duplicate")["total"] == 0
    assert manager.snapshot(queue="exact_duplicate", state="rejected")["total"] == 1
    assert DuplicateCaseManager(instance.store).get_case(duplicate["producer_id"])["current"]


def test_source_authority_restricts_only_its_scope(center):
    from provelume.domain import Source
    from provelume.storage import utc_now

    manager, collection = center
    first_source, second_source = "src_" + "1" * 32, "src_" + "2" * 32
    for source_id in (first_source, second_source):
        manager.store.write_source(
            Source(id=source_id, kind="filesystem", name="Synthetic", created_at=utc_now())
        )
    collection["items"] = [
        candidate(producer="first", evidence={"source_id": first_source}),
        candidate(producer="second", evidence={"source_id": second_source}),
    ]
    manager.set_authority(
        "extraction_error", "disabled", 0, "source_rule", {"kind": "source", "id": first_source}
    )
    items = {item["producer_id"]: item for item in manager.snapshot()["items"]}
    assert items["first"]["allowed_actions"] == []
    assert items["second"]["allowed_actions"] == ["acknowledge_evidence"]
    with pytest.raises(ActionCenterDenied):
        manager.decide(
            items["first"]["id"],
            items["first"]["revision"],
            "acknowledge_evidence",
            "restricted",
            1,
        )
    assert (
        manager.decide(
            items["second"]["id"],
            items["second"]["revision"],
            "acknowledge_evidence",
            "permitted",
            1,
        )["receipt"]["review_state"]
        == "accepted"
    )


def test_duplicate_busy_has_public_error_without_receipt(center):
    from provelume.duplicates import DuplicateCaseManager

    manager, collection = center
    collection["items"] = [candidate(queue="exact_duplicate", producer="case")]
    item = manager.snapshot()["items"][0]
    with (
        DuplicateCaseManager(manager.store).hold_cases(),
        pytest.raises(ActionCenterBusy),
    ):
        manager.decide(item["id"], item["revision"], "reject_proposal", "busy", 0)
    assert not manager.path.exists()


def test_invalid_canonical_selectors_are_rejected_before_read(center, monkeypatch):
    manager, _ = center

    def forbidden(*args, **kwargs):
        pytest.fail("unvalidated selector reached canonical storage")

    monkeypatch.setattr(manager.store, "read_canonical", forbidden)
    with pytest.raises(ActionCenterError):
        manager.propose_version_conflict(
            "../outside", "ver_" + "1" * 32, [], "competing_versions", "unsafe", 0
        )
    with pytest.raises(ActionCenterError):
        manager.set_authority(
            "intake", "disabled", 0, "unsafe_scope", {"kind": "source", "id": "../outside"}
        )
    assert not manager.root.exists()
