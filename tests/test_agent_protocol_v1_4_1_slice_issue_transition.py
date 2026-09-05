from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_protocol_v1_4_1_slice_issue_transition",
    ROOT / "tools" / "agent_protocol_v1_4_1.py",
)
assert SPEC is not None and SPEC.loader is not None
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)


def test_planned_slice_issue_opening_has_a_closed_observed_event() -> None:
    assert "SLICE_ISSUE_OPENED" in protocol.OBSERVED_EVENTS


def test_planned_slice_may_still_start_without_a_preassigned_issue() -> None:
    slices = [
        {
            "id": "pilot/S01",
            "state": "PLANNED",
            "issue": "NONE",
            "pull_requests": [],
        }
    ]
    assert protocol.validate_slices(slices, "SINGLE_SLICE") == slices
