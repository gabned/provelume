from __future__ import annotations

import json
from pathlib import Path

from tools import agent_protocol as protocol

BASE = "a" * 40
HEAD = "b" * 40
MOVED_HEAD = "c" * 40


def make_event(
    *,
    workstream_class: str | None = "PROTOCOL",
    escalation: str = "NONE",
    head_sha: str = HEAD,
    extra_body: str = "",
    sender_type: str = "User",
) -> dict[str, object]:
    marker = (
        f"WORKSTREAM_CLASS: {workstream_class}\n"
        if workstream_class is not None
        else ""
    )
    return {
        "number": 46,
        "repository": {"full_name": protocol.REPOSITORY},
        "sender": {"login": "gabned", "type": sender_type},
        "pull_request": {
            "body": (
                marker
                + f"PROTOCOL_ESCALATION: {escalation}\n"
                + extra_body
            ),
            "author_association": "OWNER",
            "base": {"sha": BASE},
            "head": {"sha": head_sha},
        },
    }


def make_report(
    event: dict[str, object],
    paths: list[str],
    *,
    head_sha: str = HEAD,
    credentials_accessed: bool | None = False,
    production_environment_accessed: bool | None = False,
) -> dict[str, object]:
    return protocol.build_change_control_report(
        event=event,
        changed_paths=paths,
        expected_base_sha=BASE,
        expected_head_sha=head_sha,
        complete=True,
        credentials_accessed=credentials_accessed,
        production_environment_accessed=production_environment_accessed,
    )


def waiver_body(*, head_sha: str = HEAD) -> str:
    waiver = {
        "active": True,
        "approver_login": "gabned",
        "approver_type": "User",
        "change_control_version": protocol.CHANGE_CONTROL_VERSION,
        "credentials_accessed": False,
        "head_sha": head_sha,
        "human_only": True,
        "mode": "EMERGENCY_WAIVER",
        "owner_pr": "#46",
        "production_environment_accessed": False,
        "reason_code": "EMERGENCY_SECURITY_RESPONSE",
        "repository": protocol.REPOSITORY,
        "schema_version": protocol.CHANGE_CONTROL_SCHEMA_VERSION,
        "source": "GITHUB_CONNECTOR",
        "static": True,
        "waived_blocker_codes": [
            "MIXED_SCOPE",
            "PROTOCOL_TOUCHES_PRODUCT",
        ],
    }
    return (
        "<!-- PROTOCOL_EMERGENCY_WAIVER\n"
        + json.dumps(waiver, indent=2, sort_keys=True)
        + "\nPROTOCOL_EMERGENCY_WAIVER -->\n"
    )


def test_change_control_accepts_protocol_only_pr() -> None:
    event = make_event()
    paths = [
        ".github/pull_request_template.md",
        "AGENTS.md",
        "docs/agent-development-v1.2.1.md",
        "tests/test_agent_protocol_v1_2_1.py",
        "tools/agent_protocol.py",
    ]
    report = make_report(event, paths)
    assert report["workstream_class"] == "PROTOCOL"
    assert report["observed_path_categories"] == ["PROTOCOL_SURFACE"]
    assert report["blocker_codes"] == []
    assert report["merge_allowed"] is True
    protocol.verify_change_control_report(
        report,
        event=event,
        changed_paths=paths,
        expected_base_sha=BASE,
        expected_head_sha=HEAD,
        complete=True,
        credentials_accessed=False,
        production_environment_accessed=False,
    )


def test_pr_class_is_mandatory_and_closed() -> None:
    missing = make_report(make_event(workstream_class=None), ["AGENTS.md"])
    assert missing["blocker_codes"] == ["PR_CLASS_MISSING"]
    assert missing["merge_allowed"] is False

    invalid = make_report(make_event(workstream_class="MAINTENANCE"), ["AGENTS.md"])
    assert invalid["blocker_codes"] == ["PR_CLASS_INVALID"]
    assert invalid["merge_allowed"] is False


def test_mixed_scope_guard_fails_closed() -> None:
    report = make_report(
        make_event(),
        ["AGENTS.md", "core/provelume/cli.py"],
    )
    assert report["observed_path_categories"] == [
        "PRODUCT_SURFACE",
        "PROTOCOL_SURFACE",
    ]
    assert report["blocker_codes"] == [
        "MIXED_SCOPE",
        "PROTOCOL_TOUCHES_PRODUCT",
    ]
    assert report["required_action"] == "PROTOCOL_ESCALATION"
    assert report["merge_allowed"] is False


def test_product_protocol_finding_stops_and_emits_escalation() -> None:
    event = make_event(
        workstream_class="PRODUCT",
        escalation="PROTOCOL_DEFECT_SUSPECTED",
    )
    report = make_report(event, ["core/provelume/cli.py"])
    assert report["blocker_codes"] == ["PROTOCOL_ESCALATION_REQUIRED"]
    assert report["required_action"] == "PROTOCOL_ESCALATION"

    escalation = protocol.build_protocol_escalation(
        event=event,
        finding_code="PROTOCOL_DEFECT_SUSPECTED",
        expected_head_sha=HEAD,
        credentials_accessed=False,
        production_environment_accessed=False,
    )
    assert escalation["mode"] == "PROTOCOL_ESCALATION"
    assert escalation["result"] == "STOPPED"
    assert escalation["required_action"] == "OPEN_SEPARATE_PROTOCOL_PR"
    assert escalation["agents_may_modify_protocol_in_current_pr"] is False


def test_static_human_exact_head_waiver_can_cover_only_declared_blockers() -> None:
    event = make_event(extra_body=waiver_body())
    report = make_report(event, ["AGENTS.md", "core/provelume/cli.py"])
    assert report["active_blocker_codes"] == [
        "MIXED_SCOPE",
        "PROTOCOL_TOUCHES_PRODUCT",
    ]
    assert report["waiver_status"] == "VALID"
    assert report["waived_blocker_codes"] == [
        "MIXED_SCOPE",
        "PROTOCOL_TOUCHES_PRODUCT",
    ]
    assert report["blocker_codes"] == []
    assert report["merge_allowed"] is True


def test_moved_head_invalidates_static_waiver() -> None:
    event = make_event(head_sha=MOVED_HEAD, extra_body=waiver_body())
    report = make_report(
        event,
        ["AGENTS.md", "core/provelume/cli.py"],
        head_sha=MOVED_HEAD,
    )
    assert report["waiver_status"] == "INVALID"
    assert "WAIVER_HEAD_MISMATCH" in report["blocker_codes"]
    assert report["merge_allowed"] is False


def test_non_human_sender_cannot_activate_waiver() -> None:
    event = make_event(extra_body=waiver_body(), sender_type="Bot")
    report = make_report(event, ["AGENTS.md", "core/provelume/cli.py"])
    assert report["waiver_status"] == "INVALID"
    assert "WAIVER_NOT_HUMAN" in report["blocker_codes"]
    assert report["merge_allowed"] is False


def test_connector_only_evidence_is_explicit_and_fail_closed() -> None:
    event = make_event(workstream_class="PRODUCT")
    ready = make_report(event, ["core/provelume/cli.py"])
    assert ready["source"] == "GITHUB_CONNECTOR"
    assert ready["connector_only"] is True
    assert ready["credentials_accessed"] is False
    assert ready["production_environment_accessed"] is False
    assert ready["merge_allowed"] is True

    accessed = make_report(
        event,
        ["core/provelume/cli.py"],
        credentials_accessed=True,
    )
    assert accessed["blocker_codes"] == ["CONNECTOR_EVIDENCE_INVALID"]
    assert accessed["merge_allowed"] is False


def test_name_status_rename_preserves_source_and_destination(tmp_path: Path) -> None:
    evidence = tmp_path / "name-status.z"
    evidence.write_bytes(b"R100\0AGENTS.md\0README.md\0M\0core/provelume/cli.py\0")
    assert protocol.read_name_status(evidence) == [
        "AGENTS.md",
        "README.md",
        "core/provelume/cli.py",
    ]


def test_global_checkpoint_path_is_never_waivable() -> None:
    report = make_report(make_event(), ["AGENT_STATUS.md"])
    assert report["observed_path_categories"] == ["FORBIDDEN_GLOBAL_STATE"]
    assert report["blocker_codes"] == ["GLOBAL_STATE_FORBIDDEN"]
    assert report["merge_allowed"] is False
