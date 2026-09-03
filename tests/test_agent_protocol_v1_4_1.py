from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_protocol_v1_4_1",
    ROOT / "tools" / "agent_protocol_v1_4_1.py",
)
assert SPEC is not None and SPEC.loader is not None
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)

FIXTURE = ROOT / ".github" / "agent-protocol" / "conformance-v1.4.1.json"


def campaign() -> dict[str, object]:
    return deepcopy(protocol.sample_campaign())


def initialize(value: dict[str, object], event: dict[str, object]) -> dict[str, object]:
    value["receipts"] = []
    protocol.validate_campaign_v2(value, validate_receipt_chain=False)
    value["receipts"] = [
        protocol.build_receipt(
            sequence=1,
            operation="INITIALIZE",
            campaign_id=value["campaign_id"],
            github_event=event,
            previous_state_sha256=protocol.GENESIS_STATE_SHA256,
            successor_state_sha256=protocol.campaign_state_sha256(value),
            previous_receipt_sha256="NONE",
        )
    ]
    protocol.validate_campaign_v2(value)
    return value


def profile_campaign(repository: str) -> dict[str, object]:
    profile = protocol.REPOSITORY_PROFILES[repository]
    value = campaign()
    value.update(
        {
            "repository": repository,
            "campaign_id": repository.replace("/", "-") + "-pilot",
            "campaign_mode": "SINGLE_SLICE",
            "campaign_state": "ACTIVE",
            "workstream_class": "PROTOCOL",
            "authority_envelope": "SOURCE_ONLY",
            "risk_profile": "NO_PRODUCTION",
            "release_profile": profile["release_profile"],
            "observed_event": "INITIAL_AUTHORIZATION",
            "observed_event_ref": "#164",
            "pending_action": {
                "kind": "START_NEXT_SLICE",
                "slice_id": "profile/S01",
            },
            "stop_reason": "NONE",
            "next_action": {
                "type": "AUTO_CONTINUE",
                "summary": "Start profile/S01 from the exact owner issue.",
                "prompt": "NONE",
            },
        }
    )
    value["checkpoint"] = {
        "policy": "RELEASE_BOUNDARY",
        "state": "NOT_DUE",
        "reference": "NONE",
    }
    value["train"] = {
        "train_id": value["campaign_id"],
        "target_version": "1.4.1",
        "publication_state": "UNPUBLISHED",
        "published_version": "NONE",
        "candidate_build_sha": "NONE",
        "deployed_build_sha": "NONE",
        "published_build_sha": "NONE",
        "upstream": {
            "repository": profile["upstream_repository"],
            "published_version": "NONE",
            "published_build_sha": "NONE",
            "verification_state": (
                "PENDING"
                if profile["release_profile"] == "UPSTREAM_RELEASE_VERIFIED"
                else "NOT_APPLICABLE"
            ),
        },
    }
    value["slices"] = [
        {
            "id": "profile/S01",
            "state": "PLANNED",
            "issue": "#165",
            "pull_requests": [],
        }
    ]
    return initialize(
        value,
        {
            "kind": "ISSUE",
            "action": "OPENED",
            "repository": repository,
            "reference": "#164",
            "sha": "NONE",
        },
    )


def activate_second_slice() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    before = campaign()
    after = deepcopy(before)
    after["slices"][1]["state"] = "ACTIVE"
    after["slices"][1]["pull_requests"] = [
        {
            "sequence": 1,
            "role": "OWNER",
            "pr": "#4",
            "state": "OPEN",
            "head_sha": "4" * 40,
            "merge_sha": "NONE",
        }
    ]
    after["observed_event"] = "PR_OPENED"
    after["observed_event_ref"] = "#4"
    after["pending_action"] = {
        "kind": "CONTINUE_ACTIVE_SLICE",
        "slice_id": "pilot/S02",
    }
    after["next_action"] = {
        "type": "AUTO_CONTINUE",
        "summary": "Continue pilot/S02 on its one owner PR.",
        "prompt": "NONE",
    }
    event = {
        "kind": "PULL_REQUEST",
        "action": "OPENED",
        "repository": "gabned/provelume",
        "reference": "#4",
        "sha": "4" * 40,
    }
    return before, protocol.append_transition_receipt(before, after, event), event


def test_v1_campaign_migration_is_deterministic_and_idempotent() -> None:
    legacy = protocol.sample_campaign_v1()
    first = protocol.migrate_campaign(legacy)
    second = protocol.migrate_campaign(legacy)

    assert first == second
    assert protocol.migrate_campaign(first) == first
    assert first["schema_version"] == 2
    assert first["protocol_version"] == "1.4.1"
    assert first["receipts"][0]["operation"] == "SCHEMA_MIGRATION"
    assert first["receipts"][0]["previous_state_sha256"] == protocol.object_sha256(
        legacy
    )


def test_migration_retains_recorded_pr_without_inventing_overwritten_history() -> None:
    legacy = protocol.sample_campaign_v1()
    legacy["slices"][0].update(
        {
            "pr": "#173",
            "head_sha": "a" * 40,
            "merge_sha": "b" * 40,
        }
    )
    legacy["observed_event_ref"] = "b" * 40

    migrated = protocol.migrate_campaign(legacy)

    assert migrated["slices"][0]["pull_requests"] == [
        {
            "sequence": 1,
            "role": "OWNER",
            "pr": "#173",
            "state": "MERGED",
            "head_sha": "a" * 40,
            "merge_sha": "b" * 40,
        }
    ]


def test_owner_and_correction_ledger_is_ordered_and_history_preserving() -> None:
    ledger = [
        {
            "sequence": 1,
            "role": "OWNER",
            "pr": "#172",
            "state": "MERGED",
            "head_sha": "1" * 40,
            "merge_sha": "2" * 40,
        },
        {
            "sequence": 2,
            "role": "CORRECTION",
            "pr": "#173",
            "state": "MERGED",
            "head_sha": "3" * 40,
            "merge_sha": "4" * 40,
        },
    ]

    assert protocol.validate_pull_request_ledger(ledger, label="ledger") == ledger
    rewritten = deepcopy(ledger[1:])
    rewritten[0]["sequence"] = 1
    with pytest.raises(protocol.ContractError, match="starts with OWNER"):
        protocol.validate_pull_request_ledger(rewritten, label="ledger")


def test_only_the_final_single_pr_may_be_open() -> None:
    ledger = [
        {
            "sequence": 1,
            "role": "OWNER",
            "pr": "#10",
            "state": "OPEN",
            "head_sha": "1" * 40,
            "merge_sha": "NONE",
        },
        {
            "sequence": 2,
            "role": "CORRECTION",
            "pr": "#11",
            "state": "OPEN",
            "head_sha": "2" * 40,
            "merge_sha": "NONE",
        },
    ]

    with pytest.raises(protocol.ContractError, match="final ledger entry"):
        protocol.validate_pull_request_ledger(ledger, label="ledger")


def test_transition_receipts_are_append_only_and_idempotent() -> None:
    before, after, event = activate_second_slice()

    protocol.validate_append_only(before, after)
    assert len(after["receipts"]) == len(before["receipts"]) + 1
    assert after["receipts"][:-1] == before["receipts"]
    assert protocol.append_transition_receipt(after, after, event) == after


def test_continuation_cannot_replace_a_retained_pr_ledger_entry() -> None:
    _, before, _ = activate_second_slice()
    successor = deepcopy(before)
    successor["slices"][1]["pull_requests"][0].update(
        {"pr": "#5", "head_sha": "5" * 40}
    )
    successor["observed_event_ref"] = "#5"

    with pytest.raises(protocol.ContractError, match="ledger history"):
        protocol.append_transition_receipt(
            before,
            successor,
            {
                "kind": "PULL_REQUEST",
                "action": "OPENED",
                "repository": "gabned/provelume",
                "reference": "#5",
                "sha": "5" * 40,
            },
        )


def test_open_pr_head_advances_through_a_github_backed_receipt() -> None:
    _, before, _ = activate_second_slice()
    successor = deepcopy(before)
    successor["slices"][1]["pull_requests"][0]["head_sha"] = "5" * 40
    successor["observed_event"] = "PR_SYNCHRONIZED"

    after = protocol.append_transition_receipt(
        before,
        successor,
        {
            "kind": "PULL_REQUEST",
            "action": "SYNCHRONIZED",
            "repository": "gabned/provelume",
            "reference": "#4",
            "sha": "5" * 40,
        },
    )

    assert after["slices"][1]["pull_requests"][0]["pr"] == "#4"
    assert after["slices"][1]["pull_requests"][0]["head_sha"] == "5" * 40
    protocol.validate_append_only(before, after)


def test_closed_owner_is_retained_before_a_correction_opens() -> None:
    _, opened, _ = activate_second_slice()
    closed = deepcopy(opened)
    closed["slices"][1]["pull_requests"][0]["state"] = "CLOSED"
    closed["observed_event"] = "PR_CLOSED"
    closed = protocol.append_transition_receipt(
        opened,
        closed,
        {
            "kind": "PULL_REQUEST",
            "action": "CLOSED",
            "repository": "gabned/provelume",
            "reference": "#4",
            "sha": "4" * 40,
        },
    )

    correction = deepcopy(closed)
    correction["slices"][1]["pull_requests"].append(
        {
            "sequence": 2,
            "role": "CORRECTION",
            "pr": "#5",
            "state": "OPEN",
            "head_sha": "5" * 40,
            "merge_sha": "NONE",
        }
    )
    correction["observed_event"] = "PR_OPENED"
    correction["observed_event_ref"] = "#5"
    correction = protocol.append_transition_receipt(
        closed,
        correction,
        {
            "kind": "PULL_REQUEST",
            "action": "OPENED",
            "repository": "gabned/provelume",
            "reference": "#5",
            "sha": "5" * 40,
        },
    )

    ledger = correction["slices"][1]["pull_requests"]
    assert [(entry["role"], entry["pr"], entry["state"]) for entry in ledger] == [
        ("OWNER", "#4", "CLOSED"),
        ("CORRECTION", "#5", "OPEN"),
    ]
    protocol.validate_append_only(closed, correction)


def test_transition_receipt_binds_predecessor_successor_and_real_event() -> None:
    before, after, _ = activate_second_slice()
    receipt = after["receipts"][-1]

    assert receipt["previous_state_sha256"] == protocol.campaign_state_sha256(before)
    assert receipt["successor_state_sha256"] == protocol.campaign_state_sha256(after)
    assert receipt["github_event"]["kind"] == "PULL_REQUEST"
    assert receipt["github_event"]["action"] == "OPENED"
    assert receipt["github_event"]["reference"] == "#4"
    assert receipt["github_event"]["sha"] == "4" * 40


def test_receipt_digest_or_history_rewrite_fails_closed() -> None:
    _, after, _ = activate_second_slice()
    after["receipts"][0]["successor_state_sha256"] = "0" * 64

    with pytest.raises(protocol.ContractError, match="digest|receipt"):
        protocol.validate_campaign_v2(after)


def test_forged_receipt_cannot_reuse_a_prior_github_event() -> None:
    _, after, _ = activate_second_slice()
    forged = deepcopy(after)
    receipt = forged["receipts"][-1]
    receipt["github_event"] = deepcopy(forged["receipts"][0]["github_event"])
    receipt["idempotency_key"] = protocol.receipt_idempotency_key(
        campaign_id=forged["campaign_id"],
        operation=receipt["operation"],
        github_event=receipt["github_event"],
        previous_state_sha256=receipt["previous_state_sha256"],
        successor_state_sha256=receipt["successor_state_sha256"],
    )
    receipt["receipt_sha256"] = protocol.receipt_sha256(receipt)

    with pytest.raises(protocol.ContractError, match="cannot be reused"):
        protocol.validate_campaign_v2(forged)


def test_non_github_event_reference_fails_closed() -> None:
    before = campaign()
    after = deepcopy(before)
    after["next_action"]["summary"] = "Start pilot/S02 from fabricated evidence."

    with pytest.raises(protocol.ContractError, match="workflow event"):
        protocol.append_transition_receipt(
            before,
            after,
            {
                "kind": "WORKFLOW_RUN",
                "action": "COMPLETED",
                "repository": "gabned/provelume",
                "reference": "timer:midnight",
                "sha": "1" * 40,
            },
        )


def test_slice_count_mismatch_is_a_closed_contract_failure() -> None:
    before = campaign()
    after = deepcopy(before)
    after["slices"].append(
        {
            "id": "pilot/S03",
            "state": "PLANNED",
            "issue": "#5",
            "pull_requests": [],
        }
    )
    after["campaign_state"] = "WAITING_EVENT"
    after["observed_event"] = "GATES_PASSED"
    after["observed_event_ref"] = "9" * 40
    after["pending_action"] = {"kind": "WAIT_FOR_EVENT", "slice_id": "NONE"}
    after["next_action"] = {
        "type": "WAIT_EVENT",
        "summary": "Wait for one new exact GitHub event.",
        "prompt": "NONE",
    }
    after["receipts"].append(
        protocol.build_receipt(
            sequence=2,
            operation="STATE_TRANSITION",
            campaign_id=after["campaign_id"],
                github_event={
                    "kind": "WORKFLOW_RUN",
                    "action": "COMPLETED",
                    "repository": "gabned/provelume",
                    "reference": "run:405",
                    "sha": "9" * 40,
                },
            previous_state_sha256=protocol.campaign_state_sha256(before),
            successor_state_sha256=protocol.campaign_state_sha256(after),
            previous_receipt_sha256=before["receipts"][-1]["receipt_sha256"],
        )
    )
    protocol.validate_campaign_v2(after)

    with pytest.raises(protocol.ContractError, match="frozen slice scope"):
        protocol.validate_append_only(before, after)


def test_joint_campaign_handoff_generation_binds_exact_digest() -> None:
    value = campaign()
    bundle = protocol.build_bundle(
        value,
        delivered="The migration and current continuation state are validated together.",
    )

    assert protocol.validate_bundle(bundle) == bundle
    assert bundle["handoff"]["campaign_sha256"] == protocol.campaign_sha256(value)
    assert protocol.word_count(bundle["handoff"]["human_report"]) <= 120
    assert bundle["handoff"]["human_report"].count("Next action [") == 1


def test_joint_validation_rejects_handoff_drift() -> None:
    bundle = protocol.build_bundle(
        campaign(),
        delivered="The exact campaign is bound.",
    )
    bundle["handoff"]["next_action"] = "Do a different action."
    bundle["handoff"]["human_report"] = protocol.render_handoff(bundle["handoff"])

    with pytest.raises(protocol.ContractError, match="generated and validated jointly"):
        protocol.validate_bundle(bundle)


def test_handoff_limit_is_enforced_after_joint_generation() -> None:
    delivered = " ".join(["x"] * 121)

    with pytest.raises(protocol.ContractError, match="120 words"):
        protocol.build_bundle(campaign(), delivered=delivered)


def test_session_limit_has_distinct_resume_required_outcome() -> None:
    bundle = protocol.build_bundle(
        campaign(),
        delivered="The bounded session ended without changing campaign state.",
        resume_required=True,
    )
    handoff = bundle["handoff"]

    assert handoff["outcome"] == "RESUME_REQUIRED"
    assert handoff["resume_reason"] == "SESSION_LIMIT"
    assert handoff["next_action_type"] == "RESUME_SESSION"
    assert handoff["next_prompt"] == "NONE"


def test_session_limit_cannot_replace_a_blocker_or_human_decision() -> None:
    before, active, _ = activate_second_slice()
    blocked = deepcopy(active)
    blocked["campaign_state"] = "BLOCKED"
    blocked["slices"][1]["state"] = "BLOCKED"
    blocked["observed_event"] = "GATES_FAILED"
    blocked["observed_event_ref"] = "4" * 40
    blocked["pending_action"] = {"kind": "WAIT_FOR_EVENT", "slice_id": "NONE"}
    blocked["stop_reason"] = "GATE_FAILURE"
    blocked["next_action"] = {
        "type": "USER_ACTION_REQUIRED",
        "summary": "Resolve the failed exact-head gate without changing scope.",
        "prompt": "Resolve the failed exact-head gate, then resume this campaign.",
    }
    blocked = protocol.append_transition_receipt(
        active,
        blocked,
        {
            "kind": "WORKFLOW_RUN",
            "action": "COMPLETED",
            "repository": "gabned/provelume",
            "reference": "run:400",
            "sha": "4" * 40,
        },
    )
    protocol.validate_append_only(before, active)

    with pytest.raises(protocol.ContractError, match="cannot replace"):
        protocol.build_handoff(
            blocked,
            delivered="The exact-head workflow failed.",
            resume_required=True,
        )


@pytest.mark.parametrize("repository", sorted(protocol.REPOSITORY_PROFILES))
def test_each_closed_repository_profile_accepts_a_protocol_campaign(
    repository: str,
) -> None:
    value = profile_campaign(repository)

    assert protocol.validate_campaign_v2(value)["repository"] == repository


def test_repository_release_profile_mismatch_fails_closed() -> None:
    value = profile_campaign("gabned/provelume")
    value["release_profile"] = "CODE_ONLY_PRODUCTION_B"
    value["receipts"] = []

    with pytest.raises(protocol.ContractError, match="does not match"):
        protocol.validate_campaign_v2(value, validate_receipt_chain=False)


def terminal_profile_campaign(repository: str) -> dict[str, object]:
    value = profile_campaign(repository)
    value["campaign_mode"] = "RELEASE_TRAIN"
    value["workstream_class"] = "PRODUCT"
    value["slices"] = [
        {
            "id": "profile/S01",
            "state": "MERGED",
            "issue": "#165",
            "pull_requests": [
                {
                    "sequence": 1,
                    "role": "OWNER",
                    "pr": "#166",
                    "state": "MERGED",
                    "head_sha": "5" * 40,
                    "merge_sha": "6" * 40,
                }
            ],
        }
    ]
    value["train"]["publication_state"] = "CANDIDATE"
    value["train"]["candidate_build_sha"] = "7" * 40
    value["observed_event"] = "GATES_PASSED"
    value["observed_event_ref"] = "7" * 40
    value["receipts"] = []
    return value


def test_code_only_production_b_profile_accepts_only_reversible_deploy() -> None:
    value = terminal_profile_campaign("brickms/brickms")
    value["authority_envelope"] = "THROUGH_PRODUCTION_B"
    value["risk_profile"] = "REVERSIBLE_PRODUCTION"
    value["pending_action"] = {"kind": "DEPLOY_PRODUCTION_B", "slice_id": "NONE"}
    value["next_action"] = {
        "type": "AUTO_CONTINUE",
        "summary": "Deploy the exact candidate through code-only production B.",
        "prompt": "NONE",
    }

    initialize(
        value,
        {
            "kind": "WORKFLOW_RUN",
            "action": "COMPLETED",
            "repository": "brickms/brickms",
            "reference": "run:401",
            "sha": "7" * 40,
        },
    )


def test_level_c_profile_requires_a_closed_human_gate() -> None:
    value = terminal_profile_campaign("maxithlon/maxithlon")
    value["authority_envelope"] = "THROUGH_PRODUCTION_B"
    value["risk_profile"] = "CRITICAL_PRODUCTION"
    value["campaign_state"] = "HUMAN_GATE"
    value["pending_action"] = {"kind": "DEPLOY_PRODUCTION_C", "slice_id": "NONE"}
    value["stop_reason"] = "LEVEL_C_AUTHORIZATION"
    value["next_action"] = {
        "type": "USER_ACTION_REQUIRED",
        "summary": "Authorize the exact candidate for deployment Level C.",
        "prompt": "CONFIRM-PRODUCTION-RELEASE 1.4.1",
    }
    initialize(
        value,
        {
            "kind": "WORKFLOW_RUN",
            "action": "COMPLETED",
            "repository": "maxithlon/maxithlon",
            "reference": "run:402",
            "sha": "7" * 40,
        },
    )

    value["campaign_state"] = "ACTIVE"
    value["stop_reason"] = "NONE"
    value["next_action"] = {
        "type": "AUTO_CONTINUE",
        "summary": "Deploy the exact candidate through Level C.",
        "prompt": "NONE",
    }
    value["receipts"] = []
    with pytest.raises(protocol.ContractError, match="closed human gate"):
        protocol.validate_campaign_v2(value, validate_receipt_chain=False)


def test_site_profile_requires_verified_upstream_before_production_b() -> None:
    value = terminal_profile_campaign("gabned/provelume.com")
    value["authority_envelope"] = "THROUGH_PRODUCTION_B"
    value["risk_profile"] = "REVERSIBLE_PRODUCTION"
    value["pending_action"] = {"kind": "DEPLOY_PRODUCTION_B", "slice_id": "NONE"}
    value["next_action"] = {
        "type": "AUTO_CONTINUE",
        "summary": "Deploy the site after verified upstream release evidence.",
        "prompt": "NONE",
    }

    with pytest.raises(protocol.ContractError, match="cannot precede"):
        protocol.validate_campaign_v2(value, validate_receipt_chain=False)

    value["train"]["upstream"] = {
        "repository": "gabned/provelume",
        "published_version": "0.9.0",
        "published_build_sha": "8" * 40,
        "verification_state": "VERIFIED",
    }
    initialize(
        value,
        {
            "kind": "WORKFLOW_RUN",
            "action": "COMPLETED",
            "repository": "gabned/provelume.com",
            "reference": "run:403",
            "sha": "7" * 40,
        },
    )


def test_train_separates_candidate_deployed_and_published_builds() -> None:
    value = campaign()["train"]
    value["publication_state"] = "PUBLISHED"
    value["published_version"] = value["target_version"]
    value["candidate_build_sha"] = "8" * 40
    value["published_build_sha"] = "8" * 40

    checked = protocol.validate_train(value, "GITHUB_ARTIFACT")
    assert checked["candidate_build_sha"] == checked["published_build_sha"]
    assert checked["deployed_build_sha"] == "NONE"


def test_github_artifact_profile_rejects_a_deployed_build_claim() -> None:
    value = campaign()["train"]
    value["publication_state"] = "CANDIDATE"
    value["candidate_build_sha"] = "8" * 40
    value["deployed_build_sha"] = "8" * 40

    with pytest.raises(protocol.ContractError, match="no deployment"):
        protocol.validate_train(value, "GITHUB_ARTIFACT")


def test_release_publication_and_verification_use_distinct_github_events() -> None:
    candidate = terminal_profile_campaign("gabned/provelume")
    candidate["authority_envelope"] = "THROUGH_RELEASE"
    candidate["risk_profile"] = "PUBLIC_ARTIFACT"
    candidate["observed_event"] = "RELEASE_CANDIDATE_MERGED"
    candidate["observed_event_ref"] = "7" * 40
    candidate["pending_action"] = {"kind": "PUBLISH_RELEASE", "slice_id": "NONE"}
    candidate["next_action"] = {
        "type": "AUTO_CONTINUE",
        "summary": "Publish the exact candidate as the target release.",
        "prompt": "NONE",
    }
    candidate = initialize(
        candidate,
        {
            "kind": "COMMIT",
            "action": "CREATED",
            "repository": "gabned/provelume",
            "reference": "7" * 40,
            "sha": "7" * 40,
        },
    )

    published = deepcopy(candidate)
    published["train"].update(
        {
            "publication_state": "PUBLISHED",
            "published_version": "1.4.1",
            "published_build_sha": "7" * 40,
        }
    )
    published["observed_event"] = "RELEASE_PUBLISHED"
    published["observed_event_ref"] = "release:v1.4.1"
    published["pending_action"] = {"kind": "VERIFY_RELEASE", "slice_id": "NONE"}
    published["next_action"]["summary"] = "Verify the exact published release."
    published = protocol.append_transition_receipt(
        candidate,
        published,
        {
            "kind": "RELEASE",
            "action": "PUBLISHED",
            "repository": "gabned/provelume",
            "reference": "release:v1.4.1",
            "sha": "7" * 40,
        },
    )

    verified = deepcopy(published)
    verified["checkpoint"]["state"] = "DUE"
    verified["observed_event"] = "RELEASE_VERIFIED"
    verified["pending_action"] = {"kind": "RECORD_CHECKPOINT", "slice_id": "NONE"}
    verified["next_action"]["summary"] = "Record the verified release checkpoint."
    verified = protocol.append_transition_receipt(
        published,
        verified,
        {
            "kind": "WORKFLOW_RUN",
            "action": "COMPLETED",
            "repository": "gabned/provelume",
            "reference": "run:404",
            "sha": "7" * 40,
        },
    )

    assert published["receipts"][-1]["github_event"]["kind"] == "RELEASE"
    assert verified["receipts"][-1]["github_event"]["kind"] == "WORKFLOW_RUN"
    protocol.validate_append_only(published, verified)


def test_deployed_build_is_not_reported_as_only_a_candidate() -> None:
    value = terminal_profile_campaign("brickms/brickms")
    value["train"]["deployed_build_sha"] = value["train"]["candidate_build_sha"]

    assert protocol.release_status(value) == "DEPLOYED"


def test_read_only_conformance_fixture_covers_all_four_repositories() -> None:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    checked = protocol.validate_conformance_fixture(value)

    assert checked["mode"] == "READ_ONLY"
    assert {row["repository"] for row in checked["repositories"]} == set(
        protocol.REPOSITORY_PROFILES
    )
    assert all(row["writes_performed"] is False for row in checked["repositories"])


def test_conformance_fixture_retains_172_owner_then_173_correction() -> None:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ledger = value["ledger_regression"]["pull_requests"]

    assert [(item["role"], item["pr"]) for item in ledger] == [
        ("OWNER", "#172"),
        ("CORRECTION", "#173"),
    ]
    protocol.validate_conformance_fixture(value)


def test_legacy_validator_remains_available_and_unchanged() -> None:
    legacy = protocol.load_legacy_module()

    assert legacy.PROTOCOL_VERSION == "1.4.0"
    assert legacy.SCHEMA_VERSION == 1
    legacy.validate_campaign(legacy.sample_campaign())
