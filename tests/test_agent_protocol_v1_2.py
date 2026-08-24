from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import agent_protocol as protocol


def test_protocol_self_test() -> None:
    protocol.self_test()


def test_exact_safe_delta_round_trip(tmp_path: Path) -> None:
    base_sha = "a" * 40
    head_sha = "b" * 40
    paths = sorted(protocol.SAFE_PROTOCOL_PATHS)
    report = protocol.predict_effect(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=paths,
        policy="NO_PRODUCTION",
        complete=True,
        observed_at="2026-01-01T00:00:00Z",
    )
    path = tmp_path / "effect.json"
    protocol.write_object(path, report)
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    protocol.verify_effect_report(
        reloaded,
        base_sha=base_sha,
        head_sha=head_sha,
        policy="NO_PRODUCTION",
    )
    assert reloaded["effect"] == "NO_PRODUCTION"
    assert reloaded["bind_allowed"] is True


def test_incomplete_delta_is_unknown_and_cannot_bind() -> None:
    report = protocol.predict_effect(
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_paths=[],
        policy="REPOSITORY_POLICY",
        complete=False,
        observed_at="2026-01-01T00:00:00Z",
    )
    assert report["effect"] == "UNKNOWN"
    assert report["bind_allowed"] is False
    with pytest.raises(protocol.ContractError):
        protocol.verify_effect_report(
            report,
            base_sha="a" * 40,
            head_sha="b" * 40,
            policy="REPOSITORY_POLICY",
        )


def test_connector_unknown_is_fail_closed() -> None:
    snapshot = {
        "schema_version": 2,
        "protocol_version": "1.2",
        "source": "GITHUB_CONNECTOR",
        "repository": "gabned/provelume",
        "default_branch": "main",
        "default_sha": "a" * 40,
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "merge_base": "a" * 40,
        "owner_pr": "#1",
        "pr_state": "OPEN",
        "ci_state": "UNKNOWN",
        "review_state": "NOT_REQUIRED",
        "threads_state": "RESOLVED",
        "mergeability": "MERGEABLE",
        "base_ancestry": "TRUE",
        "credentials_accessed": False,
        "production_environment_accessed": False,
    }
    with pytest.raises(protocol.ContractError, match="UNKNOWN"):
        protocol.validate_connector_snapshot(snapshot)


def test_reconciliation_proves_merge_identity_without_inference() -> None:
    evidence = {
        "schema_version": 2,
        "protocol_version": "1.2",
        "source": "GITHUB_CONNECTOR",
        "repository": "gabned/provelume",
        "default_branch": "main",
        "default_sha": "b" * 40,
        "active_pr": "#1",
        "binding_basis_sha": "a" * 40,
        "binding_basis_ancestor": "TRUE",
        "merge_sha": "b" * 40,
        "merge_sha_on_default": "TRUE",
        "pr_state": "MERGED",
        "result": "UNKNOWN",
        "production_action_performed": False,
    }
    report = protocol.reconcile(evidence, observed_at="2026-01-01T00:00:00Z")
    assert report["release_allowed"] is True
    assert report["result"] == "UNKNOWN"
    assert report["observational_only"] is True
    assert report["production_action_performed"] is False
