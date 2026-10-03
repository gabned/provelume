"""Evaluate external native network observations; missing evidence stays NOT_RUN."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from ai_runtime_report import evaluate  # noqa: E402


def observe(report, *, trace=None, events=None):
    pids = report.get("worker_pids", [])
    complete = (len(report.get("samples", [])) == 60 and bool(report.get("cancel_load"))
                and bool(report.get("cancel_generation")) and bool(report.get("idle_unload"))
                and bool(report.get("worker_error")) and bool(pids))
    evidence = {"status": "NOT_RUN", "complete_phases": complete, "worker_pids": pids}
    if trace is not None and complete:
        texts = []
        for pid in pids:
            path = Path(str(trace) + "." + str(pid))
            if not path.is_file():
                break
            texts.append(path.read_text(encoding="utf-8"))
        if len(texts) == len(pids):
            # Include every traced thread/descendant, not only the Python leaders.
            all_text = "\n".join(p.read_text(encoding="utf-8")
                                 for p in trace.parent.glob(trace.name + ".*"))
            calls = [line for line in all_text.splitlines()
                     if re.search(r"\b(socket|connect|sendto|sendmsg|sendmmsg)\(", line)]
            evidence.update(method="strace-network-all-threads-from-exec-through-exit",
                control="worker seccomp blocks sockets, x32 and io_uring",
                trace_files=len(list(trace.parent.glob(trace.name + ".*"))),
                network_calls=calls,
                status="PASS" if all("= -1 EPERM" in line for line in calls) else "FAIL")
    elif events is not None and complete:
        data = json.loads(events.read_text(encoding="utf-8-sig"))
        rows = data.get("events", [])
        allowed = [r for r in rows if r["pid"] in pids and r["id"] == 5156]
        evidence.update(method="Windows Filtering Platform Security event audit",
            control="ephemeral CI-only outbound firewall rule for exact worker interpreter",
            observer_probe_denied=data.get("probe_denied", False),
            audit_enabled=data.get("audit_enabled", False), successful_events=allowed,
            status=("NOT_RUN" if not data.get("probe_denied") or not data.get("audit_enabled")
                    else "FAIL" if allowed else "PASS"))
    report["network_observation"] = evidence
    report["network"] = evidence["status"]
    evaluate(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--events", type=Path)
    args = parser.parse_args()
    report = observe(json.loads(args.report.read_text(encoding="utf-8")),
                     trace=args.trace, events=args.events)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("S05_REAL_REPORT=" + json.dumps(report))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
