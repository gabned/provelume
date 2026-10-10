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
    return setup, synthetic


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
