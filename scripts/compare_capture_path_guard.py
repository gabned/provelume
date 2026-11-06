"""One fixed Capture guard source-factor comparison; never qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "core")]
from scripts import compare_concordia_journal as common  # noqa: E402
from scripts.diagnose_concordia_cpu import calibrate_scheduler  # noqa: E402

BASE = "d5b2cc9f06c14be8c51a082d309dbde0358552e8"
CHANGE = "d7368ccfcc869afd677e8d881c943b34b2e69de1"
MAIN = "1711f037b1467d84eb5e145466dad6a6171643fc"
PRODUCT = "core/provelume/capture_journal.py"
HASHES = {BASE: "3f0a6808d5754660d5a150a1c8a1ab13b71ef4094d23e3a1440ce586e9c4159b",
          CHANGE: "a7aad4b5230382b9651dfb882fe8a69ef6c1b15eb05156fab71b0b14f36eb44f"}
SCRIPT = Path(__file__).resolve()
PATHS = {PRODUCT, "tests/test_capture_path_guard.py",
         "docs/qualification/concordia-cpu-diagnosis.md"}
DRIVER_PATHS = {"scripts/compare_capture_path_guard.py", "tests/test_capture_guard_comparison.py",
                ".github/workflows/ai-runtime-candidate.yml",
                "docs/qualification/concordia-cpu-diagnosis.md"}


def verify_factor(before, after, paths):
    if set(paths) != PATHS:
        raise ValueError("uncontrolled Capture guard delta")
    if any(hashlib.sha256(value).hexdigest() != HASHES[revision]
           for revision, value in ((BASE, before), (CHANGE, after))):
        raise ValueError("Capture guard bytes differ from the declared factor")


def sources(repository):
    def git(*args):
        return common.git(repository, *args).decode().strip()
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("clean committed owner required")
    if git("rev-parse", "refs/remotes/origin/main") != MAIN:
        raise ValueError("fresh fetched main changed; stop")
    if git("show", "-s", "--format=%P", CHANGE) != BASE:
        raise ValueError("declared factor is not the sole child of A")
    paths = git("diff", "--name-only", BASE, CHANGE).splitlines()
    verify_factor(*(common.git(repository, "show", ref + ":" + PRODUCT)
                    for ref in (BASE, CHANGE)), paths)
    if git("rev-parse", MAIN + ":core") != git("rev-parse", BASE + ":core"):
        raise ValueError("baseline PRODUCT differs from accepted main")
    if git("rev-parse", "HEAD:core") != git("rev-parse", CHANGE + ":core"):
        raise ValueError("driver introduces another PRODUCT factor")
    if not set(git("diff", "--name-only", CHANGE, "HEAD").splitlines()) <= DRIVER_PATHS:
        raise ValueError("driver source changed outside its diagnostic scope")
    fixed = ["scripts/qualify_ai_runtime.py", "scripts/qualify_ai_jobs.py",
             "scripts/qualify_ai_setup.py", "scripts/qualify_ai_synthesis.py",
             "scripts/ai_runtime_report.py", "scripts/ai_runtime_network.py",
             "scripts/ai_runtime_acquire.py", "scripts/compare_concordia_journal.py",
             "scripts/diagnose_concordia_cpu.py", "pyproject.toml", "requirements-build.txt"]
    for path in fixed:
        if len({git("rev-parse", ref + ":" + path) for ref in (BASE, CHANGE, "HEAD")}) != 1:
            raise ValueError("fixed qualification input changed: " + path)
    return {"owner_head": git("rev-parse", "HEAD"), "main": MAIN, "changed_paths": paths,
            "trees": {ref: git("rev-parse", ref + "^{tree}") for ref in (BASE, CHANGE)},
            "product_sha256": HASHES,
            "driver_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest()}


def admit(repository, output):
    from provelume.ai_runtime_contract import hardware

    receipt = {"schema": "concordia-capture-guard-admission/v1",
               "status": "CAPABILITY_MISSING", "qualification_eligible": False}
    try:
        receipt.update(source=sources(repository), environment=common.environment(),
                       native_hardware=hardware())
        receipt["scheduler"] = calibrate_scheduler()
        if receipt["scheduler"]["status"] != "POSITIVE_RUNQUEUE_CONTROL":
            raise ValueError("positive scheduler control required")
        with tempfile.TemporaryDirectory(prefix="capture-guard-smoke-") as scratch:
            trace = Path(scratch) / "network"
            import subprocess

            smoke = subprocess.run(["strace", "-ff", "-tt", "-e", "trace=network",
                "-o", str(trace), sys.executable, "-c",
                "import socket,threading; "
                "t=threading.Thread(target=lambda:socket.socket().close());"
                "t.start();t.join()"], capture_output=True, text=True, timeout=20)
            texts = [p.read_text() for p in trace.parent.glob("network.*")]
            receipt["strace_smoke"] = {"exit": smoke.returncode, "traces": texts}
            if smoke.returncode or len(texts) < 2 or not any("socket(AF_INET" in t for t in texts):
                raise ValueError("all-thread network observer unavailable")
        receipt["status"] = "ADMITTED"
    finally:
        common.write(output, receipt, exclusive=True)


def consume(admission, source, observed, output):
    if (admission.get("schema") != "concordia-capture-guard-admission/v1"
            or admission.get("status") != "ADMITTED" or admission.get("source") != source
            or admission.get("environment") != observed):
        raise ValueError("source, driver or host changed after admission")
    common.write(output, {"source": source, "qualification_eligible": False}, exclusive=True)


def run(repository, inputs, admission_path, output):
    from provelume.ai_runtime_contract import MODEL_SHA256, MODEL_SIZE, runtime_lock

    source = sources(repository)
    admission = json.loads(admission_path.read_text())
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
    consume(admission, source, common.environment(), admission_path.with_suffix(".started.json"))
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema": "concordia-capture-guard-comparison/v1", "status": "RUNNING",
                "qualification_eligible": False, "source": source, "admission": admission,
                "arms": [], "order": [BASE, CHANGE, CHANGE, BASE],
                "observer": "original strace -ff -tt -e trace=network; no wrappers or BPF",
                "findings": "CURRENT / NOT_DEMONSTRATED"}
    common.write(output / "manifest.json", manifest)
    shutil.copyfile(SCRIPT, output / "driver.py")
    deadline = time.monotonic() + 85 * 60

    def remaining(limit):
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("85-minute overall bound; no next arm")
        return min(limit, seconds)

    try:
        with (tempfile.TemporaryDirectory(prefix="capture-guard-source-") as scratch,
              tempfile.TemporaryDirectory(prefix="replay-", dir=inputs.parent) as replay):
            checkout, data = Path(scratch) / "source", Path(replay)
            if len(data.parts) != len(inputs.parts):
                raise ValueError("unequal input/store path depth")
            for index, revision in enumerate(manifest["order"]):
                remaining(1200)
                if (sources(repository) != source
                        or common.environment() != admission["environment"]):
                    raise ValueError("source or host changed between arms")
                arm_output = output / f"arm-{index}"
                arm_output.mkdir()
                arm = {"source": revision, "index": index, "started_ns": time.time_ns()}
                manifest["arms"].append(arm)
                common.write(output / "manifest.json", manifest)
                common.git(repository, "worktree", "add", "--detach", str(checkout), revision)
                try:
                    shutil.copytree(inputs / "linux", data / "linux")
                    shutil.copyfile(inputs / "model.gguf", data / "model.gguf")
                    original = arm_output / "report-before-observer.json"
                    trace = arm_output / "network"
                    arm["exit"] = common.execute(["strace", "-ff", "-tt", "-e", "trace=network",
                        "-o", str(trace), sys.executable,
                        str(checkout / "scripts/qualify_ai_runtime.py"),
                        "--artifacts", str(data), "--output", str(original)], checkout,
                        arm_output / "execution.log", remaining(1200))
                    if arm["exit"] not in {0, 1} or not original.is_file():
                        raise ValueError("abnormal application exit or missing report")
                    report = arm_output / "report.json"
                    shutil.copyfile(original, report)
                    arm["observer_exit"] = common.execute([sys.executable,
                        str(checkout / "scripts/ai_runtime_network.py"), "--report", str(report),
                        "--trace", str(trace)], checkout, arm_output / "observer.log",
                        remaining(60))
                    observed = json.loads(report.read_text())
                    arm.update(original_status=observed.get("status"),
                               original_gates=observed.get("gates"), finished_ns=time.time_ns())
                    if observed.get("network") != "PASS" or observed.get("failures"):
                        raise ValueError("application or mandatory network failure; no next arm")
                    if any(not re.search(r"\+\+\+ (exited with|killed by)", p.read_text())
                           for p in arm_output.glob("network.*")):
                        raise ValueError("tracee exit unobserved; no next arm")
                    analysis_path = arm_output / "analysis.json"
                    if common.execute([sys.executable, str(common.SCRIPT), "inspect", "--source",
                        str(checkout), "--report", str(report), "--output", str(analysis_path)],
                        checkout, arm_output / "analysis.log", remaining(60)):
                        raise ValueError("incomplete original stop control")
                    analysis = json.loads(analysis_path.read_text())
                    arm["capture"] = analysis["capture"]
                    if not analysis["non_capture_conjuncts_checked"]:
                        raise ValueError("non-timing failure; no next arm")
                finally:
                    common.git(repository, "worktree", "remove", str(checkout))
                    shutil.rmtree(data)
                    data.mkdir()
                    common.write(output / "manifest.json", manifest)
        manifest["status"] = "COMPLETE_DIAGNOSTIC_ONLY"
    except BaseException as exc:
        manifest.update(status="STOPPED", error={"type": type(exc).__name__, "detail": str(exc)})
        raise
    finally:
        common.write(output / "manifest.json", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("admit", "run"))
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--admission", type=Path)
    args = parser.parse_args()
    if args.command == "admit":
        admit(args.repository.resolve(), args.output.resolve())
    else:
        if args.inputs is None or args.admission is None:
            parser.error("run requires --inputs and --admission")
        run(args.repository.resolve(), args.inputs.resolve(), args.admission.resolve(),
            args.output.resolve())


if __name__ == "__main__":
    main()
