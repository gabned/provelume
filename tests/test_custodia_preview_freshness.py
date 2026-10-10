"""Explicit renewal preserves the original consent boundary and full source binding."""

import time
from dataclasses import replace

import pytest
from test_ai_synthesis import preview, synthesis  # noqa: F401
from test_custodia_guided_setup import install_inert_model

from provelume.ai_runtime import LocalRuntime
from provelume.ai_runtime_contract import MODEL_ID


def expire(setup):
    evidence = replace(setup.self_test_evidence, expires=time.monotonic() - 1)
    setup.self_test_evidence = setup.models._evidence[MODEL_ID] = evidence


@pytest.fixture
def ready(synthesis, monkeypatch):  # noqa: F811
    setup = synthesis[0]
    runner = install_inert_model(setup, monkeypatch)
    setup.run_operation(setup.begin_operation("self_test"))
    assert setup.operation["state"] == "completed"
    return synthesis, runner


def test_verify_and_generate_renews_only_the_original_planned_preview(ready):
    fixture, _ = ready
    setup = fixture[0]
    ref, prepared, _ = preview(fixture)
    expire(setup)
    with pytest.raises(ValueError):
        setup.approve(ref)  # Ordinary consent, GET and enqueue cannot renew proof.
    setup.approve_generation(ref)
    assert setup.previews[ref]["prepared"] is prepared
    assert setup.previews[ref]["approved"] is True
    assert setup.previews[ref]["job"] is None
    assert not setup.jobs.journal.list_jobs()
    assert setup.self_test_evidence.expires > time.monotonic()


def test_denied_preview_needs_a_new_preview_and_new_consent(ready):
    fixture, _ = ready
    setup = fixture[0]
    expire(setup)
    ref, denied, _ = preview(fixture, task="key-points", language="it")
    assert denied[1].outcome != "planned"
    with pytest.raises(ValueError):
        setup.approve_generation(ref)
    new_ref, prepared, _ = setup.verify_preview(ref, fresh=True)
    assert new_ref != ref and prepared[1].outcome == "planned"
    assert prepared[0].manifest.template.id == "key-points-it-v1"
    assert not setup.previews[new_ref]["approved"]
    assert not setup.previews[ref]["approved"]
    with pytest.raises(ValueError):
        setup.approve(ref)
    assert not setup.jobs.journal.list_jobs()


@pytest.mark.parametrize("change", ["source", "config", "off", "paused", "policy", "proof"])
def test_renewal_cannot_authorize_a_changed_preview(ready, monkeypatch, change):
    fixture, runner = ready
    setup, document, bundle = fixture
    ref, _, _ = preview(fixture)
    expire(setup)

    def during_verification(runtime, *args, **kwargs):
        result = runner(runtime, *args, **kwargs)
        if change == "source":
            path = setup.instance.root / bundle["outputs"][0]["storage_ref"]
            path.write_text("A changed public source.")
        elif change == "config":
            setup.save({"period_units": 90000}, setup.configuration()["revision"])
        elif change in {"off", "paused"}:
            setup.control(change, setup.configuration()["revision"])
        elif change == "policy":
            setup.synthesis.restrict(document, "instance", setup.instance_id, "deny", 0)
        else:
            runtime.last_observation["load"]["limits"]["changed_proof"] = True
        return result

    monkeypatch.setattr(LocalRuntime, "__call__", during_verification)
    with pytest.raises(ValueError):
        setup.approve_generation(ref)
    assert not setup.jobs.journal.list_jobs()
    assert ref not in setup.previews or not setup.previews[ref]["approved"]
