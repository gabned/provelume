"""Public filesystem stand-ins and closed projections, never Windows qualification."""

import copy
import json
import os
import time
from contextlib import ExitStack, contextmanager
from html import escape
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from provelume import ai_windows_package as package
from provelume.ai_models import ModelError
from provelume.ai_runtime_diagnostics import (
    model_operation_snapshot,
    native_failure,
    public_inventory_observation,
    valid_native_failure,
)


@pytest.fixture
def observation():
    return {
        "stage": "hash-file", "elapsed_ms": 300, "stage_elapsed_ms": 100,
        "budget_at_entry_ms": 40000, "budget_remaining_ms": 39700,
        "files_total": 3, "files_verified": 1, "bytes_hashed": 1024,
        "grants_total": 7, "grants_completed": 0,
    }


@pytest.fixture
def public_package(tmp_path, monkeypatch):
    from provelume import ai_windows_acl as acl

    root = tmp_path / "public-stand-in"
    (root / "_internal/provelume").mkdir(parents=True)
    executable = root / "Provelume.exe"
    executable.write_bytes(b"public stand-in, never executed")
    (root / "_internal/provelume/a.json").write_bytes(b'{"public":true}')
    (root / "_internal/provelume/b.json").write_bytes(b'{"second":true}')
    manifest = json.loads(package.build_inventory(root, "a" * 40))
    monkeypatch.setattr(package, "read_embedded_inventory", lambda: copy.deepcopy(manifest))
    clock = [time.monotonic()]
    monkeypatch.setattr(package, "monotonic", lambda: clock[0])
    handles, grants, events = [], [], []

    @contextmanager
    def pin(path, *, directory):
        events.append(("pin", Path(path).name))
        if directory:
            yield -len(events)
        else:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            handles.append(descriptor)
            try:
                yield descriptor
            finally:
                os.close(descriptor)

    def grant(descriptor, _sid):
        grants.append(descriptor)
        events.append(("grant", descriptor))

    monkeypatch.setattr(acl, "pin_acl_path", pin)
    monkeypatch.setattr(acl, "grant_public_read", grant)
    return SimpleNamespace(root=root, executable=executable, manifest=manifest, handles=handles,
                           grants=grants, events=events, clock=clock, pin=pin, acl=acl)


def assert_closed(handles):
    for descriptor in handles:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_success_keeps_all_verification_grants_and_handle_lifetimes(public_package):
    p = public_package
    with ExitStack() as stack:
        result = package.pin_public_package(stack, p.executable, None, cancel=lambda: False,
                                            deadline=p.clock[0] + 60)
        assert set(result) == {"public_code_files", "public_code_inventory"}
        assert result["public_code_files"] == len(p.manifest["files"]) + 1
        assert len(p.grants) == len(p.manifest["files"]) + len(p.manifest["directories"]) + 2
        assert len(p.handles) == len(p.manifest["files"]) + 1
        for descriptor in p.handles:
            os.fstat(descriptor)
        assert len([e for e in p.events if e[0] == "pin"]) == len(p.grants)
    assert_closed(p.handles)


@pytest.mark.parametrize("fault,stage", [
    ("enumerate", "enumerate"), ("pin", "pin-file"),
    ("hash", "hash-file"), ("acl", "grant-acl"),
])
def test_failure_carries_only_current_step_counts_and_preserves_cleanup(
    public_package, monkeypatch, fault, stage,
):
    p = public_package
    if fault == "enumerate":
        def fail(*args, **kwargs):
            p.clock[0] += 20
            raise OSError("DoNotPublishPrivatePath")
        monkeypatch.setattr(package, "inventory", fail)
    elif fault == "pin":
        @contextmanager
        def fail(path, *, directory):
            if not directory:
                p.clock[0] += 10
                raise OSError("DoNotPublishPrivatePath")
            with p.pin(path, directory=True) as descriptor:
                yield descriptor
        monkeypatch.setattr(p.acl, "pin_acl_path", fail)
    elif fault == "hash":
        path = p.root / "_internal/provelume/a.json"
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    else:
        def fail(descriptor, sid):
            p.clock[0] += 5
            raise OSError("DoNotPublishPrivatePath")
        monkeypatch.setattr(p.acl, "grant_public_read", fail)
    with pytest.raises((OSError, ModelError)) as failure, ExitStack() as stack:
        package.pin_public_package(stack, p.executable, None, cancel=lambda: False,
                                   deadline=p.clock[0] + 60)
    observed = failure.value.public_inventory
    assert public_inventory_observation(observed) == observed
    assert observed["stage"] == stage
    assert "DoNotPublish" not in json.dumps(observed)
    assert str(p.root) not in json.dumps(observed)
    if fault == "enumerate":
        assert observed["files_total"] is observed["grants_total"] is None
        assert 19999 <= observed["elapsed_ms"] <= 20001
    else:
        assert observed["files_total"] == len(p.manifest["files"])
    if fault == "acl":
        assert observed["files_verified"] == len(p.manifest["files"])
        assert observed["bytes_hashed"] == sum(r["bytes"] for r in p.manifest["files"].values())
    else:
        assert observed["files_verified"] == 0
    assert observed["grants_completed"] == 0 and p.grants == []
    assert_closed(p.handles)


@pytest.mark.parametrize("cancelled", [False, True])
def test_original_deadline_and_cancellation_checkpoints_still_deny_before_file_access(
    public_package, cancelled,
):
    p = public_package
    deadline = p.clock[0] + (60 if cancelled else -1)
    with pytest.raises(ModelError) as failure, ExitStack() as stack:
        package.pin_public_package(stack, p.executable, None, cancel=lambda: cancelled,
                                   deadline=deadline)
    assert failure.value.code == ("cancelled" if cancelled else "timeout")
    observed = failure.value.public_inventory
    assert public_inventory_observation(observed) == observed
    assert observed["stage"] == "pin-file"
    assert observed["files_verified"] == observed["bytes_hashed"] == 0
    if not cancelled:
        assert observed["budget_at_entry_ms"] < 0
    assert p.handles == p.grants == []


@pytest.mark.parametrize("mutation", [
    {"path": "DoNotPublishPrivatePath"}, {"stage": "DoNotPublishPrivateStage"},
    {"elapsed_ms": True}, {"elapsed_ms": -1}, {"stage_elapsed_ms": 301},
    {"budget_remaining_ms": 40001}, {"files_total": True}, {"files_verified": 4},
    {"bytes_hashed": 512 * 1024**2 + 1}, {"grants_total": 4}, {"grants_completed": 1},
    {"files_total": None}, {"stage": ["DoNotPublishPrivateStage"]},
])
def test_malformed_or_private_observation_is_rejected_as_a_whole(observation, mutation):
    invalid = {**observation, **mutation}
    assert public_inventory_observation(invalid) is None
    historical = native_failure({"native_stage": "public-inventory"}, code="timeout")
    assert native_failure({"native_stage": "public-inventory", "public_inventory": invalid},
                          code="timeout") == historical
    assert not valid_native_failure({**historical, "public_inventory": invalid})
    missing = dict(observation)
    missing.pop("elapsed_ms")
    assert public_inventory_observation(missing) is None


def test_historical_records_and_other_stages_do_not_acquire_new_data(observation):
    historical = native_failure({"native_stage": "public-inventory"}, code="timeout")
    assert "public_inventory" not in historical
    assert native_failure(historical, code="timeout") == historical
    assert valid_native_failure(historical)
    projected = native_failure({"native_stage": "public-inventory",
                                "public_inventory": observation}, code="timeout")
    assert valid_native_failure(projected)
    observation["stage"] = "DoNotPublishPrivateStage"
    assert projected["public_inventory"]["stage"] == "hash-file"
    assert "public_inventory" not in native_failure(
        {"native_stage": "process-create", "public_inventory": projected["public_inventory"]},
        code="timeout")


@pytest.mark.parametrize("stage", ["public-inventory", "process-create"])
def test_read_snapshot_keeps_historical_shape_and_drops_invalid_nested_data(observation, stage):
    historical = {"state": "failed", "action": "self_test", "error": "timeout"}
    assert model_operation_snapshot(None) is None
    assert model_operation_snapshot(historical) == historical
    assert model_operation_snapshot(historical) is not historical
    operation = {**historical, "diagnostic_stage": stage,
                 "public_inventory": copy.deepcopy(observation)}
    snapshot = model_operation_snapshot(operation)
    if stage == "public-inventory":
        assert snapshot["public_inventory"] == observation
        snapshot["public_inventory"]["files_verified"] = 2
        assert operation["public_inventory"] == observation
    else:
        assert "public_inventory" not in snapshot
    operation["public_inventory"]["path"] = "DoNotPublishPrivatePath"
    assert "public_inventory" not in model_operation_snapshot(operation)
    assert "DoNotPublish" not in json.dumps(model_operation_snapshot(operation))


def test_diagnostic_failure_does_not_replace_original_exception_or_native_error(monkeypatch):
    native = [0]
    original = OSError("DoNotPublishPrivatePath")
    monkeypatch.setattr(package, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(package.c, "get_last_error", lambda: native[0], raising=False)
    monkeypatch.setattr(package.c, "set_last_error", lambda code: native.__setitem__(0, code),
                        raising=False)

    def fail(*args, **kwargs):
        native[0] = 203
        raise original

    def broken_snapshot(self):
        native[0] = 5
        raise RuntimeError("DoNotPublishPrivateObservationError")

    monkeypatch.setattr(package, "_pin_public_package", fail)
    monkeypatch.setattr(package._PublicInventoryObservation, "snapshot", broken_snapshot)
    with pytest.raises(OSError) as failure:
        package.pin_public_package(None, None, None, cancel=lambda: False,
                                   deadline=time.monotonic() + 60)
    assert failure.value is original and native[0] == 203
    assert not hasattr(original, "public_inventory")


@pytest.mark.parametrize("valid", [False, True])
def test_form_driver_and_ci_summary_retain_only_closed_current_details(
    observation, monkeypatch, valid,
):
    import scripts.custodia_ordinary as driver

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from scripts.qualify_custodia_installed import summary

    candidate = observation if valid else {**observation, "path": "DoNotPublishPrivatePath"}
    hidden = "".join(f'<input type="hidden" name="{key}" value="synthetic">'
                     for key in ("csrf_token", "mutation_nonce", "instance_id", "authority"))
    markup = (hidden + '<div id="ai-model-operation" data-state="failed" '
              'data-action="self_test" data-error="timeout" '
              'data-diagnostic-stage="public-inventory" data-native-code="0" '
              f'data-public-inventory="{escape(json.dumps(candidate), quote=True)}"></div>')
    requests = []

    class Client:
        def get(self, path):
            return httpx.Response(200, text=markup,
                                  request=httpx.Request("GET", "http://test" + path))

        def post(self, path, *, data):
            requests.append((path, data))
            return httpx.Response(303, request=httpx.Request("POST", "http://test" + path))

    report = {"status": "FAIL", "phase": "parent_death_prepare", "checks": {},
              "failure_type": "ValueError", "failure_code": "model_operation"}
    with pytest.raises(ValueError, match="model_operation"):
        driver.model_action(Client(), "self_test", report)
    assert len(requests) == 1
    operation = report["operation_history"][-1]
    assert ("public_inventory" in operation) is valid
    assert "public-inventory" not in operation
    result = summary(report)
    failed = result["failed_model_operation"]
    assert failed["native_code"] == 0 and failed["error"] == "timeout"
    assert ("public_inventory" in failed) is valid
    assert "DoNotPublish" not in json.dumps(report) + json.dumps(result)
    assert "parent_death_seconds" not in result


def test_ci_summary_never_prints_artifact_paths_or_arbitrary_failure_text(monkeypatch, observation):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from scripts.qualify_custodia_installed import summary

    report = {"status": "FAIL", "phase": "parent_death_prepare", "checks": {},
              "failure_type": "ValueError", "failure_code": "model_operation",
              "private": "DoNotPublishPrivateArtifactText",
              "operation_history": [{"state": "failed", "action": "self_test",
                                     "error": "DoNotPublishPrivateError",
                                     "native-code": "DoNotPublishPrivateCode",
                                     "diagnostic-stage": "DoNotPublishPrivateStage",
                                     "elapsed_seconds": float("nan"),
                                     "public_inventory": observation}]}
    result = summary(report)
    assert result["failed_model_operation"] == {"state": "failed", "action": "self_test"}
    assert "DoNotPublish" not in json.dumps(result)
    report["failure_type"] = "DoNotPublishPrivateType"
    assert set(summary(report)) == {"status", "phase", "checks"}
