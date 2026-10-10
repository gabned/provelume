"""Explicit setup authority across cancellable heavy local-model operations."""

from __future__ import annotations

from .ai_contract import digest
from .ai_job_contract import check
from .ai_model_download import checkpoint
from .ai_model_file import ReadAuthority
from .ai_runtime import native_selection
from .ai_runtime_contract import MODEL_ID


def authority(setup):
    return {
        "configuration": setup.configuration(),
        "control": setup.jobs._control(),
        "session": setup.jobs.session_authorized,
        "models": setup.models._state(),
        "selection": native_selection(),
        "runtime": setup.runtime,
        "allowed": tuple(setup.models.allowed_ids),
    }


def require_current(setup, operation):
    check(setup.operation is operation and operation["state"] == "running",
          "ai_setup_stale")
    checkpoint(setup.cancel.is_set, float("inf"))
    check(authority(setup) == setup._operation_authority, "ai_setup_stale")


def cancelled(setup, operation):
    require_current(setup, operation)
    return False


def record_evidence(setup, operation, evidence):
    observation = setup.runtime.last_observation or {}
    proof = observation.get("load", {}).get("limits", {})
    check(evidence.result == "PASSED", "ai_locality_unqualified")
    confined = proof.get("network_control") in {
        "seccomp:socket-syscalls-EPERM", "AppContainer:no-capabilities-no-loopback-exemption",
    }
    with setup.lock:
        require_current(setup, operation)
        setup.self_test_evidence = evidence
        # A native self-test can succeed without establishing network isolation.
        # Retain its measurement, but never grant locality or activation from it.
        setup.local_evidence = digest(proof) if confined else None


def enable_local(setup, operation, evidence):
    """Only the explicitly labelled operation may configure and enable a session."""
    check(setup.local_evidence is not None, "ai_locality_unqualified")
    snapshot = setup._operation_authority
    updated = {**snapshot["configuration"], "mode": "local",
               "revision": snapshot["configuration"]["revision"] + 1}
    setup.validate(updated, setup.instance_id)

    def commit(write):
        with setup.lock:
            def publish():
                require_current(setup, operation)
                write()
                setup.instance.store._atomic_json(setup.path, updated)
                setup.previews.clear()

            # This is the same transaction as normal session controls. A newer
            # Off/Pause/configuration wins over the earlier asynchronous request.
            setup.jobs.configure(mode="enabled", budget=setup.budget(updated), before=publish)
            setup.bind_adapters(updated)

    setup.models.activate(
        MODEL_ID, native_selection(), evidence, requested=True,
        cancel=ReadAuthority(lambda: cancelled(setup, operation), immediate=setup.cancel.is_set),
        commit=commit,
    )
