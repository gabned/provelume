from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import agent_protocol as protocol

BASE = "a" * 40
HEAD = "b" * 40


def make_safe_report() -> dict[str, object]:
    return protocol.build_effect_report(
        base_sha=BASE,
        head_sha=HEAD,
        changed_paths=sorted(protocol.SAFE_PROTOCOL_PATHS),
        policy="NO_PRODUCTION",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=protocol.now_utc(),
    )


def make_binding(report: dict[str, object]) -> dict[str, object]:
    return protocol.build_binding(
        report,
        active_pr="#45",
        workstream="agent-protocol-v1.2-subset",
    )


def make_snapshot(
    report: dict[str, object],
    *,
    owner_pr: str = "#45",
    checks: str = "SUCCESS",
    review: str = "UNKNOWN",
    requires_approval: str = "FALSE",
) -> dict[str, object]:
    return protocol.seal(
        {
            "schema_version": protocol.SCHEMA_VERSION,
            "protocol_version": protocol.PROTOCOL_VERSION,
            "mode": "SNAPSHOT",
            "source": "GITHUB_CONNECTOR",
            "repository": protocol.REPOSITORY,
            "observed_at": protocol.now_utc(),
            "default_branch": protocol.DEFAULT_BRANCH,
            "default_sha": BASE,
            "owner_pr": owner_pr,
            "base_sha": BASE,
            "head_sha": HEAD,
            "binding_basis_sha": HEAD,
            "effect_report_sha256": report["report_sha256"],
            "pr_state": "OPEN",
            "draft": "FALSE",
            "checks": checks,
            "review": review,
            "requires_approval": requires_approval,
            "unresolved_threads": 0,
            "mergeability": "MERGEABLE",
            "base_ancestry": "TRUE",
            "binding_basis_ancestor": "TRUE",
            "credentials_accessed": False,
            "production_environment_accessed": False,
        }
    )


def test_protocol_self_test() -> None:
    protocol.self_test()


def test_exact_safe_delta_round_trip(tmp_path: Path) -> None:
    report = make_safe_report()
    path = tmp_path / "effect.json"
    protocol.write_object(path, report)
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    protocol.verify_effect_report(
        reloaded,
        base_sha=BASE,
        head_sha=HEAD,
        policy="NO_PRODUCTION",
    )
    assert reloaded["effect"] == "NO_PRODUCTION"
    assert reloaded["bind_allowed"] is True
    assert len(reloaded["report_sha256"]) == 64


def test_unclassified_path_fails_closed_under_no_production_policy() -> None:
    report = protocol.build_effect_report(
        base_sha=BASE,
        head_sha=HEAD,
        changed_paths=["compose.yml"],
        policy="NO_PRODUCTION",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=protocol.now_utc(),
    )
    assert report["effect"] == "PRODUCTION"
    assert report["bind_allowed"] is False
    assert report["matches"] == [
        {"identifier": "UNCLASSIFIED_PATH", "path": "compose.yml"}
    ]


def test_verification_recomputes_effect_and_authorization() -> None:
    report = protocol.build_effect_report(
        base_sha=BASE,
        head_sha=HEAD,
        changed_paths=["core/provelume/cli.py"],
        policy="REPOSITORY_POLICY",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=protocol.now_utc(),
    )
    tampered = dict(report)
    tampered["effect"] = "NO_PRODUCTION"
    tampered["matches"] = []
    tampered = protocol.seal(tampered)
    with pytest.raises(protocol.ContractError, match="classifications"):
        protocol.verify_effect_report(
            tampered,
            base_sha=BASE,
            head_sha=HEAD,
            policy="REPOSITORY_POLICY",
        )


def test_rename_connector_evidence_includes_both_paths() -> None:
    paths = protocol.connector_paths(
        {
            "changed_files": [
                {"previous_path": "core/old.py", "filename": "docs/new.md"}
            ]
        }
    )
    assert paths == ["core/old.py", "docs/new.md"]


def test_connector_snapshot_is_cross_bound_to_owner_and_shas() -> None:
    report = make_safe_report()
    binding = make_binding(report)
    ready = protocol.preflight(make_snapshot(report), binding)
    assert ready["merge_ready"] is True

    unrelated = protocol.preflight(make_snapshot(report, owner_pr="#999"), binding)
    assert unrelated["merge_ready"] is False
    assert any("owner_pr" in error for error in unrelated["errors"])


def test_unknown_required_gate_is_fail_closed() -> None:
    report = make_safe_report()
    binding = make_binding(report)
    blocked = protocol.preflight(make_snapshot(report, checks="UNKNOWN"), binding)
    assert blocked["merge_ready"] is False
    assert any("checks" in error for error in blocked["errors"])


def test_advisory_unknown_review_is_allowed_only_when_approval_not_required() -> None:
    report = make_safe_report()
    binding = make_binding(report)
    advisory = protocol.preflight(
        make_snapshot(report, review="UNKNOWN", requires_approval="FALSE"), binding
    )
    assert advisory["merge_ready"] is True

    required = protocol.preflight(
        make_snapshot(report, review="UNKNOWN", requires_approval="TRUE"), binding
    )
    assert required["merge_ready"] is False


def test_reconciliation_accepts_newer_default_tip_without_inferring_release() -> None:
    report = make_safe_report()
    binding = make_binding(report)
    evidence = protocol.seal(
        {
            "schema_version": protocol.SCHEMA_VERSION,
            "protocol_version": protocol.PROTOCOL_VERSION,
            "mode": "RECONCILE_EVIDENCE",
            "source": "GITHUB_CONNECTOR",
            "repository": protocol.REPOSITORY,
            "observed_at": protocol.now_utc(),
            "default_branch": protocol.DEFAULT_BRANCH,
            "default_sha": "d" * 40,
            "active_pr": "#45",
            "pr_state": "MERGED",
            "binding_basis_sha": HEAD,
            "binding_basis_ancestor": "TRUE",
            "effect_report_sha256": report["report_sha256"],
            "merge_sha": "c" * 40,
            "merge_sha_on_default": "TRUE",
            "workflow_status": "UNKNOWN",
            "release_status": "NOT_APPLICABLE",
            "production_action_performed": False,
        }
    )
    reconciled = protocol.reconcile(evidence, binding)
    assert evidence["default_sha"] != evidence["merge_sha"]
    assert reconciled["release_allowed"] is True
    assert reconciled["result"] == "UNKNOWN"
    assert reconciled["observational_only"] is True
    assert reconciled["production_action_performed"] is False
