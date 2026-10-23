"""TEMP full-ordinary C4 entry; explicit credential-free Linux diagnostic only.

Copied as scripts/diagnose_capture_cost_v4.py. All original Product operations,
report/evaluator/network bytes and original returned rows remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    selected = argparse.ArgumentParser(description=__doc__)
    for name in ("artifacts", "output", "telemetry", "plan"):
        selected.add_argument("--" + name, type=Path, required=True)
    selected.add_argument("--plan-sha256", required=True)
    selected.add_argument("--cell-ordinal", type=int, choices=range(4), required=True)
    selected.add_argument("--observer-control-fd", type=int)
    args = selected.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import capture_cost_v4_observer as observer

    plan = observer.load_plan(args.plan, args.plan_sha256)
    cell = plan["cells"][args.cell_ordinal]
    if cell.get("ordinal") != args.cell_ordinal or cell.get("ordinary_arm") not in {"A", "B"}:
        raise ValueError("cell_identity")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    expected = plan["original_commit"] if cell["ordinary_arm"] == "A" else plan["fast_commit"]
    if head != expected or subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=root):
        raise ValueError("checkout_head_or_cleanliness")
    for relative, expected_sha in plan["helper_sha256"].items():
        if relative not in {"scripts/capture_cost_v4_telemetry.py",
                            "scripts/capture_cost_v4_observer.py",
                            "scripts/diagnose_capture_cost_v4.py"}:
            raise ValueError("unexpected_diagnostic_helper")
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected_sha:
            raise ValueError("diagnostic_helper_hash")
    if len(plan["helper_sha256"]) != 3:
        raise ValueError("exact_three_diagnostic_helpers")
    # Only after frozen identities pass; the workflow already removed credentials.
    sys.path.insert(0, str(root / "core"))
    import capture_cost_v4_telemetry as telemetry
    import ai_runtime_report as report_module
    import qualify_ai_runtime as qualification
    import qualify_ai_jobs as jobs
    import qualify_ai_setup as setup
    import qualify_ai_synthesis as synthesis
    import diagnose_ai_capture as diagnostics
    from provelume import atomic_commit, capture_adapter
    from provelume.ai_runtime import LocalRuntime, native_selection
    from provelume.ai_runtime_contract import LOCK_SHA256, MODEL_SHA256
    from provelume.instance_lifecycle import InstanceLifecycleManager

    control = observer.DisabledControl("parent_control_unavailable")
    if args.observer_control_fd is not None:
        try:
            control = observer.ControlWriter.attach(args.observer_control_fd)
        except Exception as exc:
            control = observer.DisabledControl("attach_" + type(exc).__name__)
    identity = {"head": head, "cell": cell, "mode": observer.MODE, "regime": observer.REGIME,
                "frozen_plan_sha256": args.plan_sha256,
                "workflow_head": os.environ.get("GITHUB_SHA"),
                "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
                "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                "workflow_job": os.environ.get("GITHUB_JOB"),
                "scope": "All19 qualification Capture probes; legacy6 cProfile probes unmodified outside slots"}
    recorder = None
    ordinary = None
    primary = None
    cleanup_errors = []
    observation_setup_errors = []
    def note_error(code):
        if recorder is None:
            return
        try:
            recorder.error(code)
        except BaseException as exc:
            cleanup_errors.append({"operation": "record_observation_error", "code": code,
                                   "exception_type": type(exc).__name__})
    diagnostic_returncode = 42
    intended_entry_returncode = 42
    before_network = None
    started_at, started_ns = observer.utc_now(), time.monotonic_ns()
    try:
        selection = native_selection()
        coordinates = {"configuration_sha256": hashlib.sha256(selection.configuration).hexdigest(),
                       "model_sha256": MODEL_SHA256, "runtime_lock_sha256": LOCK_SHA256}
        if coordinates != plan["runtime_coordinates"]:
            raise ValueError("fixed_runtime_coordinates")
        identity["runtime_coordinates"] = coordinates
        # Frozen source/runtime checks above fail closed. An observation setup
        # fault below must not replace or skip the original ordinary workload.
        operation = "telemetry_directory"
        try:
            args.telemetry.parent.mkdir(parents=True, exist_ok=True)
            operation = "recorder_create"
            recorder = telemetry.Recorder(identity=identity, output=args.telemetry, control=control)
            operation = "install"
            recorder.install(qualification=qualification, jobs=jobs, report=report_module,
                             setup=setup, synthesis=synthesis, diagnostics=diagnostics,
                             atomic=atomic_commit, capture=capture_adapter,
                             lifecycle_class=InstanceLifecycleManager, runtime_class=LocalRuntime)
            operation = "calibrate"
            recorder.calibrate()
        except BaseException as exc:
            observation_setup_errors.append({"operation": operation, "exception_type": type(exc).__name__})
            note_error("observation_setup_" + operation)
            if recorder is not None:
                try:
                    recorder.uninstall()
                except BaseException as restoration_error:
                    cleanup_errors.append({"operation": "restore_after_observation_setup_failure",
                                           "exception_type": type(restoration_error).__name__})
                    note_error("observation_setup_restoration_failed")
        # Exactly one unchanged full ordinary call. No append or extra Capture.
        ordinary = qualification.measure(args.artifacts.absolute(), args.output)
    except BaseException as exc:
        primary = type(exc).__name__
        note_error("entry_workload_or_setup_" + primary)
        raise
    finally:
        # Preserve even a partial original report before the later network writer.
        try:
            if args.output.is_file():
                raw = args.output.read_bytes()
                before_path = args.telemetry.parent / "ordinary-before-network.json"
                with before_path.open("xb") as stream:
                    stream.write(raw)
                before_network = {"path": str(before_path), "bytes": len(raw),
                                  "sha256": hashlib.sha256(raw).hexdigest()}
                if recorder is not None:
                    recorder.identity["ordinary_raw_before_network_observer"] = before_network
        except BaseException as exc:
            cleanup_errors.append({"operation": "preserve_original_report", "exception_type": type(exc).__name__})
            note_error("entry_preserve_report_failed")
        for label, cleanup in (("uninstall", recorder.uninstall if recorder is not None else None),
                               ("control_close", control.close)):
            if cleanup is None:
                continue
            try:
                cleanup()
            except BaseException as exc:
                cleanup_errors.append({"operation": label, "exception_type": type(exc).__name__})
                note_error("entry_cleanup_" + label)
        result = {"status": "INCOMPLETE", "path": str(args.telemetry)}
        try:
            if recorder is not None:
                result = recorder.flush(ordinary_report=ordinary)
        except BaseException as exc:
            cleanup_errors.append({"operation": "flush", "exception_type": type(exc).__name__})
        try:
            control_summary = control.summary()
        except BaseException as exc:
            cleanup_errors.append({"operation": "control_summary", "exception_type": type(exc).__name__})
            control_summary = {"status": "INCOMPLETE", "published_slots": [],
                               "errors": [{"reason": "summary_" + type(exc).__name__}]}
        complete = (primary is None and not observation_setup_errors and not cleanup_errors
                    and result.get("status") == "COMPLETE"
                    and control_summary["status"] == "COMPLETE"
                    and control_summary["published_slots"] == list(range(19))
                    and ordinary is not None and before_network is not None)
        status = ordinary.get("status") if ordinary else None
        gates = ordinary.get("gates") if ordinary else None
        original_cli_equivalent_rc = 0 if status == "PASS" else 1
        if complete:
            diagnostic_returncode = 0
            # Producer0 is neutral, not an ordinary PASS or a GitHub job verdict.
            network_only_pending = (status == "BLOCKED" and type(gates) is dict
                and gates.get("network") == "NOT_RUN"
                and all(value == "PASS" for key, value in gates.items() if key != "network"))
            intended_entry_returncode = 0 if status == "PASS" or network_only_pending else 1
        sidecar = {"schema": "capture-process-entry-execution/v4", "authority": "NONE_MECHANISM_ONLY",
                   "qualification": "NOT_GRANTED", "correction_support": "NOT_GRANTED",
                   "mode": observer.MODE, "regime": observer.REGIME,
                   "started_at": started_at, "completed_at": observer.utc_now(),
                   "started_ns": started_ns, "completed_ns": time.monotonic_ns(),
                   "head": head, "cell": cell, "plan_sha256": args.plan_sha256,
                   "diagnostic_complete": complete, "diagnostic_returncode": diagnostic_returncode,
                   "intended_entry_returncode": intended_entry_returncode if primary is None else None,
                   "primary_exception_type": primary, "cleanup_errors": cleanup_errors,
                   "observation_setup_errors": observation_setup_errors,
                   "original_status_before_network": status,
                   "original_gates_before_network": gates,
                   "original_cli_equivalent_returncode_before_network": original_cli_equivalent_rc,
                   "ordinary_before_network": before_network, "telemetry": result,
                   "control": control_summary,
                   "neutral_zero_scope": "diagnostic complete; ordinary pending network remains BLOCKED"}
        try:
            observer.write_json_new(args.telemetry.with_name("telemetry.execution.json"), sidecar)
        except BaseException as exc:
            if primary is None:
                raise
            print(json.dumps({"sidecar_write_failed": type(exc).__name__,
                              "primary_exception_type": primary}), file=sys.stderr)
    return intended_entry_returncode


if __name__ == "__main__":
    raise SystemExit(main())
