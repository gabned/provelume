"""One preregistered prospective comparison; original outcomes are never qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path


def run(source, output, case, arm, expected_head):
    source = source.resolve()
    output.mkdir(parents=True, exist_ok=False)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    assert head == expected_head
    assert not subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True
    )
    sys.path[:0] = [str(source / "tests"), str(source / "core")]
    from test_capture_shell_contract import node
    from test_mobile_shell_contract import (
        test_share_error_reads_only_existing_language_preference_and_falls_back_on_unavailable_store,
    )

    held = []
    processes = []
    rows = []
    lock = threading.Lock()
    original_handles = subprocess.Popen._get_handles
    original_init = subprocess.Popen.__init__
    record = {
        "schema": "entitas-node-stdio-controlled-observation/v1",
        "source_head": head,
        "source_tree": subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True
        ).strip(),
        "arm": arm,
        "case": case,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "node": subprocess.check_output([shutil.which("node"), "--version"], text=True).strip(),
        "ordinary_node_timeout_seconds": 30,
        "held_writer_release_fallback_seconds": 35,
        "root_samples": [],
        "fallback_released": False,
        "qualification": "NOT_GRANTED",
    }

    def selected(process):
        return isinstance(process.args, (list, tuple)) and Path(process.args[0]).name.lower() in {
            "node",
            "node.exe",
        }

    def close_held(fallback=False):
        with lock:
            record["fallback_released"] |= fallback
            while held:
                handle = held.pop()
                if os.name == "nt":
                    import _winapi

                    _winapi.CloseHandle(handle)
                else:
                    os.close(handle)

    def get_handles(process, stdin, stdout, stderr):
        result = original_handles(process, stdin, stdout, stderr)
        if selected(process):
            fixture = Path(process.args[1]).read_bytes()
            (output / "actual-node-fixture.mjs").write_bytes(fixture)
            row = {
                "script_sha256": hashlib.sha256(fixture).hexdigest(),
                "script_bytes": len(fixture),
                "transport": "PIPE" if stdout == subprocess.PIPE else "FILE",
            }
            if case == "held_writer_actual_case":
                if os.name == "nt":
                    import _winapi

                    owner = _winapi.GetCurrentProcess()
                    handle = _winapi.DuplicateHandle(
                        owner, int(result[3]), owner, 0, False, _winapi.DUPLICATE_SAME_ACCESS
                    )
                else:
                    handle = os.dup(result[3])
                    row["native_is_fifo"] = stat.S_ISFIFO(os.fstat(handle).st_mode)
                with lock:
                    held.append(handle)
                row["additional_noninheritable_writer_kept_by_owning_parent"] = True
            rows.append(row)
        return result

    def initialize(process, *args, **kwargs):
        original_init(process, *args, **kwargs)
        if selected(process):
            processes.append(process)

    def sample():
        record["root_samples"].append(
            {
                "parent_perf_ns": time.perf_counter_ns(),
                "root_exit_codes": [process.poll() for process in processes],
                "held_writer_count": len(held),
            }
        )

    fallback = threading.Timer(35, lambda: close_held(True))
    fallback.daemon = True
    samplers = [threading.Timer(delay, sample) for delay in (1, 5, 20, 31)]
    for timer in samplers:
        timer.daemon = True
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    subprocess.Popen._get_handles = get_handles
    subprocess.Popen.__init__ = initialize
    fallback.start()
    for timer in samplers:
        timer.start()
    try:
        if case in {"ordinary_actual_case", "held_writer_actual_case"}:
            test_share_error_reads_only_existing_language_preference_and_falls_back_on_unavailable_store()
        elif case == "nonzero_assertion":
            node("throw new Error('synthetic-node-assertion-must-remain-a-failure');")
        elif case == "live_child_timeout":
            node("setInterval(()=>{},1000);")
        else:
            raise ValueError("case outside frozen cohort")
        record["outcome"] = "PASS"
    except subprocess.TimeoutExpired as error:
        record["outcome"] = "TIMEOUT"
        record["exception"] = {"type": type(error).__name__, "timeout": error.timeout}
        for label, value in [("stdout", error.stdout), ("stderr", error.stderr)]:
            if value is not None:
                raw = value if isinstance(value, bytes) else value.encode("utf-8", "surrogatepass")
                (output / (label + ".output")).write_bytes(raw)
                record[label] = {
                    "type": type(value).__name__,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "representation": "EXACT_BYTES"
                    if isinstance(value, bytes)
                    else "PYTHON_STR_UTF8",
                }
    except AssertionError as error:
        record["outcome"] = "REJECTED_ASSERTION"
        record["exception"] = {"type": type(error).__name__, "message": str(error)}
    except Exception as error:
        record["outcome"] = "UNKNOWN_ERROR"
        record["exception"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        record["wall_ns"] = time.perf_counter_ns() - start
        record["cpu_ns"] = time.process_time_ns() - cpu
        record["held_writers_at_completion"] = len(held)
        record["root_exit_codes_at_completion"] = [process.poll() for process in processes]
        subprocess.Popen._get_handles = original_handles
        subprocess.Popen.__init__ = original_init
        fallback.cancel()
        for timer in samplers:
            timer.cancel()
        close_held()
        fallback.join(timeout=1)
        for timer in samplers:
            timer.join(timeout=1)
        record["controls_reaped"] = all(process.poll() is not None for process in processes)
        record["timers_ended"] = not fallback.is_alive() and all(not t.is_alive() for t in samplers)
        record["node_invocations"] = rows
        record["monetary_cost"] = "UNKNOWN"
        (output / "observation.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: record[k]
                for k in ["arm", "case", "outcome", "wall_ns", "root_exit_codes_at_completion"]
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--arm", choices=["baseline", "fixed"], required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    run(args.source, args.output, args.case, args.arm, args.expected_head)
