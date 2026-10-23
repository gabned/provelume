"""TEMP dedicated sparse Capture/atomic-component entry; explicit isolated CI invocation.

Copied as scripts/diagnose_capture_cost_v3.py with explicit C3 helper modules.
The separate C1 whole ordinary control is never synthesized by this entry.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--telemetry", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--plan-sha256", required=True)
    p.add_argument("--original-commit", required=True)
    p.add_argument("--fast-commit", required=True)
    p.add_argument("--cell-ordinal", type=int, choices=range(4), required=True)
    p.add_argument("--first-step-epoch", type=float, required=True)
    args = p.parse_args()
    if (not math.isfinite(args.first_step_epoch) or not 0 < args.first_step_epoch <= time.time()
            or any(re.fullmatch("[0-9a-f]{40}", value) is None
                   for value in (args.original_commit, args.fast_commit))):
        raise ValueError("first_step_clock_or_commit_identity")
    root = Path(__file__).resolve().parents[1]
    raw = args.plan.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.plan_sha256:
        raise ValueError("frozen_plan_sha256")
    plan = json.loads(raw)
    if (plan.get("status") != "FROZEN" or plan.get("schema") != "capture-single-task-experiment/v3"
            or plan.get("mode") != "SPARSE_COMPONENT_V3"
            or plan.get("regime") != "SPARSE_CAPTURE_AND_ATOMIC_COMPONENT_WITH_SEPARATE_C1_CONTROL"
            or (plan.get("job_seconds"), plan.get("micro_budget_seconds"),
                plan.get("work_budget_seconds"), plan.get("cleanup_budget_seconds"),
                plan.get("upload_reserve_seconds"), plan.get("minimum_remaining_seconds"))
            != (1200, 600, 540, 60, 90, 690)):
        raise ValueError("plan_not_frozen")
    cell = plan["cells"][args.cell_ordinal]
    if cell["ordinal"] != args.cell_ordinal:
        raise ValueError("cell_identity")
    if (plan["original_commit"] != args.original_commit
            or plan["fast_commit"] != args.fast_commit):
        raise ValueError("plan_source_identity")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    expected = args.original_commit if cell["ordinary_arm"] == "A" else args.fast_commit
    if head != expected or subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root):
        raise ValueError("checkout_head_or_cleanliness")
    # Candidate imports begin only after explicit frozen inputs pass. The caller
    # must already have established credential-free process/network containment.
    sys.path.insert(0, str(root / "scripts"))
    sys.path.insert(0, str(root / "core"))
    import capture_cost_v3_telemetry as telemetry
    import capture_cost_v3_cohort as cohort
    import ai_runtime_report as report_module
    import qualify_ai_runtime as qualification
    import qualify_ai_jobs as jobs
    from provelume import atomic_commit, capture_adapter, capture_journal
    from provelume.ai_runtime import LocalRuntime, native_selection
    from provelume.ai_runtime_contract import LOCK_SHA256, MODEL_ID, MODEL_SHA256
    from provelume.ai_model_store import ModelStore
    from provelume.service import ProvelumeInstance
    from provelume.storage import InstanceStore

    recorder = telemetry.Recorder(identity={"head": head, "cell": cell,
                                           "regime": "SPARSE_CAPTURE_AND_ATOMIC_COMPONENT_WITH_SEPARATE_C1_CONTROL",
                                           "frozen_plan_sha256": args.plan_sha256,
                                           "first_step_epoch": args.first_step_epoch,
                                           "workflow_head": os.environ.get("GITHUB_SHA"),
                                           "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
                                           "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                                           "workflow_job": os.environ.get("GITHUB_JOB"),
                                           "time_boundary": "Actual first workflow step; server job-start is not asserted."},
                                  output=args.telemetry)
    appended = None
    diagnostic_exit = 42
    primary_error = None
    cleanup_errors = []
    try:
        recorder.install(qualification=qualification, jobs=jobs, report=report_module,
                         atomic=atomic_commit, capture=capture_adapter, journal=capture_journal,
                         runtime_class=LocalRuntime, instance_class=ProvelumeInstance,
                         store_class=InstanceStore)
        recorder.arm = cell["ordinary_arm"]
        variant_dir = args.telemetry.parent / "capture-cost-variant-inputs"
        variant_dir.mkdir(exist_ok=False)
        for arm, commit in (("A", args.original_commit), ("B", args.fast_commit)):
            source = subprocess.check_output(["git", "show", commit + ":core/provelume/atomic_commit.py"], cwd=root)
            source_path = variant_dir / (arm + ".py")
            source_path.write_bytes(source)
            recorder.add_variant(arm, source=source_path,
                                 expected_sha256=plan["atomic_source_sha256"][arm],
                                 atomic_module=atomic_commit)
        recorder.method_identity = recorder._variants[cell["ordinary_arm"]]["identity"]
        recorder.section = "micro_model_import"
        selection = native_selection()
        recorder.identity["runtime_coordinates"] = {
            "configuration_sha256": hashlib.sha256(selection.configuration).hexdigest(),
            "model_sha256": MODEL_SHA256, "runtime_lock_sha256": LOCK_SHA256}
        if any(plan["runtime_coordinates"].get(key) != value
               for key, value in recorder.identity["runtime_coordinates"].items()):
            raise ValueError("fixed_runtime_coordinate_changed")
        store = ModelStore(args.artifacts.absolute() / "store")
        setup_started = time.monotonic_ns()
        installation = store.import_offline(MODEL_ID, args.artifacts.absolute() / "model.gguf", selection,
                                            requested=True, license_accepted="Apache-2.0")
        recorder.identity["micro_model_setup"] = {"started_ns": setup_started,
            "completed_ns": time.monotonic_ns(), "installation": installation,
            "scope": "Explicit same accepted offline model import; not ordinary qualification."}
        # C3 cohort owns calibration and controls after its total600s clock starts.
        remaining = plan["job_seconds"] - (time.time() - args.first_step_epoch)
        required = plan["micro_budget_seconds"] + plan["upload_reserve_seconds"]
        if remaining < required:
            appended = {"status": "NOT_RUN_INSUFFICIENT_REMAINING_BUDGET",
                        "actual_remaining_seconds": remaining,
                        "required_seconds": required}
        else:
            runtime = LocalRuntime(args.artifacts.absolute() / "linux")
            appended = cohort.run(recorder, root=args.artifacts.absolute(), store=store,
                                  runtime=runtime, initialise=ProvelumeInstance.initialise,
                                  measure_jobs=jobs.measure_jobs, selection=selection,
                                  model_id=MODEL_ID, order=cell["micro_order"],
                                  seconds=plan["micro_budget_seconds"],
                                  work_seconds=plan["work_budget_seconds"],
                                  cleanup_seconds=plan["cleanup_budget_seconds"],
                                  upload_reserve_seconds=plan["upload_reserve_seconds"])
    except BaseException as exc:
        primary_error = type(exc).__name__
        recorder.error("entry_workload_or_setup_failed")
        raise
    finally:
        appended = appended or getattr(recorder, "partial_appended", None)
        cohort_cleanup_verified = getattr(recorder, "cohort_cleanup_completed", False) is True
        if cohort_cleanup_verified:
            cleanup_scope = "VERIFIED_ALREADY_COMPLETED_WITHIN_COHORT"
        else:
            cleanup_scope = "EMERGENCY_AFTER_SETUP_OR_COHORT_FAILURE"
            recorder.error("entry_emergency_cleanup_outside_completed_cohort")
            for label, cleanup in (("component_fixtures", recorder.cleanup_component_fixtures),
                                   ("pool_drain", recorder.drain_pools),
                                   ("uninstall", recorder.uninstall)):
                try:
                    cleanup()
                except BaseException as exc:
                    cleanup_errors.append({"operation": label, "exception_type": type(exc).__name__})
                    recorder.error("entry_cleanup_failed_" + label)
        result = {"status": "INCOMPLETE", "path": str(args.telemetry)}
        try:
            result = recorder.flush(ordinary_report=None, appended_report=appended)
        except BaseException as exc:
            cleanup_errors.append({"operation": "flush", "exception_type": type(exc).__name__})
        if (primary_error is None and not cleanup_errors and cohort_cleanup_verified
                and result["status"] == "COMPLETE"
                and appended and appended.get("status") == "COMPLETE"):
            diagnostic_exit = 0
        sidecar = args.telemetry.with_name(args.telemetry.stem + ".execution.json")
        sidecar_raw = json.dumps({"authority": "NONE_DIAGNOSTIC_NOT_QUALIFICATION",
                                      "diagnostic_returncode": diagnostic_exit,
                                      "primary_exception_type": primary_error,
                                      "cleanup_errors": cleanup_errors,
                                      "cohort_cleanup_completed": cohort_cleanup_verified,
                                      "cleanup_scope": cleanup_scope,
                                      "mode": "SPARSE_COMPONENT_V3", "ordinary_report": None,
                                      "telemetry": result,
                                      "appended_status": appended.get("status") if appended else None}, indent=2) + "\n"
        try:
            with sidecar.open("x") as stream:
                stream.write(sidecar_raw)
        except BaseException as exc:
            try:
                print(json.dumps({"diagnostic_sidecar_write_failed": type(exc).__name__,
                                  "primary_exception_type": primary_error}), file=sys.stderr)
            except BaseException:
                pass
            if primary_error is None:
                raise
    # Workflow must independently observe ALL C3 traces and worker PIDs.
    # It must not pass a component-only report to the canonical ordinary observer.
    return diagnostic_exit


if __name__ == "__main__":
    raise SystemExit(main())
