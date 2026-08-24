#!/usr/bin/env python3
"""Repository-local contracts for Agent Development Protocol v1.2.

The module is deliberately offline. It validates caller-supplied evidence, classifies
an exact Git path set, and produces observational reconciliation reports. It never
calls GitHub, reads credentials, dispatches workflows, publishes releases, or touches
runtime data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "1.2"
SCHEMA_VERSION = 2
REPOSITORY = "gabned/provelume"
DEFAULT_BRANCH = "main"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PR_PATTERN = re.compile(r"^#[1-9][0-9]*$")
EFFECTS = {"NO_PRODUCTION", "PRODUCTION", "UNKNOWN"}
POLICIES = {"NO_PRODUCTION", "REPOSITORY_POLICY"}
TRUTH_VALUES = {"TRUE", "FALSE", "UNKNOWN"}
RESULTS = {"NOT_TRIGGERED", "SUCCEEDED", "FAILED", "PENDING", "UNKNOWN"}
SAFE_PROTOCOL_PATHS = {
    ".github/workflows/ci.yml",
    ".gitignore",
    "AGENTS.md",
    "docs/agent-development-v1.2.md",
    "tests/test_agent_protocol_v1_2.py",
    "tools/agent_protocol.py",
}
PRODUCTION_PREFIXES = ("core/", "scripts/")
PRODUCTION_EXACT = {
    "CHANGELOG.md",
    "pyproject.toml",
    "requirements-release.txt",
}


class ContractError(ValueError):
    """Raised when protocol evidence is incomplete or inconsistent."""


def fail(message: str) -> None:
    raise ContractError(message)


def now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be a full lowercase SHA-1")
    return value


def require_choice(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        fail(f"{label} has unsupported value {value!r}")
    return value


def require_closed_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        fail(f"{label} must be a non-empty closed identifier")
    if any(character.isspace() for character in value):
        fail(f"{label} must not contain whitespace or prose")
    if any(character in value for character in "()[]{}"):
        fail(f"{label} must not contain annotations")
    return value


def normalize_path(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    parts = value.split("/")
    if (
        not value
        or value.startswith(("/", "./"))
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in parts)
    ):
        fail(f"invalid changed path: {raw!r}")
    return value


def path_digest(paths: list[str]) -> str:
    payload = "".join(f"{path}\n" for path in paths).encode()
    return hashlib.sha256(payload).hexdigest()


def classify_path(path: str) -> tuple[str, str | None]:
    if path in SAFE_PROTOCOL_PATHS:
        return "NO_PRODUCTION", None
    if path in PRODUCTION_EXACT or path.startswith(PRODUCTION_PREFIXES):
        return "PRODUCTION", path
    if path.startswith(".github/workflows/"):
        return "PRODUCTION", path
    return "NO_PRODUCTION", None


def predict_effect(
    *,
    base_sha: str,
    head_sha: str,
    changed_paths: list[str],
    policy: str,
    complete: bool,
    observed_at: str | None = None,
) -> dict[str, Any]:
    require_sha(base_sha, "base_sha")
    require_sha(head_sha, "head_sha")
    require_choice(policy, "policy", POLICIES)
    normalized = [normalize_path(path) for path in changed_paths]
    if normalized != sorted(set(normalized)):
        fail("changed_paths must be sorted and unique")

    matches: list[str] = []
    errors: list[str] = []
    if not complete:
        effect = "UNKNOWN"
        errors.append("changed-path enumeration is incomplete")
    else:
        effect = "NO_PRODUCTION"
        for path in normalized:
            path_effect, match = classify_path(path)
            if path_effect == "PRODUCTION":
                effect = "PRODUCTION"
                if match is not None:
                    matches.append(match)

    bind_allowed = effect != "UNKNOWN" and (
        policy == "REPOSITORY_POLICY" or effect == "NO_PRODUCTION"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "PREDICT",
        "source": "LOCAL_GIT",
        "repository": REPOSITORY,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "policy": policy,
        "complete": complete,
        "changed_paths": normalized,
        "changed_paths_sha256": path_digest(normalized),
        "effect": effect,
        "matches": sorted(matches),
        "bind_allowed": bind_allowed,
        "errors": errors,
        "observed_at": observed_at or now_utc(),
    }


def verify_effect_report(
    report: dict[str, Any],
    *,
    base_sha: str,
    head_sha: str,
    policy: str,
) -> None:
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "PREDICT",
        "source": "LOCAL_GIT",
        "repository": REPOSITORY,
        "base_sha": require_sha(base_sha, "base_sha"),
        "head_sha": require_sha(head_sha, "head_sha"),
        "policy": require_choice(policy, "policy", POLICIES),
    }
    for key, value in expected.items():
        if report.get(key) != value:
            fail(f"effect report {key} mismatch")

    paths = report.get("changed_paths")
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        fail("effect report changed_paths must be a string list")
    if paths != sorted(set(paths)):
        fail("effect report changed_paths must be sorted and unique")
    for path in paths:
        normalize_path(path)
    if report.get("changed_paths_sha256") != path_digest(paths):
        fail("effect report changed-path digest mismatch")

    effect = require_choice(report.get("effect"), "effect", EFFECTS)
    if report.get("complete") is not True and effect != "UNKNOWN":
        fail("an incomplete effect report must be UNKNOWN")
    if effect == "UNKNOWN" or report.get("bind_allowed") is not True:
        fail("effect report does not authorize PR binding")
    if policy == "NO_PRODUCTION" and effect != "NO_PRODUCTION":
        fail("NO_PRODUCTION policy rejects production-capable paths")


def validate_connector_snapshot(snapshot: dict[str, Any]) -> None:
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
    }
    for key, value in expected.items():
        if snapshot.get(key) != value:
            fail(f"connector snapshot {key} mismatch")

    for key in ("default_sha", "base_sha", "head_sha", "merge_base"):
        require_sha(snapshot.get(key), key)
    owner_pr = require_closed_identifier(snapshot.get("owner_pr"), "owner_pr")
    if PR_PATTERN.fullmatch(owner_pr) is None:
        fail("owner_pr must be an exact #N identifier")

    closed_gates = {
        "pr_state": {"OPEN"},
        "ci_state": {"SUCCESS"},
        "review_state": {"APPROVED", "NOT_REQUIRED"},
        "threads_state": {"RESOLVED"},
        "mergeability": {"MERGEABLE"},
        "base_ancestry": {"TRUE"},
    }
    for key, allowed in closed_gates.items():
        value = snapshot.get(key)
        if value == "UNKNOWN":
            fail(f"connector snapshot {key} is UNKNOWN")
        require_choice(value, key, allowed)

    if snapshot.get("credentials_accessed") is not False:
        fail("connector snapshot must not access credentials")
    if snapshot.get("production_environment_accessed") is not False:
        fail("connector snapshot must not access production environments")


def reconcile(evidence: dict[str, Any], observed_at: str | None = None) -> dict[str, Any]:
    identity_errors: list[str] = []
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            identity_errors.append(f"{key} mismatch")

    for key in ("default_sha", "merge_sha", "binding_basis_sha"):
        try:
            require_sha(evidence.get(key), key)
        except ContractError as error:
            identity_errors.append(str(error))

    active_pr = evidence.get("active_pr")
    if not isinstance(active_pr, str) or PR_PATTERN.fullmatch(active_pr) is None:
        identity_errors.append("active_pr must be an exact #N identifier")
    for key in ("binding_basis_ancestor", "merge_sha_on_default"):
        if evidence.get(key) not in TRUTH_VALUES:
            identity_errors.append(f"{key} is invalid")
    if evidence.get("pr_state") not in {"MERGED", "UNKNOWN"}:
        identity_errors.append("pr_state is invalid")
    if evidence.get("production_action_performed") is not False:
        identity_errors.append("reconciliation must be observational-only")

    result = evidence.get("result", "UNKNOWN")
    if result not in RESULTS:
        identity_errors.append("result is invalid")
    identity_proven = (
        not identity_errors
        and evidence.get("pr_state") == "MERGED"
        and evidence.get("binding_basis_ancestor") == "TRUE"
        and evidence.get("merge_sha_on_default") == "TRUE"
        and evidence.get("default_sha") == evidence.get("merge_sha")
    )
    observation_errors = []
    if result == "UNKNOWN":
        observation_errors.append("post-merge effect evidence is UNKNOWN")

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "RECONCILE",
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "observed_at": observed_at or now_utc(),
        "observational_only": True,
        "production_action_performed": False,
        "active_pr": active_pr or "UNKNOWN",
        "binding_basis_sha": evidence.get("binding_basis_sha", "UNKNOWN"),
        "binding_basis_ancestor": evidence.get("binding_basis_ancestor", "UNKNOWN"),
        "merge_sha": evidence.get("merge_sha", "UNKNOWN"),
        "merge_sha_on_default": evidence.get("merge_sha_on_default", "UNKNOWN"),
        "default_sha": evidence.get("default_sha", "UNKNOWN"),
        "pr_state": evidence.get("pr_state", "UNKNOWN"),
        "result": result,
        "release_allowed": identity_proven,
        "identity_errors": identity_errors,
        "observation_errors": observation_errors,
        "errors": identity_errors + observation_errors,
        "evidence": evidence,
    }


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"invalid JSON evidence {path}: {error}")
    if not isinstance(value, dict):
        fail(f"JSON evidence must be an object: {path}")
    return value


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def self_test() -> None:
    base_sha = "a" * 40
    head_sha = "b" * 40
    safe_paths = sorted(SAFE_PROTOCOL_PATHS)
    safe = predict_effect(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=safe_paths,
        policy="NO_PRODUCTION",
        complete=True,
        observed_at="2026-01-01T00:00:00Z",
    )
    assert safe["effect"] == "NO_PRODUCTION"
    assert safe["bind_allowed"] is True
    verify_effect_report(
        safe,
        base_sha=base_sha,
        head_sha=head_sha,
        policy="NO_PRODUCTION",
    )

    product = predict_effect(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=["core/provelume/example.py"],
        policy="REPOSITORY_POLICY",
        complete=True,
        observed_at="2026-01-01T00:00:00Z",
    )
    assert product["effect"] == "PRODUCTION"
    assert product["bind_allowed"] is True

    incomplete = predict_effect(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=[],
        policy="REPOSITORY_POLICY",
        complete=False,
        observed_at="2026-01-01T00:00:00Z",
    )
    assert incomplete["effect"] == "UNKNOWN"
    assert incomplete["bind_allowed"] is False

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
        "default_sha": base_sha,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_base": base_sha,
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
    try:
        validate_connector_snapshot(snapshot)
    except ContractError:
        pass
    else:
        fail("UNKNOWN connector gate was accepted")

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
        "default_sha": head_sha,
        "active_pr": "#1",
        "binding_basis_sha": base_sha,
        "binding_basis_ancestor": "TRUE",
        "merge_sha": head_sha,
        "merge_sha_on_default": "TRUE",
        "pr_state": "MERGED",
        "result": "UNKNOWN",
        "production_action_performed": False,
    }
    report = reconcile(evidence, observed_at="2026-01-01T00:00:00Z")
    assert report["release_allowed"] is True
    assert report["result"] == "UNKNOWN"
    assert report["production_action_performed"] is False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    predict = commands.add_parser("predict")
    predict.add_argument("--base-sha", required=True)
    predict.add_argument("--head-sha", required=True)
    predict.add_argument("--changed-paths", required=True)
    predict.add_argument("--policy", choices=sorted(POLICIES), required=True)
    predict.add_argument("--complete", action="store_true")
    predict.add_argument("--output", required=True)

    verify = commands.add_parser("verify-effect")
    verify.add_argument("--report", required=True)
    verify.add_argument("--base-sha", required=True)
    verify.add_argument("--head-sha", required=True)
    verify.add_argument("--policy", choices=sorted(POLICIES), required=True)

    connector = commands.add_parser("validate-connector")
    connector.add_argument("--snapshot", required=True)

    reconcile_parser = commands.add_parser("reconcile")
    reconcile_parser.add_argument("--evidence", required=True)
    reconcile_parser.add_argument("--output", required=True)

    commands.add_parser("self-test")
    return parser


def read_changed_paths(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        fail(f"unable to read changed paths: {error}")
    paths = [normalize_path(line) for line in lines if line.strip()]
    if len(paths) != len(set(paths)):
        fail("changed-path input contains duplicates")
    return sorted(paths)


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "predict":
            report = predict_effect(
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                changed_paths=read_changed_paths(Path(args.changed_paths)),
                policy=args.policy,
                complete=args.complete,
            )
            write_object(Path(args.output), report)
            print(json.dumps(report, indent=2, sort_keys=True))
        elif args.command == "verify-effect":
            verify_effect_report(
                load_object(Path(args.report)),
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                policy=args.policy,
            )
            print("Effect report is exact and binding-compatible.")
        elif args.command == "validate-connector":
            validate_connector_snapshot(load_object(Path(args.snapshot)))
            print("Connector snapshot closes all required gates.")
        elif args.command == "reconcile":
            report = reconcile(load_object(Path(args.evidence)))
            write_object(Path(args.output), report)
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            self_test()
            print("Agent Development Protocol v1.2 self-test passed.")
    except ContractError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
