from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from provelume.action_center import ActionCenter
from provelume.action_center_model import digest
from provelume.domain import Document
from provelume.instance_lifecycle import InstanceLifecycleBusy, InstanceLifecycleManager
from provelume.review_decisions import ReviewDecisions
from provelume.review_effects import (
    ABSENT,
    PreparedEffect,
    PreparedWrite,
    ReviewConflict,
    ReviewDenied,
    ReviewError,
    ReviewStale,
    ReviewUnavailable,
)
from provelume.review_routing import PlacementProvider, RoutingProvider
from provelume.review_runtime import recover_review_transactions_locked, review_transaction_factory
from provelume.service import ProvelumeInstance


@pytest.fixture
def review(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.txt").write_text("Synthetic review first document.", encoding="utf-8")
    (source / "two.txt").write_text("Synthetic review second document.", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Review fixture")
    instance.ingest(source, source_name="Synthetic source")
    area = instance.create_hierarchy_node("area", "First")
    other = instance.create_hierarchy_node("project", "Second")
    documents = sorted(instance.list_documents(), key=lambda item: item["title"])
    authority = {
        "revision": digest("authority-1"),
        "mode": "confirm-each",
        "scope": {"kind": "instance"},
        "automatic_allowed": False,
    }
    routing = RoutingProvider(instance.store)
    decisions = ReviewDecisions(
        instance.store,
        [PlacementProvider(instance.store), routing],
        authority_resolver=lambda *args: dict(authority),
        transaction_factory=review_transaction_factory(instance.store),
        mutation_guard=recover_review_transactions_locked,
    )
    return instance, decisions, routing, authority, area, other, documents, source


def _confirm(decisions, plan, request_id, principal="local_browser"):
    return decisions.confirm(
        plan["domain"],
        plan["subject"],
        plan["action"],
        plan["parameters"],
        expected_plan_revision=plan["plan_revision"],
        expected_authority_revision=plan["authority_revision"],
        request_id=request_id,
        principal=principal,
    )


def _placement(decisions, document, node):
    return decisions.preview(
        "placement",
        document["id"],
        "classify",
        {"primary_node_id": node["id"], "secondary_node_ids": []},
    )


def _save_rule(decisions, document, area, *, key="a", automatic=True, prefix=""):
    rule_id = "routing_" + key * 32
    plan = decisions.preview(
        "routing",
        rule_id,
        "save_rule",
        {
            "source_id": document["source_id"],
            "path_prefix": prefix,
            "primary_node_id": area["id"],
            "secondary_node_ids": [],
            "automatic_enabled": automatic,
        },
    )
    _confirm(decisions, plan, "save-" + key)
    return rule_id


def _bytes(root: Path):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_correct_existing_placement_retains_original_versions_old_edges_and_replays(review):
    instance, decisions, _routing, _authority, area, other, documents, _source = review
    original = _bytes(instance.store.paths.originals)
    first = _confirm(decisions, _placement(decisions, documents[0], area), "first")
    old_edges = {x["id"] for x in instance.store.list_canonical("provenance")}
    versions = _bytes(instance.store.paths.canonical_dir("versions"))
    second_plan = _placement(decisions, documents[0], other)
    second = _confirm(decisions, second_plan, "second")
    replay = _confirm(decisions, second_plan, "second")
    assert replay["replayed"] and replay["receipt"] == second["receipt"]
    assert first["receipt"]["history_ref"] != second["receipt"]["history_ref"]
    assert (
        instance.hierarchy.get_classification(documents[0]["id"])["primary_node_id"] == other["id"]
    )
    assert old_edges <= {x["id"] for x in instance.store.list_canonical("provenance")}
    assert _bytes(instance.store.paths.originals) == original
    assert _bytes(instance.store.paths.canonical_dir("versions")) == versions
    assert len(decisions.history()["items"]) == 2
    with pytest.raises(ReviewConflict):
        _confirm(decisions, second_plan, "second", "local_cli")


@pytest.mark.parametrize("change", ["node", "document", "authority", "classification"])
def test_stale_placement_inputs_never_apply(review, change):
    instance, decisions, _routing, authority, area, other, documents, _source = review
    document = documents[0]
    plan = _placement(decisions, document, area)
    if change == "node":
        instance.rename_hierarchy_node(area["id"], "Changed")
    elif change == "document":
        record = instance.store.read_canonical("documents", document["id"])
        record["title"] = "Changed"
        instance.store.write_canonical("documents", Document(**record))
    elif change == "authority":
        authority["revision"] = digest("authority-2")
    else:
        instance.classify_document(document["id"], other["id"])
    before = _bytes(instance.store.paths.root)
    with pytest.raises(ReviewStale):
        _confirm(decisions, plan, "stale")
    assert _bytes(instance.store.paths.root) == before


def test_preview_history_and_routing_reads_are_pure_and_missing_state_stays_absent(review):
    instance, decisions, routing, _authority, area, _other, documents, _source = review
    before = _bytes(instance.store.paths.root)
    first = _placement(decisions, documents[0], area)
    assert first == _placement(decisions, documents[0], area)
    assert decisions.history()["items"] == []
    assert routing.candidates(documents[0]["id"])["rule_ids"] == []
    assert _bytes(instance.store.paths.root) == before
    assert not (instance.root / "state/review").exists()


def test_routing_reuses_rule_for_second_object_and_later_intake_without_overwrite(review):
    instance, decisions, routing, authority, area, other, documents, source = review
    rule_id = _save_rule(decisions, documents[0], area)
    authority.update(mode="controlled-automatic", automatic_allowed=True)
    for index, document in enumerate(documents):
        assert routing.candidates(document["id"])["automatic_rule_id"] == rule_id
        plan = decisions.preview("routing", document["id"], "apply_rule", {"rule_id": rule_id})
        _confirm(decisions, plan, "apply-" + str(index), "rule:" + rule_id)
    (source / "three.txt").write_text("Later acquisition preserves rule reuse.", encoding="utf-8")
    instance.ingest(source, source_name="Synthetic source")
    third = next(x for x in instance.list_documents() if x["title"] == "three.txt")
    plan = decisions.preview("routing", third["id"], "apply_rule", {"rule_id": rule_id})
    _confirm(decisions, plan, "apply-later", "rule:" + rule_id)
    authority.update(mode="confirm-each", automatic_allowed=False)
    _confirm(decisions, _placement(decisions, third, other), "human-correction")
    assert routing.candidates(third["id"])["reason"] == "already_classified"
    with pytest.raises(ReviewDenied):
        decisions.preview("routing", third["id"], "apply_rule", {"rule_id": rule_id})
    assert instance.hierarchy.get_classification(third["id"])["primary_node_id"] == other["id"]


def test_ambiguous_rules_propose_but_never_run_automatically_and_revocation_stales(review):
    instance, decisions, routing, authority, area, other, documents, _source = review
    rule_id = _save_rule(decisions, documents[0], area)
    _save_rule(decisions, documents[0], other, key="b")
    authority.update(mode="controlled-automatic", automatic_allowed=True)
    candidates = routing.candidates(documents[0]["id"])
    assert candidates["reason"] == "ambiguous_matches" and candidates["automatic_rule_id"] is None
    plan = decisions.preview("routing", documents[0]["id"], "apply_rule", {"rule_id": rule_id})
    with pytest.raises(ReviewDenied):
        _confirm(decisions, plan, "ambiguous", "rule:" + rule_id)
    assert instance.hierarchy.get_classification(documents[0]["id"]) is None
    _confirm(decisions, plan, "explicit-choice")
    pending = decisions.preview("routing", documents[1]["id"], "apply_rule", {"rule_id": rule_id})
    revoke = decisions.preview("routing", rule_id, "revoke_rule", {})
    _confirm(decisions, revoke, "revoke")
    with pytest.raises((ReviewStale, ReviewDenied)):
        _confirm(decisions, pending, "revoked")


@pytest.mark.parametrize("mode", ["disabled", "proposal-only"])
def test_closed_authority_never_writes(review, mode):
    instance, decisions, _routing, authority, area, _other, documents, _source = review
    authority["mode"] = mode
    plan = _placement(decisions, documents[0], area)
    before = _bytes(instance.root)
    with pytest.raises(ReviewDenied):
        _confirm(decisions, plan, "denied")
    assert _bytes(instance.root) == before


def test_lifecycle_serializes_legacy_hierarchy_writer_and_review(review):
    instance, decisions, _routing, _authority, area, _other, documents, _source = review
    plan = _placement(decisions, documents[0], area)
    with InstanceLifecycleManager(instance.store)._hold(purpose="synthetic-owner"):
        with pytest.raises(InstanceLifecycleBusy):
            instance.classify_document(documents[0]["id"], area["id"])
        with pytest.raises(InstanceLifecycleBusy):
            _confirm(decisions, plan, "busy")


def test_corrupt_or_missing_history_is_never_replayed_as_success(review):
    instance, decisions, _routing, _authority, area, _other, documents, _source = review
    plan = _placement(decisions, documents[0], area)
    result = _confirm(decisions, plan, "history")
    path = instance.root / result["receipt"]["history_ref"]
    path.write_text('{"schema_version":999}', encoding="utf-8")
    with pytest.raises(ReviewUnavailable):
        _confirm(decisions, plan, "history")


def test_unsupported_registration_allowlist_and_preimages_fail_before_effect(review):
    instance, decisions, _routing, _authority, area, _other, documents, _source = review
    plan = _placement(decisions, documents[0], area)
    provider = decisions.providers["placement"]
    original_prepare = provider.prepare

    def wrong(plan, **kwargs):
        effect = original_prepare(plan, **kwargs)
        return PreparedEffect(
            effect.domain,
            effect.action,
            (*effect.writes, PreparedWrite("state/evil.json", ABSENT, b"{}")),
            effect.result,
            effect.history_ref,
            effect.effect,
            effect.reversibility,
        )

    provider.prepare = wrong
    with pytest.raises(ReviewDenied):
        _confirm(decisions, plan, "outside")
    assert not (instance.root / "state/evil.json").exists()
    provider.prepare = original_prepare
    original_factory = decisions.transaction_factory
    decisions.transaction_factory = None
    with pytest.raises(ReviewDenied):
        _confirm(decisions, plan, "unregistered")
    decisions.transaction_factory = original_factory

    def wrong_preimage(plan, **kwargs):
        effect = original_prepare(plan, **kwargs)
        first = effect.writes[0]
        writes = (PreparedWrite(first.relative, "a" * 64, first.data), *effect.writes[1:])
        return PreparedEffect(
            effect.domain,
            effect.action,
            writes,
            effect.result,
            effect.history_ref,
            effect.effect,
            effect.reversibility,
        )

    provider.prepare = wrong_preimage
    with pytest.raises(ReviewStale):
        _confirm(decisions, plan, "preimage")
    assert decisions.history()["items"] == []


def test_value_contracts_reject_unsafe_paths_and_result_mutation():
    with pytest.raises(ReviewError):
        PreparedWrite("state/../outside", ABSENT, b"{}")
    with pytest.raises(ReviewError):
        PreparedWrite("state/value.json", "a" * 64, b"{}", immutable=True)
    result = {"nested": ["original"]}
    effect = PreparedEffect(
        "placement",
        "classify",
        (PreparedWrite("state/review/h.json", ABSENT, b"{}", immutable=True),),
        result,
        "state/review/h.json",
        "effect",
        "reversible",
    )
    result["nested"].append("changed")
    effect.result["nested"].append("changed")
    assert effect.result == {"nested": ["original"]}


def test_interrupted_commit_never_exposes_partial_receipt_and_recovers_without_false_replay(review):
    instance, decisions, _routing, _authority, area, _other, documents, _source = review
    plan = _placement(decisions, documents[0], area)
    factory = decisions.transaction_factory

    class Interrupted(BaseException):
        pass

    def interrupted_factory(owner_id):
        transaction = factory(owner_id)
        replace = transaction._replace

        def stop_after_receipt(source, target):
            replace(source, target)
            if target.parent.name == "receipts":
                raise Interrupted()

        transaction._replace = stop_after_receipt
        return transaction

    decisions.transaction_factory = interrupted_factory
    with pytest.raises(Interrupted):
        _confirm(decisions, plan, "interrupted")
    before_get = _bytes(instance.root)
    with pytest.raises(ReviewUnavailable):
        decisions.history()
    with pytest.raises(ReviewUnavailable):
        _placement(decisions, documents[0], area)
    assert _bytes(instance.root) == before_get
    decisions.transaction_factory = factory
    result = _confirm(decisions, plan, "interrupted")
    assert result["replayed"] is False
    assert _confirm(decisions, plan, "interrupted")["replayed"] is True
    assert len(decisions.history()["items"]) == 1


def test_action_center_projects_domain_receipts_without_fabricating_inspection_receipts(review):
    instance, decisions, _routing, _authority, area, _other, documents, _source = review
    center = ActionCenter(instance.store)
    projection = center.review_projection(decisions, queue="classification")
    assert all(item["domain_review"]["domain"] == "placement" for item in projection["items"])
    assert all(item["allowed_actions"] == [] for item in projection["items"])
    result = _confirm(decisions, _placement(decisions, documents[0], area), "actual-domain")
    projection = center.review_projection(decisions, queue="classification")
    assert projection["domain_history"]["items"][0]["id"] == result["receipt"]["id"]
    assert not center.path.exists()
    assert all(item["domain_receipts"] == [] for item in projection["items"])


def test_rule_edit_invalidates_pending_plan_and_prefix_matches_path_components(review):
    instance, decisions, routing, _authority, area, other, documents, _source = review
    rule_id = _save_rule(decisions, documents[0], area, prefix="one.txt")
    assert routing.candidates(documents[1]["id"])["rule_ids"] == []
    pending = decisions.preview("routing", documents[0]["id"], "apply_rule", {"rule_id": rule_id})
    edited = decisions.preview(
        "routing",
        rule_id,
        "save_rule",
        {
            "source_id": documents[0]["source_id"],
            "path_prefix": "one.txt",
            "primary_node_id": other["id"],
            "secondary_node_ids": [],
            "automatic_enabled": False,
        },
    )
    _confirm(decisions, edited, "edit-rule")
    with pytest.raises(ReviewStale):
        _confirm(decisions, pending, "before-rule-edit")
    assert routing.rules()[0]["revision"] == 2
    assert instance.hierarchy.get_classification(documents[0]["id"]) is None


def test_prepared_effect_is_io_free_and_corrupt_rule_fails_closed(review, monkeypatch):
    instance, decisions, routing, _authority, area, _other, documents, _source = review
    plan = _placement(decisions, documents[0], area)
    provider = decisions.providers["placement"]

    def forbidden(*args, **kwargs):
        raise AssertionError("prepare must not perform store IO")

    with monkeypatch.context() as selected:
        for method in ("read_config", "read_canonical", "list_canonical", "_atomic_bytes"):
            selected.setattr(instance.store, method, forbidden)
        effect = provider.prepare(
            plan,
            request_id="prepared",
            principal="local_browser",
            recorded_at="2026-09-19T22:00:00+00:00",
        )
        assert all(
            write.relative in provider.allowed_paths(plan, "prepared") for write in effect.writes
        )
    _confirm(decisions, plan, "actual-prepared")
    rule_id = _save_rule(decisions, documents[0], area)
    rule_path = instance.root / f"state/review/routing/rules/{rule_id}.json"
    rule_path.write_text('{"schema_version":999}', encoding="utf-8")
    with pytest.raises(ReviewUnavailable):
        routing.rules()
    with pytest.raises(ReviewUnavailable):
        routing.candidates(documents[1]["id"])


def test_service_ingest_applies_explicit_scoped_rule_to_later_acquisitions(review):
    instance, _decisions, _routing, _authority, area, other, documents, source = review
    decisions = instance.review_decisions

    def grant(domain, mode, actions, request, sources=None):
        plan = decisions.preview(
            "capabilities",
            domain,
            "configure",
            {
                "mode": mode,
                "scope": {"subjects": ["*"], "actions": sorted(actions), "sources": sources or []},
            },
        )
        return _confirm(decisions, plan, request)

    grant("placement", "confirm-each", ["classify"], "allow-placement")
    _confirm(decisions, _placement(decisions, documents[0], other), "human-prior-placement")
    grant("routing", "confirm-each", ["save_rule", "revoke_rule"], "allow-rule-edit")
    rule_id = _save_rule(decisions, documents[0], area, key="c")
    grant(
        "routing",
        "controlled-automatic",
        ["apply_rule"],
        "allow-scoped-routing",
        [documents[0]["source_id"]],
    )
    for name in ("later-three.txt", "later-four.txt"):
        (source / name).write_text("Later synthetic intake: " + name, encoding="utf-8")
    result = instance.ingest_run(source, source_name="Synthetic source")
    later = [item for item in instance.list_documents() if item["title"].startswith("later-")]
    assert len(later) == 2
    committed = {
        item["document_id"] for item in result["review_routing"] if item["status"] == "committed"
    }
    assert {item["id"] for item in later} <= committed
    for document in later:
        assert (
            instance.hierarchy.get_classification(document["id"])["primary_node_id"] == area["id"]
        )
        history = decisions.history(domain="routing", subject=document["id"])["items"]
        assert len(history) == 1 and history[0]["principal"] == "rule:" + rule_id
    assert (
        instance.hierarchy.get_classification(documents[0]["id"])["primary_node_id"] == other["id"]
    )
    history_count = len(decisions.history()["items"])
    repeated = instance.ingest_run(source, source_name="Synthetic source")
    assert not any(item["status"] == "committed" for item in repeated.get("review_routing", []))
    assert len(decisions.history()["items"]) == history_count


@pytest.mark.parametrize(
    "corruption", ["state_flag", "history_flag", "missing_receipt", "missing_revision"]
)
def test_routing_requires_confirmed_history_even_with_real_automatic_grant(review, corruption):
    instance, _decisions, routing, _authority, area, _other, documents, _source = review
    decisions = instance.review_decisions

    def grant(mode, actions, request, sources):
        return _confirm(
            decisions,
            decisions.preview(
                "capabilities",
                "routing",
                "configure",
                {
                    "mode": mode,
                    "scope": {"subjects": ["*"], "actions": sorted(actions), "sources": sources},
                },
            ),
            request,
        )

    grant("confirm-each", ["save_rule", "revoke_rule"], "grant-rule-writing", [])
    rule_id = _save_rule(decisions, documents[0], area, automatic=False)
    revision_two = decisions.preview(
        "routing",
        rule_id,
        "save_rule",
        {
            "source_id": documents[0]["source_id"],
            "path_prefix": "",
            "primary_node_id": area["id"],
            "secondary_node_ids": [],
            "automatic_enabled": False,
        },
    )
    result = _confirm(decisions, revision_two, "second-confirmed-rule")
    grant("controlled-automatic", ["apply_rule"], "grant-scoped-auto", [documents[0]["source_id"]])
    assert instance.review_authority.resolve("routing", documents[0]["id"], "apply_rule")[
        "automatic_allowed"
    ]
    assert routing.candidates(documents[0]["id"])["automatic_rule_id"] is None
    retained_plan = decisions.preview(
        "routing", documents[0]["id"], "apply_rule", {"rule_id": rule_id}
    )
    rule_path = instance.root / f"state/review/routing/rules/{rule_id}.json"
    history_path = instance.root / result["receipt"]["history_ref"]
    if corruption == "state_flag":
        state = json.loads(rule_path.read_bytes())
        state["automatic_enabled"] = True
        rule_path.write_text(json.dumps(state), encoding="utf-8")
    elif corruption == "history_flag":
        history = json.loads(history_path.read_bytes())
        history["after"]["automatic_enabled"] = True
        history_path.write_text(json.dumps(history), encoding="utf-8")
    elif corruption == "missing_receipt":
        (instance.root / f"state/review/receipts/{result['receipt']['id']}.json").unlink()
    else:
        next(path for path in history_path.parent.iterdir() if path != history_path).unlink()
    before = _bytes(instance.root)
    with pytest.raises(ReviewUnavailable):
        routing.rules()
    with pytest.raises(ReviewUnavailable):
        routing.candidates(documents[0]["id"])
    with pytest.raises(ReviewUnavailable):
        decisions.preview("routing", documents[0]["id"], "apply_rule", {"rule_id": rule_id})
    with pytest.raises(ReviewUnavailable):
        _confirm(decisions, retained_plan, "never-auto-apply", "rule:" + rule_id)
    assert instance.hierarchy.get_classification(documents[0]["id"]) is None
    assert _bytes(instance.root) == before
