"""A slow explicit verification cannot overwrite a newer session/configuration choice."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from provelume.ai_models import ModelError
from provelume.ai_runtime import LocalRuntime
from provelume.ai_runtime_contract import MODEL_ID
from provelume.ai_runtime_diagnostics import PHASES, native_failure, valid_native_failure
from provelume.ai_setup import AiSetup
from provelume.service import ProvelumeInstance


@pytest.fixture
def installed(tmp_path, monkeypatch):
    setup = AiSetup(ProvelumeInstance.initialise(tmp_path / "instance"))
    return setup, install_inert_model(setup, monkeypatch)


def install_inert_model(setup, monkeypatch):
    raw = b"GGUF\x03\0\0\0Public inert lifecycle fixture, never passed to a model."
    entry = replace(setup.models.registry.entry(MODEL_ID), model_size=len(raw),
                    model_sha256=hashlib.sha256(raw).hexdigest())
    setup.models._prepare()
    setup.models._path(entry).write_bytes(raw)
    monkeypatch.setattr(setup.models, "_entry", lambda *_: entry)
    monkeypatch.setattr(LocalRuntime, "validate_installation", lambda *_: None)

    def synthetic(runtime, *_args, **_kwargs):
        runtime.last_observation = {"load": {"limits": {
            "network_control": "seccomp:socket-syscalls-EPERM", "test_owned": True}}}
        return "PASSED"

    monkeypatch.setattr(LocalRuntime, "__call__", synthetic)
    return synthetic


def test_guided_action_explicitly_enables_local_only_for_current_session(installed):
    setup, _ = installed
    assert setup.configuration()["mode"] == "off"
    setup.run_operation(setup.begin_operation("enable_local"))
    assert setup.operation["state"] == "completed", setup.operation
    assert setup.models._state()["active"] == MODEL_ID
    assert setup.configuration()["mode"] == "local"
    assert setup.configuration()["revision"] == 1
    assert setup.jobs.status()["mode"] == "enabled"
    assert setup.jobs.session_authorized
    assert not setup.jobs.journal.list_jobs()
    assert not setup.instance.store.read_config()["network"]["external_access"]
    setup.close()
    restarted = AiSetup(ProvelumeInstance(setup.instance.root))
    assert not restarted.jobs.session_authorized


@pytest.mark.parametrize("change", ["off", "paused", "save", "revoked", "cancel", "close"])
def test_newer_authority_wins_during_guided_verification(installed, monkeypatch, change):
    setup, synthetic = installed
    setup.jobs.configure(mode="off", budget=setup.budget(setup.configuration()))
    entered, release = threading.Event(), threading.Event()

    def slow(runtime, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return synthetic(runtime, *args, **kwargs)

    monkeypatch.setattr(LocalRuntime, "__call__", slow)
    identity = setup.begin_operation("enable_local")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(setup.run_operation, identity)
        try:
            assert entered.wait(10)
            # Rendering and cancellation remain responsive during the heavy step.
            assert setup.read()["operation"]["state"] == "running"
            if change in {"off", "paused"}:
                setup.control(change, 0)
            elif change == "save":
                setup.save({"period_units": 90000}, 0)
            elif change == "revoked":
                setup.models.allowed_ids = ()
            elif change == "cancel":
                setup.cancel_operation(identity)
            else:
                setup.request_close()
        finally:
            release.set()
        future.result(timeout=10)
    assert setup.operation["state"] in {"failed", "cancelled"}
    assert setup.models._state()["active"] is None
    assert setup.configuration()["mode"] == "off"
    assert setup.jobs._control()["mode"] == ("paused" if change == "paused" else "off")
    assert not setup.jobs.session_authorized
    assert not setup.jobs.journal.list_jobs()


def test_explicit_self_test_alone_never_enables_or_activates(installed):
    setup, _ = installed
    setup.run_operation(setup.begin_operation("self_test"))
    assert setup.operation["state"] == "completed"
    assert setup.models._state()["active"] is None
    assert setup.configuration()["mode"] == "off"
    assert not setup.jobs.session_authorized


@pytest.mark.parametrize("observation,stage,code", [
    (None, None, None),
    (native_failure({"phase": "hardware-admission", "native_stage": "public-inventory",
                     "native_code": 5}, code="timeout"), "public-inventory", 5),
    (native_failure({"phase": "hardware-admission", "native_code": 0}, code="timeout"),
     "hardware-admission", 0),
    ({**native_failure({}, code="timeout"), "private": "DoNotPublishPrivateText"}, None, None),
    ({**native_failure({}, code="timeout"), "native_code": True}, None, None),
    *[(native_failure({"phase": phase}, code="timeout"), phase, None)
      for phase in sorted(PHASES - {"hardware-admission"})],
])
def test_failed_operation_uses_only_its_exception_observation(
    installed, monkeypatch, observation, stage, code,
):
    import copy
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    import provelume.ai_setup as module
    from scripts.custodia_ordinary import Page

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from scripts.qualify_custodia_installed import summary

    setup, _ = installed
    stale = native_failure({"phase": "hardware-admission", "native_code": 203}, code="timeout")
    setup.runtime.last_observation = stale

    def fail_before_runner(*args, **kwargs):
        # Even a newly allocated ambient observation belongs to another call.
        setup.runtime.last_observation = dict(stale)
        error = ModelError("timeout")
        if observation is not None:
            error.runtime_observation = copy.deepcopy(observation)
        raise error

    monkeypatch.setattr(setup.models, "self_test", fail_before_runner)
    setup.run_operation(setup.begin_operation("self_test"))
    operation = setup.operation
    assert operation["state"] == "failed" and operation["error"] == "timeout"
    assert operation.get("diagnostic_stage") == stage
    assert operation.get("native_code") == code
    assert "DoNotPublishPrivateText" not in str(operation)
    assert setup.runtime.last_observation == stale
    assert setup.models._state()["active"] is None
    assert not setup.jobs.session_authorized and not setup.jobs.journal.list_jobs()
    environment = Environment(
        loader=FileSystemLoader(str(Path(module.__file__).parent / "templates")), autoescape=True)
    markup = environment.get_template("ai_model_progress.html").render(
        ai={"operation": operation, "model_actions": []},
        t=lambda key: key, ui_number=lambda value, digits: str(value))
    projected = Page(markup).operation
    assert projected["diagnostic-stage"] == (stage or "")
    report = {"status": "FAIL", "phase": "parent_death_prepare", "checks": [],
              "failure_type": "ValueError", "failure_code": "model_operation",
              "operation_history": [projected]}
    failed = summary(report)["failed_model_operation"]
    assert failed.get("diagnostic_stage") == stage
    assert failed.get("native_code") == code
    assert "DoNotPublishPrivateText" not in str(failed)


@pytest.mark.parametrize("point", [
    "admission", "model_verification", "runtime", "result_validation",
    "final_verification", "evidence",
])
def test_self_test_failure_owns_its_lifecycle_phase_without_ambient_native_data(
    installed, monkeypatch, point,
):
    from provelume.ai_runtime import native_selection

    setup, synthetic = installed
    stale = native_failure({"native_stage": "public-inventory", "native_code": 203},
                           code="timeout")
    setup.runtime.last_observation = stale
    calls = []
    original_verify = setup.models._verify

    def fail(*args, **kwargs):
        error = ModelError("timeout")
        if point != "runtime":
            error.runtime_observation = dict(stale)
        raise error

    def verify(*args, **kwargs):
        calls.append("verify")
        if ((point == "model_verification" and calls.count("verify") == 1)
                or (point == "final_verification" and calls.count("verify") == 2)):
            fail()
        return original_verify(*args, **kwargs)

    def run(runtime, *args, **kwargs):
        calls.append("runtime")
        if point == "runtime":
            fail()
        if point == "result_validation":
            return "DoNotPublishPrivateResult"
        return synthetic(runtime, *args, **kwargs)

    monkeypatch.setattr(setup.models, "_verify", verify)
    monkeypatch.setattr(LocalRuntime, "__call__", run)
    if point == "admission":
        monkeypatch.setattr(setup.models, "_entry", fail)
    if point == "evidence":
        monkeypatch.setattr(setup.models, "_binding", fail)
    with pytest.raises(ModelError) as failure:
        setup.models.self_test(MODEL_ID, native_selection(), setup.runtime, requested=True)
    observed = failure.value.runtime_observation
    assert valid_native_failure(observed)
    assert observed["phase"] == "self_test_" + point
    assert observed["native_stage"] is observed["native_code"] is None
    assert "public_inventory" not in observed
    assert observed["model_code"] == ("self_test" if point == "result_validation" else "timeout")
    assert "DoNotPublishPrivateResult" not in str(observed) + str(failure.value)
    assert calls.count("runtime") == (0 if point in {"admission", "model_verification"} else 1)
    assert not setup.models._evidence and not setup.models._native_runners
    assert not setup.jobs.session_authorized and not setup.jobs.journal.list_jobs()


@pytest.mark.parametrize("phase", ["model_load", "native_prefill", "native_decode"])
def test_self_test_preserves_the_current_runtime_exception_phase(installed, monkeypatch, phase):
    from provelume.ai_runtime import native_selection

    setup, _ = installed
    owned = native_failure({"phase": phase}, code="timeout")
    stale = native_failure({"native_stage": "process-create", "native_code": 203},
                           code="compatibility")
    setup.runtime.last_observation = stale

    def fail(*args, **kwargs):
        error = ModelError("timeout")
        error.runtime_observation = dict(owned)
        raise error

    monkeypatch.setattr(LocalRuntime, "__call__", fail)
    with pytest.raises(ModelError, match="timeout") as failure:
        setup.models.self_test(MODEL_ID, native_selection(), setup.runtime, requested=True)
    assert failure.value.runtime_observation == owned
    assert failure.value.runtime_observation is not owned
    assert setup.runtime.last_observation == stale
    assert not setup.models._evidence and not setup.models._native_runners


@pytest.mark.parametrize("profiled", [False, True])
def test_owned_public_inventory_observation_reaches_existing_operation_markup(
    installed, monkeypatch, profiled,
):
    import json
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    import provelume.ai_setup as module
    from scripts.custodia_ordinary import Page

    setup, _ = installed
    progress = {
        "stage": "hash-file", "elapsed_ms": 300, "stage_elapsed_ms": 100,
        "budget_at_entry_ms": 40000, "budget_remaining_ms": 39700,
        "files_total": 3, "files_verified": 1, "bytes_hashed": 1024,
        "grants_total": 7, "grants_completed": 0,
    }
    if profiled:
        progress.update(checkpoint_calls=4, checkpoint_elapsed_ms=123, acl_elapsed_ms=0,
                        **{f"checkpoint_{part}_elapsed_ms": 10
                           for part in ("configuration", "control", "models", "selection")})
    owned = native_failure({"native_stage": "public-inventory", "native_code": 0,
                            "public_inventory": progress}, code="timeout")
    ambient = native_failure({"native_stage": "process-create", "native_code": 203},
                             code="compatibility")
    setup.runtime.last_observation = ambient

    def fail(*args, **kwargs):
        error = ModelError("timeout")
        error.runtime_observation = owned
        raise error

    monkeypatch.setattr(setup.models, "self_test", fail)
    setup.run_operation(setup.begin_operation("self_test"))
    operation = setup.operation
    assert operation["public_inventory"] == progress
    assert operation["public_inventory"] is not owned["public_inventory"]
    assert setup.runtime.last_observation == ambient
    snapshot = setup.read()["operation"]
    assert snapshot["public_inventory"] == progress
    snapshot["public_inventory"]["files_verified"] = 2
    assert operation["public_inventory"] == progress
    assert setup.read()["operation"]["public_inventory"] == progress
    environment = Environment(
        loader=FileSystemLoader(str(Path(module.__file__).parent / "templates")), autoescape=True)
    markup = environment.get_template("ai_model_progress.html").render(
        ai={"operation": operation, "model_actions": []},
        t=lambda key: key, ui_number=lambda value, digits: str(value))
    projected = Page(markup).operation
    assert projected["diagnostic-stage"] == "public-inventory"
    assert projected["native-code"] == "0"
    assert json.loads(projected["public-inventory"]) == progress
    assert setup.models._state()["active"] is None
    assert not setup.jobs.session_authorized and not setup.jobs.journal.list_jobs()


@pytest.mark.parametrize("action", ["runtime", "deactivate", "remove", "recover"])
def test_newer_control_at_publication_fences_setup_mutations(installed, monkeypatch, action):
    setup, _ = installed
    setup.jobs.configure(mode="off", budget=setup.budget(setup.configuration()))
    if action == "deactivate":
        setup.models._write_state({"schema_version": 1, "active": MODEL_ID, "previous": None})
    path = setup.models._path(setup.models.registry.entry(MODEL_ID))
    before_bytes, before_state, runtime = path.read_bytes(), setup.models._state(), setup.runtime
    touched = []
    original_change = setup.jobs.change_authority
    original_configure = setup.jobs.configure

    def newer_control():
        touched.append(True)
        original_configure(mode="off")

    def change(callback, **kwargs):
        newer_control()
        return original_change(callback, **kwargs)

    def configure(*, before=None, **kwargs):
        if before is not None:
            newer_control()
        return original_configure(before=before, **kwargs)

    monkeypatch.setattr(setup.jobs, "change_authority", change)
    monkeypatch.setattr(setup.jobs, "configure", configure)
    setup.run_operation(setup.begin_operation(action), path=path.parent)
    assert touched == [True]
    assert setup.operation["state"] == "failed"
    assert setup.models._state() == before_state
    assert path.read_bytes() == before_bytes
    assert setup.runtime is runtime
    assert setup.jobs._control()["mode"] == "off"
    assert not setup.jobs.session_authorized


def test_successful_inference_without_isolation_never_grants_locality(installed, monkeypatch):
    setup, _ = installed

    def unconfined(runtime, *_args, **_kwargs):
        runtime.last_observation = {"load": {"limits": {"network_control": "NONE"}}}
        return "PASSED"

    monkeypatch.setattr(LocalRuntime, "__call__", unconfined)
    setup.run_operation(setup.begin_operation("self_test"))
    assert setup.operation["state"] == "completed"
    assert setup.self_test_evidence.result == "PASSED"
    assert setup.local_evidence is None
    assert not setup.read()["locality_verified"]
    assert "activate" not in setup.model_actions()
    setup.run_operation(setup.begin_operation("enable_local"))
    assert setup.operation["state"] == "failed"
    assert setup.models._state()["active"] is None
    assert setup.configuration()["mode"] == "off"
    assert not setup.jobs.session_authorized


def test_displayed_setup_authority_rejects_a_newer_configuration(installed):
    setup, _ = installed
    displayed = setup.model_authority()
    setup.save({"period_units": 90000}, 0)
    with pytest.raises(ValueError, match="ai_setup_stale"):
        setup.begin_operation("enable_local", expected_authority=displayed)
    assert setup.operation is None
    assert not setup.jobs.session_authorized


def test_removal_targets_the_displayed_retired_installation(installed):
    setup, _ = installed
    current = setup.models._path(setup.models.registry.entry(MODEL_ID)).read_bytes()
    retired = next(row for row in setup.models.registry.entries if row.qualification == "RETIRED")
    path = setup.models._path(retired)
    path.write_bytes(b"Public inert retired installation for deletion test")
    setup.run_operation(setup.begin_operation("remove:" + retired.id,
                                               expected_authority=setup.model_authority()))
    assert setup.operation["state"] == "completed"
    assert not path.exists()
    assert setup.models._path(setup.models.registry.entry(MODEL_ID)).read_bytes() == current
    with pytest.raises(ValueError):
        setup.begin_operation("remove:../../outside")
