"""Synthetic receipt/authority/atomic-boundary tests; no real model quality claim."""

import json
from copy import deepcopy

import pytest
from test_ai_synthesis import TEXT, execute
from test_ai_synthesis import synthesis as _synthesis
from test_review_placement_routing import _bytes, _confirm

from provelume.action_center_model import json_bytes
from provelume.ai_contract import digest as ai_digest
from provelume.knowledge_object_contract import record_digest
from provelume.knowledge_object_review import HISTORY, PROPOSALS, history_record
from provelume.portable_transfer import PortableTransferError
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
from provelume.review_integrity import review_state_findings
from provelume.service import ProvelumeInstance

synthesis = _synthesis


def _draft():
    return {"kind": "claim", "title": "Workshop date", "aliases": [], "state": "asserted",
            "body": {"statement": TEXT.split("\n\n")[0]}}


def _proposal(synthesis, draft=None):
    setup, _, _ = synthesis
    job = execute(synthesis)
    assert job["status"] == "succeeded"
    proposal = setup.instance.object_review.prepare_proposal(
        job["id"], _draft() if draft is None else draft,
        consent=True, expected_instance_id=setup.instance_id,
    )
    return setup, job, proposal


def _grant(instance, *, sources=None):
    plan = instance.review_decisions.preview("capabilities", "knowledge_objects", "configure", {
        "mode": "confirm-each", "scope": {"subjects": ["*"], "actions": ["apply", "reject"],
                                           "sources": [] if sources is None else sources},
    })
    return _confirm(instance.review_decisions, plan, "grant-object-review")


def _plan(instance, proposal, action="apply", draft=None):
    return instance.review_decisions.preview(
        "knowledge_objects", proposal["id"], action,
        {"draft": proposal["draft"] if draft is None else draft},
    )


def test_prepare_is_inert_and_disabled_authority_cannot_apply(synthesis):
    setup, job, proposal = _proposal(synthesis)
    instance = setup.instance
    before = _bytes(instance.store.paths.knowledge)
    assert not instance.store.list_canonical("objects")
    assert instance.object_review.inspect(proposal["id"])["proposal"] == proposal
    plan = _plan(instance, proposal)
    assert plan["authority"]["mode"] == "disabled"
    assert not plan["authority"]["automatic_allowed"]
    with pytest.raises(ReviewDenied):
        _confirm(instance.review_decisions, plan, "disabled-object")
    assert _bytes(instance.store.paths.knowledge) == before
    assert instance.ai_jobs.journal.get_job(job["id"]) == job


def test_edited_approval_replay_ai_off_disposal_and_later_manual_edit(synthesis):
    setup, job, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    originals = _bytes(instance.store.paths.originals)
    # Turning inference off does not revoke a separate manual review capability.
    setup.save({"mode": "off"}, setup.configuration()["revision"])
    assert setup.configuration()["mode"] == setup.jobs._control()["mode"] == "off"
    scheduler = _bytes(instance.store.paths.state / "scheduler")
    edited = {**proposal["draft"], "title": "Reviewed date", "body": {"statement": "Monday"}}
    plan = _plan(instance, proposal, draft=edited)
    result = _confirm(instance.review_decisions, plan, "approve-edited-object")
    assert result["receipt"]["canonical_mutation"]
    assert _confirm(instance.review_decisions, plan, "approve-edited-object")["replayed"]
    canonical = result["result"]["canonical"]
    value = instance.object_services().get(canonical["id"])["record"]
    assert value["body"] == {"statement": "Monday"}
    assert value["origin"] == {"kind": "reviewed_proposal", "proposal_id": proposal["id"]}
    assert value["created_at"] == result["receipt"]["recorded_at"]
    retained = history_record(instance.store, proposal["id"])
    assert retained["edited"] and retained["canonical"]["sha256"] == record_digest(value)
    instance.object_review.discard(proposal["id"], consent=True,
                                   expected_instance_id=setup.instance_id)
    setup.synthesis.discard(job["id"])
    instance.object_services().update(value["id"], {"title": "Later manual edit"},
                                      expected_sha256=record_digest(value), consent=True)
    assert history_record(instance.store, proposal["id"]) == retained
    assert _bytes(instance.store.paths.originals) == originals
    assert _bytes(instance.store.paths.state / "scheduler") == scheduler
    assert review_state_findings(instance.store, {}) == []


def test_reject_retains_hashes_without_canonical_or_rejected_private_text(synthesis):
    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    original = _bytes(instance.store.paths.knowledge)
    result = _confirm(instance.review_decisions, _plan(instance, proposal, "reject"),
                      "reject-object")
    assert result["result"]["canonical"] is None
    assert not result["receipt"]["canonical_mutation"]
    retained = history_record(instance.store, proposal["id"])
    assert retained["action"] == "reject"
    assert TEXT.split("\n\n")[0] not in json.dumps(retained)
    assert _bytes(instance.store.paths.knowledge) == original
    with pytest.raises(ReviewConflict):
        _plan(instance, proposal)
    instance.object_review.discard(proposal["id"], consent=True,
                                   expected_instance_id=setup.instance_id)
    assert history_record(instance.store, proposal["id"]) == retained


@pytest.mark.parametrize("change", ["output", "original", "base-discard", "receipt", "proposal"])
def test_changed_producer_blocks_mutation_and_draft_remains_disposable(synthesis, change):
    setup, job, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    before = _bytes(instance.store.paths.knowledge)
    if change == "output":
        output = synthesis[2]["outputs"][0]
        (instance.root / output["storage_ref"]).write_bytes(b"Changed output")
    elif change == "original":
        original = instance.store.list_canonical("originals")[0]
        (instance.root / original["storage_ref"]).write_bytes(b"Changed Original")
        before = _bytes(instance.store.paths.knowledge)
    elif change == "base-discard":
        setup.synthesis.discard(job["id"])
    elif change == "receipt":
        (instance.root / "state/scheduler/receipts" /
         (proposal["scheduler_receipt_id"] + ".json")).unlink()
    else:
        path = instance.root / PROPOSALS / (proposal["id"] + ".json")
        value = deepcopy(proposal)
        value["draft"]["title"] = "Forged title"
        path.write_bytes(json_bytes(value))
    with pytest.raises(ValueError):
        _plan(instance, proposal)
    assert _bytes(instance.store.paths.knowledge) == before
    if change != "proposal":  # Preserve corrupt records for diagnosis.
        instance.object_review.discard(proposal["id"], consent=True,
                                       expected_instance_id=setup.instance_id)


def test_model_or_browser_cannot_select_origin_identity_or_hierarchy(synthesis):
    setup, job, proposal = _proposal(synthesis)
    for extra in ("id", "origin", "created_at", "evidence_ids"):
        with pytest.raises(ReviewError):
            _plan(setup.instance, proposal, draft={**proposal["draft"], extra: "host-owned"})
    with pytest.raises(ReviewError):
        _plan(setup.instance, proposal, draft={**proposal["draft"], "kind": "project"})
    with pytest.raises(ReviewDenied):
        setup.instance.object_review.prepare_proposal(job["id"], _draft())
    assert not (setup.instance.root / HISTORY).exists()


def test_action_center_routes_fresh_domain_review_and_keeps_legacy_inspection_receipts(synthesis):
    from provelume.action_center import ActionCenter

    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    center = ActionCenter(instance.store)
    before = _bytes(instance.root)
    snapshot = center.review_projection(instance.review_decisions, queue="knowledge_objects")
    assert snapshot["queues"]["knowledge_objects"]["complete"]
    item, = snapshot["items"]
    assert item["allowed_actions"] == []
    assert item["domain_review"]["href"] == "/objects/proposals/" + proposal["id"]
    assert not item["domain_review"]["grants_mutation_authority"]
    assert _bytes(instance.root) == before and not center.path.exists()
    _grant(instance)
    _confirm(instance.review_decisions, _plan(instance, proposal), "from-action-center")
    after = center.review_projection(instance.review_decisions, queue="knowledge_objects")
    assert after["items"] == []
    assert any(row["subject"] == proposal["id"] for row in after["domain_history"]["items"])
    assert not center.path.exists()


@pytest.mark.parametrize("kind,body,state", [
    ("entity", {"description": "A person"}, "active"),
    ("claim", {"statement": "An assertion"}, "asserted"),
    ("decision", {"rationale": "An explicit choice"}, "decided"),
    ("task", {"description": "Work", "due_at": None}, "open"),
    ("outcome", {"description": "A result"}, "proposed"),
    ("calendar_event", {"description": "Meeting", "starts_at": "2026-10-19T09:00:00+02:00",
                        "ends_at": "2026-10-19T10:00:00+02:00", "time_zone": "Europe/Rome"},
     "tentative"),
    ("commitment", {"description": "Promise", "due_at": "2026-10-20T08:00:00Z"}, "open"),
], ids=["entity", "claim", "decision", "task", "outcome", "calendar", "commitment"])
def test_typed_objects_retain_explicit_fields_and_exact_version(synthesis, kind, body, state):
    draft = {"kind": kind, "body": body, "state": state, "title": "Explicit", "aliases": ["Name"]}
    setup, _, proposal = _proposal(synthesis, draft)
    _grant(setup.instance)
    result = _confirm(setup.instance.review_decisions, _plan(setup.instance, proposal),
                      "typed-object")
    record = setup.instance.object_services().get(result["result"]["canonical"]["id"])["record"]
    assert record["body"] == body and record["kind"] == kind and record["aliases"] == ["Name"]
    evidence = setup.instance.store.list_canonical("object-evidence")
    assert evidence == [proposal["evidence"]]
    assert evidence[0]["version_id"] == proposal["source"]["version"]["version_id"]


def test_relation_pins_current_endpoints_and_requires_explicit_refresh_after_edit(synthesis):
    setup, _, _ = synthesis
    instance = setup.instance
    objects = [instance.object_services().create("entity", title, {"description": ""}, consent=True)
               for title in ("Source", "Target")]
    refs = [{"id": row["record"]["id"], "revision": 1, "sha256": row["sha256"]} for row in objects]
    draft = {"kind": "relation", "relation_type": "relates_to", "source": refs[0],
             "target": refs[1], "state": "active"}
    _, _, proposal = _proposal(synthesis, draft)
    _grant(instance)
    plan = _plan(instance, proposal)
    updated = instance.object_services().update(refs[1]["id"], {"title": "Changed target"},
                                               expected_sha256=refs[1]["sha256"], consent=True)
    with pytest.raises(ValueError):
        _confirm(instance.review_decisions, plan, "old-endpoints")
    with pytest.raises(ValueError):
        _plan(instance, proposal)
    refreshed = {**draft, "target": {"id": refs[1]["id"], "revision": 2,
                                     "sha256": updated["sha256"]}}
    applied = _confirm(instance.review_decisions, _plan(instance, proposal, draft=refreshed),
                       "explicit-new-endpoint")
    relation = instance.object_services().get(applied["result"]["canonical"]["id"],
                                               relation=True)["record"]
    assert relation["target"] == refreshed["target"] and "origin" not in relation
    assert history_record(instance.store, proposal["id"])["edited"]


@pytest.mark.parametrize("mode", ["rebuild", "include"])
def test_origin_and_history_survive_disposal_and_portable_roundtrip(synthesis, tmp_path, mode):
    setup, job, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    result = _confirm(instance.review_decisions, _plan(instance, proposal), "portable-approved")
    retained = history_record(instance.store, proposal["id"])
    instance.object_review.discard(proposal["id"], consent=True,
                                   expected_instance_id=setup.instance_id)
    setup.synthesis.discard(job["id"])
    if mode == "include":
        instance.rebuild_index()
        instance.rebuild_library()
    archive = tmp_path / "portable.zip"
    instance.export_portable(archive, derived_state=mode)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    foreign_before = _bytes(target.root)
    with pytest.raises(PortableTransferError, match="verified target backup was restored"):
        target.import_portable(archive)
    assert _bytes(target.root) == foreign_before
    # Existing AI accounting deliberately forbids rebinding a portable Instance.
    instance.import_portable(archive)
    assert history_record(instance.store, proposal["id"]) == retained
    assert instance.object_services().get(result["result"]["canonical"]["id"])["evidence"][0][
        "status"] == "AVAILABLE"


@pytest.mark.parametrize("stop", ["object-evidence", "object-revisions", "objects",
                                  "object-proposals", "receipts"])
def test_interruption_hides_partial_review_and_recovers_at_registered_boundary(synthesis, stop):
    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    decisions = instance.review_decisions
    plan = _plan(instance, proposal)
    factory = decisions.transaction_factory

    class Interrupted(BaseException):
        pass

    def interrupted_factory(identity):
        transaction = factory(identity)
        original = transaction._replace

        def interrupt(source, target):
            original(source, target)
            if target.parent.name == stop:
                raise Interrupted()

        transaction._replace = interrupt
        return transaction

    decisions.transaction_factory = interrupted_factory
    with pytest.raises(Interrupted):
        _confirm(decisions, plan, "interrupted-object")
    before = _bytes(instance.root)
    with pytest.raises(ReviewUnavailable):
        instance.object_review.inspect(proposal["id"])
    assert _bytes(instance.root) == before
    decisions.transaction_factory = factory
    result = _confirm(decisions, plan, "interrupted-object")
    assert not result["replayed"]
    assert _confirm(decisions, plan, "interrupted-object")["replayed"]
    assert len(instance.store.list_canonical("objects")) == 1
    assert history_record(instance.store, proposal["id"])["canonical"] == (
        result["result"]["canonical"])


def test_source_update_never_retargets_old_proposal_evidence(synthesis):
    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    plan = _plan(instance, proposal)
    source = instance.root.parent / "source"
    (source / "note.txt").write_text("A genuinely different current Version.\n")
    instance.ingest(source)
    document = instance.get_document(proposal["source"]["version"]["document_id"])
    assert document["current_version"]["id"] != proposal["evidence"]["version_id"]
    old_evidence = instance.object_services().evidence_for_version(
        proposal["evidence"]["version_id"])
    assert old_evidence == proposal["evidence"]
    before = _bytes(instance.store.paths.knowledge)
    with pytest.raises(ValueError):
        _confirm(instance.review_decisions, plan, "source-changed")
    assert _bytes(instance.store.paths.knowledge) == before
    instance.object_review.discard(proposal["id"], consent=True,
                                   expected_instance_id=setup.instance_id)


def test_source_scoped_review_authority_and_changed_grant_invalidate_confirmation(synthesis):
    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance, sources=[proposal["source"]["source_id"]])
    plan = _plan(instance, proposal)
    assert plan["authority"]["mode"] == "confirm-each"
    authority = instance.review_decisions.preview(
        "capabilities", "knowledge_objects", "configure", {
            "mode": "disabled", "scope": {"subjects": ["*"], "actions": ["apply", "reject"],
                                           "sources": [proposal["source"]["source_id"]]},
        })
    _confirm(instance.review_decisions, authority, "disable-object-review")
    before = _bytes(instance.root)
    with pytest.raises(ReviewStale):
        _confirm(instance.review_decisions, plan, "stale-grant")
    assert _bytes(instance.root) == before


def test_automatic_object_capability_and_wrong_source_scope_are_denied(synthesis):
    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    with pytest.raises(ReviewUnavailable):
        instance.review_decisions.preview("capabilities", "knowledge_objects", "configure", {
            "mode": "controlled-automatic", "scope": {"subjects": ["*"], "actions": ["apply"],
                                                       "sources": []},
        })
    _grant(instance, sources=["src_" + "f" * 32])
    plan = _plan(instance, proposal)
    assert plan["authority"]["mode"] == "disabled" and not plan["authority"]["automatic_allowed"]
    with pytest.raises(ReviewDenied):
        _confirm(instance.review_decisions, plan, "wrong-source")
    assert not instance.store.list_canonical("objects")


@pytest.mark.parametrize("payload", [b'{"id":1,"id":2}', b'{"value":NaN}',
                                     b'{"value":' + b'[' * 40 + b'0' + b']' * 40 + b'}',
                                     b'{' + b' ' * (256 * 1024) + b'}'],
                         ids=["duplicate", "nonfinite", "deep", "oversize"])
def test_malformed_disposable_record_is_rejected_without_mutation(synthesis, payload):
    setup, _, proposal = _proposal(synthesis)
    path = setup.instance.root / PROPOSALS / (proposal["id"] + ".json")
    path.write_bytes(payload)
    before = _bytes(setup.instance.root)
    with pytest.raises(ValueError):
        setup.instance.object_review.inspect(proposal["id"])
    assert _bytes(setup.instance.root) == before


def test_forged_result_cannot_become_attributable_by_rehashing_only_job(synthesis):
    setup, job, proposal = _proposal(synthesis)
    job["ai"]["result"]["value"]["model"] = "forged-model"
    job["ai"]["result_fingerprint"] = ai_digest(job["ai"]["result"])
    path = setup.instance.root / "state/scheduler/jobs" / (job["id"] + ".json")
    path.write_bytes(json_bytes(job))
    with pytest.raises(ReviewUnavailable):
        setup.instance.object_review.inspect(proposal["id"])
    assert not setup.instance.store.list_canonical("objects")


def test_independent_allowlist_rejects_extra_provider_write(synthesis, monkeypatch):
    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    plan = _plan(instance, proposal)
    original = instance.object_review.prepare

    def extra(plan, **kwargs):
        effect = original(plan, **kwargs)
        return PreparedEffect(effect.domain, effect.action,
                              (*effect.writes, PreparedWrite("provelume.yml", ABSENT, b"forged")),
                              effect.result, effect.history_ref, effect.effect,
                              effect.reversibility)

    monkeypatch.setattr(instance.object_review, "prepare", extra)
    before = _bytes(instance.root)
    with pytest.raises(ReviewDenied):
        _confirm(instance.review_decisions, plan, "extra-write")
    assert _bytes(instance.root) == before


def test_same_instance_backup_restore_retains_review_after_derived_disposal(synthesis, tmp_path):
    setup, job, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    result = _confirm(instance.review_decisions, _plan(instance, proposal),
                      "backup-reviewed-object")
    retained = history_record(instance.store, proposal["id"])
    record = instance.object_services().get(result["result"]["canonical"]["id"])["record"]
    instance.object_review.discard(proposal["id"], consent=True,
                                   expected_instance_id=setup.instance_id)
    setup.synthesis.discard(job["id"])
    backup = instance.backup(destination=tmp_path / "backups")
    instance.restore(backup["archive"])
    assert history_record(instance.store, proposal["id"]) == retained
    assert instance.object_services().get(record["id"])["record"] == record
    assert instance.object_services().get(record["id"])["evidence"][0]["status"] == "AVAILABLE"


@pytest.mark.parametrize("damage", ["history", "receipt", "revision", "origin"])
def test_deep_validation_rejects_lost_or_tampered_review_provenance(synthesis, damage):
    from provelume.instance_validation import inspect_instance

    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    applied = _confirm(instance.review_decisions, _plan(instance, proposal), "retained-integrity")
    retained = history_record(instance.store, proposal["id"])
    if damage == "history":
        (instance.root / HISTORY / (proposal["id"] + ".json")).unlink()
    elif damage == "receipt":
        (instance.root / "state/review/receipts" / (retained["receipt_id"] + ".json")).unlink()
    elif damage == "revision":
        (instance.root / "knowledge/object-revisions" /
         ("objrev_" + retained["canonical"]["sha256"] + ".json")).unlink()
    else:
        path = instance.root / "knowledge/objects" / (
            applied["result"]["canonical"]["id"] + ".json")
        value = json.loads(path.read_bytes())
        value["origin"]["proposal_id"] = "objprop_" + "f" * 64
        path.write_bytes(json_bytes(value))
    before = _bytes(instance.root)
    report = inspect_instance(instance.root, deep=True)
    assert report["status"] == "invalid"
    assert _bytes(instance.root) == before


def test_saved_draft_bound_denies_another_draft_without_removing_existing_records(synthesis):
    from provelume.action_center_model import digest

    setup, job, proposal = _proposal(synthesis)
    instance = setup.instance
    directory = instance.root / PROPOSALS
    for index in range(127):
        value = deepcopy(proposal)
        value.pop("id")
        value["request_id"] = f"{index:032x}"
        value["id"] = "objprop_" + digest(value)
        (directory / (value["id"] + ".json")).write_bytes(json_bytes(value))
    before = _bytes(instance.root)
    with pytest.raises(ReviewUnavailable, match="limit reached"):
        instance.object_review.prepare_proposal(job["id"], _draft(), consent=True,
                                                expected_instance_id=setup.instance_id)
    assert _bytes(instance.root) == before and len(list(directory.iterdir())) == 128


def test_changed_ai_scope_policy_blocks_review_but_not_explicit_disposal(synthesis):
    setup, _, proposal = _proposal(synthesis)
    instance = setup.instance
    _grant(instance)
    plan = _plan(instance, proposal)
    setup.synthesis.restrict(proposal["evidence"]["document_id"], "instance",
                             setup.instance_id, "deny", 0)
    before = _bytes(instance.store.paths.knowledge)
    with pytest.raises(ReviewStale):
        _confirm(instance.review_decisions, plan, "changed-ai-scope-policy")
    assert _bytes(instance.store.paths.knowledge) == before
    instance.object_review.discard(proposal["id"], consent=True,
                                   expected_instance_id=setup.instance_id)


def test_empty_instance_and_legacy_queue_state_reads_create_no_files_or_new_grants(tmp_path):
    from provelume.action_center import ActionCenter
    from provelume.action_center_model import QUEUES

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    before = _bytes(instance.root)
    assert instance.object_review.listing() == []
    assert _bytes(instance.root) == before
    center = ActionCenter(instance.store)
    legacy = [queue for queue in QUEUES if queue != "knowledge_objects"]
    assert len(legacy) == 8
    for index, queue in enumerate(legacy):
        center.set_authority(queue, "proposal-only", index, "legacy-queue-" + queue)
    before = _bytes(instance.root)
    rules = center.authority()["rules"]
    snapshot = center.snapshot(queue="knowledge_objects")
    assert snapshot["items"] == [] and snapshot["queues"]["knowledge_objects"]["complete"]
    assert center.authority()["rules"] == rules
    assert all(rule["queue"] in legacy for rule in rules)
    assert instance.review_authority.resolve("knowledge_objects", "objprop_" + "a" * 64,
                                              "apply")["mode"] == "disabled"
    assert _bytes(instance.root) == before


@pytest.mark.parametrize("damage", ["oversize", "duplicate", "substituted", "missing"])
def test_producer_job_reads_are_bounded_closed_and_identity_checked(synthesis, damage):
    setup, job, proposal = _proposal(synthesis)
    path = setup.instance.root / "state/scheduler/jobs" / (job["id"] + ".json")
    if damage == "oversize":
        path.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    elif damage == "duplicate":
        path.write_bytes(b'{"schema_version":2,"schema_version":2}')
    elif damage == "substituted":
        job["id"] = "job_" + "f" * 32
        path.write_bytes(json_bytes(job))
    else:
        path.unlink()
    before = _bytes(setup.instance.root)
    with pytest.raises(ValueError):
        setup.instance.object_review.inspect(proposal["id"])
    assert _bytes(setup.instance.root) == before
