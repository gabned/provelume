"""Evaluate the entire frozen 48-operation cohort, never app qualification."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    cells, errors = {}, []
    for case in plan["cases"]:
        for arm in plan["order"]:
            path = args.root / f"{case}-{arm}/observation.json"
            try:
                d = json.loads(path.read_text())
                expected = plan["baseline"] if arm.startswith("A") else plan["fixed"]
                assert d["head"] == expected and d["arm"] == arm and d["case"] == case
                assert len(d["rows"]) == 3
                if case == "canonical_error":
                    assert all(r["status"] == "REFUSED" for r in d["rows"])
                    assert d["snapshot"] == d["initial_snapshot"]
                    assert len([e for e in d["events"] if e["error"] == "OSError"]) == 3
                else:
                    assert all(r["status"] == "SUCCEEDED" and all(r["outcome"][k] is True
                        for k in ["preserved", "search_found", "product_dispatch_blocked"])
                        for r in d["rows"])
                    assert all(e["error"] is None for e in d["events"])
                    assert d["fsync_counts"].get("owner",0) == (6 if arm.startswith("A") else 0)
                cells[case,arm] = d
            except Exception as exc:
                errors.append({"case":case,"arm":arm,"error":type(exc).__name__})
        available = [cells[case,a] for a in plan["order"] if (case,a) in cells]
        if len(available) == 4:
            if len({d["snapshot"]["sha256"] for d in available}) != 1:
                errors.append({"case":case,"error":"canonical snapshots differ"})
            counts = [{k:v for k,v in d["fsync_counts"].items() if k != "owner"} for d in available]
            if any(d != counts[0] for d in counts):
                errors.append({"case":case,"error":"canonical fsync counts differ"})
    try:
        aa = [cells["owner_delay",a] for a in ["A1","A2"]]
        bb = [cells["owner_delay",a] for a in ["B1","B2"]]
        assert all(sum(e["injected_delay_seconds"] for e in d["events"]
                   if e["category"] == "owner") >= 1 for d in aa)
        assert all(a["elapsed_seconds"] >= b["elapsed_seconds"]+.8 for a in aa for b in bb)
        ordinary = max(cells["ordinary",a]["elapsed_seconds"] for a in ["B1","B2"])
        assert all(d["elapsed_seconds"] <= ordinary+.25 for d in bb)
        for arm in ["B1","B2"]:
            d = cells["canonical_delay",arm]
            assert d["elapsed_seconds"] >= .6
            assert all(e["injected_delay_seconds"] == .06 for e in d["events"]
                       if e["category"] == "journal_payload")
    except Exception as exc:
        errors.append({"criteria":"delay intervention","error":type(exc).__name__})
    result = {"classification":plan["classification"], "plan":plan,
              "result":("SUPPORTED_PROSPECTIVE_ADVISORY_SYNC_CORRECTION"
                        if not errors else "NOT_SUPPORTED"),
              "operations":sum(len(d["rows"]) for d in cells.values()), "errors":errors,
              "cells":[{"case":case,"arm":arm,"elapsed_seconds":d["elapsed_seconds"],
                        "fsync_counts":d["fsync_counts"],"snapshot":d["snapshot"]["sha256"]}
                       for (case,arm),d in cells.items()],
              "historical_cause":"UNKNOWN", "qualification":"NOT_GRANTED"}
    (args.root / "evaluation.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
