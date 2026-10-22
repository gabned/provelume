"""Fixed native replay of public S06 inputs; diagnostic, never qualification.

The two cycles repeat the same three cold/warm pairs byte for byte. Real model
import, self-test, activation, admission and worker containment remain required.
This isolates native/admission costs; it does not measure the governed scheduler,
source-policy polling, reservation, persistence or deterministic busy probes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from provelume.ai_contract import digest  # noqa: E402
from provelume.ai_model_file import ReadAuthority  # noqa: E402
from provelume.ai_model_store import ModelStore  # noqa: E402
from provelume.ai_models import ModelError  # noqa: E402
from provelume.ai_runtime import LocalRuntime, native_selection  # noqa: E402
from provelume.ai_runtime_contract import (  # noqa: E402
    CONFIGURATION,
    LOCK_SHA256,
    MODEL_ID,
    MODEL_SHA256,
    hardware,
)
from provelume.ai_runtime_diagnostic_counters import difference, snapshot  # noqa: E402

INPUTS = ROOT / "tests/fixtures/entitas_s06_diagnostic_inputs.json"
INPUTS_SHA256 = "c6f9f1dea75d57040a79811a7ff7ae253a6c84c6a2fe284c40050bc17bd4b61f"
SCHEMA = "provelume-s06-fixed-native-diagnostic/v1"
SCOPE = digest({"public_synthetic_diagnostic": "entitas-fixed-replay-v1"})


class DiagnosticError(ValueError):
    """Only a closed diagnostic check below supplies this public reason."""


def require(condition, reason):
    if not condition:
        raise DiagnosticError(reason)


def load_inputs():
    raw = INPUTS.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == INPUTS_SHA256, "fixed input bytes changed")
    value = json.loads(raw)
    require(value["schema"] == "provelume-s06-diagnostic-inputs/v1", "input schema")
    pairs = value["pairs"]
    require(len(pairs) == 3, "three fixed pairs required")
    for index, pair in enumerate(pairs):
        require(pair["id"] == f"pair-{index}", "fixed pair order")
        for phase in ("cold", "warm"):
            row = pair[phase]
            encoded = row["utf8"].encode("utf-8")
            require(0 < len(encoded) <= CONFIGURATION["input_bytes"], "input byte bound")
            require(hashlib.sha256(encoded).hexdigest() == row["sha256"], "input digest")
            require("<|" not in row["utf8"], "input contains a role delimiter")
            require(type(row["expected_input_tokens"]) is int
                    and type(row["expected_reused_input_tokens"]) is int, "token observations")
    return value


def plan(pairs):
    return [{"cycle": cycle, "pair": pair["id"], "phase": phase,
             "payload_sha256": pair[phase]["sha256"], "outcome": "NOT_RUN"}
            for cycle in ("A", "B") for pair in pairs for phase in ("cold", "warm")]


def save(output, report):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")


def clocks():
    result = {}
    for name in ("monotonic", "perf_counter", "process_time"):
        value = time.get_clock_info(name)
        result[name] = {"implementation": value.implementation,
                        "resolution_seconds": value.resolution,
                        "monotonic": value.monotonic, "adjustable": value.adjustable}
    return result


def error_record(error):
    # Native exceptions expose closed codes; never copy an arbitrary path/token.
    value = {"type": type(error).__name__,
             "code": error.code if isinstance(error, ModelError) else "diagnostic_error"}
    if isinstance(error, DiagnosticError):
        value["reason"] = str(error)
    return value


def require_windows_control():
    require(os.name == "nt", "Windows diagnostic only")
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_OS") == "Windows"
            and os.environ.get("S06_WFP_VERIFIED") == "1",
            "independently verified exact-interpreter WFP control required")


def measure_request(store, runtime, selection, payload, phase):
    """Same model admission and native operation deadline; no retry or gate score."""
    started = time.monotonic()
    precise_started = time.perf_counter_ns()
    deadline = started + CONFIGURATION["seconds"]
    admitted_started = snapshot()
    with (runtime._admit(deadline=deadline, cancel=lambda: False),
          store.use(selection, cancel=ReadAuthority(lambda: False), deadline=deadline) as model):
        admitted_at = time.monotonic()
        admitted_counter = snapshot()
        value = runtime._infer_admitted(
            model, selection, payload["utf8"], cancel=lambda: False,
            deadline=deadline, reuse_scope=SCOPE,
        )
        returned_counter = snapshot()
    elapsed = time.monotonic() - started
    precise_elapsed_ns = time.perf_counter_ns() - precise_started
    worker = runtime.last_observation
    require(worker["cold"] is (phase == "cold"), "observed worker condition differs")
    require(worker["input_tokens"] == payload["expected_input_tokens"]
            and worker["reused_input_tokens"] == payload["expected_reused_input_tokens"],
            "fixed input tokenization/reuse differs from retained source")
    return {
        "outcome": "MEASURED",
        "model_admission_seconds": admitted_at - started,
        "elapsed_seconds": elapsed,
        "elapsed_perf_counter_ns": precise_elapsed_ns,
        "first_seconds_including_admission_and_return": (
            worker["first_wall_seconds"] + elapsed - worker["total_seconds"]),
        "result_sha256": hashlib.sha256(value["text"].encode("utf-8")).hexdigest(),
        "parent_admission_counters": difference(admitted_started, admitted_counter),
        "parent_runtime_counters": difference(admitted_counter, returned_counter),
        "worker": worker,
    }


def measure(artifacts, output):
    inputs = load_inputs()
    report = {
        "schema": SCHEMA,
        "status": "DIAGNOSTIC",
        "qualification": "NOT_QUALIFIED",
        "measures": "native replay plus real model admission; no governed dispatch/persistence",
        "started_at": datetime.now(UTC).isoformat(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip(),
        "configuration": CONFIGURATION,
        "runtime_lock_sha256": LOCK_SHA256,
        "model_sha256": MODEL_SHA256,
        "clocks": clocks(),
        "inputs_sha256": INPUTS_SHA256,
        "input_provenance": inputs["provenance"],
        "fixed_inputs": inputs["pairs"],
        "plan": "A: pair0 cold/warm, pair1 cold/warm, pair2 cold/warm; identical cycle B",
        "planned_self_tests": 6,
        "samples": plan(inputs["pairs"]),
        "self_tests": [{"cycle": cycle, "pair": pair["id"], "outcome": "NOT_RUN"}
                       for cycle in ("A", "B") for pair in inputs["pairs"]],
        "errors": [],
        "cohort_complete": False,
        "worker_pids": [],
        "network_audit": {"status": "NOT_RUN"},
    }
    runtime = None
    try:
        require_windows_control()
        report["environment"] = hardware()
        selection = native_selection()
        runtime = LocalRuntime(artifacts / "windows")
        store = ModelStore(artifacts / "diagnostic-model-store")
        report["installation"] = store.import_offline(
            MODEL_ID, artifacts / "model.gguf", selection,
            requested=True, license_accepted="Apache-2.0")
        save(output, report)
        index = 0
        for cycle in ("A", "B"):
            for pair in inputs["pairs"]:
                # Six explicitly planned setup operations, not retries. Each pair
                # receives fresh real authority and then an actually cold worker.
                setup = report["self_tests"][index // 2]
                require(setup["cycle"] == cycle and setup["pair"] == pair["id"],
                        "fixed setup order differs")
                setup["outcome"] = "STARTED"
                try:
                    runtime.close()
                    evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
                    setup["evidence"] = evidence.public_record()
                    setup["worker"] = runtime.last_observation
                    require(evidence.result == "PASSED", "real self-test did not pass")
                    store.activate(MODEL_ID, selection, evidence, requested=True)
                    runtime.close()
                    setup["outcome"] = "SUCCEEDED"
                except Exception as error:
                    setup.update(outcome="ERROR", error=error_record(error),
                                 worker=getattr(error, "runtime_observation", None))
                    raise
                finally:
                    report["worker_pids"] = sorted(set(runtime.worker_history))
                    save(output, report)
                for phase in ("cold", "warm"):
                    row = report["samples"][index]
                    try:
                        row.update(measure_request(store, runtime, selection, pair[phase], phase))
                    except Exception as error:
                        row.update(outcome="ERROR", error=error_record(error),
                                   worker=getattr(error, "runtime_observation", None))
                        raise
                    finally:
                        report["worker_pids"] = sorted(set(runtime.worker_history))
                        save(output, report)
                    index += 1
        report["cohort_complete"] = all(r["outcome"] == "MEASURED" for r in report["samples"])
    except Exception as error:
        report["errors"].append(error_record(error))
        report["aborted_remaining_plan"] = "NOT_RUN after recorded error; no retry"
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception as error:
                report["errors"].append(error_record(error))
            report["worker_pids"] = sorted(set(runtime.worker_history))
            report["worker_history"] = list(runtime.worker_history)
            report["worker_absent_after_cleanup"] = not runtime.loaded
        report["finished_at"] = datetime.now(UTC).isoformat()
        save(output, report)
    return report


def audit_network(report, data):
    """Audit only the observed diagnostic workers; never invent S05 coverage."""
    require(report.get("schema") == SCHEMA and report.get("status") == "DIAGNOSTIC"
            and report.get("qualification") == "NOT_QUALIFIED", "diagnostic report required")
    pids = report.get("worker_pids", [])
    require(isinstance(pids, list)
            and all(type(pid) is int and pid > 0 for pid in pids), "observed worker PID list")
    rows = data.get("events", [])
    require(isinstance(rows, list) and len(rows) <= 65536, "bounded WFP event inventory")
    require(all(isinstance(row, dict) and type(row.get("pid")) is int
                and row["pid"] > 0 and type(row.get("id")) is int
                and row["id"] in (5156, 5157) for row in rows), "WFP event shape")
    worker_events = [row for row in rows if row["pid"] in pids]
    calibrated = data.get("audit_enabled") is True and data.get("probe_denied") is True
    samples, setups = report.get("samples", []), report.get("self_tests", [])
    history = report.get("worker_history", [])
    measured = (isinstance(samples, list) and len(samples) == 12
                and all(isinstance(row, dict) and row.get("outcome") == "MEASURED"
                        for row in samples)
                and isinstance(setups, list) and len(setups) == 6
                and all(isinstance(row, dict) and row.get("outcome") == "SUCCEEDED"
                        for row in setups))

    def worker_pid(row):
        worker = row.get("worker")
        load = worker.get("load") if isinstance(worker, dict) else None
        return load.get("pid") if isinstance(load, dict) else None

    observed = [worker_pid(row) for row in [*samples, *setups]] if measured else []
    complete = (bool(pids) and isinstance(history, list) and len(history) == 12
                and all(type(pid) is int and pid > 0 for pid in history)
                and set(history) == set(pids)
                and measured and set(observed) == set(pids)
                and report.get("cohort_complete") is True
                and report.get("worker_absent_after_cleanup") is True
                and not report.get("errors"))
    report["network_audit"] = {
        "method": "Windows Filtering Platform Security event audit",
        "scope": "all recorded worker PIDs through self-test, measured calls and cleanup",
        "worker_pids": pids,
        "worker_events": worker_events,
        "audit_enabled": data.get("audit_enabled") is True,
        "probe_denied": data.get("probe_denied") is True,
        "cohort_and_cleanup_complete": complete,
        "status": ("FAIL" if worker_events else "NOT_RUN" if not calibrated or not complete
                   else "PASS"),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path,
                        help="Audit an existing report only; performs no inference")
    args = parser.parse_args()
    if args.audit:
        require(args.artifacts is None, "audit and measurement are separate operations")
        report = json.loads(args.output.read_text(encoding="utf-8"))
        data = json.loads(args.audit.read_text(encoding="utf-8-sig"))
        report = audit_network(report, data)
        save(args.output, report)
        return 0 if report["network_audit"]["status"] == "PASS" else 2
    require(args.artifacts is not None and args.artifacts.is_absolute(),
            "absolute locked-artifact directory required")
    report = measure(args.artifacts, args.output)
    return 0 if report["cohort_complete"] and not report["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
