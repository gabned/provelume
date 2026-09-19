from __future__ import annotations

import pytest

from provelume.action_center import ActionCenter
from provelume.assurance import OriginalAssuranceManager
from provelume.duplicates import DuplicateCaseManager
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.instance_validation import inspect_instance
from provelume.portable_transfer import PortableInstanceTransfer
from provelume.review_authority import ReviewAuthority
from provelume.review_decisions import ReviewDecisions
from provelume.review_documents import DuplicateDecisionProvider
from provelume.review_effects import ReviewError, ReviewStale, ReviewUnavailable
from provelume.review_integrity import CAPABILITIES
from provelume.review_runtime import recover_review_transactions_locked, review_transaction_factory
from provelume.service import ProvelumeInstance


def confirm(coordinator, plan, request_id):
    return coordinator.confirm(
        plan["domain"],
        plan["subject"],
        plan["action"],
        plan["parameters"],
        expected_plan_revision=plan["plan_revision"],
        expected_authority_revision=plan["authority_revision"],
        request_id=request_id,
    )


def seeded(tmp_path):
    documents = tmp_path / "input"
    documents.mkdir()
    (documents / "a.txt").write_text("Exact source content", encoding="utf-8")
    (documents / "b.txt").write_text("Exact source content", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest_run(documents)
    scan = DuplicateCaseManager(instance.store).scan()
    case = scan["exact"][0]
    authority = ReviewAuthority(instance.store, CAPABILITIES)
    coordinator = ReviewDecisions(
        instance.store,
        [authority, DuplicateDecisionProvider(instance.store)],
        authority_resolver=authority.resolve,
        transaction_factory=review_transaction_factory(instance.store),
        mutation_guard=recover_review_transactions_locked,
    )
    plan = coordinator.preview(
        "capabilities",
        "duplicates",
        "configure",
        {
            "mode": "confirm-each",
            "scope": {
                "subjects": [case["id"]],
                "actions": sorted(CAPABILITIES["duplicates"]),
                "sources": [],
            },
        },
    )
    confirm(coordinator, plan, "enable-duplicates")
    return instance, coordinator, case


def test_exact_relation_is_retained_without_merging_and_stales_competing_choice(tmp_path):
    instance, coordinator, case = seeded(tmp_path)
    before = instance.store.knowledge_fingerprint()
    plan = coordinator.preview("duplicates", case["id"], "link_exact", {})
    alternate = coordinator.preview("duplicates", case["id"], "keep_separate", {})
    result = confirm(coordinator, plan, "link-exact")
    assert result["receipt"]["canonical_mutation"] is False
    assert instance.store.knowledge_fingerprint() == before
    assert result["result"]["decision"] == "link_exact"
    assert confirm(coordinator, plan, "link-exact")["replayed"] is True
    with pytest.raises(ReviewStale):
        confirm(coordinator, alternate, "stale-separate")
    fresh = coordinator.preview("duplicates", case["id"], "keep_separate", {})
    confirm(coordinator, fresh, "separate")
    assert instance.store.knowledge_fingerprint() == before


def test_new_target_version_retains_all_identities_and_explicit_origin(tmp_path):
    instance, coordinator, case = seeded(tmp_path)
    store = instance.store
    left, right = case["documents"]
    acquisitions = store.list_canonical("acquisitions")
    old_versions = store.list_canonical("versions")
    original_bytes = {
        row["id"]: store.original_bytes(row["id"]) for row in store.list_canonical("originals")
    }
    plan = coordinator.preview(
        "duplicates",
        case["id"],
        "new_version",
        {
            "target_document_id": left["document_id"],
            "version_id": right["version_id"],
        },
    )
    result = confirm(coordinator, plan, "version-choice")
    identifier = result["result"]["version_id"]
    assert identifier not in {row["id"] for row in old_versions}
    assert (
        store.read_canonical("documents", left["document_id"])["current_version_id"] == identifier
    )
    assert (
        store.read_canonical("documents", right["document_id"])["current_version_id"]
        == right["version_id"]
    )
    assert store.list_canonical("acquisitions") == acquisitions
    for row in old_versions:
        assert store.read_canonical("versions", row["id"]) == row
    assert {
        identifier: store.original_bytes(identifier) for identifier in original_bytes
    } == original_bytes
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    assurance = OriginalAssuranceManager(store).check()
    assert not any(
        row["code"] in {"version_without_acquisition", "review_origin_invalid"}
        for row in assurance["findings"]
    )
    origin_path = store.paths.canonical_dir("review-origins") / (identifier + ".json")
    origin_path.unlink()  # This test-created Instance is disposable.
    assert inspect_instance(instance.root, deep=True)["status"] == "invalid"


def test_original_tampering_denies_reviewed_version_without_receipt(tmp_path):
    instance, coordinator, case = seeded(tmp_path)
    left, right = case["documents"]
    version = instance.store.read_canonical("versions", right["version_id"])
    original = instance.store.read_canonical("originals", version["original_id"])
    (instance.root / original["storage_ref"]).write_bytes(b"synthetic corrupt bytes")
    with pytest.raises((ReviewUnavailable, ReviewError)):
        coordinator.preview(
            "duplicates",
            case["id"],
            "new_version",
            {
                "target_document_id": left["document_id"],
                "version_id": right["version_id"],
            },
        )
    assert len(coordinator.history()["items"]) == 1  # Only the explicit capability grant.


def test_manual_version_conflict_selects_owned_version_without_creating_acquisition(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    target_file = source / "target.txt"
    target_file.write_text("First retained version", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest_run(source)
    target_file.write_text("Second distinct retained version", encoding="utf-8")
    instance.ingest_run(source)
    store = instance.store
    document = store.list_canonical("documents")[0]
    versions = sorted(store.list_canonical("versions"), key=lambda row: row["sequence"])
    assert len(versions) == 2
    alternatives = [
        {"version_id": row["id"], "original_id": row["original_id"], "sha256": row["content_hash"]}
        for row in versions
    ]
    proposal = ActionCenter(store).propose_version_conflict(
        document["id"],
        document["current_version_id"],
        alternatives,
        "manual_comparison",
        "compare-versions",
        0,
    )
    coordinator = instance.review_decisions
    grant = coordinator.preview(
        "capabilities",
        "versions",
        "configure",
        {
            "mode": "confirm-each",
            "scope": {
                "subjects": [proposal["proposal_id"]],
                "actions": ["new_version", "select_current"],
                "sources": [],
            },
        },
    )
    confirm(coordinator, grant, "enable-version-choice")
    acquisitions = store.list_canonical("acquisitions")
    plan = coordinator.preview(
        "versions",
        proposal["proposal_id"],
        "select_current",
        {
            "version_id": versions[0]["id"],
        },
    )
    result = confirm(coordinator, plan, "choose-existing")
    assert result["result"]["version_id"] == versions[0]["id"]
    assert (
        store.read_canonical("documents", document["id"])["current_version_id"] == versions[0]["id"]
    )
    assert store.list_canonical("acquisitions") == acquisitions
    assert len(store.list_canonical("versions")) == 2
    assert store.list_canonical("review-origins") == []
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_document_effect_preparation_reads_only_bound_plan(tmp_path, monkeypatch):
    from provelume import review_documents

    instance, coordinator, case = seeded(tmp_path)
    left, right = case["documents"]
    plan = coordinator.preview(
        "duplicates",
        case["id"],
        "new_version",
        {
            "target_document_id": left["document_id"],
            "version_id": right["version_id"],
        },
    )

    def unexpected_read(*args, **kwargs):
        raise AssertionError("prepare must not observe new input")

    monkeypatch.setattr(review_documents, "read_bytes", unexpected_read)
    monkeypatch.setattr(review_documents, "read_json", unexpected_read)
    effect = DuplicateDecisionProvider(instance.store).prepare(
        plan,
        request_id="pure-prepare",
        principal="local_browser",
        recorded_at="2026-09-19T22:00:00+00:00",
    )
    assert len(effect.writes) == 4


def test_reviewed_origin_and_history_survive_backup_and_portable_rebuild(tmp_path):
    instance, coordinator, case = seeded(tmp_path)
    left, right = case["documents"]
    plan = coordinator.preview(
        "duplicates",
        case["id"],
        "new_version",
        {
            "target_document_id": left["document_id"],
            "version_id": right["version_id"],
        },
    )
    confirm(coordinator, plan, "version-to-preserve")

    def retained(root):
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for sub in ("state/review", "knowledge/review-origins")
            for path in (root / sub).rglob("*")
            if path.is_file()
        }

    before = retained(instance.root)
    assert before
    lifecycle = InstanceLifecycleManager(instance.store)
    backup = lifecycle.backup(destination=tmp_path / "review-backup.zip")
    lifecycle.restore(backup["archive"])
    assert retained(instance.root) == before
    portable = tmp_path / "review-portable.zip"
    PortableInstanceTransfer(instance.store).export(portable, derived_state="rebuild")
    destination = ProvelumeInstance.initialise(tmp_path / "destination")
    PortableInstanceTransfer(destination.store).import_bundle(portable)
    assert retained(destination.root) == before
    assert inspect_instance(destination.root, deep=True)["status"] == "valid"
