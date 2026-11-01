"""One bounded journal-path A/B/B/A diagnostic; never application qualification."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = "1ad882478636dbd4e5c7fc676fb0d861224e067e"
CHANGE = "fc06497b21ecaa370b87927351b87d310572ac47"
TREES = {BASE: "6d7094fc3bb7a008a5d336e1853a05bf6b74bb31",
         CHANGE: "c56fae1ef68e2cdfa1836631bb568c15aa43ffcc"}
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
ATOMIC = "core/provelume/atomic_commit.py"
BEFORE = b"        path = safe_instance_path(stage, relative)\n"
AFTER = (
    b"        lexical = stage.joinpath(*PurePosixPath(relative).parts)\n"
    b"        # The kernel validates the complete chain without following links.\n"
    b"        # Keep the original resolver on unsupported hosts and the fresh\n"
    b"        # per-component checks below on every host; no observation is cached.\n"
    b"        path = (lexical if stage.is_absolute() and kernel_no_links(lexical)\n"
    b"                else safe_instance_path(stage, relative))\n"
)


def write(path, value, *, exclusive=False):
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def git(repository, *args):
    return subprocess.check_output(["git", *args], cwd=repository, timeout=30)


def verify_factor(before, after, paths):
    expected = {ATOMIC, "docs/qualification/concordia-cpu-diagnosis.md",
                "tests/test_atomic_journal_paths.py"}
    if set(paths) != expected or before.count(BEFORE) != 1:
        raise ValueError("uncontrolled journal comparison delta")
    if before.replace(BEFORE, AFTER, 1) != after:
        raise ValueError("journal replacement differs from the declared factor")


def sources(repository):
    if git(repository, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("committed clean owner source required")
    if git(repository, "show", "-s", "--format=%P", CHANGE).decode().strip() != BASE:
        raise ValueError("journal source must be the sole direct child of A")
    paths = git(repository, "diff", "--name-only", BASE, CHANGE).decode().splitlines()
    before, after = (git(repository, "show", ref + ":" + ATOMIC) for ref in (BASE, CHANGE))
    verify_factor(before, after, paths)
    if git(repository, "show", "HEAD:" + ATOMIC) != after:
        raise ValueError("owner no longer contains the exact journal change")
    trees = {ref: git(repository, "rev-parse", ref + "^{tree}").decode().strip()
             for ref in (BASE, CHANGE)}
    if trees != TREES:
        raise ValueError("immutable comparison tree mismatch")
    return {"owner_head": git(repository, "rev-parse", "HEAD").decode().strip(),
            "trees": trees, "changed_paths": paths,
            "atomic_sha256": {BASE: hashlib.sha256(before).hexdigest(),
                              CHANGE: hashlib.sha256(after).hexdigest()}}


def environment():
    return {"kernel": platform.release(), "machine": platform.machine(),
            "python": platform.python_version(), "executable": sys.executable,
            "allowed_cpus": sorted(os.sched_getaffinity(0)),
            "cpu_models": sorted({line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")}),
            "topology": {str(cpu): {name: Path(
                f"/sys/devices/system/cpu/cpu{cpu}/topology", name).read_text().strip()
                for name in ("physical_package_id", "core_id", "thread_siblings_list")}
                for cpu in sorted(os.sched_getaffinity(0))},
            "cgroup_limits": {name: Path("/sys/fs/cgroup", name).read_text().strip()
                              for name in ("cpu.max", "memory.max", "cpuset.cpus.effective")}}


def admit(repository, output):
    from provelume.ai_runtime_contract import hardware
    from scripts.diagnose_concordia_cpu import calibrate_scheduler

    source = sources(repository)
    observed = environment()
    native = hardware()
    scheduler = calibrate_scheduler()
    if scheduler["status"] != "POSITIVE_RUNQUEUE_CONTROL":
        raise ValueError("positive scheduler control required")
    with tempfile.TemporaryDirectory(prefix="journal-strace-") as name:
        trace = Path(name) / "network"
        smoke = subprocess.run([
            "strace", "-ff", "-tt", "-e", "trace=network", "-o", str(trace),
            sys.executable, "-c", "import socket; s=socket.socket(); s.close()",
        ], capture_output=True, text=True, timeout=20)
        traces = [path.read_text() for path in trace.parent.glob("network.*")]
        if smoke.returncode or not traces or not any("socket(AF_INET" in t for t in traces):
            raise ValueError("actual all-thread strace smoke required")
    receipt = {"schema": "concordia-journal-admission/v1", "status": "ADMITTED",
               "source": source, "environment": observed, "native_hardware": native,
               "scheduler_control": scheduler, "strace_smoke": traces,
               "driver_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
               "qualification_eligible": False}
    write(output, receipt, exclusive=True)
    print(json.dumps({"status": receipt["status"], "environment": observed}))


def timing_projection(report):
    """Classify mixed gates on a disposable copy; never alter original evidence.

    Only concurrent Capture/search durations are projected to zero. The original
    evaluator then checks every other conjunct, including correctness, native
    inference, cancellation and cleanup. Original idle limits and every original
    gate/result survive unchanged. This is a stop control, never a PASS receipt.
    """
    result = copy.deepcopy(report)
    probes = list(result.get("deterministic_busy", []))
    probes += result.get("s06", {}).get("deterministic_busy", [])
    probes += [row["probe"] for row in result.get("s07", {}).get("samples", [])]
    probes += [row["probe"] for row in result.get("s08", {}).get("performance", [])]
    for probe in probes:
        for key in ("capture_seconds", "search_seconds"):
            if key in probe:
                probe[key] = 0
    return result


def inspect_report(source, report_path, output):
    sys.path[:0] = [str(source / "scripts"), str(source / "core"), str(source)]
    from ai_runtime_report import evaluate

    report = json.loads(report_path.read_text())
    projected = evaluate(timing_projection(report))
    result = {"schema": "concordia-journal-stop-control/v1",
              "qualification_eligible": False, "original_status": report["status"],
              "original_gates": report["gates"], "original_failures": report["failures"],
              "non_capture_conjuncts_checked": not projected["failures"]
                  and all(value == "PASS" for value in projected["gates"].values()),
              "projection": "zero concurrent Capture/search times in disposable copy only",
              "capture": {}}
    for label, idle, busy in (
        ("deterministic", report["deterministic_idle"], report["deterministic_busy"]),
        ("s06", report["deterministic_idle"], report["s06"]["deterministic_busy"]),
        ("s07", report["deterministic_idle"], [r["probe"] for r in report["s07"]["samples"]]),
        ("s08", report["s08"]["idle"], [r["probe"] for r in report["s08"]["performance"]]),
    ):
        result["capture"][label] = {}
        for key in ("capture_seconds", "search_seconds"):
            limit = min(1, 2 * statistics.median(r[key] for r in idle) + 0.1)
            values = [r[key] for r in busy]
            result["capture"][label][key] = {"limit": limit, "values": values,
                "margins": [limit - value for value in values],
                "exceedances": sum(value > limit for value in values)}
    write(output, result, exclusive=True)


def execute(command, source, log, timeout):
    with log.open("x") as stream:
        process = subprocess.Popen(command, cwd=source, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
            raise


def run(repository, inputs, admission_path, output):
    from provelume.ai_runtime_contract import MODEL_SHA256, MODEL_SIZE, runtime_lock

    admission = json.loads(admission_path.read_text())
    source = sources(repository)
    if (admission.get("status") != "ADMITTED" or admission["source"] != source
            or admission["environment"] != environment()
            or admission["driver_sha256"] != hashlib.sha256(SCRIPT.read_bytes()).hexdigest()):
        raise ValueError("source, driver or host changed after admission")
    inventory = {"model.gguf": {"size": MODEL_SIZE, "sha256": MODEL_SHA256},
                 **{"linux/" + name: pin
                    for name, pin in runtime_lock()["platforms"]["linux"].items()}}
    for name, expected in inventory.items():
        path = inputs / name
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if (path.is_symlink() or path.stat().st_size != expected["size"]
                or digest != expected["sha256"]):
            raise ValueError("locked native input mismatch: " + name)
    output.mkdir(parents=True, exist_ok=False)
    write(admission_path.with_suffix(".started.json"),
          {"output": str(output), "owner_head": source["owner_head"]}, exclusive=True)
    manifest = {"schema": "concordia-journal-comparison/v1", "status": "RUNNING",
                "qualification_eligible": False, "source": source, "admission": admission,
                "arms": [], "observer": "original network-only strace, no added wrappers",
                "order": [BASE, CHANGE, CHANGE, BASE], "findings": "CURRENT"}
    write(output / "manifest.json", manifest)
    shutil.copyfile(SCRIPT, output / "driver.py")
    deadline = time.monotonic() + 85 * 60

    def remaining(limit):
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("85-minute overall limit")
        return min(limit, seconds)

    try:
        with (tempfile.TemporaryDirectory(prefix="journal-source-") as scratch,
              tempfile.TemporaryDirectory(prefix="replay-", dir=inputs.parent) as replay):
            checkout, data = Path(scratch) / "source", Path(replay)
            if len(data.parts) != len(inputs.parts):
                raise ValueError("unequal acquired and replay path depth")
            for index, revision in enumerate(manifest["order"]):
                if time.monotonic() >= deadline:
                    raise TimeoutError("85-minute overall limit; no next arm")
                if environment() != admission["environment"] or sources(repository) != source:
                    raise ValueError("source or host changed between arms")
                arm_output = output / f"arm-{index}"
                arm_output.mkdir()
                arm = {"index": index, "source": revision, "tree": TREES[revision],
                       "started_ns": time.time_ns()}
                manifest["arms"].append(arm)
                write(output / "manifest.json", manifest)
                git(repository, "worktree", "add", "--detach", str(checkout), revision)
                try:
                    shutil.copytree(inputs / "linux", data / "linux")
                    shutil.copyfile(inputs / "model.gguf", data / "model.gguf")
                    original = arm_output / "report-before-observer.json"
                    trace = arm_output / "network"
                    command = ["strace", "-ff", "-tt", "-e", "trace=network", "-o", str(trace),
                        sys.executable, str(checkout / "scripts/qualify_ai_runtime.py"),
                        "--artifacts", str(data), "--output", str(original)]
                    arm["exit_code"] = execute(command, checkout, arm_output / "execution.log",
                                               remaining(1200))
                    if arm["exit_code"] not in {0, 1}:
                        raise ValueError("abnormal application exit; no next arm")
                    if not original.is_file():
                        raise ValueError("missing original application report")
                    report = arm_output / "report.json"
                    shutil.copyfile(original, report)
                    observer = [sys.executable, str(checkout / "scripts/ai_runtime_network.py"),
                                "--report", str(report), "--trace", str(trace)]
                    arm["observer_exit_code"] = execute(observer, checkout,
                                                        arm_output / "observer.log", remaining(60))
                    observed = json.loads(report.read_text())
                    if observed.get("network") != "PASS" or observed.get("failures"):
                        raise ValueError("application or mandatory network observation failed")
                    inspect = [sys.executable, str(SCRIPT), "inspect", "--source", str(checkout),
                               "--report", str(report),
                               "--output", str(arm_output / "analysis.json")]
                    if execute(inspect, checkout, arm_output / "analysis.log", remaining(60)):
                        raise ValueError("incomplete report analysis")
                    analysis = json.loads((arm_output / "analysis.json").read_text())
                    arm.update(finished_ns=time.time_ns(), original_status=observed["status"],
                               original_gates=observed["gates"], capture=analysis["capture"])
                    if not analysis["non_capture_conjuncts_checked"]:
                        raise ValueError("non-capture gate failure; no next arm")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("85-minute overall limit")
                finally:
                    git(repository, "worktree", "remove", str(checkout))
                    shutil.rmtree(data)
                    data.mkdir()
                    write(output / "manifest.json", manifest)
        manifest["status"] = "COMPLETE_DIAGNOSTIC_ONLY"
    except Exception as exc:
        manifest.update(status="STOPPED", error={"type": type(exc).__name__, "detail": str(exc)})
        raise
    finally:
        write(output / "manifest.json", manifest)


def main():
    sys.path[:0] = [str(ROOT), str(ROOT / "core")]
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    admission = commands.add_parser("admit")
    admission.add_argument("--repository", type=Path, required=True)
    admission.add_argument("--output", type=Path, required=True)
    study = commands.add_parser("run")
    for name in ("repository", "inputs", "admission", "output"):
        study.add_argument("--" + name, type=Path, required=True)
    inspection = commands.add_parser("inspect")
    for name in ("source", "report", "output"):
        inspection.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "admit":
        admit(args.repository.resolve(), args.output.resolve())
    elif args.command == "inspect":
        inspect_report(args.source.resolve(), args.report.resolve(), args.output.resolve())
    else:
        run(args.repository.resolve(), args.inputs.resolve(), args.admission.resolve(),
            args.output.resolve())


if __name__ == "__main__":
    main()
