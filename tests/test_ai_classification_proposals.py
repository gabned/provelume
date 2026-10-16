"""Synthetic governed-job contracts only; no real classifier quality is measured."""

from dataclasses import replace
from html import unescape

import pytest
from ai_context_fakes import context_plan
from ai_provider_fakes import provider_case
from fastapi.testclient import TestClient
from test_ai_setup import form
from test_representations import _implementation, _seed, _snapshots

from provelume.ai_classification_proposals import classification_request_ref
from provelume.ai_context import Selection, preview_context, validate_candidate
from provelume.ai_contract import Capability, Mode, PolicyRule, Scope, ScopeRef, digest
from provelume.ai_job_contract import Budget
from provelume.ai_job_runtime import JobOutcome
from provelume.ai_setup import AiSetup
from provelume.maintenance_local_files import MaintenanceTargetError
from provelume.representations import canonical_json_bytes
from provelume.scheduler_model import SchedulerError
from provelume.service import ProvelumeInstance
from provelume.shell_settings import ShellSettingsManager, default_settings
from provelume.web import create_app

TEXT = "Public synthetic Atlas report."
BUDGET = Budget(100000, 1000000)


@pytest.fixture
def governed(tmp_path, request):
    instance, version = _seed(tmp_path)
    document = instance.store.list_canonical("documents")[0]["id"]
    label = getattr(request, "param", {}).get("label", "Work")
    area = instance.create_hierarchy_node("area", label)
    if getattr(request, "param", {}).get("existing_placement"):
        previous = instance.create_hierarchy_node("project", "Previous destination")
        secondary = ([area["id"]] if getattr(request, "param", {}).get("existing_secondary")
                     else [])
        instance.classify_document(document, previous["id"], secondary_node_ids=secondary)
    allowlist = (("area", area["id"]),)
    targets = instance.ai_classification_targets(document, allowlist)
    bundle = instance.representations.bundles.materialize(
        version, recipe_id="synthetic-classification", recipe_version="1", recipe_settings={},
        output_payloads={"text.txt": ("text/plain", TEXT.encode())},
        implementation=_implementation(), anchor_targets=({"kind": "page", "page": 1},),
    )
    setup = AiSetup(instance)
    _, _, source = setup.synthesis.source(document, bundle["representation_id"],
                                          bundle["outputs"][0]["id"])
    selections = (Selection(source.version, bundle["representation_id"], digest(bundle),
                            bundle["outputs"][0]["id"], bundle["anchors"][0]["id"],
                            0, len(TEXT)),)
    base = provider_case(text=TEXT)
    current = dict(base.current)
    scopes = (ScopeRef(Scope.INSTANCE, targets.instance_id),
              ScopeRef(Scope.SOURCE, targets.source_id),
              ScopeRef(Scope.CATEGORY, "public_synthetic_classification"))
    current["snapshot"] = replace(
        current["snapshot"], scopes=scopes,
        context=replace(current["snapshot"].context, instance_id=targets.instance_id,
                        document_id=document, version_id=version),
    )
    current["rules"] = tuple(PolicyRule(
        scope, digest("synthetic-only-source-policy"),
        mode=Mode.LOCAL_ONLY if i == 0 else None,
        allowed_profiles=(base.profiles[0].id,) if i == 0 else None,
        allowed_capabilities=(Capability.STRUCTURED_OUTPUT,) if i == 0 else None,
        limits=current["request_limits"] if i == 0 else None,
        route=(base.profiles[0].id,) if i == 0 else (),
    ) for i, scope in enumerate(scopes))
    current["template"] = targets.template("en")
    preview = preview_context(source, selections, **current)
    plan = context_plan(preview, source, selections, current,
                        {"profiles": base.profiles, "evidence": base.evidence})
    holder = [replace(base, source=source, selections=selections, current=current,
                      preview=preview, plan=plan)]
    ref = ("0" * 64 if getattr(request, "param", {}).get("wrong_ref")
           else classification_request_ref(preview, targets))

    class Fake:
        network_used = False
        calls = 0
        target = getattr(request, "param", {}).get("target", 0)

        def exchange(self, callback, *, cancel):
            self.calls += 1
            inputs = callback()
            inputs.prepare()
            assert not cancel()
            value = {
                "schema_version": 1, "preview_fingerprint": inputs.preview.fingerprint,
                "status": "selected" if self.target is not None else "abstained",
                "references": [0] if self.target is not None else [], "target": self.target,
                **getattr(request, "param", {}).get("changes", {}),
            }
            raw = canonical_json_bytes(value)
            if getattr(request, "param", {}).get("raw"):
                output = {"kind": "untrusted_text", "value": raw.decode()}
            else:
                candidate = validate_candidate(raw, inputs.preview, source, selections, **current)
                output = {"kind": "context_check", "value": candidate.as_record()}
            return JobOutcome(output,
                              units=12, micros=0, usage_source="LOCAL")

    fake = Fake()

    def live(request_ref, route):
        assert request_ref == ref
        targets.revalidate(instance.store)
        return replace(holder[0], route_index=route)

    def project(job, result):
        projected = setup.project_result(job, result)
        if getattr(request, "param", {}).get("orphan"):
            raise ValueError("synthetic interruption after body publication")
        return projected

    jobs = instance.bind_ai_execution(current=live,
                                      adapters={base.profiles[0].fingerprint: fake},
                                      result_projector=project)
    setup.jobs = jobs
    jobs.configure(mode="enabled", budget=BUDGET)
    job = jobs.enqueue(ref, request_key="explicit-synthetic-classification", budget=BUDGET)
    instance.run_ai_job(job["id"])
    expected = "failed" if getattr(request, "param", {}).get("failed") else "succeeded"
    assert jobs.journal.get_job(job["id"])["status"] == expected
    yield setup, job["id"], allowlist, fake, holder
    setup.close()


@pytest.mark.parametrize("governed", [
    {"target": 0}, {"target": None}, {"target": 0, "raw": True}, {"target": None, "raw": True},
], indirect=True)
def test_receipt_anchors_private_record_without_new_inference_or_canonical_changes(governed):
    setup, job_id, allowlist, fake, _ = governed
    before = _snapshots(setup.instance.store)
    producer = setup.classification
    body, reference, _, job, targets = producer.read(job_id)
    assert job["ai"]["result"]["kind"] == "classification_ref"
    assert reference["body_sha256"] == digest(body)
    assert body["assessment"]["target"] == fake.target
    assert targets.allowlist == allowlist
    assert body["classification_quality"] == "NOT_EVALUATED"
    assert body["confidence"] is None
    assert body["canonical_mutation"] is body["automation_authorized"] is False
    assert fake.calls == 1
    assert len(setup.jobs.journal.list_receipts()) == 1
    assert _snapshots(setup.instance.store) == before
    # A terminal job cannot re-enter the pre-terminal projector, even explicitly.
    with pytest.raises(SchedulerError):
        producer.project(job, {})
    assert fake.calls == 1


@pytest.mark.parametrize("change", ["rename", "add", "payload", "policy"])
def test_changed_source_targets_or_policy_fail_closed_without_rewriting(governed, change):
    setup, job_id, allowlist, fake, _ = governed
    producer = setup.classification
    path = producer.path(job_id)
    before = path.read_bytes()
    if change == "rename":
        setup.instance.rename_hierarchy_node(allowlist[0][1], "Changed")
    elif change == "add":
        setup.instance.create_hierarchy_node("area", "Another target")
    elif change == "payload":
        original = setup.instance.store.list_canonical("originals")[0]
        (setup.instance.root / original["storage_ref"]).write_bytes(b"Altered synthetic payload")
    else:
        # Existing source policy owner; affects read association without any inference.
        document = setup.instance.get_document(
            setup.jobs.journal.get_job(job_id)["ai"]["request"]["context"]["document_id"])
        scopes, _ = setup.document_governance(document)
        scope = next(s for s in scopes if s.kind == Scope.SOURCE)
        setup.synthesis.restrict(document["id"], scope.kind, scope.id, "deny", 0)
    with pytest.raises((SchedulerError, ValueError)):
        producer.read(job_id)
    assert path.read_bytes() == before
    assert fake.calls == 1


def test_offline_read_discard_and_restart_preserve_receipt_and_usage_without_replay(governed):
    setup, job_id, _, fake, _ = governed
    producer = setup.classification
    accounting = setup.jobs.status()["accounting"]
    receipts = setup.jobs.journal.list_receipts()
    setup.jobs.current = None
    body = producer.read(job_id)[0]  # No consent/model renewal for a private read.
    assert body["classification_quality"] == "NOT_EVALUATED"
    producer.discard(job_id)
    producer.discard(job_id)
    assert not producer.path(job_id).exists()
    assert setup.jobs.status()["accounting"] == accounting
    assert setup.jobs.journal.list_receipts() == receipts
    with pytest.raises(MaintenanceTargetError):
        producer.read(job_id)
    assert fake.calls == 1
    # A new ordinary host can inspect attribution/remove absence without a provider.
    reopened = AiSetup(ProvelumeInstance(setup.instance.root))
    assert reopened.classification.reference(job_id)[0]["status"] == "succeeded"
    reopened.classification.discard(job_id)
    assert reopened.jobs.session_authorized is False
    reopened.close()


def test_invalid_paths_do_not_access_other_entries(governed):
    setup, job_id, _, _, _ = governed
    for bad in ("../outside", True, job_id + "/outside"):
        with pytest.raises(SchedulerError):
            setup.classification.path(bad)


def test_linked_record_safe_discard_unlinks_only_local_entry(governed, tmp_path):
    setup, job_id, _, _, _ = governed
    path = setup.classification.path(job_id)
    path.unlink()
    external = tmp_path / "external.json"
    external.write_bytes(b"synthetic external bytes")
    try:
        path.symlink_to(external)
    except OSError:
        pytest.skip("test host cannot create symlinks")
    with pytest.raises(MaintenanceTargetError):
        setup.classification.read(job_id)
    setup.classification.discard(job_id)
    assert not path.is_symlink()
    assert external.read_bytes() == b"synthetic external bytes"


def test_tampered_derived_bytes_fail_hash_check_but_remain_disposable(governed):
    setup, job_id, _, fake, _ = governed
    path = setup.classification.path(job_id)
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"NOT_EVALUATED", b"FAKE_EVIDENCE"))
    with pytest.raises((SchedulerError, ValueError)):
        setup.classification.read(job_id)
    setup.classification.discard(job_id)
    assert not path.exists() and fake.calls == 1


def test_action_center_projects_attribution_without_placement_authority(governed):
    from provelume.action_center import ActionCenter
    from provelume.action_center_adapters import domain_review_target

    setup, job_id, _, fake, _ = governed
    before = _snapshots(setup.instance.store)
    center = ActionCenter(setup.instance.store)
    rows = center.snapshot(queue="classification", state="all")["items"]
    item = next(r for r in rows if r["producer_id"] == "ai-classification:" + job_id)
    assert item["proposal"]["confidence"] is None
    assert item["evidence"]["classification_quality"] == "NOT_EVALUATED"
    assert item["evidence"]["automation_authorized"] is False
    assert item["allowed_actions"] == [] and domain_review_target(item) is None
    assert item["domain_links"][0]["href"] == f"/operations/ai/{job_id}/classification"
    setup.classification.discard(job_id)
    assert all(r["producer_id"] != "ai-classification:" + job_id
               for r in center.snapshot(queue="classification", state="all")["items"])
    assert fake.calls == 1 and _snapshots(setup.instance.store) == before


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
@pytest.mark.parametrize("interface", ["preview", "current"])
def test_read_remove_headers_csrf_and_catalogs_in_both_interfaces(
    governed, tmp_path, language, interface,
):
    import json
    from pathlib import Path

    setup, job_id, _, fake, _ = governed
    before = _snapshots(setup.instance.store)
    defaults = replace(default_settings(), instance_path=str(setup.instance.root),
                       language=language)
    manager = ShellSettingsManager(tmp_path / "shell.json", defaults)
    manager.save(defaults)
    if interface == "current":
        manager.set_interface_mode("current", expected_revision=0)
    app = create_app(setup.instance.root, shell_settings_file=manager.path)
    url = f"/operations/ai/{job_id}/classification"
    catalog = json.loads((Path(__file__).parents[1] / "core/provelume/i18n" /
                          (language + ".json")).read_text(encoding="utf-8"))
    with TestClient(app) as client:
        response = client.get(url, params={"lang": language})
        assert response.status_code == 200
        assert catalog["classification.title"] in unescape(response.text)
        assert catalog["classification.unqualified"] in unescape(response.text)
        assert "Work" in response.text and TEXT in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "/synthesis/execute" not in response.text and "/classify" not in response.text
        assert client.post(url + "/discard", data={
            **form(response), "csrf_token": "wrong",
        }).status_code == 403
        removed = client.post(url + "/discard", data=form(response))
        assert removed.status_code == 200
        assert catalog["classification.unavailable"] in unescape(removed.text)
        assert not setup.classification.path(job_id).exists()
    assert fake.calls == 1 and _snapshots(setup.instance.store) == before


@pytest.mark.parametrize("governed", [{"label": "<img src=x onerror=alert(1)>"}], indirect=True)
def test_untrusted_target_label_is_escaped(governed, tmp_path):
    setup, job_id, _, _, _ = governed
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    with TestClient(app) as client:
        response = client.get(f"/operations/ai/{job_id}/classification")
    assert response.status_code == 200
    assert "<img src=x onerror=alert(1)>" not in response.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in response.text


def test_stale_source_stays_removable_through_existing_form_authority(governed, tmp_path):
    setup, job_id, allowlist, _, _ = governed
    setup.instance.rename_hierarchy_node(allowlist[0][1], "Renamed")
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    url = f"/operations/ai/{job_id}/classification"
    with TestClient(app) as client:
        page = client.get(url)
        assert page.status_code == 200 and TEXT not in page.text
        assert client.post(url + "/discard", data=form(page)).status_code == 200
    assert not setup.classification.path(job_id).exists()


@pytest.mark.parametrize("governed", [
    {"raw": True, "failed": True, "changes": {"target": 99}},
    {"raw": True, "failed": True, "changes": {"confidence": 1}},
    {"raw": True, "failed": True, "changes": {"references": [99]}},
    {"raw": True, "failed": True, "changes": {"status": "apply"}},
    {"failed": True, "wrong_ref": True},
], indirect=True)
def test_invalid_output_or_unbound_inventory_settles_usage_without_proposal_or_retry(governed):
    setup, job_id, _, fake, _ = governed
    job = setup.jobs.journal.get_job(job_id)
    assert job["ai"]["blocked"] == "ai_result_invalid"
    assert job["ai"]["attempts"][0]["phase"] == "settled"
    assert job["ai"]["attempts"][0]["units"] == 12
    assert job["ai"]["result"] is None
    assert not setup.classification.path(job_id).exists()
    assert len(setup.jobs.journal.list_receipts()) == 1 and fake.calls == 1


@pytest.mark.parametrize("governed", [{"orphan": True, "failed": True}], indirect=True)
def test_interrupted_projection_requires_explicit_bound_cleanup_without_refund(governed):
    from provelume.ai_synthesis_recovery import candidate, discard

    setup, job_id, _, fake, _ = governed
    producer = setup.classification
    assert producer.path(job_id).exists()
    accounting = setup.jobs.status()["accounting"]
    receipts = setup.jobs.journal.list_receipts()
    observed = candidate(producer, job_id)
    with pytest.raises(SchedulerError):
        discard(producer, job_id, "0" * 64)
    assert producer.path(job_id).exists()
    discard(producer, job_id, observed["revision"])
    assert not producer.path(job_id).exists()
    assert setup.jobs.status()["accounting"] == accounting
    assert setup.jobs.journal.list_receipts() == receipts
    assert fake.calls == 1


@pytest.mark.parametrize("field,value", [("template", []), ("execution", {}),
                                         ("allowlist", [["area", {}]])])
def test_malformed_reference_values_fail_as_closed_data(governed, field, value):
    import copy

    from provelume.ai_classification_proposals import validate_reference

    setup, job_id, _, _, _ = governed
    reference = copy.deepcopy(setup.classification.reference(job_id)[1])
    if field == "execution":
        reference[field] = value
    else:
        reference["recipe"][field] = value
    with pytest.raises(ValueError):
        validate_reference(reference)


def test_record_review_adds_no_default_generation_or_apply_endpoint(governed, tmp_path):
    setup, job_id, _, fake, _ = governed
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    with TestClient(app) as client:
        for suffix in ("execute", "enqueue", "apply", "regenerate"):
            response = client.post(f"/operations/ai/{job_id}/classification/{suffix}")
            assert response.status_code == 404
    assert fake.calls == 1 and app.state.ai_setup.jobs.session_authorized is False
