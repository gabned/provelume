"""TEMP Linux Capture-cost entry draft; explicit invocation in isolated CI only.

Copied by the coordinator as scripts/diagnose_capture_cost_v1.py, with helpers
scripts/capture_cost_v1_telemetry.py and scripts/capture_cost_v1_cohort.py.
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
    p.add_argument("--output", type=Path, required=True)
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
    if plan.get("status") != "FROZEN" or plan.get("schema") != "capture-single-task-experiment/v1":
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
    import capture_cost_v1_telemetry as telemetry
    import capture_cost_v1_cohort as cohort
    import ai_runtime_report as report_module
    import qualify_ai_runtime as qualification
    import qualify_ai_jobs as jobs
    from provelume import atomic_commit, capture_adapter, capture_journal
    from provelume.ai_runtime import LocalRuntime, native_selection
    from provelume.ai_runtime_contract import MODEL_ID
    from provelume.ai_model_store import ModelStore
    from provelume.service import ProvelumeInstance
    from provelume.storage import InstanceStore

    recorder = telemetry.Recorder(identity={"head": head, "cell": cell,
                                           "frozen_plan_sha256": args.plan_sha256,
                                           "first_step_epoch": args.first_step_epoch,
                                           "workflow_head": os.environ.get("GITHUB_SHA"),
                                           "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
                                           "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                                           "workflow_job": os.environ.get("GITHUB_JOB"),
                                           "time_boundary": "Actual first workflow step; server job-start is not asserted."},
                                  output=args.telemetry)
    ordinary, appended = None, None
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
        # Byte-identical complete ordinary workload and report writer/evaluator.
        ordinary = qualification.measure(args.artifacts.absolute(), args.output)
        ordinary_raw = args.output.read_bytes()
        before_network_path = args.telemetry.parent / "ordinary-before-network.json"
        with before_network_path.open("xb") as stream:
            stream.write(ordinary_raw)
        recorder.identity["ordinary_raw_before_network_observer"] = {
            "path": str(before_network_path), "bytes": len(ordinary_raw),
            "sha256": hashlib.sha256(ordinary_raw).hexdigest()}
        recorder.calibrate()
        remaining = plan["job_seconds"] - (time.time() - args.first_step_epoch)
        required = plan["micro_budget_seconds"] + plan["upload_reserve_seconds"]
        if remaining < required:
            appended = {"status": "NOT_RUN_INSUFFICIENT_REMAINING_BUDGET",
                        "actual_remaining_seconds": remaining,
                        "required_seconds": required}
        else:
            runtime = LocalRuntime(args.artifacts.absolute() / "linux")
            store = ModelStore(args.artifacts.absolute() / "store")
            appended = cohort.run(recorder, root=args.artifacts.absolute(), store=store,
                                  runtime=runtime, initialise=ProvelumeInstance.initialise,
                                  measure_jobs=jobs.measure_jobs, selection=native_selection(),
                                  model_id=MODEL_ID, order=cell["micro_order"],
                                  seconds=plan["micro_budget_seconds"])
    except BaseException as exc:
        primary_error = type(exc).__name__
        recorder.error("entry_workload_or_setup_failed")
        raise
    finally:
        appended = appended or getattr(recorder, "partial_appended", None)
        for label, cleanup in (("pool_drain", recorder.drain_pools),
                               ("uninstall", recorder.uninstall)):
            try:
                cleanup()
            except BaseException as exc:
                cleanup_errors.append({"operation": label, "exception_type": type(exc).__name__})
                recorder.error("entry_cleanup_failed_" + label)
        result = {"status": "INCOMPLETE", "path": str(args.telemetry)}
        try:
            result = recorder.flush(ordinary_report=ordinary, appended_report=appended)
        except BaseException as exc:
            cleanup_errors.append({"operation": "flush", "exception_type": type(exc).__name__})
        if (primary_error is None and not cleanup_errors and result["status"] == "COMPLETE"
                and appended and appended.get("status") == "COMPLETE"):
            diagnostic_exit = 0
        sidecar = args.telemetry.with_name(args.telemetry.stem + ".execution.json")
        sidecar_raw = json.dumps({"authority": "NONE_DIAGNOSTIC_NOT_QUALIFICATION",
                                      "diagnostic_returncode": diagnostic_exit,
                                      "primary_exception_type": primary_error,
                                      "cleanup_errors": cleanup_errors,
                                      "ordinary_report_status_before_network_observer": ordinary.get("status") if ordinary else None,
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
    # Workflow must still run the unchanged network observer, retain its actual
    # exit and the ordinary 28 gates, then require BOTH it and this sidecar.
    return diagnostic_exit


if __name__ == "__main__":
    raise SystemExit(main())
