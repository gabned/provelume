"""A slow explicit verification cannot overwrite a newer session/configuration choice."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from provelume.ai_runtime import LocalRuntime
from provelume.ai_runtime_contract import MODEL_ID
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
