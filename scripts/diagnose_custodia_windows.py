"""One instrumented Windows observation of S05; never a qualification or retry gate."""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "cd7dc64f3ffb2a17689018b3350f0e1c073abdd4"
_rows = []
_sample = "setup"
_request = None
_runtime = None


def stamp():
    return {"wall_ns": time.monotonic_ns(), "performance_ns": time.perf_counter_ns(),
            "cpu_ns": time.process_time_ns(),
            "thread_cpu_ns": time.thread_time_ns(), "pid": os.getpid(),
            "tid": threading.get_native_id()}


def record(phase, start, end=None, **extra):
    _rows.append({"phase": phase, "sample": _sample, "request": _request,
                  "start": start, "end": end or stamp(), **extra})


def wrap(target, name, phase, *, after=None):
    original = getattr(target, name)

    @functools.wraps(original)
    def observed(*args, **kwargs):
        start = stamp()
        try:
            result = original(*args, **kwargs)
            if after is not None:
                after(args, result)
            return result
        finally:
            record(phase, start)

    setattr(target, name, observed)


def install_worker(directory):
    """Installed only by this harness before the unchanged containment/main entry."""
    from provelume import ai_llama, ai_model_file, ai_runtime_worker

    trace = (Path(directory) / f"worker-{os.getpid()}.jsonl").open("w", encoding="utf-8")
    wrap(ai_model_file, "verify_stream", "gguf.verify_stream")
    # The worker imports this function directly; preserve its original behavior.
    ai_runtime_worker.verify_stream = ai_model_file.verify_stream
    wrap(hashlib, "file_digest", "runtime.file_digest")
    state = {"phase": "idle"}

    def read_request(args, value):
        global _request
        _request = value.get("request")
        point = stamp()
        record("worker.request_read", point, point)

    wrap(ai_runtime_worker, "read", "worker.read", after=read_request)

    def installed(args, result):
        engine = args[0]
        decode = engine.decode

        def measured_decode(*values):
            start = stamp()
            try:
                return decode(*values)
            finally:
                if state["phase"] == "prefill":
                    record("native.prefill_decode", start)

        engine.decode = measured_decode

    wrap(ai_llama.Llama, "__init__", "native.load", after=installed)
    wrap(ai_llama.Llama, "generate", "native.generate")
    emit = ai_runtime_worker.emit

    def observed_emit(value):
        if value["event"] == "prefill":
            state["phase"] = "prefill"
        elif value["event"] == "first":
            state["phase"] = "decode"
        start = stamp()
        emit(value)  # No diagnostic keys enter the accepted IPC protocol.
        record("worker.emit." + value["event"], start)
        if value["event"] in {"loaded", "result", "error", "unloaded"}:
            start = stamp()
            for row in _rows:
                trace.write(json.dumps(row, separators=(",", ":")) + "\n")
            _rows.clear()
            trace.flush()
            record("observer.flush", start)

    ai_runtime_worker.emit = observed_emit


def install_parent(directory, capture=None):
    from provelume import ai_model_file, ai_model_store, ai_runtime

    wrap(ai_model_file, "verify_stream", "gguf.verify_stream")
    wrap(ai_runtime.LocalRuntime, "validate_installation", "runtime.validate_installation")
    wrap(ai_runtime.LocalRuntime, "qualify", "parent.qualify")
    wrap(ai_runtime.LocalRuntime, "_infer", "parent.infer")
    wrap(ai_runtime.LocalRuntime, "_infer_owned", "parent.infer_owned")
    use = ai_model_store.ModelStore.use

    @contextlib.contextmanager
    def observed_use(*args, **kwargs):
        start = stamp()
        with use(*args, **kwargs) as model:
            record("admission.store_use", start)
            yield model

    ai_model_store.ModelStore.use = observed_use
    send = ai_runtime.LocalRuntime._send

    def observed_send(runtime, value, **kwargs):
        global _request
        _request = value.get("request")
        start = stamp()
        try:
            return send(runtime, value, **kwargs)
        finally:
            record("parent.send", start, worker_pid=runtime._process.pid)

    ai_runtime.LocalRuntime._send = observed_send
    receive = ai_runtime.LocalRuntime._receive

    def observed_receive(runtime, event, **kwargs):
        start = stamp()
        result = receive(runtime, event, **kwargs)
        record("parent.receive." + event, start, worker_pid=runtime._process.pid,
               first_received=runtime._first_received,
               prefill_received=runtime._prefill_observation)
        return result

    ai_runtime.LocalRuntime._receive = observed_receive
    put = ai_runtime.queue.Queue.put_nowait

    def observed_put(queue, value):
        if type(value) is dict and value.get("event") in {"first", "prefill"}:
            point = stamp()
            record("reader.queue." + value["event"], point, point)
        return put(queue, value)

    ai_runtime.queue.Queue.put_nowait = observed_put
    get = ai_runtime.queue.Queue.get

    def observed_get(queue, *args, **kwargs):
        value = get(queue, *args, **kwargs)
        if type(value) is dict and value.get("event") in {"first", "prefill"}:
            point = stamp()
            record("supervisor.dequeue." + value["event"], point, point)
        return value

    ai_runtime.queue.Queue.get = observed_get
    popen = subprocess.Popen

    def observed_popen(command, *args, **kwargs):
        marker = "from provelume.ai_runtime_limits import contain;"
        if type(command) is list and "-c" in command:
            index = command.index("-c") + 1
            if marker in command[index]:
                command = list(command)
                setup = ("import runpy;runpy.run_path(" + repr(str(Path(__file__).resolve()))
                         + ")[\"install_worker\"](" + repr(str(directory)) + ");")
                command[index] = command[index].replace(marker, setup + marker, 1)
        return popen(command, *args, **kwargs)

    subprocess.Popen = observed_popen
    if capture is not None:
        qualify = ai_runtime.LocalRuntime.qualify
        target = next(row for row in json.loads(
            (ROOT / "tests/fixtures/ai_runtime_quality.json").read_text()) if row["id"] == "en04")
        target_prompt = "Text: " + target["text"] + "\nQuestion: " + target["question"]

        def captured_qualify(runtime, store, prompt, **kwargs):
            if _sample.endswith("/en01") and capture.active is None:
                capture.start(int(_sample.split("/", 1)[0][3:]), runtime)
            try:
                return qualify(runtime, store, prompt, **kwargs)
            finally:
                if _sample.endswith("/en04") and prompt == target_prompt:
                    capture.stop(runtime)

        ai_runtime.LocalRuntime.qualify = captured_qualify


def main():
    global _runtime, _sample, _request
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scheduler-trace", action="store_true")
    args = parser.parse_args()
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("Requires a disposable GitHub Windows runner; no native run performed.")
    sys.path[:0] = [str(ROOT / "core"), str(ROOT / "scripts")]
    from qualify_ai_runtime import measure_busy_probe, measure_warm_case

    from provelume.ai_model_store import ModelStore
    from provelume.ai_runtime import LocalRuntime, native_selection
    from provelume.ai_runtime_contract import MODEL_ID, hardware
    from provelume.service import ProvelumeInstance

    # The immutable accepted source is a comparison anchor, not a qualification claim.
    subprocess.run(["git", "diff", "--exit-code", SOURCE, "--", "core",
                    "tests/fixtures/ai_runtime_quality.json", "scripts/qualify_ai_runtime.py"],
                   cwd=ROOT, check=True)
    directory = args.output.parent.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    report = {"purpose": "DIAGNOSTIC_ONLY", "qualification": "NOT_EVALUATED",
              "original_run": 38289564204, "original_attempt": 1,
              "original_fail": {"family": 25, "model": 1, "case": "en04", "run": 2,
                                "first_wall_seconds": 5.797, "limit_seconds": 5},
              "source_runtime": SOURCE, "diagnostic_head": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "environment": hardware(), "samples": [], "warm_preparations": [],
              "observer": "wrappers, monotonic/QPC/process/thread clocks; buffered child trace",
              "causal_attribution_to_original": "NOT_DEMONSTRATED",
              "status": "STARTED"}
    capture = None
    if args.scheduler_trace:
        from custodia_windows_etw import SchedulerCapture

        capture = SchedulerCapture(directory)
        report["scheduler_sessions"] = capture.sessions
    install_parent(directory, capture)
    store = ModelStore(args.artifacts / "diagnostic-store")
    selection = native_selection()
    _runtime = runtime = LocalRuntime((args.artifacts / "windows").resolve())

    def save():
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (directory / "parent.jsonl").write_text("".join(
            json.dumps(r, separators=(",", ":")) + "\n" for r in _rows), encoding="utf-8")

    try:
        store.import_offline(MODEL_ID, args.artifacts / "model.gguf", selection,
                             requested=True, license_accepted="Apache-2.0")
        corpus = json.loads((ROOT / "tests/fixtures/ai_runtime_quality.json").read_text())
        instance = ProvelumeInstance.initialise(args.artifacts / "diagnostic-instance")
        # One fixed observation, retaining all original S05 warm-case ordering.
        # No score evaluation, stop-on-green, thresholds, or qualification workflow rerun.
        for run in range(3):
            _sample = f"run{run}/setup"
            runtime.close()
            evidence = store.self_test(MODEL_ID, selection, runtime, requested=True)
            report.setdefault("self_tests", []).append(evidence.public_record())
            if evidence.result != "PASSED":
                raise RuntimeError("Diagnostic self-test failed; no repeat.")
            store.activate(MODEL_ID, selection, evidence, requested=True)
            model = store.verify(MODEL_ID, selection)
            outcomes, errors = [], []

            def busy(model=model, outcomes=outcomes, errors=errors):
                try:
                    outcomes.append(runtime._infer(model, selection,
                        "Text: The synthetic word is orchid. Question: Repeat orchid 100 times."))
                except Exception as exc:
                    errors.append(type(exc).__name__)

            started, previous = time.monotonic(), runtime._request_id
            thread = threading.Thread(target=busy)
            thread.start()
            report.setdefault("busy_probes", []).append(measure_busy_probe(
                instance, runtime, thread, run, started=started, previous_request=previous))
            thread.join()
            if errors:
                raise RuntimeError("Diagnostic busy probe failed; no repeat.")
            for case in corpus:
                _sample, _request = f"run{run}/{case['id']}", None
                evidence = measure_warm_case(report, store, runtime, selection, evidence, case, run)
                save()
        report["status"] = "OBSERVED"
    except Exception as exc:
        report["status"] = "DIAGNOSTIC_ERROR"
        report["error_type"] = type(exc).__name__
        raise
    finally:
        try:
            if capture is not None:
                capture.stop(runtime)
        finally:
            runtime.close()
            report["worker_absent"] = not runtime.loaded
            save()


if __name__ == "__main__":
    main()
