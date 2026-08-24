#!/usr/bin/env python3
"""Stateless, repository-local Agent Development Protocol v1.2 contracts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL_VERSION = "1.2"
SCHEMA_VERSION = 2
REPOSITORY = "gabned/provelume"
DEFAULT_BRANCH = "main"
MAX_EVIDENCE_AGE = timedelta(minutes=15)
CLOCK_SKEW = timedelta(seconds=30)
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
PR_PATTERN = re.compile(r"#[1-9][0-9]*")
WORKSTREAM_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
POLICIES = {"NO_PRODUCTION", "REPOSITORY_POLICY"}
SOURCES = {"LOCAL_GIT", "GITHUB_CONNECTOR"}
SAFE_PROTOCOL_PATHS = {
    ".github/workflows/ci.yml",
    ".gitignore",
    "AGENTS.md",
    "docs/agent-development-v1.2.md",
    "tests/test_agent_protocol_v1_2.py",
    "tools/agent_protocol.py",
}
PRODUCTION_EXACT = {
    "CHANGELOG.md",
    "pyproject.toml",
    "requirements-release.txt",
}
PRODUCTION_PREFIXES = ("core/", "release/", "scripts/")


class ContractError(ValueError):
    """Raised when protocol evidence is incomplete, open, stale or inconsistent."""


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fail(message: str) -> None:
    raise ContractError(message)


def parse_time(value: Any) -> datetime:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise ContractError("timestamp must be RFC3339") from exc
    if parsed.tzinfo is None:
        fail("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def require_fresh(value: Any) -> None:
    observed = parse_time(value)
    current = datetime.now(UTC)
    if observed > current + CLOCK_SKEW:
        fail("evidence timestamp is in the future")
    if current - observed > MAX_EVIDENCE_AGE:
        fail("evidence is outside the fifteen-minute replay window")


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be an exact lowercase 40-character SHA")
    return value


def require_choice(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        fail(f"{label} has unsupported value {value!r}")
    return value


def require_pr(value: Any, label: str = "owner_pr") -> str:
    if not isinstance(value, str) or PR_PATTERN.fullmatch(value) is None:
        fail(f"{label} must use exact #123 form")
    return value


def require_workstream(value: Any) -> str:
    if not isinstance(value, str) or WORKSTREAM_PATTERN.fullmatch(value) is None:
        fail("workstream must be a closed slug")
    return value


def normalize_path(raw: str) -> str:
    if not isinstance(raw, str):
        fail("changed path must be text")
    value = raw.strip().replace("\\", "/")
    if not value or value == "UNKNOWN" or value.startswith("/"):
        fail("changed path is empty, absolute or UNKNOWN")
    normalized = PurePosixPath(value).as_posix()
    if normalized in {".", ".."} or normalized.startswith("../") or "/../" in normalized:
        fail("changed path escapes the repository")
    return normalized


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        fail(f"JSON evidence must be an object: {path}")
    return value


def load_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON evidence {path}: {exc}") from exc


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "report_sha256"}
    return (
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def report_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["report_sha256"] = report_hash(result)
    return result


def verify_seal(payload: dict[str, Any]) -> None:
    observed = payload.get("report_sha256")
    if not isinstance(observed, str) or SHA256_PATTERN.fullmatch(observed) is None:
        fail("report_sha256 must be an exact lowercase SHA-256")
    if observed != report_hash(payload):
        fail("report_sha256 does not match the exact canonical report")


def classify_path(path: str) -> tuple[str, str | None]:
    if path in SAFE_PROTOCOL_PATHS:
        return "NO_PRODUCTION", None
    if path.startswith(".github/workflows/") or path.startswith(".github/actions/"):
        return "PRODUCTION", "WORKFLOW_OR_REUSABLE_ACTION"
    if path in PRODUCTION_EXACT:
        return "PRODUCTION", "RELEASE_IDENTITY_OR_DEPENDENCY"
    if any(path.startswith(prefix) for prefix in PRODUCTION_PREFIXES):
        return "PRODUCTION", "CORE_OR_RELEASE_PATH"
    return "PRODUCTION", "UNCLASSIFIED_PATH"


def connector_paths(payload: Any) -> list[str]:
    values = payload if isinstance(payload, list) else None
    if isinstance(payload, dict):
        values = payload.get("changed_files")
    if not isinstance(values, list):
        fail("connector input must be a list or contain changed_files")
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            result.append(item)
            continue
        if not isinstance(item, dict):
            fail("invalid connector changed-file entry")
        previous = item.get("previous_path")
        if isinstance(previous, str):
            result.append(previous)
        current = item.get("path") if isinstance(item.get("path"), str) else item.get("filename")
        if isinstance(current, str):
            result.append(current)
        elif not isinstance(previous, str):
            fail("connector changed-file entry has no path")
    return result


def read_changed_paths(path: Path) -> list[str]:
    try:
        values = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"unable to read changed paths: {exc}") from exc
    return [value for value in values if value.strip()]


def build_effect_report(
    *,
    base_sha: str,
    head_sha: str,
    changed_paths: list[str],
    policy: str,
    source: str,
    complete: bool,
    observed_at: str | None = None,
) -> dict[str, Any]:
    stamp = observed_at or now_utc()
    errors: list[str] = []
    if source not in SOURCES:
        errors.append("source uses an unsupported identifier")
    if policy not in POLICIES:
        errors.append("policy uses an unsupported identifier")
    if not isinstance(base_sha, str) or SHA_PATTERN.fullmatch(base_sha) is None:
        errors.append("base_sha must be exact")
    if not isinstance(head_sha, str) or SHA_PATTERN.fullmatch(head_sha) is None:
        errors.append("head_sha must be exact")
    try:
        parse_time(stamp)
        normalized = sorted({normalize_path(path) for path in changed_paths})
    except ContractError as exc:
        normalized = []
        errors.append(str(exc))
    if not complete:
        errors.append("changed-path enumeration is incomplete")
    if not normalized:
        errors.append("changed_paths must be non-empty")

    matches: list[dict[str, str]] = []
    if not errors:
        for path in normalized:
            effect, identifier = classify_path(path)
            if effect == "PRODUCTION" and identifier is not None:
                matches.append({"identifier": identifier, "path": path})
    effect = "UNKNOWN" if errors else ("PRODUCTION" if matches else "NO_PRODUCTION")
    bind_allowed = not errors and effect != "UNKNOWN" and (
        policy == "REPOSITORY_POLICY" or effect == "NO_PRODUCTION"
    )
    return seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "PREDICT",
            "source": source,
            "repository": REPOSITORY,
            "observed_at": stamp,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "policy": policy,
            "complete": complete,
            "changed_paths": normalized,
            "effect": effect,
            "matches": matches,
            "bind_allowed": bind_allowed,
            "errors": errors,
        }
    )


def verify_effect_report(
    report: dict[str, Any], *, base_sha: str, head_sha: str, policy: str
) -> None:
    verify_seal(report)
    expected_identity = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "PREDICT",
        "repository": REPOSITORY,
        "base_sha": require_sha(base_sha, "base_sha"),
        "head_sha": require_sha(head_sha, "head_sha"),
        "policy": require_choice(policy, "policy", POLICIES),
    }
    for key, value in expected_identity.items():
        if report.get(key) != value:
            fail(f"effect report {key} mismatch")
    paths = report.get("changed_paths")
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        fail("effect report changed_paths must be a string list")
    source = require_choice(report.get("source"), "source", SOURCES)
    complete = report.get("complete")
    if not isinstance(complete, bool):
        fail("effect report complete must be boolean")
    recomputed = build_effect_report(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=paths,
        policy=policy,
        source=source,
        complete=complete,
        observed_at=str(report.get("observed_at", "")),
    )
    if report != recomputed:
        fail("effect report classifications or authorization do not match the exact path set")
    if report.get("effect") == "UNKNOWN" or report.get("bind_allowed") is not True:
        fail("effect report does not authorize PR binding")


def build_binding(
    report: dict[str, Any], *, active_pr: str, workstream: str
) -> dict[str, Any]:
    base_sha = require_sha(report.get("base_sha"), "base_sha")
    head_sha = require_sha(report.get("head_sha"), "head_sha")
    policy = require_choice(report.get("policy"), "policy", POLICIES)
    verify_effect_report(report, base_sha=base_sha, head_sha=head_sha, policy=policy)
    return seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "BIND",
            "repository": REPOSITORY,
            "observed_at": now_utc(),
            "active_pr": require_pr(active_pr, "active_pr"),
            "workstream": require_workstream(workstream),
            "base_sha": base_sha,
            "binding_basis_sha": head_sha,
            "effect_report_sha256": report["report_sha256"],
            "effect_policy": policy,
            "effect_prediction": report["effect"],
            "state": "BOUND",
            "errors": [],
        }
    )


def validate_binding(binding: dict[str, Any]) -> None:
    verify_seal(binding)
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "BIND",
        "repository": REPOSITORY,
        "state": "BOUND",
        "errors": [],
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            fail(f"binding {key} mismatch")
    require_pr(binding.get("active_pr"), "active_pr")
    require_workstream(binding.get("workstream"))
    require_sha(binding.get("base_sha"), "base_sha")
    require_sha(binding.get("binding_basis_sha"), "binding_basis_sha")
    require_choice(binding.get("effect_policy"), "effect_policy", POLICIES)
    require_choice(
        binding.get("effect_prediction"),
        "effect_prediction",
        {"NO_PRODUCTION", "PRODUCTION"},
    )
    digest = binding.get("effect_report_sha256")
    if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        fail("binding effect_report_sha256 is invalid")


def validate_snapshot_identity(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "SNAPSHOT",
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
    }
    for key, value in expected.items():
        if snapshot.get(key) != value:
            errors.append(f"snapshot {key} mismatch")
    try:
        verify_seal(snapshot)
    except ContractError as exc:
        errors.append(str(exc))
    try:
        require_fresh(snapshot.get("observed_at"))
    except ContractError as exc:
        errors.append(str(exc))
    return errors


def preflight(snapshot: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    errors = validate_snapshot_identity(snapshot)
    try:
        validate_binding(binding)
    except ContractError as exc:
        errors.append(str(exc))

    for key in ("default_sha", "base_sha", "head_sha", "binding_basis_sha"):
        try:
            require_sha(snapshot.get(key), key)
        except ContractError as exc:
            errors.append(str(exc))
    try:
        require_pr(snapshot.get("owner_pr"), "owner_pr")
    except ContractError as exc:
        errors.append(str(exc))

    comparisons = {
        "owner_pr": "active_pr",
        "base_sha": "base_sha",
        "binding_basis_sha": "binding_basis_sha",
        "effect_report_sha256": "effect_report_sha256",
    }
    for snapshot_key, binding_key in comparisons.items():
        if snapshot.get(snapshot_key) != binding.get(binding_key):
            errors.append(f"snapshot {snapshot_key} does not match binding")

    closed = {
        "pr_state": {"OPEN", "UNKNOWN"},
        "draft": {"TRUE", "FALSE", "UNKNOWN"},
        "checks": {"SUCCESS", "PENDING", "FAILURE", "NONE", "UNKNOWN"},
        "review": {"APPROVED", "CHANGES_REQUESTED", "NONE", "UNKNOWN"},
        "requires_approval": {"TRUE", "FALSE", "UNKNOWN"},
        "mergeability": {"MERGEABLE", "CONFLICTING", "UNKNOWN"},
        "base_ancestry": {"TRUE", "FALSE", "UNKNOWN"},
        "binding_basis_ancestor": {"TRUE", "FALSE", "UNKNOWN"},
    }
    for key, allowed in closed.items():
        if snapshot.get(key) not in allowed:
            errors.append(f"snapshot {key} is not a closed identifier")

    if snapshot.get("pr_state") != "OPEN":
        errors.append("owner PR is not OPEN")
    if snapshot.get("draft") != "FALSE":
        errors.append("owner PR is draft or UNKNOWN")
    if snapshot.get("checks") != "SUCCESS":
        errors.append("required checks are not successful")
    if snapshot.get("mergeability") != "MERGEABLE":
        errors.append("mergeability is not proven")
    if snapshot.get("base_ancestry") != "TRUE":
        errors.append("base ancestry is not proven")
    if snapshot.get("binding_basis_ancestor") != "TRUE":
        errors.append("binding-basis ancestry is not proven")

    unresolved = snapshot.get("unresolved_threads")
    if not isinstance(unresolved, int) or isinstance(unresolved, bool) or unresolved != 0:
        errors.append("unresolved thread count blocks or is UNKNOWN")

    requires_approval = snapshot.get("requires_approval")
    review = snapshot.get("review")
    if requires_approval == "UNKNOWN":
        errors.append("required-review policy is UNKNOWN")
    elif requires_approval == "TRUE" and review != "APPROVED":
        errors.append("required approval is missing")
    if review == "CHANGES_REQUESTED":
        errors.append("review requests changes")

    if snapshot.get("credentials_accessed") is not False:
        errors.append("connector snapshot accessed credentials or is UNKNOWN")
    if snapshot.get("production_environment_accessed") is not False:
        errors.append("connector snapshot accessed production or is UNKNOWN")

    result = "READY" if not errors else "BLOCKED"
    return seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "PREFLIGHT",
            "repository": REPOSITORY,
            "observed_at": now_utc(),
            "result": result,
            "merge_ready": result == "READY",
            "errors": errors,
        }
    )


def reconcile(evidence: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    identity_errors: list[str] = []
    try:
        validate_binding(binding)
    except ContractError as exc:
        identity_errors.append(str(exc))
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "RECONCILE_EVIDENCE",
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
        "pr_state": "MERGED",
        "binding_basis_ancestor": "TRUE",
        "merge_sha_on_default": "TRUE",
        "production_action_performed": False,
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            identity_errors.append(f"evidence {key} mismatch")
    try:
        verify_seal(evidence)
    except ContractError as exc:
        identity_errors.append(str(exc))
    try:
        require_fresh(evidence.get("observed_at"))
    except ContractError as exc:
        identity_errors.append(str(exc))
    for key in ("default_sha", "merge_sha", "binding_basis_sha"):
        try:
            require_sha(evidence.get(key), key)
        except ContractError as exc:
            identity_errors.append(str(exc))
    try:
        require_pr(evidence.get("active_pr"), "active_pr")
    except ContractError as exc:
        identity_errors.append(str(exc))

    comparisons = {
        "active_pr": "active_pr",
        "binding_basis_sha": "binding_basis_sha",
        "effect_report_sha256": "effect_report_sha256",
    }
    for evidence_key, binding_key in comparisons.items():
        if evidence.get(evidence_key) != binding.get(binding_key):
            identity_errors.append(f"evidence {evidence_key} does not match binding")

    workflow = evidence.get("workflow_status")
    release = evidence.get("release_status")
    allowed_workflow = {"NOT_TRIGGERED", "PENDING", "SUCCEEDED", "FAILED", "UNKNOWN"}
    allowed_release = {"NOT_APPLICABLE", "NOT_TRIGGERED", "SUCCEEDED", "FAILED", "UNKNOWN"}
    observation_errors: list[str] = []
    if workflow not in allowed_workflow:
        observation_errors.append("workflow_status is not closed")
    if release not in allowed_release:
        observation_errors.append("release_status is not closed")

    if identity_errors or observation_errors or "UNKNOWN" in {workflow, release}:
        result = "UNKNOWN"
    elif "FAILED" in {workflow, release}:
        result = "FAILED"
    elif workflow == "PENDING":
        result = "PENDING"
    elif release == "SUCCEEDED":
        result = "SUCCEEDED"
    else:
        result = "NOT_TRIGGERED"

    return seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "RECONCILE",
            "repository": REPOSITORY,
            "observed_at": evidence.get("observed_at"),
            "result": result,
            "release_allowed": not identity_errors,
            "observational_only": True,
            "production_action_performed": False,
            "identity_errors": identity_errors,
            "observation_errors": observation_errors,
            "evidence": evidence,
        }
    )


def self_test() -> None:
    base_sha = "a" * 40
    head_sha = "b" * 40
    current_default = "d" * 40
    stamp = now_utc()

    safe = build_effect_report(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=sorted(SAFE_PROTOCOL_PATHS),
        policy="NO_PRODUCTION",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=stamp,
    )
    verify_effect_report(safe, base_sha=base_sha, head_sha=head_sha, policy="NO_PRODUCTION")
    assert safe["effect"] == "NO_PRODUCTION" and safe["bind_allowed"] is True

    unclassified = build_effect_report(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=["Dockerfile"],
        policy="NO_PRODUCTION",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=stamp,
    )
    assert unclassified["effect"] == "PRODUCTION"
    assert unclassified["bind_allowed"] is False

    renamed = connector_paths(
        {"changed_files": [{"previous_path": "core/old.py", "filename": "docs/new.md"}]}
    )
    assert renamed == ["core/old.py", "docs/new.md"]

    binding = build_binding(
        safe, active_pr="#45", workstream="agent-protocol-v1.2-subset"
    )
    snapshot = seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "SNAPSHOT",
            "source": "GITHUB_CONNECTOR",
            "repository": REPOSITORY,
            "observed_at": stamp,
            "default_branch": DEFAULT_BRANCH,
            "default_sha": base_sha,
            "owner_pr": "#45",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "binding_basis_sha": head_sha,
            "effect_report_sha256": safe["report_sha256"],
            "pr_state": "OPEN",
            "draft": "FALSE",
            "checks": "SUCCESS",
            "review": "UNKNOWN",
            "requires_approval": "FALSE",
            "unresolved_threads": 0,
            "mergeability": "MERGEABLE",
            "base_ancestry": "TRUE",
            "binding_basis_ancestor": "TRUE",
            "credentials_accessed": False,
            "production_environment_accessed": False,
        }
    )
    assert preflight(snapshot, binding)["merge_ready"] is True

    stale_identity = dict(snapshot)
    stale_identity["owner_pr"] = "#999"
    stale_identity = seal(stale_identity)
    assert preflight(stale_identity, binding)["merge_ready"] is False

    tampered = dict(safe)
    tampered["effect"] = "PRODUCTION"
    tampered = seal(tampered)
    try:
        verify_effect_report(
            tampered, base_sha=base_sha, head_sha=head_sha, policy="NO_PRODUCTION"
        )
    except ContractError:
        pass
    else:
        fail("tampered effect classification was accepted")

    evidence = seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "RECONCILE_EVIDENCE",
            "source": "GITHUB_CONNECTOR",
            "repository": REPOSITORY,
            "observed_at": stamp,
            "default_branch": DEFAULT_BRANCH,
            "default_sha": current_default,
            "active_pr": "#45",
            "pr_state": "MERGED",
            "binding_basis_sha": head_sha,
            "binding_basis_ancestor": "TRUE",
            "effect_report_sha256": safe["report_sha256"],
            "merge_sha": "c" * 40,
            "merge_sha_on_default": "TRUE",
            "workflow_status": "UNKNOWN",
            "release_status": "NOT_APPLICABLE",
            "production_action_performed": False,
        }
    )
    report = reconcile(evidence, binding)
    assert report["release_allowed"] is True
    assert report["result"] == "UNKNOWN"
    assert evidence["default_sha"] != evidence["merge_sha"]
    print(f"{REPOSITORY} Agent Development Protocol v{PROTOCOL_VERSION} contracts passed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    effects = commands.add_parser("effects")
    source = effects.add_mutually_exclusive_group(required=True)
    source.add_argument("--changed-paths", type=Path)
    source.add_argument("--connector-files", type=Path)
    effects.add_argument("--source", choices=sorted(SOURCES), required=True)
    effects.add_argument("--base-sha", required=True)
    effects.add_argument("--head-sha", required=True)
    effects.add_argument("--policy", choices=sorted(POLICIES), required=True)
    effects.add_argument("--complete", action="store_true")
    effects.add_argument("--output", type=Path)

    verify = commands.add_parser("verify-effect")
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--base-sha", required=True)
    verify.add_argument("--head-sha", required=True)
    verify.add_argument("--policy", choices=sorted(POLICIES), required=True)

    bind = commands.add_parser("bind")
    bind.add_argument("--report", type=Path, required=True)
    bind.add_argument("--pr", required=True)
    bind.add_argument("--workstream", required=True)
    bind.add_argument("--output", type=Path)

    check = commands.add_parser("preflight")
    check.add_argument("--snapshot", type=Path, required=True)
    check.add_argument("--binding", type=Path, required=True)
    check.add_argument("--output", type=Path)

    observed = commands.add_parser("reconcile")
    observed.add_argument("--evidence", type=Path, required=True)
    observed.add_argument("--binding", type=Path, required=True)
    observed.add_argument("--output", type=Path)

    commands.add_parser("self-test")
    return parser


def emit(payload: dict[str, Any], output: Path | None) -> None:
    if output is not None:
        write_object(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "effects":
            paths = (
                read_changed_paths(args.changed_paths)
                if args.changed_paths is not None
                else connector_paths(load_value(args.connector_files))
            )
            report = build_effect_report(
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                changed_paths=paths,
                policy=args.policy,
                source=args.source,
                complete=args.complete,
            )
            emit(report, args.output)
            return 0 if report["bind_allowed"] else 1
        if args.command == "verify-effect":
            verify_effect_report(
                load_object(args.report),
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                policy=args.policy,
            )
            print("Effect report is exact and binding-compatible.")
            return 0
        if args.command == "bind":
            emit(
                build_binding(
                    load_object(args.report),
                    active_pr=args.pr,
                    workstream=args.workstream,
                ),
                args.output,
            )
            return 0
        if args.command == "preflight":
            report = preflight(load_object(args.snapshot), load_object(args.binding))
            emit(report, args.output)
            return 0 if report["merge_ready"] else 1
        if args.command == "reconcile":
            report = reconcile(load_object(args.evidence), load_object(args.binding))
            emit(report, args.output)
            return 0 if report["release_allowed"] else 1
        self_test()
        return 0
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
