"""Synthetic state-machine checks; these do not qualify a real classifier."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_ai_classification_proposals import BUDGET
from test_ai_classification_proposals import governed as _governed
from test_review_placement_routing import _bytes, _confirm

from provelume.action_center_model import json_bytes
from provelume.classification_review import ROOT, _class_path
from provelume.review_effects import ReviewConflict, ReviewDenied, ReviewError, ReviewStale
from provelume.review_integrity import review_state_findings
from provelume.service import ProvelumeInstance
from provelume.web import create_app

POLICY = "autonomy_" + "a" * 32
governed = _governed


def _grant(instance):
    decisions = instance.review_decisions
    plan = decisions.preview("capabilities", "iudicium", "configure", {
        "mode": "confirm-each", "scope": {
            "subjects": ["*"], "actions": ["apply", "revoke_policy", "save_policy", "undo"],
            "sources": [],
        },
    })
    return _confirm(decisions, plan, "grant-reviewed-classification")


def _parameters(job, nodes):
    return {"job_id": job, "path_prefix": "", "target_ids": sorted(nodes),
            "languages": ["en"], "expires_at": (datetime.now(UTC) + timedelta(days=1))
            .isoformat().replace("+00:00", "Z"), "mode": "confirm-each", "max_applications": 2}


def _rule(setup, job, nodes):
    instance = setup.instance
    _grant(instance)
    plan = instance.review_decisions.preview("iudicium", POLICY, "save_policy",
                                            _parameters(job, nodes))
    _confirm(instance.review_decisions, plan, "save-reviewed-policy")
    return instance.classification_review.policy(POLICY)


def _application(setup, job, node):
    document = setup.jobs.journal.get_job(job)["ai"]["request"]["context"]["document_id"]
    return setup.instance.review_decisions.preview("iudicium", document, "apply", {
        "job_id": job, "policy_id": POLICY, "primary_node_id": node,
        "secondary_node_ids": [], "reviewed": True,
    })


@pytest.mark.parametrize("governed", [{}, {"existing_placement": True}], indirect=True)
def test_manual_apply_receipt_replay_exact_undo_and_original_accounting_preserved(governed):
    setup, job, allowlist, fake, _ = governed
    instance, decisions = setup.instance, setup.instance.review_decisions
    document = setup.jobs.journal.get_job(job)["ai"]["request"]["context"]["document_id"]
    nodes = [allowlist[0][1]]
    class_path = instance.root / _class_path(document)
    before = class_path.read_bytes() if class_path.exists() else None
    if before is not None:
        nodes.append(json.loads(before)["primary_node_id"])
    originals = _bytes(instance.store.paths.originals)
    versions = _bytes(instance.store.paths.canonical_dir("versions"))
    accounting, receipts = setup.jobs.status()["accounting"], setup.jobs.journal.list_receipts()
    _rule(setup, job, nodes)
    plan = _application(setup, job, nodes[0])
    assert plan["provider"]["quality"]["qualification"] == "NOT_EVALUATED"
    assert plan["provider"]["confidence"] is None
    applied = _confirm(decisions, plan, "apply-reviewed-policy")
    assert _confirm(decisions, plan, "apply-reviewed-policy")["replayed"]
    assert instance.classification_review.policy(POLICY)["used"] == 1
    # Remedial undo needs no private body, active policy, model or renewed AI consent.
    setup.classification.discard(job)
    setup.jobs.configure(mode="off", budget=BUDGET)
    revoke = decisions.preview("iudicium", POLICY, "revoke_policy", {})
    _confirm(decisions, revoke, "revoke-before-undo")
    undo = decisions.preview("iudicium", document, "undo", {
        "application": applied["receipt"]["id"],
    })
    undone = _confirm(decisions, undo, "undo-reviewed-application")
    assert undone["receipt"]["canonical_mutation"] is True
    assert _confirm(decisions, undo, "undo-reviewed-application")["replayed"]
    assert (class_path.read_bytes() if class_path.exists() else None) == before
    assert _bytes(instance.store.paths.originals) == originals
    assert _bytes(instance.store.paths.canonical_dir("versions")) == versions
    assert setup.jobs.status()["accounting"] == accounting
    assert setup.jobs.journal.list_receipts() == receipts
    assert fake.calls == 1
    assert len(decisions.history(domain="iudicium")["items"]) == 4
    assert instance.classification_review.policy(POLICY)["mode"] == "disabled"
    assert review_state_findings(instance.store, {}) == []


def test_preview_is_pure_and_disabled_host_authority_denies_application(governed):
    setup, job, allowlist, _, _ = governed
    instance, decisions = setup.instance, setup.instance.review_decisions
    before = _bytes(instance.root)
    plan = decisions.preview("iudicium", POLICY, "save_policy",
                             _parameters(job, [allowlist[0][1]]))
    assert _bytes(instance.root) == before
    assert not (instance.root / ROOT).exists()
    with pytest.raises(ReviewDenied):
        _confirm(decisions, plan, "no-host-review-authority")


@pytest.mark.parametrize("governed", [{"existing_placement": True, "existing_secondary": True}],
                         indirect=True)
@pytest.mark.parametrize("outside_role", ["primary", "secondary"])
def test_policy_cannot_change_an_unreviewed_destination_role(governed, outside_role):
    setup, job, allowlist, fake, _ = governed
    instance, decisions = setup.instance, setup.instance.review_decisions
    document = setup.jobs.journal.get_job(job)["ai"]["request"]["context"]["document_id"]
    path = instance.root / _class_path(document)
    before_class = json.loads(path.read_bytes())
    primary, secondary = before_class["primary_node_id"], allowlist[0][1]
    assert before_class["secondary_node_ids"] == [secondary]
    reviewed = secondary if outside_role == "primary" else primary
    _rule(setup, job, [reviewed])
    before = _bytes(instance.root)
    with pytest.raises(ReviewDenied, match="outside reviewed policy scope"):
        decisions.preview("iudicium", document, "apply", {
            "job_id": job, "policy_id": POLICY, "primary_node_id": secondary,
            "secondary_node_ids": [primary], "reviewed": True,
        })
    assert _bytes(instance.root) == before
    assert instance.classification_review.policy(POLICY)["used"] == 0
    assert fake.calls == 1


@pytest.mark.parametrize("governed", [{"existing_placement": True, "existing_secondary": True}],
                         indirect=True)
def test_reviewed_role_swap_can_be_applied_and_undone_exactly(governed):
    setup, job, allowlist, fake, _ = governed
    instance, decisions = setup.instance, setup.instance.review_decisions
    document = setup.jobs.journal.get_job(job)["ai"]["request"]["context"]["document_id"]
    path = instance.root / _class_path(document)
    before = path.read_bytes()
    primary, secondary = json.loads(before)["primary_node_id"], allowlist[0][1]
    _rule(setup, job, [primary, secondary])
    plan = decisions.preview("iudicium", document, "apply", {
        "job_id": job, "policy_id": POLICY, "primary_node_id": secondary,
        "secondary_node_ids": [primary], "reviewed": True,
    })
    applied = _confirm(decisions, plan, "reviewed-role-swap")
    current = json.loads(path.read_bytes())
    assert current["primary_node_id"] == secondary
    assert current["secondary_node_ids"] == [primary]
    undo = decisions.preview("iudicium", document, "undo", {
        "application": applied["receipt"]["id"],
    })
    _confirm(decisions, undo, "undo-reviewed-role-swap")
    assert path.read_bytes() == before
    assert instance.classification_review.policy(POLICY)["used"] == 1
    assert fake.calls == 1


@pytest.mark.parametrize("governed", [{"existing_placement": True, "existing_secondary": True}],
                         indirect=True)
def test_policy_keeps_an_unchanged_destination_outside_its_scope(governed):
    setup, job, allowlist, fake, _ = governed
    instance, decisions = setup.instance, setup.instance.review_decisions
    document = setup.jobs.journal.get_job(job)["ai"]["request"]["context"]["document_id"]
    path = instance.root / _class_path(document)
    before = path.read_bytes()
    primary, secondary = json.loads(before)["primary_node_id"], allowlist[0][1]
    _rule(setup, job, [secondary])
    plan = decisions.preview("iudicium", document, "apply", {
        "job_id": job, "policy_id": POLICY, "primary_node_id": primary,
        "secondary_node_ids": [], "reviewed": True,
    })
    applied = _confirm(decisions, plan, "keep-outside-primary")
    current = json.loads(path.read_bytes())
    assert current["primary_node_id"] == primary and current["secondary_node_ids"] == []
    undo = decisions.preview("iudicium", document, "undo", {
        "application": applied["receipt"]["id"],
    })
    _confirm(decisions, undo, "restore-reviewed-secondary")
    assert path.read_bytes() == before
    assert instance.classification_review.policy(POLICY)["used"] == 1
    assert fake.calls == 1


@pytest.mark.parametrize("change", ["expiry", "budget", "mode", "prefix", "language", "node"])
def test_expired_exhausted_or_outside_scope_policy_fails_closed(governed, change):
    setup, job, allowlist, _, _ = governed
    node = allowlist[0][1]
    _grant(setup.instance)
    params = _parameters(job, [node])
    if change == "mode":
        params["mode"] = "proposal-only"
    elif change == "prefix":
        params["path_prefix"] = "another-folder"
    elif change == "language":
        params["languages"] = ["it"]
    elif change == "budget":
        params["max_applications"] = 1
    decisions = setup.instance.review_decisions
    _confirm(decisions, decisions.preview("iudicium", POLICY, "save_policy", params), "rule")
    if change == "expiry":
        setup.instance.classification_review.clock = lambda: datetime.now(UTC) + timedelta(days=2)
    elif change == "node":
        setup.instance.rename_hierarchy_node(node, "A changed target")
    elif change == "budget":
        _confirm(decisions, _application(setup, job, node), "spent")
    before = _bytes(setup.instance.root)
    with pytest.raises((ReviewError, ValueError)):
        _application(setup, job, node)
    assert _bytes(setup.instance.root) == before


def test_new_target_policy_or_source_change_invalidates_confirmed_preview(governed):
    setup, job, allowlist, _, _ = governed
    _rule(setup, job, [allowlist[0][1]])
    plan = _application(setup, job, allowlist[0][1])
    revoke = setup.instance.review_decisions.preview("iudicium", POLICY, "revoke_policy", {})
    _confirm(setup.instance.review_decisions, revoke, "changed-policy")
    with pytest.raises(ReviewError):
        _confirm(setup.instance.review_decisions, plan, "old-policy")


def test_foreign_later_classification_blocks_undo_and_original_receipt_is_retained(governed):
    setup, job, allowlist, _, _ = governed
    _rule(setup, job, [allowlist[0][1]])
    decisions = setup.instance.review_decisions
    plan = _application(setup, job, allowlist[0][1])
    result = _confirm(decisions, plan, "manual-review")
    path = setup.instance.root / _class_path(plan["subject"])
    changed = json.loads(path.read_bytes())
    changed["updated_at"] = "2099-01-01T00:00:00Z"
    path.write_bytes(json_bytes(changed))
    before = _bytes(setup.instance.root)
    with pytest.raises(ReviewConflict):
        decisions.preview("iudicium", plan["subject"], "undo", {
            "application": result["receipt"]["id"],
        })
    assert _bytes(setup.instance.root) == before


def test_tampered_policy_and_automatic_authority_are_never_accepted(governed):
    setup, job, allowlist, _, _ = governed
    _rule(setup, job, [allowlist[0][1]])
    decisions = setup.instance.review_decisions
    plan = _application(setup, job, allowlist[0][1])
    with pytest.raises(ReviewError):
        _confirm(decisions, plan, "automatic", "rule:routing_" + "a" * 32)
    path = setup.instance.root / ROOT / "policies" / (POLICY + ".json")
    modified = json.loads(path.read_bytes())
    modified["max_applications"] = 999
    path.write_bytes(json_bytes(modified))
    with pytest.raises(ReviewError):
        _application(setup, job, allowlist[0][1])


def test_undo_preview_rechecks_later_classification_at_confirmation(governed):
    setup, job, allowlist, _, _ = governed
    _rule(setup, job, [allowlist[0][1]])
    decisions = setup.instance.review_decisions
    plan = _application(setup, job, allowlist[0][1])
    applied = _confirm(decisions, plan, "apply")
    undo = decisions.preview("iudicium", plan["subject"], "undo", {
        "application": applied["receipt"]["id"],
    })
    path = setup.instance.root / _class_path(plan["subject"])
    raw = path.read_bytes()
    path.write_bytes(raw + b"\n")
    with pytest.raises((ReviewStale, ReviewConflict)):
        _confirm(decisions, undo, "undo-stale")
    assert path.read_bytes() == raw + b"\n"


@pytest.mark.parametrize("mode", ["preview", "current"])
def test_ordinary_browser_policy_apply_undo_local_nonce_and_pure_get(governed, tmp_path, mode):
    from test_review_decision_routes import _confirm as browser_confirm
    from test_review_decision_routes import _preview, _token

    from provelume.shell_settings import ShellSettingsManager, default_settings

    setup, job, allowlist, fake, _ = governed
    manager = ShellSettingsManager(tmp_path / "review-shell.json", default_settings())
    manager.save(default_settings())
    manager.set_interface_mode(mode, expected_revision=0)
    app = create_app(setup.instance.root, shell_settings_file=manager.path)
    document = setup.jobs.journal.get_job(job)["ai"]["request"]["context"]["document_id"]
    _grant(app.state.ai_setup.instance)
    with TestClient(app) as client:
        # Browser host is a fresh Instance, with no inference/operational consent.
        policy_path = "/review/decisions/iudicium/" + POLICY
        before = _bytes(setup.instance.root)
        token = _token(client, policy_path)
        assert _bytes(setup.instance.root) == before
        plan = _preview(client, policy_path, token, "save_policy",
                        _parameters(job, [allowlist[0][1]]))
        assert plan.status_code == 200, plan.text
        changes = json.dumps(plan.json()["summary"]["changes"])
        assert "Work" in changes
        source_id = setup.instance.store.read_canonical("documents", document)["source_id"]
        assert setup.instance.store.read_canonical("sources", source_id)["name"] in changes
        saved = browser_confirm(client, policy_path, token, plan)
        assert saved.status_code == 200, saved.text
        assert client.get("/review/iudicium").status_code == 200
        path = "/review/decisions/iudicium/" + document
        token = _token(client, path)
        assert "Review the source and choose the destinations yourself." in client.get(path).text
        params = {"job_id": job, "policy_id": POLICY, "primary_node_id": allowlist[0][1],
                  "secondary_node_ids": [], "reviewed": True}
        hostile = client.post(path + "/preview", headers={"Origin": "https://example.invalid"},
                              json={"csrf_token": token, "action": "apply", "parameters": params})
        assert hostile.status_code == 403
        plan = _preview(client, path, token, "apply", params)
        assert plan.status_code == 200, plan.text
        assert plan.json()["summary"]["confidence"] is None
        source = plan.json()["summary"]["evidence"]["selected_source"]
        assert source and source[0]["text"]
        applied = browser_confirm(client, path, token, plan)
        assert applied.status_code == 200, applied.text
        assert browser_confirm(client, path, token, plan).status_code == 409
        receipt = applied.json()["receipt"]
        assert source[0]["text"] not in json.dumps(receipt)
        # Undo remains reachable after the private body is gone.
        setup.classification.discard(job)
        token = _token(client, path)
        plan = _preview(client, path, token, "undo", {"application": receipt["id"]})
        assert plan.status_code == 200, plan.text
        assert browser_confirm(client, path, token, plan).status_code == 200
        assert not (setup.instance.root / _class_path(document)).exists()
        assert fake.calls == 1
        assert app.state.ai_setup.jobs.session_authorized is False


@pytest.mark.parametrize("field,value", [
    ("languages", [["en"]]), ("target_ids", [["not-an-identity"]]),
    ("max_applications", True), ("max_applications", 1001), ("mode", ["confirm-each"]),
    ("expires_at", "2099-01-01T00:00:00Z"),
])
def test_malformed_rule_never_reaches_writes(governed, field, value):
    setup, job, allowlist, _, _ = governed
    parameters = _parameters(job, [allowlist[0][1]])
    parameters[field] = value
    before = _bytes(setup.instance.root)
    with pytest.raises(ReviewError):
        setup.instance.review_decisions.preview("iudicium", POLICY, "save_policy", parameters)
    assert _bytes(setup.instance.root) == before


@pytest.mark.parametrize("change", ["target", "placement", "payload", "policy", "quality"])
def test_pending_application_rechecks_current_source_policy_targets_and_quality(governed, change,
                                                                               monkeypatch):
    from provelume import classification_autonomy
    from provelume.ai_contract import Scope

    setup, job, allowlist, _, _ = governed
    node = allowlist[0][1]
    _rule(setup, job, [node])
    decisions = setup.instance.review_decisions
    plan = _application(setup, job, node)
    if change == "target":
        setup.instance.rename_hierarchy_node(node, "Changed after review")
    elif change == "placement":
        setup.instance.classify_document(plan["subject"], node)
    elif change == "payload":
        original = setup.instance.store.list_canonical("originals")[0]
        (setup.instance.root / original["storage_ref"]).write_bytes(b"Changed public fixture")
    elif change == "policy":
        document = setup.instance.get_document(plan["subject"])
        scopes, _ = setup.document_governance(document)
        scope = next(s for s in scopes if s.kind == Scope.SOURCE)
        setup.synthesis.restrict(plan["subject"], scope.kind, scope.id, "deny", 0)
    else:
        previous = classification_autonomy.quality_scope
        monkeypatch.setattr(classification_autonomy, "quality_scope", lambda *args: {
            **previous(*args), "revision": "f" * 64,
        })
    before = _bytes(setup.instance.root)
    with pytest.raises(ValueError):
        _confirm(decisions, plan, "stale-application")
    assert _bytes(setup.instance.root) == before


def test_missing_consumption_index_cannot_reuse_retained_assessment(governed):
    setup, job, allowlist, _, _ = governed
    _rule(setup, job, [allowlist[0][1]])
    decisions = setup.instance.review_decisions
    plan = _application(setup, job, allowlist[0][1])
    _confirm(decisions, plan, "application")
    (setup.instance.root / ROOT / "applications" / (job + ".json")).unlink()
    with pytest.raises(ReviewError):
        setup.instance.classification_review.policy(POLICY)
    assert review_state_findings(setup.instance.store, {})


def test_readonly_review_does_not_replace_an_existing_execution_owner(governed):
    setup, job, _, _, _ = governed
    reopened = ProvelumeInstance(setup.instance.root)
    current = object()
    jobs = reopened.bind_ai_execution(current=current, adapters={"unchanged-host": object()})
    before = _bytes(reopened.root)
    assessment = reopened.classification_review.assessment(job)[0]
    assert assessment["classification_quality"] == "NOT_EVALUATED"
    assert reopened.ai_jobs is jobs and reopened.scheduler.ai_jobs is jobs
    assert jobs.current is current and set(jobs.adapters) == {"unchanged-host"}
    assert _bytes(reopened.root) == before
