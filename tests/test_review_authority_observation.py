from __future__ import annotations

import copy
import json

import pytest

from provelume import review_authority as authority_module
from provelume.review_authority import AUTHORITY_PATH, ReviewAuthority
from provelume.review_decisions import ReviewDecisions
from provelume.review_effects import ReviewUnavailable
from provelume.review_runtime import recover_review_transactions_locked, review_transaction_factory
from provelume.storage import InstanceStore


def test_authority_never_validates_changed_history_against_an_earlier_digest(tmp_path, monkeypatch):
    store = InstanceStore.initialise(tmp_path / "instance")
    authority = ReviewAuthority(store, {"routing": ("apply_rule",)})
    decisions = ReviewDecisions(
        store, [authority], authority_resolver=authority.resolve,
        transaction_factory=review_transaction_factory(store),
        mutation_guard=recover_review_transactions_locked,
    )
    plan = decisions.preview("capabilities", "routing", "configure", {
        "mode": "proposal-only",
        "scope": {"subjects": ["*"], "actions": ["apply_rule"], "sources": []},
    })
    result = decisions.confirm(
        plan["domain"], plan["subject"], plan["action"], plan["parameters"],
        expected_plan_revision=plan["plan_revision"],
        expected_authority_revision=plan["authority_revision"],
        request_id="synthetic-history-observation",
    )
    history_ref = result["receipt"]["history_ref"]
    history_path = store.paths.root / history_ref
    original = history_path.read_bytes()
    replacement = json.loads(original)
    changed_state = copy.deepcopy(authority.read())
    changed_state["grants"]["routing"]["mode"] = "controlled-automatic"
    replacement["after"] = changed_state
    store._atomic_json(store.paths.root / AUTHORITY_PATH, changed_state)
    real_read_bytes = authority_module.read_bytes

    def change_after_observation(current_store, relative, **kwargs):
        raw = real_read_bytes(current_store, relative, **kwargs)
        if relative == history_ref:
            assert raw == original
            store._atomic_json(history_path, replacement)
        return raw

    monkeypatch.setattr(authority_module, "read_bytes", change_after_observation)
    with pytest.raises(ReviewUnavailable, match="confirmed history"):
        authority.resolve("routing", "doc_" + "a" * 32, "apply_rule")
