"""Synthetic operational observations; no private registry data or network access."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "protocol142_ops", ROOT / "tools/agent_protocol_v1_4_2_ops.py"
)
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)
PROTOCOL_SPEC = importlib.util.spec_from_file_location(
    "protocol142", ROOT / "tools/agent_protocol_v1_4_2.py"
)
assert PROTOCOL_SPEC and PROTOCOL_SPEC.loader
protocol = importlib.util.module_from_spec(PROTOCOL_SPEC)
PROTOCOL_SPEC.loader.exec_module(protocol)
REPO = "gabned/provelume"
BASE, HEAD, TREE, MERGE = (char * 40 for char in "abcd")
PROTOCOL_PATH = "tools/agent_protocol_v1_4_2.py"


@pytest.mark.parametrize("suffix", ["\nnotes.md", "\r\nnotes.md", "\tnotes.md", "notes.md\n"])
def test_operation_paths_preserve_git_whitespace_names(suffix):
    value = operations("gabned/provelume.com")
    name = "docs/agent-development-v1.4.2-" + suffix
    value["pr"]["changed_paths"] = [name]
    value["pr"]["file_patches"] = {name: "+Protocol documentation\n"}
    value["baseline_paths"] = [name]
    decoded = json.loads(ops.canonical(value))
    assert ops.validate_operations(decoded)["pr"]["changed_paths"] == [name]
    assert list(decoded["pr"]["file_patches"]) == [name]


@pytest.mark.parametrize("name", ["", "docs/\0name", "../docs/name", "docs/../name",
                                  "/docs/name", "C:/docs/name", "docs\\name", "docs//name"])
def test_git_path_transport_retains_safety_checks(name):
    with pytest.raises(ValueError):
        ops.paths([name])


@pytest.mark.parametrize("repository", list(ops.PROFILES))
@pytest.mark.parametrize("damage", ["missing", "different", "duplicate"])
def test_audit_requires_exact_campaign_on_every_integration(repository, damage):
    value = audit()
    row = next(row for row in value["repositories"] if row["repository"] == repository)
    pr_value = row["operations"][0]["pr"]
    marker = "CAMPAIGN_REF: " + value["campaign_ref"] + "\n"
    if damage == "missing":
        pr_value["body"] = pr_value["body"].replace(marker, "")
    elif damage == "different":
        pr_value["body"] = pr_value["body"].replace("/issues/200", "/issues/199")
    else:
        pr_value["body"] += marker
    with pytest.raises(ValueError, match="audited campaign"):
        ops.generate_audit(value)


@pytest.mark.parametrize("part", ["origin", "correction"])
@pytest.mark.parametrize("damage", ["missing", "different", "duplicate"])
def test_audit_binds_retained_late_finding_integrations(part, damage):
    value = audit()
    finding = resolved_finding()
    value["repositories"][0]["operations"][0]["late_findings"] = [finding]
    receipt = ops.generate_audit(value)
    pr_value = finding[part]["pr"]
    marker = "CAMPAIGN_REF: " + value["campaign_ref"] + "\n"
    if damage == "missing":
        pr_value["body"] = pr_value["body"].replace(marker, "")
    elif damage == "different":
        pr_value["body"] = pr_value["body"].replace("/issues/200", "/issues/199")
    else:
        pr_value["body"] += marker
    with pytest.raises(ValueError, match="audited campaign"):
        ops.generate_audit(value)

    receipt["evidence"] = value
    receipt["evidence_sha256"] = ops.digest(value)
    with pytest.raises(ValueError, match="audited campaign"):
        ops.validate_audit(receipt)


def test_native_brick_lifecycle_validator_is_a_protocol_surface():
    value = pr("brickms/brickms")
    native = "scripts/agent/protocol-v1-2.py"
    value["changed_paths"] = [native]
    value["file_patches"] = {native: "+exact Protocol metadata paths\n"}
    ops.validate_scope(None, value, [native])
    other = "scripts/agent/protocol-v1-2-product.py"
    value["changed_paths"] = [other]
    value["file_patches"] = {other: "+unrelated path\n"}
    with pytest.raises(ValueError, match="non-Protocol surface"):
        ops.validate_scope(None, value, [other])


@pytest.mark.parametrize("repository", [REPO, "maxithlon/maxithlon", "gabned/provelume.com"])
def test_brick_native_surface_does_not_expand_other_repository_scopes(repository):
    value = pr(repository)
    native = "scripts/agent/protocol-v1-2.py"
    value["changed_paths"] = [native]
    value["file_patches"] = {native: "+unrelated repository file\n"}
    with pytest.raises(ValueError, match="non-Protocol surface"):
        ops.validate_scope(None, value, [native])


def test_review_trigger_retains_independent_ci_identity():
    value = ci()
    review = deepcopy(value["runs"][0])
    review.update(run_id=101, event="pull_request_review")
    value["runs"].append(review)
    value["required_workflows"].append("ci.yml@pull_request_review")
    ops.validate_ci(value, REPO, HEAD)
    review["attempts"][-1]["conclusion"] = "FAILURE"
    review["attempts"][-1]["jobs"][0]["conclusion"] = "FAILURE"
    with pytest.raises(ValueError, match="not successful"):
        ops.validate_ci(value, REPO, HEAD)


def observed():
    return {"source": "GITHUB_CONNECTOR",
            "observed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}


def pr(repository=REPO):
    return ops.render_pr_identity({
        "repository": repository, "number": 12, "base_sha": BASE, "head_sha": HEAD,
        "tree_sha": TREE, "body": "WORKSTREAM_CLASS: PROTOCOL\n"
                                 "CAMPAIGN_REF: https://github.com/gabned/provelume/issues/200\n",
        "state": "OPEN", "draft": False, "mergeable": True,
        "changed_paths": [PROTOCOL_PATH], "paths_complete": True,
        "file_patches": {PROTOCOL_PATH: "@@ -1 +1 @@\n-old\n+new\n"}, **observed(),
    })


def attempt(index=1, conclusion="SUCCESS"):
    status = "IN_PROGRESS" if conclusion == "NONE" else "COMPLETED"
    return {"run_attempt": index, "status": status, "conclusion": conclusion,
            "jobs_complete": True, "jobs": [
                {"id": index, "name": "tests", "status": status, "conclusion": conclusion}]}


def ci(repository=REPO, head=HEAD):
    return {"repository": repository, "head_sha": head, **observed(),
            "applicability": "REQUIRED", "policy_ref": BASE if head == HEAD else head,
            "runs_complete": True,
            "required_workflows": ["ci.yml@pull_request"], "runs": [
                {"run_id": 100, "workflow": "ci.yml", "event": "pull_request", "head_sha": head,
                 "latest_attempt": 1, "attempts": [attempt()]}]}


def operations(repository=REPO):
    p = pr(repository)
    p["state"] = "CLOSED"
    if repository == "gabned/nexus":
        p["changed_paths"] = ["docs/protocol-registry.md"]
        p["file_patches"] = {"docs/protocol-registry.md": "+Protocol registry\n"}
    commit = {"sha": MERGE, "tree_sha": TREE, "parents": [BASE]}
    return {"protocol_version": "1.4.2", "phase": "POST_MERGE", "pr": p,
            "default_branch": {"repository": repository, "name": ops.PROFILES[repository][0],
                               "sha": MERGE, **observed()},
            "baseline_paths": p["changed_paths"].copy(), "scope_exception": None,
            "ci": ci(repository), "reviews": {
                "repository": repository, "pr": 12, "head_sha": HEAD,
                "requirement": "NONE", "state": "NOT_APPLICABLE",
                "unresolved_threads": [], "current_findings": [], "complete": True, **observed()},
            "merge": {"merged": True, "state": "CLOSED", "merge_sha": MERGE,
                      "method": "SQUASH", "commit": commit, "default_sha": MERGE,
                      "ancestry": [deepcopy(commit)], **observed()},
            "post_merge_ci": ci(repository, MERGE), "late_findings": [],
            "late_findings_complete": True,
            "effect_policy": "NO_PRODUCTION"}


def audit():
    files = [{"path": name, "mode": mode, "commit_sha": MERGE,
              "git_blob": ops.blob(name.encode()), "content": name}
             for name, mode in ops.VENDOR_FILES.items()]
    canonical = {"protocol_version": "1.4.2", "source_repository": REPO,
                 "source_commit": MERGE, "files": [
                     {"path": f["path"], "mode": f["mode"], "git_blob": f["git_blob"],
                      "sha256": hashlib.sha256(f["content"].encode()).hexdigest()}
                     for f in files]}
    ref = "https://github.com/gabned/provelume/issues/200"
    registry_content = f"Protocol 1.4.2\nCanonical {MERGE}\nCampaign {ref}\n"
    registry_content += "\n".join(f"https://github.com/{repo}/pull/12 {MERGE}"
                                  for repo in ops.PROFILES if repo != "gabned/nexus")
    rows = []
    for repo, (branch, profile) in ops.PROFILES.items():
        registry = repo == "gabned/nexus"
        rows.append({"repository": repo, "default_branch": branch, "profile": profile,
                     "default_sha": MERGE, "operations": [operations(repo)],
                     "vendor_manifest": None if registry else deepcopy(canonical),
                     "vendor_files": [] if registry else deepcopy(files),
                     "provenance_files": [] if registry or repo == REPO else [
                         {"path": path, "mode": "100644", "commit_sha": MERGE,
                          "content": content.decode(), "git_blob": ops.blob(content)}
                         for path, content in ops.provenance_files(canonical).items()],
                     "registry": {"path": "docs/protocol-registry.md", "commit_sha": MERGE,
                                  "content": registry_content,
                                  "git_blob": ops.blob(registry_content.encode())}
                     if registry else None,
                     "open_campaign_prs": [], "unresolved_threads": []})
    return {"protocol_version": "1.4.2", "campaign_ref": ref, "canonical": canonical,
            **observed(), "repositories": rows}


def test_complete_audit_and_cli_receipt_roundtrip(tmp_path):
    source = tmp_path / "audit.json"
    source.write_text(json.dumps(audit()), encoding="utf-8")
    receipt = ops.command(SimpleNamespace(command="generate-audit", path=source))
    source.write_text(json.dumps(receipt), encoding="utf-8")
    assert ops.command(SimpleNamespace(command="validate-audit", path=source)) == receipt


@pytest.mark.parametrize("conclusion", ["NONE", "FAILURE", "CANCELLED", "TIMED_OUT"])
def test_new_attempt_invalidates_old_green(conclusion):
    value = ci()
    value["runs"][0].update(latest_attempt=2, attempts=[attempt(), attempt(2, conclusion)])
    with pytest.raises(ValueError, match="latest applicable"):
        ops.validate_ci(value, REPO, HEAD)


def test_failed_history_can_be_retained_when_new_attempt_succeeds():
    before = ci()
    before["runs"][0]["attempts"] = [attempt(conclusion="FAILURE")]
    after = deepcopy(before)
    after["runs"][0]["attempts"].append(attempt(2))
    after["runs"][0]["latest_attempt"] = 2
    ops.validate_ci(after, REPO, HEAD)
    ops.validate_ci_append_only(before, after)
    after["runs"][0]["attempts"][0] = attempt()
    with pytest.raises(ValueError, match="terminal attempt rewritten"):
        ops.validate_ci_append_only(before, after)


def test_ci_history_retains_old_observations_without_treating_them_as_current():
    before = ci()
    before["observed_at"] = "2020-01-01T00:00:00Z"
    after = ci()
    ops.validate_ci_append_only(before, after)
    with pytest.raises(ValueError, match="stale"):
        ops.validate_ci(before, REPO, HEAD)


def test_completed_job_cannot_be_rewritten_inside_a_live_attempt():
    before = ci()
    before["runs"][0]["attempts"][0].update(status="IN_PROGRESS", conclusion="NONE")
    after = deepcopy(before)
    after["runs"][0]["attempts"][0]["jobs"][0]["conclusion"] = "FAILURE"
    with pytest.raises(ValueError, match="terminal job rewritten"):
        ops.validate_ci_append_only(before, after)


def test_new_run_invalidates_old_green():
    value = ci()
    newer = deepcopy(value["runs"][0])
    newer.update(run_id=101, attempts=[attempt(conclusion="NONE")])
    value["runs"].append(newer)
    with pytest.raises(ValueError, match="latest applicable"):
        ops.validate_ci(value, REPO, HEAD)


def test_trusted_base_success_cannot_hide_same_workflow_candidate_failure():
    value = ci()
    value["runs"][0]["attempts"] = [attempt(conclusion="FAILURE")]
    trusted = deepcopy(value["runs"][0])
    trusted.update(run_id=101, event="pull_request_target", attempts=[attempt()])
    value["runs"].append(trusted)
    value["required_workflows"].append("ci.yml@pull_request_target")
    with pytest.raises(ValueError, match="latest applicable"):
        ops.validate_ci(value, REPO, HEAD)
    value["runs"][0]["attempts"] = [attempt()]
    ops.validate_ci(value, REPO, HEAD)


@pytest.mark.parametrize("damage", ["pagination", "attempt_gap", "partial_jobs", "wrong_head"])
def test_partial_ci_evidence_rejected(damage):
    value = ci()
    if damage == "pagination":
        value["runs_complete"] = False
    elif damage == "attempt_gap":
        value["runs"][0]["latest_attempt"] = 2
    elif damage == "partial_jobs":
        value["runs"][0]["attempts"][0]["jobs_complete"] = False
    else:
        value["runs"][0]["head_sha"] = BASE
    with pytest.raises(ValueError):
        ops.validate_ci(value, REPO, HEAD)


def test_expired_wait_keeps_same_handle_and_never_transitions():
    now = datetime.now(UTC).replace(microsecond=0)
    value = {"repository": REPO, "run_id": 100, "run_attempt": 2, "head_sha": HEAD,
             "status": "IN_PROGRESS", "conclusion": "NONE", **observed(),
             "deadline": (now + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "handle": f"https://api.github.com/repos/{REPO}/actions/runs/100/attempts/2"}
    result = ops.validate_wait(value, now + timedelta(seconds=6))
    assert result["next_action"] == "REOBSERVE_SAME_HANDLE"
    assert result["handle"] == value["handle"]
    assert not result["campaign_transition"] and not result["automatic_retry"]
    value["handle"] = value["handle"].replace("attempts/2", "attempts/1")
    with pytest.raises(ValueError, match="handle"):
        ops.validate_wait(value, now)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "stale", "wrong_tree"])
def test_pr_identity_rejects_invalid_declarations_and_renderer_repairs(damage):
    value = pr()
    if damage == "missing":
        value["body"] = value["body"].replace(f"HEAD_SHA: {HEAD}\n", "")
    elif damage == "duplicate":
        value["body"] += f"HEAD_SHA: {HEAD}\n"
    elif damage == "stale":
        value["body"] = value["body"].replace(HEAD, BASE)
    else:
        value["body"] = value["body"].replace(TREE, BASE)
    with pytest.raises(ValueError, match="declaration"):
        ops.validate_pr(value)
    fixed = ops.render_pr_identity(value)
    assert ops.render_pr_identity(fixed) == fixed


def test_github_managed_dynamic_ci_retains_attempts_and_supersession():
    value = ci()
    managed = deepcopy(value["runs"][0])
    managed.update(run_id=101, workflow="dynamic/github-code-quality/codeql", event="dynamic")
    value["runs"].append(managed)
    value["required_workflows"].append(managed["workflow"] + "@dynamic")
    ops.validate_ci(value, REPO, HEAD)
    prior = deepcopy(value)
    managed.update(latest_attempt=2, attempts=[attempt(), attempt(2, "FAILURE")])
    with pytest.raises(ValueError, match="latest applicable"):
        ops.validate_ci(value, REPO, HEAD)
    ops.validate_ci_append_only(prior, value)
    managed["attempts"][0]["jobs"][0]["name"] = "rewritten"
    with pytest.raises(ValueError, match="terminal attempt rewritten"):
        ops.validate_ci_append_only(prior, value)
    newer = deepcopy(prior["runs"][-1])
    newer.update(run_id=102, attempts=[attempt(1, "NONE")])
    prior["runs"].append(newer)
    with pytest.raises(ValueError, match="latest applicable"):
        ops.validate_ci(prior, REPO, HEAD)


@pytest.mark.parametrize("workflow,event", [
    ("ci.yml", "dynamic"),
    ("dynamic/github-code-quality/codeql", "pull_request"),
    ("dynamic/../ci.yml", "dynamic"),
])
def test_dynamic_trigger_cannot_relabel_repository_workflows(workflow, event):
    value = ci()
    value["runs"][0].update(workflow=workflow, event=event)
    value["required_workflows"] = [workflow + "@" + event]
    with pytest.raises(ValueError, match="dynamic trigger|unsafe path"):
        ops.validate_ci(value, REPO, HEAD)


@pytest.mark.parametrize("continuation", [False, True, "version-prefix"])
def test_scope_authorization_binds_actual_patch_and_head(continuation):
    value = operations("brickms/brickms")
    p = value["pr"]
    p["changed_paths"].insert(0, "CHANGELOG.md")
    patch = ("diff --git a/CHANGELOG.md b/CHANGELOG.md\n--- a/CHANGELOG.md\n"
             "+++ b/CHANGELOG.md\n@@ -1,0 +2 @@\n+" "- Protocol 1.4.2 canonical sync.\n")
    if continuation:
        patch = ("diff --git a/CHANGELOG.md b/CHANGELOG.md\n--- a/CHANGELOG.md\n"
                 "+++ b/CHANGELOG.md\n@@ -2 +2,2 @@\n - Protocol 1.4.2 canonical sync.\n"
                 "+  Agent Development Protocol v1.3.0 / Protocol v1.4.2: correction.\n")
    if continuation == "version-prefix":
        patch = patch.replace(" - Protocol 1.4.2", " - 0.309 Agent Development Protocol v1.3.0 "
                              "governance adopts canonical Protocol v1.4.2")
    p["file_patches"]["CHANGELOG.md"] = patch
    approval = {"repository": p["repository"], "pr": 12, "base_sha": BASE, "head_sha": HEAD,
                "paths_sha256": ops.digest(p["changed_paths"]), "patch": patch,
                "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                "actor": "example-maintainer", "actor_role": "VERIFIED_HUMAN_MAINTAINER",
                "authorization_source": "GITHUB_COMMENT",
                "authorization_text": "Approve the single technical Protocol changelog line.",
                "authorization_ref": "https://github.com/brickms/brickms/pull/12#issuecomment-1",
                "decision": "APPROVED", **observed()}
    ops.validate_scope(approval, p, value["baseline_paths"])
    session_approval = {**approval, "authorization_source": "USER_INSTRUCTION",
                        "authorization_ref":
                            "codex-goal:11111111-2222-3333-4444-555555555555:1788613263"}
    ops.validate_scope(session_approval, p, value["baseline_paths"])
    if continuation:
        for context in (" - Product release 2.0", " - Protocol 1.4.1 old entry", " "):
            old_line = next(line for line in patch.splitlines() if line.startswith(" - "))
            bad_patch = patch.replace(old_line, context)
            p["file_patches"]["CHANGELOG.md"] = bad_patch
            bad_approval = {**approval, "patch": bad_patch,
                            "patch_sha256": hashlib.sha256(bad_patch.encode()).hexdigest()}
            with pytest.raises(ValueError, match="continuation must follow"):
                ops.validate_scope(bad_approval, p, value["baseline_paths"])
        p["file_patches"]["CHANGELOG.md"] = patch
    deleted_patch = patch + "-- Protocol 1.4.2 old text\n"
    p["file_patches"]["CHANGELOG.md"] = deleted_patch
    with pytest.raises(ValueError, match="append exactly one"):
        ops.validate_scope({**approval, "patch": deleted_patch,
                            "patch_sha256": hashlib.sha256(deleted_patch.encode()).hexdigest()},
                           p, value["baseline_paths"])
    p["file_patches"]["CHANGELOG.md"] = patch
    p["file_patches"]["CHANGELOG.md"] += "+unapproved text\n"
    with pytest.raises(ValueError, match="observed exact-head patch"):
        ops.validate_scope(approval, p, value["baseline_paths"])
    p["file_patches"]["CHANGELOG.md"] = patch
    approval["head_sha"] = BASE
    with pytest.raises(ValueError, match="exact PR"):
        ops.validate_scope(approval, p, value["baseline_paths"])


def test_baseline_cannot_smuggle_product_paths_or_changelog():
    for name in ("core/provelume/app.py", "CHANGELOG.md", "AGENT_STATUS.md", "app/VERSION"):
        p = pr()
        p["changed_paths"] = [name]
        with pytest.raises(ValueError, match="non-Protocol"):
            ops.validate_scope(None, p, [name])


@pytest.mark.parametrize("damage", ["provisional", "tree", "parents", "ancestry"])
def test_merge_requires_actual_accepted_commit(damage):
    value = operations()
    merge = value["merge"]
    if damage == "provisional":
        merge["merged"] = False
    elif damage == "tree":
        merge["commit"]["tree_sha"] = BASE
    elif damage == "parents":
        merge["commit"]["parents"] = [HEAD]
    else:
        merge["ancestry"] = []
    with pytest.raises(ValueError):
        ops.validate_operations(value)


def test_post_merge_ci_policy_binds_the_audited_default():
    value = operations()
    ops.validate_operations(value)
    value["post_merge_ci"]["policy_ref"] = BASE
    with pytest.raises(ValueError, match="policy is not bound to the audited default"):
        ops.validate_operations(value)
    receipt_input = audit()
    receipt_input["repositories"][0]["operations"][0]["post_merge_ci"]["policy_ref"] = BASE
    with pytest.raises(ValueError, match="policy is not bound to the audited default"):
        ops.generate_audit(receipt_input)


@pytest.mark.parametrize("damage", ["missing_repo", "duplicate_repo", "source", "vendor_commit",
                                    "vendor_bytes", "open_pr", "finding", "stale"])
def test_audit_fails_closed_on_incomplete_or_conflicting_evidence(damage):
    value = audit()
    row = value["repositories"][0]
    if damage == "missing_repo":
        value["repositories"].pop()
    elif damage == "duplicate_repo":
        value["repositories"][-1] = deepcopy(row)
    elif damage == "source":
        value["canonical"]["source_commit"] = BASE
        for item in value["repositories"][:-1]:
            item["vendor_manifest"]["source_commit"] = BASE
    elif damage == "vendor_commit":
        row["vendor_files"][0]["commit_sha"] = BASE
    elif damage == "vendor_bytes":
        row["vendor_files"][0]["content"] += "corrupt"
    elif damage == "open_pr":
        row["open_campaign_prs"] = [13]
    elif damage == "finding":
        row["operations"][0]["reviews"]["current_findings"] = ["unresolved"]
    else:
        value["observed_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        ops.generate_audit(value)


@pytest.mark.parametrize("damage", ["missing", "bytes", "commit", "blob", "mode"])
def test_audit_requires_committed_canonical_documentation(damage):
    value = audit()
    row = value["repositories"][1]
    if damage == "missing":
        row["provenance_files"].pop()
    elif damage == "bytes":
        row["provenance_files"][0]["content"] += "changed"
    elif damage == "commit":
        row["provenance_files"][0]["commit_sha"] = BASE
    elif damage == "blob":
        row["provenance_files"][0]["git_blob"] = BASE
    else:
        row["provenance_files"][0]["mode"] = "100755"
    with pytest.raises(ValueError):
        ops.generate_audit(value)


@pytest.mark.parametrize("damage", ["path", "integration"])
def test_registry_must_describe_the_audited_integrations(damage):
    value = audit()
    registry = value["repositories"][-1]["registry"]
    if damage == "path":
        registry["path"] = "docs/unrelated.md"
    else:
        registry["content"] = registry["content"].replace(
            "https://github.com/brickms/brickms/pull/12", "omitted")
        registry["git_blob"] = ops.blob(registry["content"].encode())
    with pytest.raises(ValueError):
        ops.generate_audit(value)


def canonical_checkout(source):
    source.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args],
                                       stderr=subprocess.DEVNULL).decode().strip()
    git("init")
    git("config", "core.autocrlf", "false")
    git("remote", "add", "origin", "https://github.com/gabned/provelume.git")
    for name, mode in ops.VENDOR_FILES.items():
        f = source / name
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(name.encode())
        git("add", "--", name)
        git("update-index", "--chmod=" + ("+x" if mode == "100755" else "-x"), "--", name)
        if os.name != "nt":
            f.chmod(int(mode[-3:], 8))
    git("-c", "user.name=Protocol test", "-c", "user.email=protocol@example.invalid",
        "commit", "-m", "Synthetic canonical fixture")
    return git("rev-parse", "HEAD"), git


def test_synchronizer_is_deterministic_and_check_mode_never_writes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    commit, _ = canonical_checkout(source)
    target.mkdir()
    untouched = target / "VERSION"
    untouched.write_bytes(b"product-version\n")
    with pytest.raises(ValueError, match="drift"):
        ops.sync_vendor(source, target, commit, check=True)
    assert list(target.iterdir()) == [untouched]
    ops.sync_vendor(source, target, commit)
    assert ops.sync_vendor(source, target, commit, check=True)["changed_paths"] == []
    assert ops.sync_vendor(source, target, commit)["changed_paths"] == []
    assert untouched.read_bytes() == b"product-version\n"
    (target / PROTOCOL_PATH).write_bytes(b"drift")
    with pytest.raises(ValueError, match="drift"):
        ops.sync_vendor(source, target, commit, check=True)
    assert (target / PROTOCOL_PATH).read_bytes() == b"drift"


@pytest.mark.parametrize("damage", ["dirty", "wrong_commit", "wrong_repository", "hidden_drift"])
def test_synchronizer_rejects_unbound_source_before_writing(tmp_path, damage):
    source, target = tmp_path / "source", tmp_path / "target"
    commit, git = canonical_checkout(source)
    target.mkdir()
    if damage == "wrong_commit":
        commit = BASE
    elif damage == "wrong_repository":
        git("remote", "set-url", "origin", "https://github.com/example/unrelated.git")
    else:
        if damage == "hidden_drift":
            git("update-index", "--assume-unchanged", "--", PROTOCOL_PATH)
        (source / PROTOCOL_PATH).write_bytes(b"uncommitted bytes")
    with pytest.raises(ValueError, match="source|canonical"):
        ops.sync_vendor(source, target, commit)
    assert list(target.iterdir()) == []


def test_missing_promisor_blob_never_starts_a_fetch(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    commit, git = canonical_checkout(source)
    target.mkdir()
    oid = git("rev-parse", "HEAD:" + PROTOCOL_PATH)
    git("config", "remote.origin.promisor", "true")
    git("config", "remote.origin.partialclonefilter", "blob:none")
    missing = source / ".git" / "objects" / oid[:2] / oid[2:]
    assert missing.is_relative_to(source)
    missing.chmod(stat.S_IREAD | stat.S_IWRITE)
    missing.unlink()
    trace = tmp_path / "git-trace.log"
    monkeypatch.setenv("GIT_TRACE", trace.as_posix())
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "https:file")
    with pytest.raises(ValueError, match="Git source verification failed"):
        ops.sync_vendor(source, target, commit)
    text = trace.read_text(encoding="utf-8")
    assert " fetch " not in text
    assert "git-upload-pack" not in text and "remote-https" not in text
    assert list(target.iterdir()) == []


def test_audit_generation_and_replay_share_the_observation_anchor():
    value = audit()
    value["observed_at"] = (datetime.now(UTC) - timedelta(minutes=10)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(ValueError, match="stale"):
        ops.generate_audit(value)
    value["observed_at"] = observed()["observed_at"]
    receipt = ops.generate_audit(value)
    assert ops.validate_audit(receipt) == receipt


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable modes; Git modes checked on Windows")
def test_synchronizer_applies_and_repairs_executable_modes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    commit, _ = canonical_checkout(source)
    target.mkdir()
    ops.sync_vendor(source, target, commit)
    for name, mode in ops.VENDOR_FILES.items():
        assert bool((target / name).stat().st_mode & stat.S_IXUSR) == (mode == "100755")
    executable = target / PROTOCOL_PATH
    executable.chmod(0o644)
    with pytest.raises(ValueError, match="drift"):
        ops.sync_vendor(source, target, commit, check=True)
    assert stat.S_IMODE(executable.stat().st_mode) == 0o644
    assert PROTOCOL_PATH in ops.sync_vendor(source, target, commit)["changed_paths"]
    assert stat.S_IMODE(executable.stat().st_mode) == 0o744


@pytest.mark.skipif(os.name == "nt", reason="POSIX checkout permissions")
def test_synchronizer_preserves_restrictive_permissions(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    commit, _ = canonical_checkout(source)
    target.mkdir()
    previous_umask = os.umask(0o077)
    try:
        ops.sync_vendor(source, target, commit)
    finally:
        os.umask(previous_umask)
    names = [*ops.VENDOR_FILES, ops.MANIFEST_PATH, ops.PROVENANCE_PATH]
    modes = {name: 0o700 if ops.VENDOR_FILES.get(name) == "100755" else 0o600
             for name in names}
    for name, mode in modes.items():
        assert stat.S_IMODE((target / name).stat().st_mode) == mode
    assert ops.sync_vendor(source, target, commit, check=True)["changed_paths"] == []
    assert ops.sync_vendor(source, target, commit)["changed_paths"] == []
    for name in names:
        (target / name).write_bytes(b"stale")
    ops.sync_vendor(source, target, commit)
    for name, mode in modes.items():
        assert stat.S_IMODE((target / name).stat().st_mode) == mode


def test_archived_closure_preserves_integrity_without_live_freshness():
    value = audit()
    old = "2025-01-01T00:00:00Z"
    def archive(obj):
        if isinstance(obj, dict):
            if "observed_at" in obj:
                obj["observed_at"] = old
            for item in obj.values():
                archive(item)
        elif isinstance(obj, list):
            for item in obj:
                archive(item)
    archive(value)
    receipt = {"protocol_version": "1.4.2", "result": "PASS", "evidence": value,
               "evidence_sha256": ops.digest(value)}
    assert ops.validate_audit(receipt) == receipt
    with pytest.raises(ValueError, match="stale"):
        ops.generate_audit(value)
    receipt["evidence"]["repositories"][0]["operations"][0]["ci"]["observed_at"] = \
        "2025-01-02T00:00:00Z"
    with pytest.raises(ValueError, match="rewritten"):
        ops.validate_audit(receipt)
    receipt["evidence_sha256"] = ops.digest(receipt["evidence"])
    with pytest.raises(ValueError, match="stale"):
        ops.validate_audit(receipt)


@pytest.mark.parametrize("observation_delay", [0, 90])
def test_gate_transition_requires_persisted_attempt_bound_operational_evidence(observation_delay):
    legacy = protocol.sample_campaign_v1()
    legacy.update(workstream_class="PROTOCOL", risk_profile="NO_PRODUCTION",
                  observed_event="GATES_PASSED", observed_event_ref=HEAD)
    legacy["slices"][1].update(state="ACTIVE", pr="#12", head_sha=HEAD, merge_sha="NONE")
    legacy["pending_action"] = {"kind": "MERGE_ACTIVE_SLICE", "slice_id": "pilot/S02"}
    before = protocol.migrate_campaign(legacy)
    after = deepcopy(before)
    after["campaign_state"] = "ACTIVE"
    after["pending_action"] = {"kind": "MERGE_ACTIVE_SLICE", "slice_id": "pilot/S02"}
    after["next_action"] = {"type": "AUTO_CONTINUE", "summary": "Merge pilot/S02 at exact head.",
                            "prompt": "NONE"}
    event = {"kind": "WORKFLOW_RUN", "action": "COMPLETED", "repository": REPO,
             "reference": "run:100", "sha": HEAD, "conclusion": "SUCCESS", "run_attempt": 1}
    with pytest.raises(ValueError, match="require operational evidence"):
        protocol.append_transition_receipt(before, after, event)
    evidence = operations()
    evidence.update(phase="PRE_MERGE", merge=None, post_merge_ci=None)
    evidence["default_branch"]["sha"] = BASE
    evidence["pr"]["state"] = "OPEN"
    evidence["pr"]["observed_at"] = (datetime.now(UTC) - timedelta(
        seconds=observation_delay)).strftime("%Y-%m-%dT%H:%M:%SZ")
    newer = deepcopy(evidence["ci"]["runs"][0])
    newer["run_id"] = 101
    evidence["ci"]["runs"].append(newer)
    with pytest.raises(ValueError, match="superseded workflow"):
        protocol.append_transition_receipt(before, after, event, operational_evidence=evidence)
    evidence["ci"]["runs"].pop()
    legacy_evidence = deepcopy(evidence)
    del legacy_evidence["default_branch"]
    with pytest.raises(ValueError, match="missing or extra fields"):
        protocol.append_transition_receipt(before, after, event,
                                           operational_evidence=legacy_evidence)
    result = protocol.append_transition_receipt(before, after, event,
                                                operational_evidence=evidence)
    assert result["receipts"][-1]["operational_evidence"] == evidence
    protocol.validate_campaign_v2(result)
    moved = deepcopy(result)
    moved["receipts"][-1]["operational_evidence"]["default_branch"]["sha"] = MERGE
    moved["receipts"][-1]["receipt_sha256"] = protocol.receipt_sha256(moved["receipts"][-1])
    with pytest.raises(ValueError, match="accepted base differs"):
        protocol.validate_campaign_v2(moved)
    # Recomputing the enclosing digest cannot turn missing evidence into proof.
    too_old = deepcopy(evidence)
    too_old["pr"]["observed_at"] = (datetime.now(UTC) - timedelta(
        minutes=16)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(ValueError, match="stale"):
        protocol.append_transition_receipt(before, after, event, operational_evidence=too_old)
    result["receipts"][-1]["operational_evidence"] = None
    result["receipts"][-1]["receipt_sha256"] = protocol.receipt_sha256(result["receipts"][-1])
    with pytest.raises(ValueError, match="require operational evidence"):
        protocol.validate_campaign_v2(result)


@pytest.mark.parametrize("state,draft,mergeable", [
    ("CLOSED", False, True), ("OPEN", True, True),
    ("OPEN", False, False), ("OPEN", False, None),
])
def test_pre_merge_requires_observed_ready_mergeable_pr(state, draft, mergeable):
    value = operations()
    value.update(phase="PRE_MERGE", merge=None, post_merge_ci=None)
    value["default_branch"]["sha"] = BASE
    value["pr"].update(state="OPEN", draft=False, mergeable=True)
    ops.validate_operations(value)
    value["pr"].update(state=state, draft=draft, mergeable=mergeable)
    with pytest.raises(ValueError, match="open, ready and mergeable"):
        ops.validate_operations(value)


@pytest.mark.parametrize("damage", ["missing", "moved", "repository", "name", "stale", "source"])
def test_pre_merge_requires_independent_current_default_observation(damage):
    value = operations()
    value.update(phase="PRE_MERGE", merge=None, post_merge_ci=None)
    value["pr"]["state"] = "OPEN"
    value["default_branch"]["sha"] = BASE
    ops.validate_operations(value)
    default = value["default_branch"]
    if damage == "missing":
        del value["default_branch"]
    elif damage == "moved":
        default["sha"] = MERGE
    elif damage == "repository":
        default["repository"] = "gabned/provelume.com"
    elif damage == "name":
        default["name"] = "unrelated-branch"
    elif damage == "stale":
        default["observed_at"] = (datetime.now(UTC) - timedelta(minutes=16)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    else:
        default["source"] = "UNVERIFIED"
    with pytest.raises(ValueError):
        ops.validate_operations(value)


def test_post_merge_default_observation_binds_the_reconciled_ancestry():
    value = operations()
    value["default_branch"]["sha"] = BASE
    with pytest.raises(ValueError, match="reconciliation differs"):
        ops.validate_operations(value)


@pytest.mark.parametrize("conclusion", ["FAILURE", "CANCELLED", "TIMED_OUT"])
@pytest.mark.parametrize("status", ["QUEUED", "IN_PROGRESS"])
def test_terminal_attempt_cannot_freeze_live_jobs(conclusion, status):
    value = ci()
    first = attempt(1, conclusion)
    value["runs"][0].update(latest_attempt=2, attempts=[first, attempt(2)])
    ops.validate_ci(value, REPO, HEAD)
    first["jobs"][0].update(status=status, conclusion="NONE")
    with pytest.raises(ValueError, match="terminal attempt contains a live job"):
        ops.validate_ci(value, REPO, HEAD)


@pytest.mark.parametrize("damage", ["drop_run", "rewrite_job"])
@pytest.mark.parametrize("legacy_history", [False, True])
def test_receipt_chain_retains_ci_history_even_after_resealing(
    damage, legacy_history, tmp_path, monkeypatch,
):
    legacy = protocol.sample_campaign_v1()
    legacy.update(workstream_class="PROTOCOL", risk_profile="NO_PRODUCTION",
                  observed_event="GATES_PASSED", observed_event_ref=HEAD)
    legacy["slices"][1].update(state="ACTIVE", pr="#12", head_sha=HEAD, merge_sha="NONE")
    legacy["pending_action"] = {"kind": "MERGE_ACTIVE_SLICE", "slice_id": "pilot/S02"}
    before = protocol.migrate_campaign(legacy)
    gates = deepcopy(before)
    gates.update(campaign_state="ACTIVE",
                 pending_action={"kind": "MERGE_ACTIVE_SLICE", "slice_id": "pilot/S02"},
                 next_action={"type": "AUTO_CONTINUE", "summary": "Merge pilot/S02.",
                              "prompt": "NONE"})
    evidence = operations()
    evidence.update(phase="PRE_MERGE", merge=None, post_merge_ci=None)
    evidence["default_branch"]["sha"] = BASE
    evidence["pr"]["state"] = "OPEN"
    older = deepcopy(evidence["ci"]["runs"][0])
    older["run_id"] = 99
    evidence["ci"]["runs"].insert(0, older)
    event = {"kind": "WORKFLOW_RUN", "action": "COMPLETED", "repository": REPO,
             "reference": "run:100", "sha": HEAD, "conclusion": "SUCCESS", "run_attempt": 1}
    gates = protocol.append_transition_receipt(before, gates, event,
                                               operational_evidence=evidence)
    if legacy_history:
        # Synthetic immutable receipt in the pre-default-observation 1.4.2 shape.
        del gates["receipts"][-1]["operational_evidence"]["default_branch"]
        gates["receipts"][-1]["receipt_sha256"] = protocol.receipt_sha256(gates["receipts"][-1])
    trusted_history = [gates["receipts"][-1]["receipt_sha256"]] if legacy_history else []
    with protocol.trusted_legacy_receipts(trusted_history):
        protocol.validate_campaign_v2(gates)
    if legacy_history:
        with pytest.raises(ValueError, match="missing or extra fields"):
            protocol.validate_campaign_v2(gates)
        snapshot = tmp_path / "verified-pre-upgrade.json"
        policy = tmp_path / "trusted-policy.json"
        snapshot.write_bytes(ops.canonical(gates))
        policy.write_text(json.dumps({"receipt_sha256s": trusted_history}), encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["protocol", "--legacy-receipts", str(policy),
                                         "validate-campaign", str(snapshot)])
        assert protocol.main() == 0
        with pytest.raises(ValueError, match="missing or extra fields"):
            protocol.validate_campaign_v2(gates)
    retained = ops.canonical(gates["receipts"])
    merged = deepcopy(gates)
    merged.update(campaign_state="WAITING_EVENT", observed_event="PR_MERGED",
                  observed_event_ref=MERGE,
                  pending_action={"kind": "WAIT_FOR_EVENT", "slice_id": "NONE"},
                  next_action={"type": "WAIT_EVENT", "summary": "Wait for the next event.",
                               "prompt": "NONE"})
    merged["slices"][1]["state"] = "MERGED"
    merged["slices"][1]["pull_requests"][-1].update(state="MERGED", merge_sha=MERGE)
    post = operations()
    post["ci"] = deepcopy(evidence["ci"])
    merge_event = {"kind": "PULL_REQUEST", "action": "MERGED", "repository": REPO,
                   "reference": "#12", "sha": MERGE, "conclusion": "NOT_APPLICABLE"}
    with protocol.trusted_legacy_receipts(trusted_history):
        result = protocol.append_transition_receipt(gates, merged, merge_event,
                                                    operational_evidence=post)
    assert ops.canonical(result["receipts"][:-1]) == retained
    with protocol.trusted_legacy_receipts(trusted_history):
        protocol.validate_campaign_v2(result)
    legacy_post = deepcopy(post)
    del legacy_post["default_branch"]
    with protocol.trusted_legacy_receipts(trusted_history), pytest.raises(
        ValueError, match="missing or extra fields",
    ):
        protocol.append_transition_receipt(gates, merged, merge_event,
                                           operational_evidence=legacy_post)
    archived_post = deepcopy(result)
    del archived_post["receipts"][-1]["operational_evidence"]["default_branch"]
    archived_post["receipts"][-1]["receipt_sha256"] = protocol.receipt_sha256(
        archived_post["receipts"][-1])
    with protocol.trusted_legacy_receipts(trusted_history), pytest.raises(
        ValueError, match="missing or extra fields",
    ):
        protocol.validate_campaign_v2(archived_post)
    # A separate verified pre-upgrade snapshot can also contain a legacy merge.
    # Its full identity is pinned outside the replayed candidate, never inferred.
    old_merge_history = [*trusted_history, archived_post["receipts"][-1]["receipt_sha256"]]
    frozen = ops.canonical(archived_post)
    with protocol.trusted_legacy_receipts(old_merge_history):
        protocol.validate_campaign_v2(archived_post)
    assert ops.canonical(archived_post) == frozen
    changed_legacy = deepcopy(archived_post)
    changed_legacy["receipts"][-1]["operational_evidence"]["pr"]["body"] += "\nChanged text."
    changed_legacy["receipts"][-1]["receipt_sha256"] = protocol.receipt_sha256(
        changed_legacy["receipts"][-1])
    with protocol.trusted_legacy_receipts(old_merge_history), pytest.raises(
        ValueError, match="missing or extra fields",
    ):
        protocol.validate_campaign_v2(changed_legacy)
    damaged = deepcopy(post)
    if damage == "drop_run":
        damaged["ci"]["runs"].pop(0)
    else:
        damaged["ci"]["runs"][0]["attempts"][0]["jobs"][0]["name"] = "rewritten"
    with protocol.trusted_legacy_receipts(trusted_history), pytest.raises(
        ValueError, match="dropped a run|terminal attempt rewritten",
    ):
        protocol.append_transition_receipt(gates, merged, merge_event,
                                           operational_evidence=damaged)
    result["receipts"][-1]["operational_evidence"] = damaged
    result["receipts"][-1]["receipt_sha256"] = protocol.receipt_sha256(result["receipts"][-1])
    with protocol.trusted_legacy_receipts(trusted_history), pytest.raises(
        ValueError, match="dropped a run|terminal attempt rewritten",
    ):
        protocol.validate_campaign_v2(result)


def test_workflow_identity_distinguishes_attempts_and_rejects_missing_attempt():
    first = {"kind": "WORKFLOW_RUN", "action": "COMPLETED", "repository": REPO,
             "reference": "run:100", "sha": HEAD, "conclusion": "SUCCESS", "run_attempt": 1}
    second = {**first, "run_attempt": 2}
    protocol.validate_github_event(first)
    protocol.validate_github_event(second)
    assert protocol.github_event_identity(first) != protocol.github_event_identity(second)
    del first["run_attempt"]
    with pytest.raises(ValueError):
        protocol.validate_github_event(first)


def test_legacy_campaign_replay_does_not_relax_final_audit():
    value = audit()
    receipt = ops.generate_audit(value)
    del value["repositories"][0]["operations"][0]["default_branch"]
    with pytest.raises(ValueError, match="missing or extra fields"):
        ops.generate_audit(value)
    receipt["evidence"] = value
    receipt["evidence_sha256"] = ops.digest(value)
    with pytest.raises(ValueError, match="missing or extra fields"):
        ops.validate_audit(receipt)


def test_archived_operation_compatibility_requires_an_explicit_anchor():
    value = operations()
    del value["default_branch"]
    with pytest.raises(ValueError, match="observation anchor"):
        ops.validate_operations(value, archived_receipt=True)
    assert ops.validate_operations(value, archived_receipt=True, now=datetime.now(UTC)) == value


@pytest.mark.parametrize("value", [None, "a" * 64, ["bad"], ["a" * 64, "a" * 64]])
def test_trusted_legacy_policy_rejects_invalid_or_ambiguous_identities(value):
    with pytest.raises(ValueError), protocol.trusted_legacy_receipts(value):
        pass


def resolved_finding():
    origin, correction = operations(), operations()
    correction["pr"]["number"] = 13
    correction["reviews"]["pr"] = 13
    correction_merge = "e" * 40
    correction["merge"]["merge_sha"] = correction_merge
    correction["merge"]["default_sha"] = correction_merge
    correction["default_branch"]["sha"] = correction_merge
    correction["merge"]["commit"]["sha"] = correction_merge
    correction["pr"]["base_sha"] = MERGE
    correction["pr"]["body"] = correction["pr"]["body"].replace(BASE, MERGE)
    correction["ci"]["policy_ref"] = MERGE
    correction["merge"]["commit"]["parents"] = [MERGE]
    correction["merge"]["ancestry"][0]["sha"] = correction_merge
    correction["merge"]["ancestry"][0]["parents"] = [MERGE]
    correction["post_merge_ci"] = ci(REPO, correction_merge)
    origin["merge"]["default_sha"] = correction_merge
    origin["default_branch"]["sha"] = correction_merge
    origin["merge"]["ancestry"].insert(0, deepcopy(correction["merge"]["commit"]))
    origin["post_merge_ci"] = ci(REPO, correction_merge)
    prior = [{"pr": 12, "head_sha": HEAD, "merge_sha": MERGE, "state": "MERGED"}]
    ref = f"https://github.com/{REPO}/pull/12#discussion_r1"
    return {"id": "synthetic-finding", "origin_pr": 12, "origin_merge_sha": MERGE,
            "thread_ref": ref, "state": "RESOLVED", "origin": origin, "correction": correction,
            "resolution": {"repository": REPO, "origin_pr": 12, "origin_head_sha": HEAD,
                           "thread_ref": ref, "is_resolved": True, "correction_pr": 13,
                           "correction_head_sha": HEAD, "correction_merge_sha": correction_merge,
                           **observed()},
            "prior_ledger": prior, "retained_ledger": [*deepcopy(prior),
                {"pr": 13, "head_sha": HEAD, "merge_sha": correction_merge, "state": "MERGED"}]}


def test_late_finding_resolution_retains_original_and_correction():
    value = operations()
    value["late_findings"] = [resolved_finding()]
    assert ops.validate_operations(value) == value


@pytest.mark.parametrize("damage", ["stale_origin", "sibling", "reversed"])
def test_late_finding_requires_correction_after_origin(damage):
    value = operations()
    finding = resolved_finding()
    origin, correction = finding["origin"], finding["correction"]
    origin["merge"]["default_sha"] = MERGE
    origin["default_branch"]["sha"] = MERGE
    origin["merge"]["ancestry"] = [deepcopy(origin["merge"]["commit"])]
    origin["post_merge_ci"] = ci(REPO, MERGE)
    if damage == "sibling":
        correction["pr"]["base_sha"] = BASE
        correction["pr"]["body"] = correction["pr"]["body"].replace(MERGE, BASE)
        correction["ci"]["policy_ref"] = BASE
        correction["merge"]["commit"]["parents"] = [BASE]
        correction["merge"]["ancestry"][0]["parents"] = [BASE]
    elif damage == "reversed":
        origin, correction = correction, origin
        finding.update(origin=origin, correction=correction, origin_pr=13,
                       origin_merge_sha=origin["merge"]["merge_sha"])
    value["late_findings"] = [finding]
    with pytest.raises(ValueError, match="correction must descend"):
        ops.validate_operations(value)


def test_late_finding_accepts_intervening_default_commits():
    value = operations()
    finding = resolved_finding()
    intermediate = "f" * 40
    correction = finding["correction"]
    correction["pr"]["base_sha"] = intermediate
    correction["pr"]["body"] = correction["pr"]["body"].replace(MERGE, intermediate)
    correction["ci"]["policy_ref"] = intermediate
    correction["merge"]["commit"]["parents"] = [intermediate]
    correction["merge"]["ancestry"][0]["parents"] = [intermediate]
    chain = finding["origin"]["merge"]["ancestry"]
    chain[0] = deepcopy(correction["merge"]["commit"])
    chain.insert(1, {"sha": intermediate, "tree_sha": TREE, "parents": [MERGE]})
    value["late_findings"] = [finding]
    assert ops.validate_operations(value) == value


@pytest.mark.parametrize("damage", ["open", "wrong_build", "unmerged", "rewrite", "reopen"])
def test_late_finding_rejects_unproven_resolution_or_rewritten_history(damage):
    value = operations()
    f = resolved_finding()
    value["late_findings"] = [f]
    if damage == "open":
        f["resolution"]["is_resolved"] = False
    elif damage == "wrong_build":
        f["resolution"]["origin_head_sha"] = BASE
    elif damage == "unmerged":
        f["correction"]["merge"]["merged"] = False
    elif damage == "rewrite":
        f["retained_ledger"][0]["head_sha"] = BASE
    else:
        f["retained_ledger"][0]["state"] = "OPEN"
    with pytest.raises(ValueError):
        ops.validate_operations(value)


@pytest.mark.parametrize("read_only", [False, pytest.param(
    True, marks=pytest.mark.skipif(os.name == "nt", reason="POSIX read-only replacement"))])
def test_synchronizer_rolls_back_an_interrupted_write(tmp_path, monkeypatch, read_only):
    source, target = tmp_path / "source", tmp_path / "target"
    commit, _ = canonical_checkout(source)
    target.mkdir()
    original = target / PROTOCOL_PATH
    original.parent.mkdir()
    original.write_bytes(b"previous vendor")
    if read_only:
        original.chmod(0o400)
    original_mode = stat.S_IMODE(original.stat().st_mode)
    replace = ops.os.replace
    write_bytes = Path.write_bytes
    calls = 0

    def interrupt(source_path, destination):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("synthetic interruption")
        return replace(source_path, destination)

    def enforce_read_only(destination, data):
        # Exercise non-root behavior even on a privileged POSIX test runner.
        if destination.exists() and not destination.stat().st_mode & stat.S_IWUSR:
            raise PermissionError("cannot reopen a read-only destination")
        return write_bytes(destination, data)

    monkeypatch.setattr(ops.os, "replace", interrupt)
    if read_only:
        monkeypatch.setattr(Path, "write_bytes", enforce_read_only)
    with pytest.raises(OSError, match="synthetic interruption"):
        ops.sync_vendor(source, target, commit)
    assert original.read_bytes() == b"previous vendor"
    assert stat.S_IMODE(original.stat().st_mode) == original_mode
    assert [p for p in target.rglob("*") if p.is_file()] == [original]


@pytest.mark.parametrize("key", ["complete", "late_findings_complete", "policy_ref"])
def test_operational_gate_rejects_partial_or_untrusted_policy(key):
    value = operations()
    if key == "complete":
        value["reviews"][key] = False
    elif key == "policy_ref":
        value["ci"][key] = HEAD
    else:
        value[key] = False
    with pytest.raises(ValueError):
        ops.validate_operations(value)


def work_authority_fixture():
    """Synthetic approval input; never an operational maintainer instruction."""
    value = operations("brickms/brickms")
    p = value["pr"]
    p["changed_paths"].insert(0, "CHANGELOG.md")
    patch = ("diff --git a/CHANGELOG.md b/CHANGELOG.md\n--- a/CHANGELOG.md\n"
             "+++ b/CHANGELOG.md\n@@ -1,0 +2 @@\n+"
             "- Agent Development Protocol v1.3.0 / Protocol 1.4.3 source support.\n")
    p["file_patches"]["CHANGELOG.md"] = patch
    approval = {
        "repository": p["repository"], "pr": p["number"], "base_sha": BASE, "head_sha": HEAD,
        "paths_sha256": ops.digest(p["changed_paths"]), "patch": patch,
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "actor": "example-maintainer", "actor_role": "VERIFIED_HUMAN_MAINTAINER",
        "authorization_source": "WORK_USER_INSTRUCTION",
        "authorization_text": "Yes, I authorize the described Protocol work.",
        "decision": "APPROVED", **observed(),
    }
    record = {key: approval[key] for key in (
        "repository", "pr", "base_sha", "head_sha", "paths_sha256", "patch_sha256", "actor",
    )}
    record.update(
        schema="agent-work-instruction/v1", source="CURRENT_USER_CONVERSATION",
        instruction=approval["authorization_text"],
        authorized_request="Implement and merge the isolated Protocol adapter under all gates.",
        authority_envelope="THROUGH_MERGE", workstream_class="PROTOCOL",
        effect_policy="NO_PRODUCTION",
    )
    approval["authorization_ref"] = "work-instruction:sha256:" + ops.digest(record)
    return p, value["baseline_paths"], approval, record


def test_work_approval_requires_independent_host_input_and_does_not_leak():
    p, baseline, approval, record = work_authority_fixture()
    with pytest.raises(ValueError, match="independently supplied caller authority"):
        ops.validate_scope(approval, p, baseline)
    with ops.trusted_work_instructions([record]):
        ops.validate_scope(approval, p, baseline)
    with pytest.raises(ValueError, match="independently supplied caller authority"):
        ops.validate_scope(approval, p, baseline)


@pytest.mark.parametrize("key,value", [
    ("repository", "gabned/provelume"), ("pr", 13), ("base_sha", HEAD), ("head_sha", BASE),
    ("paths_sha256", "0" * 64), ("patch_sha256", "0" * 64), ("actor", "other-maintainer"),
    ("instruction", "A different instruction."),
])
def test_work_approval_cannot_cross_bind_a_different_authorized_delta(key, value):
    p, baseline, approval, record = work_authority_fixture()
    record[key] = value
    approval["authorization_ref"] = "work-instruction:sha256:" + ops.digest(record)
    with ops.trusted_work_instructions([record]), pytest.raises(ValueError):
        ops.validate_scope(approval, p, baseline)


@pytest.mark.parametrize("key,value", [
    ("source", "PULL_REQUEST_BODY"), ("authority_envelope", "THROUGH_PRODUCTION_B"),
    ("workstream_class", "PRODUCT"), ("effect_policy", "REPOSITORY_POLICY"),
])
def test_work_policy_cannot_infer_authority_or_expand_it(key, value):
    _, _, _, record = work_authority_fixture()
    record[key] = value
    with pytest.raises(ValueError), ops.trusted_work_instructions([record]):
        pass


def test_work_policy_is_copied_and_old_references_remain_distinct():
    p, baseline, approval, record = work_authority_fixture()
    with ops.trusted_work_instructions([record]):
        record["actor"] = "mutated-after-selection"
        ops.validate_scope(approval, p, baseline)
        for source in ("USER_INSTRUCTION", "GITHUB_COMMENT"):
            with pytest.raises(ValueError, match="authorization reference"):
                ops.validate_scope({**approval, "authorization_source": source}, p, baseline)


def test_campaign_validator_passes_only_explicitly_scoped_host_authority():
    p, baseline, approval, record = work_authority_fixture()
    with protocol.trusted_work_instructions([record]):
        protocol.load_operations_module().validate_scope(approval, p, baseline)
    with pytest.raises(ValueError, match="independently supplied caller authority"):
        protocol.load_operations_module().validate_scope(approval, p, baseline)


def test_work_authority_cannot_waive_the_exact_patch_gate():
    p, baseline, approval, record = work_authority_fixture()
    p["file_patches"]["CHANGELOG.md"] += "+unapproved second line\n"
    with (
        ops.trusted_work_instructions([record]),
        pytest.raises(ValueError, match="actual|exact-head"),
    ):
        ops.validate_scope(approval, p, baseline)
