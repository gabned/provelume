from __future__ import annotations

import os
import subprocess

import pytest

from provelume.atomic_commit import AtomicCommitError
from provelume.instance_lifecycle import (
    InstanceLifecycleBusy,
    InstanceLifecycleError,
    InstanceLifecycleManager,
)
from provelume.review_authority import AUTHORITY_PATH, ReviewAuthority
from provelume.review_decisions import ReviewDecisions
from provelume.review_effects import ReviewConflict, ReviewStale, ReviewUnavailable
from provelume.review_runtime import recover_review_transactions_locked, review_transaction_factory
from provelume.storage import InstanceStore


def coordinator(store):
    authority = ReviewAuthority(store, {"placement": ("classify",), "routing": ("apply_rule",)})
    decisions = ReviewDecisions(
        store,
        [authority],
        authority_resolver=authority.resolve,
        transaction_factory=review_transaction_factory(store),
        mutation_guard=recover_review_transactions_locked,
    )
    return authority, decisions


def grant(mode="confirm-each", action="classify"):
    return {"mode": mode, "scope": {"subjects": ["*"], "actions": [action], "sources": []}}


def confirm(decisions, plan, request_id):
    return decisions.confirm(
        plan["domain"],
        plan["subject"],
        plan["action"],
        plan["parameters"],
        expected_plan_revision=plan["plan_revision"],
        expected_authority_revision=plan["authority_revision"],
        request_id=request_id,
    )


def test_explicit_scoped_authority_is_pure_until_confirm_and_replay_is_exact(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    authority, decisions = coordinator(store)
    assert authority.resolve("placement", "doc_" + "a" * 32, "classify")["mode"] == "disabled"
    plan = decisions.preview("capabilities", "placement", "configure", grant())
    assert not (store.paths.state / "review").exists()
    first = confirm(decisions, plan, "grant-placement-001")
    assert first["receipt"]["status"] == "committed"
    assert authority.resolve("placement", "doc_" + "a" * 32, "classify")["mode"] == "confirm-each"
    replay = confirm(decisions, plan, "grant-placement-001")
    assert replay["replayed"] is True
    assert replay["receipt"] == first["receipt"]
    revoked = decisions.preview("capabilities", "placement", "configure", grant("disabled"))
    with pytest.raises(ReviewConflict):
        confirm(decisions, revoked, "grant-placement-001")
    confirm(decisions, revoked, "revoke-placement-001")
    assert authority.resolve("placement", "doc_" + "a" * 32, "classify")["mode"] == "disabled"
    with pytest.raises(ReviewStale):
        confirm(decisions, plan, "old-grant-002")


def test_identity_changing_automatic_grant_and_corrupt_authority_fail_closed(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    authority, decisions = coordinator(store)
    with pytest.raises(ReviewUnavailable):
        decisions.preview("capabilities", "placement", "configure", grant("controlled-automatic"))
    assert not (store.paths.state / "review").exists()
    store._atomic_json(store.paths.root / AUTHORITY_PATH, {"schema_version": 99})
    with pytest.raises(ReviewUnavailable):
        authority.resolve("placement", "doc_" + "a" * 32, "classify")


def test_lifecycle_writer_rolls_back_partial_review_before_reading_it(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    target = store.paths.state / "review" / "synthetic.json"
    before, candidate = b'{"synthetic":"before"}', b'{"synthetic":"partial"}'
    store._atomic_bytes(target, before)
    transaction = review_transaction_factory(store)("review_" + "a" * 32)
    transaction.add("state/review/synthetic.json", candidate, immutable=False)
    stage, _ = transaction._prepare()
    store._atomic_bytes(target, candidate)
    authority, _ = coordinator(store)
    with pytest.raises(ReviewUnavailable):
        authority.read()
    assert target.read_bytes() == candidate and stage.exists()
    with InstanceLifecycleManager(store)._hold(purpose="synthetic-unrelated-writer"):
        assert target.read_bytes() == before
        assert not stage.exists()
    assert recover_review_transactions_locked(store) is None


@pytest.mark.parametrize("error", [InstanceLifecycleBusy, AtomicCommitError])
def test_routing_failure_does_not_hide_already_committed_intake(tmp_path, monkeypatch, error):
    from provelume.service import ProvelumeInstance

    source = tmp_path / "input"
    source.mkdir()
    (source / "note.txt").write_text("Synthetic retained intake", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    def unavailable(document_id):
        raise error()

    monkeypatch.setattr(instance.review_routing, "candidates", unavailable)
    result = instance.ingest_run(source)
    assert result["run"]["status"] == "completed"
    assert len(result["acquisitions"]) == 1
    assert result["review_routing"][0]["status"] == "review_required"
    assert len(instance.store.list_canonical("documents")) == 1
    assert len(instance.store.list_canonical("acquisitions")) == 1


@pytest.mark.parametrize("location", ["control", "transactions", "stage"])
def test_recovery_rejects_directory_links_and_preserves_external_sentinel(tmp_path, location):
    store = InstanceStore.initialise(tmp_path / "instance")
    control = InstanceLifecycleManager(store).control_root
    target = tmp_path / "external-synthetic"
    target.mkdir()
    (target / "review-orphan").mkdir()
    sentinel = target / "review-orphan" / "sentinel"
    sentinel.write_bytes(b"Synthetic data outside the recovery root must survive")
    link = {"control": control, "transactions": control / "transactions",
            "stage": control / "transactions" / "review-orphan"}[location]
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(AtomicCommitError):
            recover_review_transactions_locked(store)
        with (
            pytest.raises((InstanceLifecycleError, AtomicCommitError)),
            InstanceLifecycleManager(store)._hold(purpose="synthetic-linked-review"),
        ):
            pytest.fail("A linked recovery tree must not admit a writer")
        assert sentinel.read_bytes() == b"Synthetic data outside the recovery root must survive"
        assert not (target / "lifecycle.lock.json").exists()
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


def test_authority_rejects_unconfirmed_mode_change_and_lost_history(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    authority, decisions = coordinator(store)
    plan = decisions.preview("capabilities", "routing", "configure",
                             grant("proposal-only", "apply_rule"))
    result = confirm(decisions, plan, "synthetic-routing-grant")
    path = store.paths.root / AUTHORITY_PATH
    original = path.read_bytes()
    state = authority.read()
    state["grants"]["routing"]["mode"] = "controlled-automatic"
    store._atomic_json(path, state)
    with pytest.raises(ReviewUnavailable, match="confirmed history"):
        authority.resolve("routing", "doc_" + "a" * 32, "apply_rule")
    store._atomic_bytes(path, original)
    history = store.paths.root / result["receipt"]["history_ref"]
    history.unlink()
    with pytest.raises(ReviewUnavailable, match="confirmed history"):
        authority.read()


def test_deep_validation_rejects_receipt_with_wrong_filename_without_content_change(tmp_path):
    from provelume.service import ProvelumeInstance

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    plan = instance.review_decisions.preview("capabilities", "placement", "configure", grant())
    result = confirm(instance.review_decisions, plan, "synthetic-renamed-receipt")
    original = instance.store.paths.state / "review/receipts" / (result["receipt"]["id"] + ".json")
    original.with_name("review_" + "f" * 32 + ".json").write_bytes(original.read_bytes())
    report = InstanceLifecycleManager(instance.store).validate(deep=True)
    assert report["status"] == "invalid"
    assert any(row["code"] == "review_state_invalid" and "identity" in row["message"]
               for row in report["errors"])
