"""Synthetic component observations, never evidence about a past Windows host."""

import json
import threading
from contextlib import ExitStack
from types import SimpleNamespace

import pytest

from provelume import ai_setup_lifecycle as lifecycle
from provelume import ai_windows_package as package
from provelume.ai_runtime_diagnostics import public_inventory_observation

PARTS = ("configuration", "control", "models", "selection")
FIELDS = tuple(f"checkpoint_{part}_elapsed_ms" for part in PARTS)


@pytest.fixture
def observation():
    return {
        "stage": "grant-acl", "elapsed_ms": 1000, "stage_elapsed_ms": 10,
        "budget_at_entry_ms": 40000, "budget_remaining_ms": 39000,
        "files_total": 3, "files_verified": 3, "bytes_hashed": 1024,
        "grants_total": 7, "grants_completed": 1,
        "checkpoint_calls": 12, "checkpoint_elapsed_ms": 800, "acl_elapsed_ms": 1,
        **dict(zip(FIELDS, (100, 200, 300, 50), strict=True)),
    }


def test_complete_authority_measurements_and_historical_shapes_remain_distinct(observation):
    assert public_inventory_observation(observation) == observation
    for field in FIELDS:
        partial = dict(observation)
        partial.pop(field)
        assert public_inventory_observation(partial) is None
    historical = {k: v for k, v in observation.items() if k not in FIELDS}
    assert public_inventory_observation(historical) == historical
    for key in ("checkpoint_calls", "checkpoint_elapsed_ms", "acl_elapsed_ms"):
        historical.pop(key)
    assert public_inventory_observation(historical) == historical


@pytest.mark.parametrize("mutation", [
    {FIELDS[0]: True}, {FIELDS[1]: -1}, {FIELDS[2]: 86400001},
    {FIELDS[3]: 300}, {"private_path": "DoNotPublish"},
    {"checkpoint_calls": 0},
])
def test_invalid_or_overlapping_authority_measurements_are_rejected(observation, mutation):
    assert public_inventory_observation({**observation, **mutation}) is None


def test_real_authority_evaluations_are_measured_once_in_original_order(monkeypatch):
    from provelume.ai_authority_observation import observe_authority

    clock = [0.0]
    monkeypatch.setattr(package, "monotonic", lambda: clock[0])
    progress = package._PublicInventoryObservation(60)
    calls, values = [], {part: object() for part in PARTS}

    def read(part, elapsed):
        def current():
            calls.append(part)
            clock[0] += elapsed
            return values[part]
        return current

    setup = SimpleNamespace(configuration=read("configuration", .1),
                            jobs=SimpleNamespace(_control=read("control", .2),
                                                 session_authorized=False),
                            models=SimpleNamespace(_state=read("models", .3), allowed_ids=("id",)),
                            runtime=object())
    monkeypatch.setattr(lifecycle, "native_selection", read("selection", .05))
    with progress.measuring("checkpoint"), observe_authority(progress):
        result = lifecycle.authority(setup)
    assert calls == list(PARTS)
    assert all(result[part] is values[part] for part in PARTS)
    measured = progress.snapshot()
    assert all(abs(measured[field] - expected) <= 1 for field, expected in
               zip(FIELDS, (100, 200, 300, 50), strict=True))
    assert measured["checkpoint_calls"] == 1
    assert result["runtime"] is setup.runtime and result["allowed"] == ("id",)
    # The next fresh read outside this scope cannot change this observation.
    lifecycle.authority(setup)
    assert calls == list(PARTS) * 2
    assert all(progress.snapshot()[field] == measured[field] for field in FIELDS)


def test_component_exception_and_native_error_survive_failed_observation(monkeypatch):
    from provelume.ai_authority_observation import authority_value, observe_authority

    native = [0]
    monkeypatch.setattr(package, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(package.c, "get_last_error", lambda: native[0], raising=False)
    monkeypatch.setattr(package.c, "set_last_error", lambda value: native.__setitem__(0, value),
                        raising=False)
    progress = package._PublicInventoryObservation(60)
    original = OSError("DoNotPublishPrivateFailure")
    calls = []

    def read():
        calls.append(True)
        native[0] = 203
        raise original

    def broken(*_args):
        native[0] = 5
        raise RuntimeError("DoNotPublishObservationFailure")

    monkeypatch.setattr(progress, "_record_time", broken)
    with pytest.raises(OSError) as failure, observe_authority(progress):
        authority_value("configuration", read)
    assert failure.value is original and native[0] == 203 and calls == [True]
    assert not set(FIELDS) & progress.snapshot().keys()
    assert "DoNotPublish" not in json.dumps(progress.snapshot())


def test_authority_observation_context_does_not_leak_between_threads_or_after_failure():
    from provelume.ai_authority_observation import authority_value, observe_authority

    progress = package._PublicInventoryObservation(60)
    observed = []

    def read():
        observed.append(True)
        return False

    with pytest.raises(ValueError), observe_authority(progress):
        thread = threading.Thread(target=lambda: authority_value("configuration", read))
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert not set(FIELDS) & progress.snapshot().keys()
        raise ValueError("synthetic")
    assert authority_value("configuration", read) is False and observed == [True, True]
    assert not set(FIELDS) & progress.snapshot().keys()


def test_public_inventory_observer_scope_preserves_call_and_cleanup_sequence(monkeypatch):
    from provelume.ai_authority_observation import authority_value

    original = OSError("DoNotPublish")

    def pin(_stack, _executable, _sid, *, cancel, deadline, progress):
        assert cancel is token and deadline == 60
        with progress.measuring("checkpoint"):
            authority_value("configuration", lambda: None)
        raise original

    token = object()
    monkeypatch.setattr(package, "_pin_public_package", pin)
    with pytest.raises(OSError) as failure, ExitStack() as stack:
        package.pin_public_package(stack, None, None, cancel=token, deadline=60)
    assert failure.value is original
    progress = failure.value.public_inventory
    assert set(FIELDS) <= progress.keys() and progress["checkpoint_calls"] == 1
    assert "DoNotPublish" not in json.dumps(progress)


def test_nested_checkpoint_observations_are_independent_and_restore_the_outer_scope():
    from provelume.ai_authority_observation import authority_value

    outer = package._PublicInventoryObservation(60)
    inner = package._PublicInventoryObservation(60)
    with outer.measuring("checkpoint"):
        authority_value("configuration", lambda: None)
        with inner.measuring("checkpoint"):
            authority_value("control", lambda: None)
        authority_value("models", lambda: None)
    assert outer.authority_observed and inner.authority_observed
    assert outer.timings["authority_control"] == 0
    assert inner.timings["authority_configuration"] == inner.timings["authority_models"] == 0
    assert outer.snapshot()["checkpoint_calls"] == inner.snapshot()["checkpoint_calls"] == 1


def test_failed_component_start_clock_still_performs_the_fresh_read_once(monkeypatch):
    from provelume.ai_authority_observation import authority_value, observe_authority

    progress = package._PublicInventoryObservation(60)
    clocks, reads = [], []

    def clock():
        clocks.append(True)
        if len(clocks) == 1:
            raise RuntimeError("DoNotPublishClockFailure")
        return 1.0

    monkeypatch.setattr(package, "monotonic", clock)
    with observe_authority(progress):
        result = authority_value("configuration", lambda: reads.append(True))
    assert result is None and reads == [True] and clocks == [True]
    assert not set(FIELDS) & progress.snapshot().keys()
