"""Validate every frozen controlled observation, retaining expected FAILs as FAILs."""

import argparse
import hashlib
import json
from pathlib import Path


def verify(root, plan_path):
    plan = json.loads(plan_path.read_text())
    instrument = plan_path.parents[1] / plan["instrument_path"]
    assert hashlib.sha256(instrument.read_bytes()).hexdigest() == plan["instrument_sha256"]
    cases = [row["case"] for row in plan["cohort"]]
    rows, failures = [], []
    expected = {
        "ordinary_actual_case": {"baseline": "PASS", "fixed": "PASS"},
        "held_writer_actual_case": {"baseline": "TIMEOUT", "fixed": "PASS"},
        "nonzero_assertion": {"baseline": "REJECTED_ASSERTION", "fixed": "REJECTED_ASSERTION"},
        "live_child_timeout": {"baseline": "TIMEOUT", "fixed": "TIMEOUT"},
    }
    for case in cases:
        pair = []
        for arm in ("baseline", "fixed"):
            try:
                row = json.loads((root / f"{case}-{arm}" / "observation.json").read_text())
                assert row["source_head"] == plan["base" if arm == "baseline" else "fixed"]
                assert row["case"] == case and row["arm"] == arm
                assert row["outcome"] == expected[case][arm]
                assert row["controls_reaped"] and row["timers_ended"]
                assert row["ordinary_node_timeout_seconds"] == 30
                assert len(row["node_invocations"]) == 1
                assert row["node_invocations"][0]["transport"] == (
                    "PIPE" if arm == "baseline" else "FILE"
                )
                if row["outcome"] == "TIMEOUT":
                    assert row["exception"]["timeout"] == 30
                if case == "held_writer_actual_case":
                    assert row["root_exit_codes_at_completion"] == [0]
                    assert row["node_invocations"][0][
                        "additional_noninheritable_writer_kept_by_owning_parent"
                    ]
                    if arm == "baseline":
                        assert any(
                            sample["root_exit_codes"] == [0] and sample["held_writer_count"] == 1
                            for sample in row["root_samples"]
                        )
                    else:
                        assert row["held_writers_at_completion"] == 1
                        assert not row["fallback_released"]
                if case == "nonzero_assertion":
                    assert (
                        "synthetic-node-assertion-must-remain-a-failure"
                        in row["exception"]["message"]
                    )
                pair.append(row)
                rows.append(row)
            except Exception as error:
                failures.append(
                    {"case": case, "arm": arm, "error": type(error).__name__ + ": " + str(error)}
                )
        if len(pair) == 2:
            if (
                pair[0]["node_invocations"][0]["script_sha256"]
                != pair[1]["node_invocations"][0]["script_sha256"]
            ):
                failures.append({"case": case, "error": "PAIRED_ACTUAL_JS_SOURCE_MISMATCH"})
            if (pair[0]["node"], pair[0]["python"], pair[0]["platform"]) != (
                pair[1]["node"],
                pair[1]["python"],
                pair[1]["platform"],
            ):
                failures.append({"case": case, "error": "PAIRED_RUNTIME_OR_PLATFORM_MISMATCH"})
    result = {
        "schema": "entitas-node-stdio-comparison-evaluation/v1",
        "result": "DEMONSTRATED_PROSPECTIVE_STDIO_CORRECTION"
        if not failures
        else "NOT_DEMONSTRATED",
        "observations": len(rows),
        "failures": failures,
        "original_outcomes": [
            {"case": r["case"], "arm": r["arm"], "outcome": r["outcome"], "wall_ns": r["wall_ns"]}
            for r in rows
        ],
        "historical_timeout_cause": "UNKNOWN_NOT_REQUIRED_FOR_THIS_PROSPECTIVE_DEMONSTRATION",
        "source_qualification": (
            "NOT_GRANTED_REQUIRES_UNINSTRUMENTED_EXACT_HEAD_NATIVE_CI_AND_POSTMERGE"
        ),
        "monetary_cost": "UNKNOWN",
    }
    (root / "evaluation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    verify(args.root, args.plan)
