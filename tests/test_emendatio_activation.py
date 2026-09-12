from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from tools import agent_protocol_v1_4_1 as protocol

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "roadmap.md"
RELEASE_PLAN = ROOT / "docs" / "releases" / "0.10.1.md"


def _initial_state() -> dict[str, object]:
    return {
        "schema_version": 2,
        "protocol_version": "1.4.1",
        "repository": "gabned/provelume",
        "campaign_id": "provelume-0.10.1-emendatio",
        "owner_issue": "#198",
        "campaign_mode": "RELEASE_TRAIN",
        "campaign_state": "ACTIVE",
        "workstream_class": "PRODUCT",
        "authority_envelope": "THROUGH_RELEASE",
        "risk_profile": "PUBLIC_ARTIFACT",
        "release_profile": "GITHUB_ARTIFACT",
        "auto_continuation": "SEQUENTIAL",
        "checkpoint": {
            "policy": "RELEASE_BOUNDARY",
            "state": "NOT_DUE",
            "reference": "NONE",
        },
        "idea_inbox": {
            "mode": "GITHUB_ISSUES_ONLY",
            "scope": "FROZEN_UNTIL_RELEASE_BOUNDARY",
            "items": [],
        },
        "train": {
            "train_id": "emendatio-0.10.1",
            "target_version": "0.10.1",
            "publication_state": "UNPUBLISHED",
            "published_version": "NONE",
            "candidate_build_sha": "NONE",
            "deployed_build_sha": "NONE",
            "published_build_sha": "NONE",
            "upstream": {
                "repository": "NONE",
                "published_version": "NONE",
                "published_build_sha": "NONE",
                "verification_state": "NOT_APPLICABLE",
            },
        },
        "slices": [
            {
                "id": f"0.10.1/S{index:02d}",
                "state": "PLANNED",
                "issue": "NONE",
                "pull_requests": [],
            }
            for index in range(1, 5)
        ],
        "observed_event": "INITIAL_AUTHORIZATION",
        "observed_event_ref": "#198",
        "pending_action": {"kind": "START_NEXT_SLICE", "slice_id": "0.10.1/S01"},
        "stop_reason": "NONE",
        "next_action": {
            "type": "AUTO_CONTINUE",
            "summary": "Start 0.10.1/S01 through its exact just-in-time owner issue event.",
            "prompt": "NONE",
        },
    }


def _campaign() -> dict[str, object]:
    initial = _initial_state()
    successor_sha = protocol.object_sha256(initial)
    event = {
        "kind": "ISSUE",
        "action": "OPENED",
        "repository": "gabned/provelume",
        "reference": "#198",
        "sha": "NONE",
        "conclusion": "NOT_APPLICABLE",
    }
    receipt = protocol.build_receipt(
        sequence=1,
        operation="INITIALIZE",
        campaign_id="provelume-0.10.1-emendatio",
        github_event=event,
        previous_state_sha256=protocol.GENESIS_STATE_SHA256,
        successor_state_sha256=successor_sha,
        previous_receipt_sha256="NONE",
        initial_state=deepcopy(initial),
    )
    campaign = {**initial, "receipts": [receipt]}
    protocol.validate_campaign_v2(campaign)
    return campaign


def test_emendatio_initial_campaign_is_native_schema_2() -> None:
    campaign = _campaign()
    assert protocol.campaign_sha256(campaign) == (
        "44af24e083d91a18a7907af5f4bf96d91f44adbad01861030e67705b6a3840f2"
    )
    assert campaign["receipts"][0]["receipt_sha256"] == (
        "3b7c114868a6eeb73a985230cce53ce8f70444bf67a525915fb0486e9c1c1bbf"
    )
    bundle = protocol.build_bundle(
        campaign,
        delivered=(
            "Emendatio is authorized under schema 2 with four frozen slices and no "
            "package identity change."
        ),
    )
    protocol.validate_bundle(bundle)
    assert bundle["handoff"]["next_action_type"] == "AUTO_CONTINUE"
    assert bundle["handoff"]["next_prompt"] == "NONE"


def test_emendatio_release_plan_keeps_identity_deferred() -> None:
    text = RELEASE_PLAN.read_text(encoding="utf-8")
    assert "RELEASE_STATE: ACTIVE_DEVELOPMENT" in text
    assert "CURRENT_PACKAGE_VERSION: 0.10.0" in text
    assert "PACKAGE_VERSION_UPDATE: DEFERRED_TO_RELEASE_PREPARATION" in text
    assert "PARENT_TRACKER: #198" in text
    assert "CURRENT_SLICE: 0.10.1/S03" in text
    assert "S01_STATE: MERGED" in text
    assert "S01_OWNER_PR: #211" in text
    assert "S01_MERGE_SHA: 26dee0fd74b43d39e46afe0e5a258130849ee97c" in text
    assert "S01_ISSUE: #210" in text
    assert "S02_STATE: MERGED" in text
    assert "S02_ISSUE: #212" in text
    assert "S02_OWNER_PR: #213" in text
    assert "S02_MERGE_SHA: ac211c4767d3cffdeb48fd5ee17300c107946062" in text
    assert "S03_STATE: ACTIVE" in text
    assert "S03_ISSUE: #214" in text
    assert "NEXT_SLICE: 0.10.1/S04" in text
    assert "S04_STATE: PLANNED" in text
    assert "NEXT_FORECAST_STATE: NOT_ACTIVATED" in text


def test_public_roadmap_activates_four_bounded_emendatio_slices() -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    assert "| Active development | `0.10.1`" in text
    assert "#198" in text
    section = text.split(
        "### 0.10.1 — Source Onboarding, Filtering and Canonical Brand Correction",
        1,
    )[1].split("### 0.11.0 — Daily-use UX, Unified Capture, Action Center and Multilingual Interface", 1)[0]
    assert "#187" in section
    assert "planning-only" in section
    for slice_id in ("0.10.1/S01", "0.10.1/S02", "0.10.1/S03", "0.10.1/S04"):
        assert slice_id in section
    assert "Source enrollment and Windows network-path qualification" in section
    assert "Per-Source exclusions, safe defaults and ingestion preview" in section
    assert "Guided read-only Google connection journey" in section
    assert "Canonical Provelume brand correction and integrated qualification" in section
    rows = [line.split("|") for line in section.splitlines() if line.startswith("| `0.10.1/S")]
    assert len(rows) == 4
    outcomes = "\n".join(row[3] for row in rows)
    assert "Lucide" not in outcomes
    assert "0.11/S02" not in outcomes
    assert "No new tray feature, general UI icon framework, Lucide rollout" in rows[3][4]
    assert "Lucide remains `0.11/S02`" in section


def test_activation_status_distinguishes_campaign_and_repository_protocol() -> None:
    plan = RELEASE_PLAN.read_text(encoding="utf-8")
    assert "CAMPAIGN_PROTOCOL_VERSION: 1.4.1" in plan
    assert "tools/agent_protocol_v1_4_1.py" in plan
    assert "repository protocol" in plan
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## In development: 0.10.1 Emendatio" in readme
    assert "docs/releases/0.10.1.md" in readme
    assert "0.11.0 — Cura remains unactivated" in readme
