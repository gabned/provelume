"""Offline execution contracts. Caller-selected trusted inputs never grant authority."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "protocol147_ops", Path(__file__).with_name("agent_protocol_v1_4_2_ops.py")
)
ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ops)

VERSION = "1.4.7"
PHASES = {"START", "RESUME", "IMPLEMENT", "QUALIFY", "POST_MERGE", "CLOSE"}
WORKSTREAMS = {"PRODUCT", "PROTOCOL", "CHECKPOINT_ONLY"}
ROLES = {"ALWAYS", "PROCEDURE", "HISTORICAL"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(ops.canonical(value)).hexdigest()


def read_bound(root, name):
    """Resolve only regular, non-symlink repository paths, including parents."""
    ops.path(name)
    root = Path(root).absolute()
    path = root / name
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink document")
    require(path.is_file(), "missing document: " + name)
    return path.read_bytes()


def select_documents(root, manifest, expected_digest, *, workstream, phase, host="WORK"):
    """Trust comes from the independently selected accepted manifest, not its hash."""
    require(digest(manifest) == expected_digest, "untrusted or changed document manifest")
    ops.obj(manifest, "schema protocol_version documents repository_policy", "manifest")
    require(
        manifest["schema"] == "agent-documents/v1" and manifest["protocol_version"] == VERSION,
        "document contract version",
    )
    rows = manifest["documents"]
    require(isinstance(rows, list) and 0 < len(rows) <= 100, "bounded document inventory")
    inventory, content = {}, {}
    for row in rows:
        ops.obj(row, "id path sha256 role workstreams phases hosts requires", "document")
        identity = ops.text(row["id"], "document id")
        require(identity not in inventory, "duplicate document id")
        require(
            row["path"] not in {r["path"] for r in inventory.values()}, "duplicate document path"
        )
        require(row["role"] in ROLES, "unknown document role")
        for key, allowed in (
            ("workstreams", WORKSTREAMS),
            ("phases", PHASES),
            ("hosts", {"WORK", "GIT"}),
        ):
            require(
                isinstance(row[key], list)
                and bool(row[key])
                and len(set(row[key])) == len(row[key])
                and set(row[key]) <= allowed,
                "unknown or duplicate reading condition",
            )
        require(
            isinstance(row["requires"], list)
            and all(isinstance(v, str) for v in row["requires"])
            and len(set(row["requires"])) == len(row["requires"]),
            "invalid references",
        )
        data = read_bound(root, row["path"])
        require(
            hashlib.sha256(data).hexdigest() == ops.sha(row["sha256"], 64),
            "document integrity: " + row["path"],
        )
        content[identity] = data.decode("utf-8")
        inventory[identity] = row
    require(any(r["role"] == "ALWAYS" for r in rows), "cross-cutting rules missing")
    visiting, visited = set(), set()

    def visit(identity):
        require(identity in inventory, "missing document reference: " + identity)
        require(identity not in visiting, "document dependency cycle")
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in inventory[identity]["requires"]:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)

    for identity in sorted(inventory):
        visit(identity)
    fallback = workstream not in WORKSTREAMS or phase not in PHASES or host not in {"WORK", "GIT"}
    selected = set()

    def include(identity):
        if identity in selected:
            return
        selected.add(identity)
        for dependency in inventory[identity]["requires"]:
            include(dependency)

    for identity, row in inventory.items():
        if (
            fallback
            or row["role"] == "ALWAYS"
            or (
                row["role"] != "HISTORICAL"
                and (
                    fallback
                    or (
                        workstream in row["workstreams"]
                        and phase in row["phases"]
                        and host in row["hosts"]
                    )
                )
            )
        ):
            include(identity)
    documents = [
        {
            "id": identity,
            "path": inventory[identity]["path"],
            "sha256": inventory[identity]["sha256"],
            "content": content[identity],
        }
        for identity in sorted(selected)
    ]
    return {
        "schema": "agent-document-selection/v1",
        "protocol_version": VERSION,
        "manifest_sha256": expected_digest,
        "selection": "FULL_FALLBACK" if fallback else "EXACT",
        "documents": documents,
        "document_count": len(documents),
        "model_bytes": sum(len(d["content"].encode()) for d in documents),
        "verified_inventory_bytes": sum(len(c.encode()) for c in content.values()),
        "push_qualified": False,
    }


def validate_qualification(operation, policy, expected_digest, *, now=None):
    """Apply the accepted repository policy without querying remote administration APIs."""
    require(digest(policy) == expected_digest, "changed trusted repository policy")
    ops.obj(
        policy,
        "schema repository required_workflows post_merge_required_workflows review_requirement",
        "policy",
    )
    require(policy["schema"] == "agent-repository-policy/v1", "policy schema")
    require(policy["repository"] == operation["pr"]["repository"], "policy repository")
    required = policy["required_workflows"]
    require(
        isinstance(required, list) and bool(required) and required == sorted(set(required)),
        "closed required workflow inventory",
    )
    require(operation["ci"]["required_workflows"] == required, "required CI policy mismatch")
    post_required = policy["post_merge_required_workflows"]
    require(
        isinstance(post_required, list)
        and bool(post_required)
        and post_required == sorted(set(post_required)),
        "closed post-merge workflow inventory",
    )
    if operation["phase"] == "POST_MERGE":
        require(
            operation["post_merge_ci"]["required_workflows"] == post_required,
            "required post-merge CI policy mismatch",
        )
    require(policy["review_requirement"] in {"NONE", "REPOSITORY"}, "unknown review policy")
    require(
        operation["reviews"]["requirement"] == policy["review_requirement"]
        or (
            policy["review_requirement"] == "NONE"
            and operation["reviews"]["requirement"] == "EXPLICIT_MAINTAINER"
        ),
        "required review policy mismatch",
    )
    ops.validate_operations(operation, now=now)
    return {
        "schema": "agent-qualification/v1",
        "protocol_version": VERSION,
        "repository": policy["repository"],
        "base_sha": operation["pr"]["base_sha"],
        "head_sha": operation["pr"]["head_sha"],
        "result": "PASS",
        "policy_sha256": expected_digest,
        "operation_sha256": digest(operation),
        "remote_enforcement": "GITHUB_DECIDES_AT_NORMAL_MERGE",
        "ruleset_observation_required": False,
        "merge_performed": False,
    }


def verify_merge_response(response, expected_head, observed_head):
    """A normal GitHub merge denial is terminal for this attempt, never bypassed."""
    ops.sha(expected_head)
    require(expected_head == ops.sha(observed_head), "head moved before merge")
    require(
        isinstance(response, dict) and response.get("merged") is True,
        "GitHub denied or did not prove merge",
    )
    return {"merge_sha": ops.sha(response.get("sha")), "post_merge_verification": "REQUIRED"}


def evidence_summary(observation, reference, *, now=None):
    """Inventory summaries preserve uncertainty and cannot become gate receipts."""
    ops.obj(reference, "id sha256", "evidence reference")
    ops.text(reference["id"], "evidence id")
    require(reference["sha256"] == digest(observation), "evidence summary digest mismatch")
    require(isinstance(observation, dict), "observation object required")
    status = observation.get("status", "UNKNOWN")
    require(status in {"OBSERVED", "UNKNOWN"}, "unknown observation state")
    stamp = observation.get("observed_at")
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        require(observed.tzinfo is not None, "observation timezone missing")
        age = ((now or datetime.now(UTC)) - observed).total_seconds()
        freshness = "FRESH" if -30 <= age <= 900 else "STALE"
    except (AttributeError, TypeError, ValueError):
        freshness = "UNKNOWN"
    raw = observation.get("response")
    response = raw if isinstance(raw, dict) else {}
    failed = bool(response.get("error")) or (
        isinstance(response.get("status"), int) and response["status"] >= 400
    )
    if failed or raw is None:
        status = "UNKNOWN"
    identity = {
        k: response[k]
        for k in ("full_name", "number", "sha", "head_sha", "run_attempt", "id")
        if isinstance(response.get(k), (str, int)) and not isinstance(response.get(k), bool)
    }
    for field in ("base", "head"):
        nested = response.get(field)
        if isinstance(nested, dict) and isinstance(nested.get("sha"), str):
            identity[field + "_sha"] = nested["sha"]
    endpoint = re.match(
        r"^https://api[.]github[.]com/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/|$)",
        observation.get("url", ""),
    )
    if endpoint:
        identity["repository"] = endpoint[1]
    annotations = {}
    for field in ("findings", "uncertainties"):
        values = observation.get(field, [])
        require(isinstance(values, list), "summary annotations must be scalar text lists")
        # Never copy nested tool responses or logs. Longer details belong in
        # the integrity-bound original; the entire transport view is bounded.
        annotations[field] = [
            ops.text(value, "summary text or evidence reference") for value in values
        ]
    result = {
        "schema": "agent-evidence-summary/v1",
        "evidence": deepcopy(reference),
        "status": status,
        "freshness": freshness,
        "observed_at": stamp,
        "complete": observation.get("complete") is True,
        "identity": identity,
        "state": {
            k: response[k]
            for k in ("state", "draft", "merged", "status", "conclusion")
            if k in response
        },
        "findings": annotations["findings"],
        "reused": observation.get("reused") is True,
        "uncertainties": annotations["uncertainties"],
        "qualification": "NOT_EVALUATED",
        "push_qualified": False,
    }
    require(
        len(ops.canonical(result)) <= 8192,
        "summary exceeds transport budget; reference the complete original evidence",
    )
    return result


def reconcile_checkpoint(cache, pr, merge, followups, *, now=None):
    """Derive a view from real merged identity; never rewrite cache or old receipts."""
    # This read-only identity view also covers historical PRODUCT checkpoints.
    # It grants no qualification and does not demand Protocol-only PR body fields
    # or replay an entire product patch merely to establish an observed merge.
    require(isinstance(pr, dict) and pr.get("repository") in ops.PROFILES, "checkpoint repository")
    ops.number(pr.get("number"), "PR number")
    for key in ("base_sha", "head_sha", "tree_sha"):
        ops.sha(pr.get(key))
    ops.observation(pr, now)
    require(pr.get("state") == "CLOSED" and pr.get("draft") is False, "merged PR identity required")
    ops.validate_merge(merge, pr, now)
    require(isinstance(cache, dict) and isinstance(followups, list), "checkpoint inputs")
    open_items, resolved_items, seen = [], [], set()
    for item in followups:
        ops.obj(item, "id owner origin_head state evidence resolution", "follow-up")
        identity = ops.text(item["id"], "finding id")
        require(identity not in seen, "duplicate finding")
        seen.add(identity)
        require(item["origin_head"] == pr["head_sha"], "finding origin mismatch")
        ops.text(item["owner"], "follow-up owner")
        ops.text(item["evidence"], "finding evidence")
        require(item["state"] in {"OPEN", "RESOLVED"}, "unknown follow-up state")
        if item["state"] == "OPEN":
            require(item["resolution"] is None, "open finding claims resolution")
            open_items.append(deepcopy(item))
        else:
            resolution = item["resolution"]
            ops.obj(resolution, "operation thread_ref thread_resolved", "finding resolution")
            ops.validate_operations(resolution["operation"], now=now)
            require(
                resolution["operation"]["phase"] == "POST_MERGE"
                and resolution["thread_resolved"] is True,
                "unverified corrective integration",
            )
            ops.text(resolution["thread_ref"], "resolved thread")
            retained = resolution["operation"]["late_findings"]
            matched = [
                f
                for f in retained
                if (
                    f["id"] == identity
                    and f["thread_ref"] == resolution["thread_ref"]
                    and f["origin"]["pr"]["head_sha"] == pr["head_sha"]
                    and f["origin_pr"] == pr["number"]
                    and f["origin_merge_sha"] == merge["merge_sha"]
                )
            ]
            require(
                len(matched) == 1,
                "complete origin/correction/thread proof required",
            )
            correction = matched[0]["correction"]["merge"]["merge_sha"]
            chain = [c["sha"] for c in merge["ancestry"]]
            require(
                correction in chain and chain.index(correction) < chain.index(merge["merge_sha"]),
                "correction must follow origin in default ancestry",
            )
            resolved_items.append(
                {
                    "id": identity,
                    "owner": item["owner"],
                    "correction_merge_sha": correction,
                    "thread_ref": resolution["thread_ref"],
                    "resolution_sha256": digest(resolution),
                }
            )
    return {
        "schema": "agent-checkpoint-view/v1",
        "repository": pr["repository"],
        "pr": pr["number"],
        "head_sha": pr["head_sha"],
        "merge_sha": merge["merge_sha"],
        "state": "MERGED",
        "followups": open_items,
        "resolved_followups": resolved_items,
        "closure": "FOLLOW_UP_REQUIRED" if open_items else "QUALIFICATION_REQUIRED",
        "cache_sha256": digest(cache),
        "observed_merge_sha256": digest(merge),
        "cache_overridden": cache.get("state") != "MERGED",
        "cache_mutated": False,
        "receipts_rewritten": False,
        "push_qualified": False,
    }


def handoff(view, *, blocker, references, next_action):
    require(isinstance(view, dict) and isinstance(references, list), "handoff inputs")
    require(view.get("state") in {"OPEN", "MERGED", "BLOCKED", "RESUME_REQUIRED"}, "handoff state")
    for value in (blocker, next_action, *references):
        ops.text(value, "handoff text")
    return {
        "schema": "agent-handoff/v3",
        "state_sha256": digest(view),
        "text": (
            f"{view['repository']} #{view['pr']} · {view['state']}\n"
            f"Head: {view['head_sha']}\nBlocker: {blocker}\n"
            f"Evidence: {', '.join(references)}\nNext action: {next_action}"
        ),
        "state_mutated": False,
    }


def ci_plan(changed_paths, suites, *, complete, merge_equivalent=False):
    """Select from accepted exact dependency paths; uncertainty runs the full set."""
    require(
        type(complete) is bool and type(merge_equivalent) is bool,
        "CI completeness must be explicit",
    )
    require(isinstance(suites, dict) and bool(suites), "suite inventory required")
    for name, dependencies in suites.items():
        ops.text(name, "suite name")
        require(isinstance(dependencies, list) and bool(dependencies), "suite dependencies")
        for dependency in dependencies:
            ops.path(dependency)
    paths = ops.paths(changed_paths)
    known = set().union(*(set(dependencies) for dependencies in suites.values()))
    fallback = not complete or not paths or not set(paths) <= known
    selected = (
        sorted(suites)
        if fallback
        else sorted(name for name, dependencies in suites.items() if set(paths) & set(dependencies))
    )
    # Equivalence is reported only; this selector never certifies a reused run.
    return {
        "schema": "agent-ci-plan/v1",
        "suites": selected,
        "full_fallback": fallback,
        "merge_tests": "REQUIRED",
        "equivalence_supplied": merge_equivalent is True,
        "required_check_completion": "EXPLICIT_RESULT_REQUIRED",
        "push_qualified": False,
    }


def storage_summary(artifacts, *, complete):
    """Actual bytes only; no inferred account billing or automatic deletion."""
    require(type(complete) is bool, "artifact completeness must be an explicit boolean")
    require(isinstance(artifacts, list), "artifact inventory required")
    seen, total = set(), 0
    for row in artifacts:
        require(
            isinstance(row, dict)
            and type(row.get("id")) is int
            and row["id"] > 0
            and row["id"] not in seen
            and type(row.get("size_in_bytes")) is int
            and row["size_in_bytes"] >= 0
            and type(row.get("expired")) is bool,
            "incomplete or duplicate artifact identity",
        )
        seen.add(row["id"])
        if not row["expired"]:
            total += row["size_in_bytes"]
    return {
        "artifact_count": len(artifacts),
        "current_bytes": total,
        "inventory": "COMPLETE" if complete else "BOUNDED_SAMPLE",
        "account_billing": "NOT_OBSERVED",
        "deletion_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select-documents")
    select.add_argument("--root", type=Path, required=True)
    select.add_argument("--manifest", type=Path, required=True)
    select.add_argument("--manifest-sha256", required=True)
    select.add_argument("--workstream", required=True)
    select.add_argument("--phase", required=True)
    select.add_argument("--host", default="WORK")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        result = select_documents(
            args.root,
            manifest,
            args.manifest_sha256,
            workstream=args.workstream,
            phase=args.phase,
            host=args.host,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"result": "BLOCKED", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
