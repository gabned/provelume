from __future__ import annotations

import pytest

from provelume.review_effects import ReviewStale
from provelume.review_routing import RoutingProvider
from provelume.scheduler import SchedulerCoordinator, schedule_payload
from provelume.service import ProvelumeInstance


def _confirm(decisions, domain, subject, action, parameters, request):
    plan = decisions.preview(domain, subject, action, parameters)
    return decisions.confirm(
        domain, subject, action, parameters,
        expected_plan_revision=plan["plan_revision"],
        expected_authority_revision=plan["authority_revision"],
        request_id=request,
    )


def _grant(instance, mode, actions, sources, request):
    return _confirm(
        instance.review_decisions, "capabilities", "routing", "configure",
        {"mode": mode, "scope": {"subjects": ["*"], "actions": sorted(actions),
                                  "sources": sorted(sources)}}, request,
    )


def _fixture(tmp_path, entry):
    source = tmp_path / "source"
    source.mkdir()
    (source / "seed.txt").write_text("Synthetic seed", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    if entry == "folder":
        record = instance.register_folder_source(
            source, name="Routing fixture", quiescence_seconds=0, stable_observations=1,
            schedule=schedule_payload(mode="manual", timezone="UTC"),
        )
        source_id = record["id"]
        assert instance.refresh_folder_source(source_id, request_key="seed")["job"][
            "status"
        ] == "succeeded"
    else:
        source_id = instance.ingest_run(source)["run"]["source_id"]
    area = instance.create_hierarchy_node("area", "Automatic destination")
    _grant(instance, "confirm-each", ["save_rule"], [], "allow-rule")
    rule_id = "routing_" + "b" * 32
    _confirm(
        instance.review_decisions, "routing", rule_id, "save_rule",
        {"source_id": source_id, "path_prefix": "", "primary_node_id": area["id"],
         "secondary_node_ids": [], "automatic_enabled": True}, "save-rule",
    )
    _grant(instance, "controlled-automatic", ["apply_rule"], [source_id], "allow-auto")
    later = source / "later.txt"
    if entry == "retry":
        later.write_text("x" * 100, encoding="utf-8")
        failed = instance.ingest_run(source, max_file_bytes=32)
        assert failed["run"]["status"] == "completed_with_errors"
        run_id = failed["run"]["id"]
    later.write_text("Synthetic later acquisition", encoding="utf-8")

    def execute():
        if entry == "retry":
            return instance.retry_ingestion(run_id)
        queued = instance.queue_folder_source_refresh(source_id, request_key="later")
        # A fresh scheduler is the autonomous path, independent of the service's manager.
        job = SchedulerCoordinator(instance.store).run_one(job_id=queued["job"]["id"])
        assert job["status"] == "succeeded"
        return job

    return instance, area, rule_id, source_id, execute


@pytest.mark.parametrize("entry", ["retry", "folder"])
def test_committed_retry_and_autonomous_folder_acquisitions_route_once(tmp_path, entry):
    instance, area, rule_id, _source_id, execute = _fixture(tmp_path, entry)
    result = execute()
    if entry == "retry":
        assert result["run"]["status"] == "completed"
        assert result["review_routing"][0]["status"] == "committed"
    document = next(x for x in instance.list_documents() if x["title"] == "later.txt")
    assert instance.hierarchy.get_classification(document["id"])["primary_node_id"] == area["id"]
    history = instance.review_decisions.history(domain="routing", subject=document["id"])["items"]
    assert len(history) == 1 and history[0]["principal"] == "rule:" + rule_id
    acquisitions = instance.store.list_canonical("acquisitions")
    repeated = instance.route_new_acquisitions(acquisitions)
    assert not any(x["status"] == "committed" for x in repeated)
    assert instance.review_decisions.history(domain="routing", subject=document["id"])[
        "items"
    ] == history


@pytest.mark.parametrize("entry", ["retry", "folder"])
@pytest.mark.parametrize("denial", ["revoked", "other_source", "stale"])
def test_new_intake_survives_unavailable_or_changed_routing_authority(
    tmp_path, monkeypatch, entry, denial,
):
    instance, _area, _rule_id, source_id, execute = _fixture(tmp_path, entry)
    if denial == "revoked":
        _grant(instance, "disabled", ["apply_rule"], [source_id], "revoke-auto")
    elif denial == "other_source":
        other_path = tmp_path / "other"
        other_path.mkdir()
        other_source = instance.ingest_run(other_path)["run"]["source_id"]
        _grant(instance, "controlled-automatic", ["apply_rule"], [other_source], "scope-other")
    else:
        def stale_prepare(*args, **kwargs):
            raise ReviewStale("Synthetic routing inputs changed after preview")

        monkeypatch.setattr(RoutingProvider, "prepare", stale_prepare)
    result = execute()
    if entry == "retry":
        assert result["run"]["status"] == "completed"
        assert result["review_routing"][0]["status"] in {"proposal", "review_required"}
    document = next(x for x in instance.list_documents() if x["title"] == "later.txt")
    assert instance.hierarchy.get_classification(document["id"]) is None
    assert instance.review_decisions.history(domain="routing", subject=document["id"])[
        "items"
    ] == []
    acquisitions = instance.store.list_canonical("acquisitions")
    assert any(x["document_id"] == document["id"] for x in acquisitions)
