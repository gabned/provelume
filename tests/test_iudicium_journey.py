"""Whole synthetic journeys through the actual services; no accuracy scoring."""

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from ai_context_fakes import context_plan
from ai_provider_fakes import provider_case
from fastapi.testclient import TestClient

from provelume.ai_context import Selection, preview_context, validate_candidate
from provelume.ai_contract import Capability, Mode, PolicyRule, Scope, ScopeRef, digest
from provelume.ai_job_contract import Budget
from provelume.ai_job_runtime import JobOutcome
from provelume.ai_setup import AiSetup
from provelume.representations import canonical_json_bytes
from provelume.review_integrity import review_state_findings
from provelume.service import ProvelumeInstance
from provelume.shell_settings import ShellSettingsManager, default_settings
from provelume.web import create_app
from scripts.ai_runtime_report import evaluate
from scripts.iudicium_journey import (
    FINAL_CHECKS,
    INPUTS_SHA256,
    ROW_CHECKS,
    finish,
    prepare,
    review_assessment,
)

BUDGET = Budget(100000, 1000000)


def execute_synthetic(setup, case, area, selected):
    """Existing test-only adapter and privacy/context planner on the acquired bundle."""
    instance, bundle = setup.instance, case["bundle"]
    document = case["document_id"]
    targets = instance.ai_classification_targets(document, (("area", area["id"]),))
    _, _, source = setup.synthesis.source(document, bundle["representation_id"],
                                          bundle["outputs"][0]["id"])
    selections = (Selection(source.version, bundle["representation_id"], digest(bundle),
                            bundle["outputs"][0]["id"], bundle["anchors"][0]["id"],
                            0, len(case["text"])),)
    base = provider_case(text=case["text"])
    current = dict(base.current)
    scopes = (ScopeRef(Scope.INSTANCE, targets.instance_id),
              ScopeRef(Scope.SOURCE, targets.source_id),
              ScopeRef(Scope.CATEGORY, "public_synthetic_classification"))
    current["snapshot"] = replace(
        current["snapshot"], scopes=scopes,
        context=replace(current["snapshot"].context, instance_id=targets.instance_id,
                        document_id=document, version_id=case["version_id"]),
    )
    current["rules"] = tuple(PolicyRule(
        scope, digest("synthetic-only-source-policy"),
        mode=Mode.LOCAL_ONLY if i == 0 else None,
        allowed_profiles=(base.profiles[0].id,) if i == 0 else None,
        allowed_capabilities=(Capability.STRUCTURED_OUTPUT,) if i == 0 else None,
        limits=current["request_limits"] if i == 0 else None,
        route=(base.profiles[0].id,) if i == 0 else (),
    ) for i, scope in enumerate(scopes))
    current["template"] = targets.template(case["language"])
    preview = preview_context(source, selections, **current)
    plan = context_plan(preview, source, selections, current,
                        {"profiles": base.profiles, "evidence": base.evidence})
    prepared = replace(base, source=source, selections=selections, current=current,
                       preview=preview, plan=plan)
    from provelume.ai_classification_proposals import classification_request_ref

    ref = classification_request_ref(preview, targets)

    class Synthetic:
        network_used = False
        calls = 0

        def exchange(self, callback, *, cancel):
            self.calls += 1
            inputs = callback()
            inputs.prepare()
            assert not cancel()
            raw = canonical_json_bytes({
                "schema_version": 1, "preview_fingerprint": inputs.preview.fingerprint,
                "status": "selected" if selected else "abstained",
                "references": [0] if selected else [], "target": 0 if selected else None,
            })
            candidate = validate_candidate(raw, inputs.preview, source, selections, **current)
            return JobOutcome({"kind": "context_check", "value": candidate.as_record()},
                              units=12, micros=0, usage_source="LOCAL")

    fake = Synthetic()

    def live(request_ref, route):
        assert request_ref == ref
        targets.revalidate(instance.store)
        return replace(prepared, route_index=route)

    jobs = instance.bind_ai_execution(current=live,
                                      adapters={base.profiles[0].fingerprint: fake},
                                      result_projector=setup.project_result)
    setup.jobs = jobs
    jobs.configure(mode="enabled", budget=BUDGET)
    job = jobs.enqueue(ref, request_key="explicit-synthetic-" + case["language"], budget=BUDGET)
    assert instance.run_ai_job(job["id"])["status"] == "succeeded"
    body = setup.classification.read(job["id"])[0]
    assert body["classification_quality"] == "NOT_EVALUATED"
    assert body["confidence"] is None and body["automation_authorized"] is False
    assert review_assessment(instance, case, job["id"], body, area["id"]) == (
        "REVIEWED_APPLIED_UNDONE" if selected else "NOT_APPLICABLE_ABSTENTION")
    accounting = jobs.status()["accounting"]
    setup.classification.discard(job["id"])
    assert not setup.classification.path(job["id"]).exists()
    assert setup.classification.reference(job["id"])[0]["status"] == "succeeded"
    assert jobs.status()["accounting"] == accounting
    assert fake.calls == 1
    return job["id"]


@pytest.mark.parametrize("mode", ["inherited", "preview", "current"])
@pytest.mark.parametrize("selected", [False, True], ids=["abstained", "selected"])
def test_complete_folder_to_knowledge_in_both_shells(tmp_path, mode, selected):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    cases = prepare(tmp_path, instance)
    assert len(cases) == 2
    assert len(instance.scheduler.journal.list_jobs(limit=100)) == 8
    assert instance.ai_jobs.status()["mode"] == "off"
    area = instance.create_hierarchy_node("area", "Public synthetic Atlas")
    setup = AiSetup(instance)
    try:
        ids = [execute_synthetic(setup, case, area, selected) for case in cases]
    finally:
        setup.close()
    report = finish(instance, cases)
    assert all(report[key] is True for key in FINAL_CHECKS)
    assert report["inputs_sha256"] == INPUTS_SHA256
    assert len(instance.store.list_canonical("versions")) == 2
    assert set(ids) <= {r["job_id"] for r in instance.ai_jobs.journal.list_receipts()}
    assert review_state_findings(instance.store, {}) == []
    settings = tmp_path / "shell.json"
    manager = ShellSettingsManager(settings, default_settings())
    if mode != "inherited":
        manager.set_interface_mode(mode, expected_revision=0)
    before = settings.read_bytes() if settings.exists() else None
    app = create_app(instance.root, shell_settings_file=settings)
    with TestClient(app) as client:
        for language in ("en", "it", "de", "es", "fr", "pt", "ro"):
            for url in ("/review/processing", "/review/iudicium"):
                page = client.get(url, params={"lang": language})
                assert page.status_code == 200
                assert page.headers["cache-control"] == "no-store"
    assert (settings.read_bytes() if settings.exists() else None) == before
    assert manager.load().settings.interface_mode == ("preview" if mode == "inherited" else mode)
    assert ProvelumeInstance(instance.root).ai_jobs.status()["mode"] == "off"


def test_capture_rejects_a_live_ai_session_before_creating_sources(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ai_jobs.configure(mode="enabled", budget=BUDGET)
    with pytest.raises(ValueError, match="journey_ai_must_start_off"):
        prepare(tmp_path, instance)
    assert instance.list_sources() == []


def test_report_requires_each_whole_journey_observation_and_retains_abstention():
    assert INPUTS_SHA256 == "6f77ac2a0c1b9ede128a823f8ac2a2457e21695ca5048ef50e44c3ebb7304d4b"
    row = {"status": "succeeded", "assessment": "abstained", "quality": "NOT_EVALUATED",
           "confidence": None, "application_authorized": False, "receipt_bound": True,
           "discarded": True, "source_preserved": True, "accounting_preserved": True,
           "journey": {**dict.fromkeys(ROW_CHECKS, True), "inputs_sha256": INPUTS_SHA256,
                       "destination_review": "NOT_APPLICABLE_ABSTENTION"}}
    report = {"samples": [], "failures": [], "iudicium_execution_required": True,
              "iudicium_execution": {"status": "MEASURED", "worker_absent": True,
                "final_off": True, "journey": {"status": "MEASURED",
                    "inputs_sha256": INPUTS_SHA256, **dict.fromkeys(FINAL_CHECKS, True)},
                "samples": [dict(deepcopy(row), language="en"),
                            dict(deepcopy(row), language="it")]}}

    def gate(value):
        return evaluate(value)["gates"]["iudicium_execution_conformance"]

    assert gate(deepcopy(report)) == "PASS"
    for key in FINAL_CHECKS:
        changed = deepcopy(report)
        del changed["iudicium_execution"]["journey"][key]
        assert gate(changed) == "FAIL", key
    for key in (*ROW_CHECKS, "inputs_sha256", "destination_review"):
        changed = deepcopy(report)
        del changed["iudicium_execution"]["samples"][0]["journey"][key]
        assert gate(changed) == "FAIL", key
    changed = deepcopy(report)
    changed["iudicium_execution"]["samples"][0]["assessment"] = "selected"
    assert gate(changed) == "FAIL"
    changed["iudicium_execution"]["samples"][0]["journey"]["destination_review"] = (
        "REVIEWED_APPLIED_UNDONE")
    assert gate(changed) == "PASS"


def test_independent_network_report_entrypoint_needs_no_ambient_import_path(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"samples": [], "failures": [],
                                  "iudicium_execution_required": True}))
    script = Path(__file__).resolve().parents[1] / "scripts/ai_runtime_network.py"
    observed = subprocess.run([sys.executable, "-I", str(script), "--report", str(report)],
                              cwd=tmp_path, capture_output=True, text=True, check=False)
    assert observed.returncode == 1
    assert observed.stderr == ""
    retained = json.loads(report.read_text())
    assert retained["network"] == "NOT_RUN"
    assert retained["gates"]["iudicium_execution_conformance"] == "NOT_RUN"
