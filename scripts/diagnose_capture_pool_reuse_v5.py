"""TEMP C5: four clocks around each of 19 unchanged full ordinary probes.

No Product alias, phase hook, sampler, extra probe, model operation or evaluator
is added. This producer supplies observations, never a GitHub job verdict.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SCHEMA = "capture-pool-reuse-temporary-telemetry/v5"
MODE = "FULL_ORDINARY_SPARSE_POOL_REUSE_V5"
REGIME = "FULL_ORDINARY_ALL19_TRANSACTION_POOL_REUSE_NOT_QUALIFICATION"
BASE = "7ec20fe0727a74a312235b53b52a5434707f4dc8"
ENTRY = "scripts/diagnose_capture_pool_reuse_v5.py"
ORDINARY = {
    "scripts/qualify_ai_runtime.py": "3c335f1c585292531d0cbc509a55560f25fe8e6c86a8669825deeee5fc0303d5",
    "scripts/qualify_ai_jobs.py": "3392d397509039ac63463b553131d56299fa0523e9651c1b10ffcdee2c2e547c",
    "scripts/qualify_ai_setup.py": "61d997909852a8dcd361ed82a6db5f848190bf63dad71bfa115ca147ae2a3b76",
    "scripts/qualify_ai_synthesis.py": "fe762c1a42567069f081edc70c6cf1d3a5f985a82610307fec064ee91d804946",
    "scripts/qualify_ai_classification.py": "b0a01b7d78c2511ec4f388572cf23a6332da15142642d959e706b37fc8e7ac80",
    "scripts/ai_runtime_report.py": "754802fe6b2eb0b5bd67d6a962dcd9ed31179c9acd8e0526df6d176600410e22",
    "scripts/ai_runtime_network.py": "9acb929c7f708a9590d9fe961744437882699daf38a9f46b2f6f14f428e624e9",
    "scripts/diagnose_ai_capture.py": "e54407f993e2d4b39185a2b12726a23f70b79080839ebfffb4b6460adb1f7939",
}
RUNTIME = {
    "configuration_sha256": "6d26739dbb863788ae9de3ed3561b74995f03afde9bfe4cd8cef8c3dc25d0f99",
    "model_sha256": "1885b3a9195f8cc09da9a7a7a75afdc1e8d5cbf9fc4a499c3961dddea37098ac",
    "runtime_lock_sha256": "0e508965cddc60d6cfb57c42d2c4039c637e8812bb25cc21b525b6d6047a4404",
}
CALLBACKS = tuple(
    {"id": ordinal, "group": group, "original_row_index": index,
     "number": number, "report_path": path, "alias": alias}
    for ordinal, (alias, group, index, number, path) in enumerate([
        *[("runtime", "s05_idle", n, n, f"deterministic_idle.{n}") for n in range(3)],
        *[("runtime", "s05_busy", n, n, f"deterministic_busy.{n}") for n in range(3)],
        *[("jobs", "s06_busy", n, n, f"s06.deterministic_busy.{n}") for n in range(6)],
        *[("setup", "s07_busy", n, 700+n, f"s07.samples.{n}.probe") for n in range(2)],
        *[("synthesis", "s08_idle", n, 800+n, f"s08.idle.{n}") for n in range(3)],
        *[("synthesis", "s08_busy", n, 810+n, f"s08.performance.{n}.probe") for n in range(2)],
    ])
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return datetime.now(UTC).isoformat()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def observation_error(recorder, operation, exc=None):
    recorder.disabled = True
    try:
        recorder.error(operation, exc)
    except BaseException:
        recorder.error_recording_failed = True


def restore_safely(recorder):
    try:
        return recorder.restore()
    except BaseException as exc:
        observation_error(recorder, "restoration_observation", exc)
        return False


def clock_safely(recorder, row, name, function):
    try:
        recorder.clock(row, name, function)
    except BaseException as exc:
        observation_error(recorder, "clock_bookkeeping_" + name, exc)


def source_identity(root, args):
    raw = args.plan.read_bytes()
    if not re.fullmatch("[0-9a-f]{64}", args.plan_sha256) or sha(raw) != args.plan_sha256:
        raise ValueError("frozen_plan_hash")
    plan = json.loads(raw)
    if (plan.get("schema"), plan.get("status"), plan.get("mode"), plan.get("regime"),
        plan.get("base_commit"), plan.get("workflow_runs"), plan.get("run_attempt"),
        plan.get("job_count"), plan.get("job_seconds"), plan.get("max_parallel"),
        plan.get("fail_fast"), plan.get("callbacks_per_job"), plan.get("callback_count_total")) != (
            "capture-pool-reuse-full-ordinary-experiment/v5", "FROZEN", MODE, REGIME,
            BASE, 1, 1, 4, 1200, 2, False, 19, 76):
        raise ValueError("frozen_plan_contract")
    selected = [{k: v for k, v in row.items() if k != "alias"} for row in CALLBACKS]
    if plan.get("selected_callbacks") != selected or plan.get("ordinary_script_sha256") != ORDINARY:
        raise ValueError("unchanged_ordinary_19_callback_contract")
    cells = plan.get("cells")
    if (not isinstance(cells, list) or len(cells) != 4
        or [(c.get("ordinal"), c.get("slot"), c.get("ordinary_arm")) for c in cells]
        != [(0, "A1", "A"), (1, "B1", "B"), (2, "B2", "B"), (3, "A2", "A")]):
        raise ValueError("fixed_ABBA_cells")
    cell = cells[args.cell_ordinal]
    expected = plan["original_commit"] if cell["ordinary_arm"] == "A" else plan["fast_commit"]
    if not re.fullmatch("[0-9a-f]{40}", expected):
        raise ValueError("exact_source_head")
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root)]
    head = subprocess.check_output([*command, "rev-parse", "HEAD"], text=True).strip()
    if head != expected or subprocess.check_output([*command, "status", "--porcelain", "--untracked-files=all"]):
        raise ValueError("exact_clean_source")
    helpers = plan.get("helper_sha256")
    if not isinstance(helpers, dict) or set(helpers) != {ENTRY}:
        raise ValueError("exact_one_temporary_entry")
    for relative, digest in {**ORDINARY, **helpers}.items():
        if sha((root / relative).read_bytes()) != digest:
            raise ValueError("source_bytes_" + relative)
    atomic = plan["atomic_source_sha256"][cell["ordinary_arm"]]
    if not re.fullmatch("[0-9a-f]{64}", atomic) or sha((root / "core/provelume/atomic_commit.py").read_bytes()) != atomic:
        raise ValueError("actual_atomic_source")
    if plan.get("runtime_coordinates") != RUNTIME:
        raise ValueError("frozen_runtime_coordinates")
    return {"head": head, "cell": cell, "frozen_plan_sha256": args.plan_sha256,
            "workflow_head": os.environ.get("GITHUB_SHA"),
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "workflow_job": os.environ.get("GITHUB_JOB"), "runtime_coordinates": RUNTIME,
            "atomic_source_sha256": atomic, "mode": MODE, "regime": REGIME}


class SparseRecorder:
    def __init__(self, identity):
        self.identity, self.rows, self.errors, self.saved = identity, [], [], []
        self.disabled, self.error_recording_failed, self.clock_read_attempts = False, False, 0
        self.clock_resolutions = {name: time.get_clock_info(name).resolution
                                  for name in ("monotonic", "process_time")}

    def error(self, operation, exc=None):
        self.disabled = True
        try:
            self.errors.append({"operation": operation,
                                "exception_type": type(exc).__name__ if exc is not None else None})
        except BaseException:
            self.error_recording_failed = True

    def restore(self):
        restored = True
        for label, module, original in self.saved:
            try:
                if module.deterministic_probe is not original:
                    module.deterministic_probe = original
                if module.deterministic_probe is not original:
                    raise RuntimeError("binding_not_restored")
            except BaseException as exc:
                restored = False
                observation_error(self, "restore_" + label, exc)
        return restored

    def clock(self, row, name, function):
        self.clock_read_attempts += 1
        try:
            row[name] = function()
        except BaseException as exc:
            row[name] = None
            observation_error(self, "clock_" + name, exc)
            try:
                row["clock_errors"].append({"clock": name, "exception_type": type(exc).__name__})
            except BaseException:
                self.error_recording_failed = True

    def wrapper(self, label, original):
        def observe(instance, number):
            if self.disabled:
                return original(instance, number)
            try:
                row = dict(CALLBACKS[len(self.rows)])
                if row["alias"] != label or row["number"] != number:
                    raise ValueError("unexpected_official_callback")
                del row["alias"]
                row.update(clock_errors=[], primary_exception_type=None, original_row=None)
                self.rows.append(row)
            except BaseException as exc:
                observation_error(self, "callback_binding", exc)
                restore_safely(self)
                return original(instance, number)
            clock_safely(self, row, "wall_before_ns", time.monotonic_ns)
            clock_safely(self, row, "process_cpu_before_ns", time.process_time_ns)
            try:
                result = original(instance, number)
            except BaseException as exc:
                try:
                    row["primary_exception_type"] = type(exc).__name__
                except BaseException as observation_exc:
                    observation_error(self, "primary_exception_observation", observation_exc)
                raise
            else:
                try:
                    row["original_row"] = result  # Actual DICT reference; callers add fields after return.
                except BaseException as exc:
                    observation_error(self, "returned_row_observation", exc)
                return result
            finally:
                clock_safely(self, row, "process_cpu_after_ns", time.process_time_ns)
                clock_safely(self, row, "wall_after_ns", time.monotonic_ns)
                if self.disabled or len(self.rows) == 19:
                    restore_safely(self)  # Before the unchanged six legacy cProfile probes.
        return observe

    def install(self, modules, original):
        for label in ("runtime", "jobs", "setup", "synthesis"):
            module = modules[label]
            if module.deterministic_probe is not original:
                raise ValueError("original_probe_alias_" + label)
            self.saved.append((label, module, original))
        for label, module, original in self.saved:
            module.deterministic_probe = self.wrapper(label, original)

    def document(self, ordinary, before_network):
        if len(self.rows) != 19:
            observation_error(self, "incomplete_official_callback_count")
        for row in self.rows:
            try:
                linked = ordinary
                for key in row["report_path"].split("."):
                    linked = linked[int(key)] if isinstance(linked, list) else linked[key]
                if type(row["original_row"]) is not dict or linked is not row["original_row"]:
                    raise ValueError("late_original_row_reference")
                for result, after, before in (("elapsed_wall_ns", "wall_after_ns", "wall_before_ns"),
                                              ("elapsed_parent_cpu_ns", "process_cpu_after_ns", "process_cpu_before_ns")):
                    if type(row[after]) is not int or type(row[before]) is not int or row[after] < row[before]:
                        raise ValueError("raw_clock_incomplete_or_reversed")
                    row[result] = row[after] - row[before]
            except BaseException as exc:
                observation_error(self, "late_callback_validation_" + str(row["id"]), exc)
        restored = restore_safely(self)
        return {"schema": SCHEMA, "mode": MODE, "regime": REGIME, "identity": self.identity,
                "status": "COMPLETE" if not self.disabled and restored else "INCOMPLETE",
                "qualification": "NOT_GRANTED", "correction_support": "NOT_GRANTED",
                "cpu_scope": "WHOLE_PROBE_PARENT_PROCESS_INCLUDES_ORIGINAL_AND_SEARCH",
                "clock_order": ["monotonic_ns", "process_time_ns", "ORIGINAL_PROBE", "process_time_ns", "monotonic_ns"],
                "clock_resolutions": self.clock_resolutions, "clock_read_attempts": self.clock_read_attempts,
                "callbacks": self.rows, "errors": self.errors,
                "error_recording_failed": self.error_recording_failed, "bindings_restored": restored,
                "ordinary_raw_before_network_observer": before_network,
                "legacy_six_probes": "UNCHANGED_UNWRAPPED_PASSTHROUGH"}


def run_ordinary(args, identity, modules, report_module):
    recorder, ordinary, primary, before_network = None, None, None, None
    setup_errors, cleanup_errors = [], []
    intended_rc, complete, telemetry = 42, False, None
    started, primary_traceback = None, None
    try:
        started = utc()
    except BaseException as exc:
        setup_errors.append({"operation": "start_time_observation", "exception_type": type(exc).__name__})
    try:
        try:
            args.telemetry.parent.mkdir(parents=True, exist_ok=True)
            recorder = SparseRecorder(identity)
            recorder.install(modules, report_module.deterministic_probe)
        except BaseException as exc:
            setup_errors.append({"operation": "observation_setup", "exception_type": type(exc).__name__})
            if recorder is not None:
                observation_error(recorder, "observation_setup", exc)
                restore_safely(recorder)
        ordinary = modules["runtime"].measure(args.artifacts.absolute(), args.output)  # Exactly once, unchanged.
    except BaseException as exc:
        primary, primary_traceback = exc, exc.__traceback__
    try:
        if recorder is not None:
            restore_safely(recorder)
        try:
            raw = args.output.read_bytes()
            target = args.telemetry.parent / "ordinary-before-network.json"
            with target.open("xb") as stream:
                stream.write(raw)
            before_network = {"path": str(target), "bytes": len(raw), "sha256": sha(raw)}
        except BaseException as exc:
            cleanup_errors.append({"operation": "preserve_original_report", "exception_type": type(exc).__name__})
        try:
            if recorder is not None:
                telemetry = recorder.document(ordinary, before_network)
                write_new(args.telemetry, telemetry)
        except BaseException as exc:
            cleanup_errors.append({"operation": "telemetry_flush", "exception_type": type(exc).__name__})
        completed = None
        try:
            completed = utc()
        except BaseException as exc:
            cleanup_errors.append({"operation": "end_time_observation", "exception_type": type(exc).__name__})
        complete = (primary is None and not setup_errors and not cleanup_errors
                    and telemetry is not None and telemetry["status"] == "COMPLETE"
                    and type(ordinary) is dict and before_network is not None)
        status = ordinary.get("status") if type(ordinary) is dict else None
        gates = ordinary.get("gates") if type(ordinary) is dict else None
        full_map = type(gates) is dict and len(gates) == 28 and "network" in gates
        network_pending = (status == "BLOCKED" and full_map and gates["network"] == "NOT_RUN"
                           and all(v == "PASS" for k, v in gates.items() if k != "network"))
        all_pass = status == "PASS" and full_map and all(v == "PASS" for v in gates.values())
        if complete:
            intended_rc = 0 if all_pass or network_pending else 1
        sidecar = {"schema": "capture-pool-reuse-entry-execution/v5", "mode": MODE, "regime": REGIME,
                   "qualification": "NOT_GRANTED", "correction_support": "NOT_GRANTED",
                   "started_at": started, "completed_at": completed, "identity": identity,
                   "diagnostic_complete": complete, "diagnostic_returncode": 0 if complete else 42,
                   "intended_entry_returncode": intended_rc if primary is None else None,
                   "primary_exception_type": type(primary).__name__ if primary is not None else None,
                   "observation_setup_errors": setup_errors,
                   "cleanup_errors": cleanup_errors, "ordinary_before_network": before_network,
                   "original_status_before_network": status, "original_gates_before_network": gates,
                   "original_cli_equivalent_returncode_before_network": 0 if status == "PASS" else 1,
                   "neutral_zero_scope": "Complete observations and all ordinary gates PASS except canonical network pending; not a report or job PASS"}
        try:
            write_new(args.telemetry.with_name("telemetry.execution.json"), sidecar)
        except BaseException as exc:
            if primary is None:
                intended_rc = 42
            print(json.dumps({"sidecar_write_failed": type(exc).__name__,
                              "primary_exception_type": type(primary).__name__ if primary is not None else None}), file=sys.stderr)
    except BaseException as exc:
        intended_rc = 42
        try:
            print(json.dumps({"observation_finalization_failed": type(exc).__name__,
                              "primary_exception_type": type(primary).__name__ if primary is not None else None}), file=sys.stderr)
        except BaseException:
            pass
    finally:
        if primary is not None:
            raise primary.with_traceback(primary_traceback)
    return intended_rc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifacts", "output", "telemetry", "plan"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--cell-ordinal", type=int, choices=range(4), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    identity = source_identity(root, args)  # Invalid source/plan fails before workload.
    sys.path[:0] = [str(root / "scripts"), str(root / "core")]
    import ai_runtime_report as report_module
    import qualify_ai_runtime as qualification
    import qualify_ai_jobs as jobs
    import qualify_ai_setup as setup
    import qualify_ai_synthesis as synthesis
    from provelume.ai_runtime import native_selection
    from provelume.ai_runtime_contract import LOCK_SHA256, MODEL_SHA256
    actual = {"configuration_sha256": sha(native_selection().configuration),
              "model_sha256": MODEL_SHA256, "runtime_lock_sha256": LOCK_SHA256}
    if actual != RUNTIME:
        raise ValueError("actual_runtime_coordinates")
    return run_ordinary(args, identity, {"runtime": qualification, "jobs": jobs,
                                       "setup": setup, "synthesis": synthesis}, report_module)


if __name__ == "__main__":
    raise SystemExit(main())
