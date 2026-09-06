#!/usr/bin/env python3
"""Run an explicitly selected canonical local check with durable raw evidence.

The caller owns authorization and runtime preparation. No GitHub operation,
CI substitution, credential acquisition or application-test authorization is
provided here. FULL is for an adopted/authorized workflow, never the active stop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import agent_protocol_work_source as source


def run_check(
    snapshot_path: Path,
    baseline: Path,
    candidate: Path,
    output: Path,
    *,
    workstream: str,
    suite: str,
    timeout: int = 900,
    canonical_snapshot: Path | None = None,
    canonical_anchor: Path | None = None,
    adapter_root: Path | None = None,
) -> tuple[dict, int]:
    source.require(os.name == "posix", "canonical Work check requires a POSIX execution host")
    source.require(workstream in {"PROTOCOL", "PRODUCT"}, "explicit supported workstream required")
    source.require(suite in {"PROTOCOL_ONLY", "FULL"}, "explicit canonical suite required")
    source.require(type(timeout) is int and 1 <= timeout <= 3600, "bounded check timeout required")
    started_clock = datetime.now(UTC)
    canonical_source = None
    source.require((canonical_snapshot is None) == (canonical_anchor is None),
                   "canonical vendor snapshot and live anchor must be supplied together")
    if canonical_snapshot is not None:
        source.require(workstream == "PROTOCOL", "canonical vendor adoption requires PROTOCOL")
        canonical_source = source.canonical_input(canonical_snapshot, canonical_anchor,
                                                  now=started_clock)
    baseline, candidate = baseline.resolve(), candidate.resolve()
    source.require(baseline != candidate, "baseline and candidate must be separate")
    source.require(
        not output.exists() and not output.is_symlink(),
        "output already exists; preserve earlier evidence",
    )
    source.require(
        not output.resolve().is_relative_to(candidate)
        and not output.resolve().is_relative_to(baseline),
        "evidence must be outside source directories",
    )
    snapshot = source.read_json(snapshot_path)
    delta = source.candidate_delta(
        snapshot, baseline, candidate, snapshot["repository"], snapshot["commit_sha"]
    )
    source.require(
        snapshot["repository"] == "brickms/brickms",
        "canonical check profile not adopted for this repository",
    )
    command = [
        "bash",
        "tools/agent-check",
        "--work-source",
        str(snapshot_path.resolve()),
        "--work-baseline",
        str(baseline),
        "--workstream-class",
        workstream,
    ]
    if adapter_root is not None:
        source.require(adapter_root.is_dir(), "pinned Work adapter directory unavailable")
        source.require(not adapter_root.resolve().is_relative_to(candidate)
                       and not adapter_root.resolve().is_relative_to(baseline),
                       "external Work adapter must remain outside source directories")
        command += ["--work-tools", str(adapter_root.resolve())]
    if canonical_snapshot is not None:
        command += ["--work-canonical-source", str(canonical_snapshot.resolve()),
                    "--work-canonical-anchor", str(canonical_anchor.resolve())]
    command.append("--protocol-only" if suite == "PROTOCOL_ONLY" else "--full")
    output.mkdir(mode=0o700, parents=False)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "COMPOSER_HOME": str(output / "composer-home"),
    }
    started = started_clock.isoformat()
    timed_out = False
    launch_error = None
    exit_code = None
    with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
        try:
            process = subprocess.Popen(
                command,
                cwd=candidate,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # Stop the private check process group, retaining the real code.
                import signal

                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    exit_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    exit_code = process.wait()
        except OSError as exc:
            launch_error = str(exc)
    source_error = None
    after = None
    try:
        after = source.tree_identity(source.inventory(candidate), verify=True)
        source.verify_source(snapshot, baseline, snapshot["repository"], snapshot["commit_sha"])
        if canonical_source is not None:
            # Replay freshness at the actual check start; do not manufacture a
            # new observation after a long process. Exact input bytes must stay.
            source.require(source.canonical_input(canonical_snapshot, canonical_anchor,
                                                  now=started_clock) == canonical_source,
                           "canonical check input changed during execution")
    except (source.EvidenceError, OSError) as exc:
        source_error = str(exc)
    unchanged = source_error is None and after == delta["candidate_tree_sha"]
    result = {
        "schema": "agent-work-check/v1",
        "repository": snapshot["repository"],
        "base_commit_sha": snapshot["commit_sha"],
        "candidate_tree_sha": delta["candidate_tree_sha"],
        "canonical_source": canonical_source,
        "candidate_tree_after": after,
        "source_unchanged": unchanged,
        "suite": suite,
        "command": command,
        "command_digest": source.digest(command),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "launch_error": launch_error,
        "source_error": source_error,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "push_qualified": False,
    }
    for stream in ("stdout", "stderr"):
        result[stream + "_sha256"] = hashlib.sha256(
            (output / (stream + ".log")).read_bytes()
        ).hexdigest()
    code = 0 if exit_code == 0 and unchanged and not timed_out and launch_error is None else 2
    result["adapter_exit_code"] = code
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "baseline", "candidate", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--workstream", choices=["PROTOCOL", "PRODUCT"], required=True)
    parser.add_argument("--suite", choices=["PROTOCOL_ONLY", "FULL"], required=True)
    parser.add_argument("--canonical-snapshot", type=Path)
    parser.add_argument("--canonical-anchor", type=Path)
    parser.add_argument("--adapter-root", type=Path)
    args = parser.parse_args()
    try:
        result, code = run_check(
            args.snapshot,
            args.baseline,
            args.candidate,
            args.output,
            workstream=args.workstream,
            suite=args.suite,
            canonical_snapshot=args.canonical_snapshot,
            canonical_anchor=args.canonical_anchor,
            adapter_root=args.adapter_root,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return code
    except (source.EvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc), "push_qualified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
