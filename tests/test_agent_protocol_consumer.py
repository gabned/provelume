"""Native entrypoint conformance against the pinned canonical Protocol package."""

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "tools/agent-protocol"


def command(*args, value=None):
    return subprocess.run(
        [sys.executable, str(ENTRY), *args],
        input=json.dumps(value) if value is not None else None,
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )


def test_current_dependency_and_native_document_routing():
    pin = json.loads((ROOT / ".github/agent-protocol/pin.json").read_text(encoding="utf-8"))
    result = command("verify")
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(result.stdout)["revision"] == pin["operational_revision"] == pin["work_revision"]
    )
    for workstream in ("PROTOCOL", "PRODUCT"):
        selected = command(
            "documents", "--phase", "START", "--host", "CLI", "--workstream", workstream
        )
        assert selected.returncode == 0, selected.stderr
        payload = json.loads(selected.stdout)
        assert payload["core"]["documents"] and payload["local"]["documents"]
        assert payload["model_text_bytes"] > 0


def test_acquisition_refuses_preview_and_preserves_corrupt_offline_cache(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "consumer_acquire", ROOT / "tools/agent_protocol_v2.py"
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    pin = adapter.verify()
    with pytest.raises(ValueError, match="Preview"):
        adapter.acquire({**pin, "candidate_preview": "NOT_ADOPTED"}, offline=True)
    monkeypatch.setattr(adapter, "ROOT", tmp_path)
    cache = tmp_path / ".agent/protocol-artifacts" / pin["operational_revision"]
    cache.mkdir(parents=True)
    damaged = cache / "source.tar.gz"
    damaged.write_bytes(b"retain damaged artifact for diagnosis")
    accepted = {"sha256": hashlib.sha256(b"expected").hexdigest(), "size": 8}
    pin = {
        **pin,
        "schema": "agent-protocol-consumer-pin/v2",
        "release_artifacts": {
            name: accepted
            for name in (
                "source.tar.gz",
                "source-manifest.json",
                "SHA256SUMS",
                "conformance.json",
                f"agent_protocol_core-{pin['source_manifest']['version']}-py3-none-any.whl",
            )
        },
    }
    with pytest.raises(ValueError, match="Cached artifact differs"):
        adapter.acquire(pin, offline=True)
    assert damaged.read_bytes() == b"retain damaged artifact for diagnosis"


def test_acquisition_refuses_wheel_from_another_release(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "consumer_acquire_mismatch", ROOT / "tools/agent_protocol_v2.py"
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    pin = adapter.verify()
    pin = {**pin, "schema": "agent-protocol-consumer-pin/v2"}
    artifacts = {
        name: {"size": 1, "sha256": "0" * 64}
        for name in (
            "source.tar.gz",
            "source-manifest.json",
            "conformance.json",
            "SHA256SUMS",
            f"agent_protocol_core-{pin['source_manifest']['version']}-py3-none-any.whl",
        )
    }
    wheel = next(name for name in artifacts if name.endswith(".whl"))
    artifacts["agent_protocol_core-0.0.0-py3-none-any.whl"] = artifacts.pop(wheel)
    monkeypatch.setattr(adapter, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Incomplete release artifact inventory"):
        adapter.acquire({**pin, "release_artifacts": artifacts}, offline=True)
    assert not (tmp_path / ".agent").exists()


def test_git_source_authentication_and_offline_cache_preservation():
    """Coherent local JSON must not enroll a source or repair corrupt originals."""
    import tempfile
    from unittest.mock import patch

    spec = importlib.util.spec_from_file_location(
        "consumer_git_acquire", ROOT / "tools/agent_protocol_v2.py"
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    pin = adapter.verify()
    assert pin["schema"] == "agent-protocol-consumer-pin/v3"
    with tempfile.TemporaryDirectory(prefix="protocol-source-refusal-") as temporary:
        isolated = Path(temporary)
        with patch.object(adapter, "ROOT", isolated):
            try:
                adapter.acquire(pin, fetch_source=lambda _: {})
            except (ValueError, KeyError):
                pass
            else:
                raise AssertionError("Unauthenticated canonical source was accepted")
            assert not (isolated / ".agent/protocol-sources").exists()
            directory = isolated / ".agent/protocol-artifacts" / pin["operational_revision"]
            directory.mkdir(parents=True)
            damaged = directory / "source.tar.gz"
            original = b"preserve corrupt acquisition original"
            damaged.write_bytes(original)
            with patch.object(
                adapter.subprocess, "run", side_effect=AssertionError("Git during offline")
            ):
                try:
                    adapter.acquire(pin, offline=True)
                except ValueError as error:
                    assert "Cached artifact differs" in str(error)
                else:
                    raise AssertionError("Corrupt Git source cache was accepted")
            assert damaged.read_bytes() == original


def test_native_engine_uses_canonical_preconditions_without_write_authority():
    fixture = json.loads(
        (ROOT / "tools/agent_protocol_core/tests/fixtures/lifecycle.json").read_text(
            encoding="utf-8"
        )
    )
    # The frozen synthetic fixture has an intentionally historical observation.
    from datetime import datetime

    fixture["observation"]["observed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = command("engine", "explain", value=fixture)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["event"]["operation"] == "START"
    fixture["request"]["expected_head"] = "f" * 40
    refused = command("engine", "explain", value=fixture)
    assert refused.returncode == 2 and "Unexpected remote candidate head" in refused.stderr
    write = command("engine", "start", value=fixture["request"])
    assert write.returncode == 2 and "Independent operator enrollment required" in write.stderr


def test_actual_event_entrypoint_preserves_local_guard_and_identity(tmp_path):
    pin = json.loads((ROOT / ".github/agent-protocol/pin.json").read_text())
    if pin["consumer"] != "gabned/provelume":
        pytest.skip("Provelume local event policy")
    base, head = "a" * 40, "b" * 40
    body = "WORKSTREAM_CLASS: PROTOCOL\nPROTOCOL_ESCALATION: NONE\n"
    pr = {
        "number": 46,
        "body": body,
        "base": {"sha": base},
        "head": {"sha": head},
        "author_association": "OWNER",
        "user": {"login": "gabned", "type": "User"},
    }
    event = {
        "number": 46,
        "repository": {"full_name": pin["consumer"], "id": pin["consumer_id"]},
        "sender": {"login": "gabned", "type": "User"},
        "pull_request": pr,
    }
    files = {"event.json": json.dumps(event), "pr.json": json.dumps(pr)}
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    delta = tmp_path / "delta.z"
    delta.write_bytes(b"M\0docs/agent-protocol/operations.md\0")
    args = (
        "event-guard",
        "--event",
        str(tmp_path / "event.json"),
        "--current-pr",
        str(tmp_path / "pr.json"),
        "--name-status",
        str(delta),
        "--expected-base-sha",
        base,
        "--expected-head-sha",
        head,
        "--complete",
    )
    valid = command(*args)
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["merge_allowed"] is True
    # Preserve the native prohibition on PRODUCT touching Protocol, even though
    # the engine and vendor source are shared with the PROTOCOL route.
    pr["body"] = "WORKSTREAM_CLASS: PRODUCT\nPROTOCOL_ESCALATION: NONE\n"
    (tmp_path / "pr.json").write_text(json.dumps(pr))
    denied = command(*args)
    assert denied.returncode == 1 and "PRODUCT_TOUCHES_PROTOCOL" in denied.stdout
    event["repository"]["id"] += 1
    (tmp_path / "event.json").write_text(json.dumps(event))
    denied = command(*args)
    assert denied.returncode == 2 and "identity changed" in denied.stderr


def test_product_host_keeps_native_policy_and_failed_gate():
    spec = importlib.util.spec_from_file_location(
        "consumer_native", ROOT / "tools/agent_protocol_v2.py"
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    pin = adapter.verify()
    from datetime import datetime

    from agent_protocol.ledger import digest, replay
    from agent_protocol.lifecycle import DEPENDENCIES

    fixture = json.loads(
        (ROOT / "tools/agent_protocol_core/tests/fixtures/lifecycle.json").read_text(
            encoding="utf-8"
        )
    )
    identity = {
        **fixture["state"]["identity"],
        "repository": adapter.REPOSITORY,
        "repository_id": adapter.REPOSITORY_ID,
        "workstream_class": "PRODUCT",
    }
    state = replay([], identity=identity, authenticated_commits={})
    authority = fixture["authority"]
    authority.update(identity=identity, pin=pin["operational_revision"])
    policy = authority["policy"]
    policy["contract"].update(
        repository=adapter.REPOSITORY,
        routing="PRODUCT/v2",
        source_commit=pin["operational_revision"],
    )
    policy.update(
        selected="REPOSITORY_POLICY",
        contract_digest=digest(policy["contract"]),
        required_gates=[
            "CI",
            "NATIVE",
            "REVIEWS",
            "EFFECTS",
            "ANCESTRY",
            "SOURCE",
            "AUTHORIZATION",
        ],
    )
    observed = fixture["observation"]
    observed.update(identity=identity, observed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    coords = observed["coordinates"]
    coords.update(
        PIN=authority["pin"],
        POLICY=digest(policy),
        REPOSITORY=digest(identity),
        AUTHORITY=digest(
            {
                k: authority[k]
                for k in ("identity", "principal", "operations", "capabilities", "signer_registry")
            }
        ),
    )
    observed["gates"] = [
        {
            "id": name,
            "gate": name,
            "result": "PASS",
            "dependencies": sorted(DEPENDENCIES[name]),
            "coordinates": {k: coords[k] for k in DEPENDENCIES[name]},
            "source": {"synthetic_native_receipt": name},
        }
        for name in policy["required_gates"]
    ]
    journal = SimpleNamespace(read=lambda: state, synchronize=lambda: None)
    host = adapter.bind_product_host(
        journal,
        collect_native=lambda _: observed,
        native_authority=lambda _: authority,
        merge_native=lambda **_: None,
        collect_recovery_native=lambda _: observed,
    )
    start = host.explain(fixture["request"])["event"]
    state = replay(
        [{"commit": "1" * 40, "parents": [], "event": start}],
        identity=identity,
        authenticated_commits={"1" * 40: "owner-a"},
    )
    request = {
        **fixture["request"],
        "operation": "QUALIFY",
        "operation_id": "qualify-native",
        "expected_tip": state["tip"],
    }
    assert host.explain(request)["event"]["payload"]["result"] == "PASS"
    observed["gates"][1]["result"] = "FAIL"
    failed = host.explain(request)["event"]
    assert failed["payload"]["result"] == "FAIL"
    state = replay(
        [
            {"commit": "1" * 40, "parents": [], "event": start},
            {"commit": "2" * 40, "parents": ["1" * 40], "event": failed},
        ],
        identity=identity,
        authenticated_commits={"1" * 40: "owner-a", "2" * 40: "owner-a"},
    )
    request.update(
        operation="INTEGRATE", operation_id="integrate-native", expected_tip=state["tip"]
    )
    try:
        host.explain(request)
    except ValueError:
        pass
    else:
        raise AssertionError("A failed native PRODUCT gate was accepted")
    policy["selected"] = "NO_PRODUCTION"
    try:
        host.explain(request)
    except ValueError as error:
        assert "cannot downgrade" in str(error)
    else:
        raise AssertionError("PRODUCT policy was downgraded")


def workspace_conformance():
    """Explicit isolated Linux profile lane; ordinary native tests do not start services."""
    assert os.name == "posix"
    profile = json.loads((ROOT / ".github/agent-protocol/workspace.json").read_text())
    assert profile["ports"] == [] and profile["services"] == {}
    marker = ROOT / ".agent/lab-synthetic-instance/operator-resume-marker.txt"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(2):
        with (ROOT / ".agent/native-profile-runtime.log").open("ab") as log:
            process = subprocess.Popen(
                profile["commands"]["start"],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:
                for _ in range(120):
                    assert process.poll() is None, "Native server exited before readiness"
                    try:
                        with opener.open("http://127.0.0.1:8000/", timeout=1) as response:
                            assert response.status == 200
                            break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.25)
                else:
                    raise AssertionError("Native loopback readiness not observed")
                if attempt == 0:
                    marker.write_text("synthetic durable resume marker")
                else:
                    assert marker.read_text() == "synthetic durable resume marker"
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=15)
    print("Native profile: loopback start/stop and durable restart PASS")


if __name__ == "__main__" and sys.argv[1:] == ["--workspace-conformance"]:
    workspace_conformance()
elif __name__ == "__main__":
    test_current_dependency_and_native_document_routing()
    test_native_engine_uses_canonical_preconditions_without_write_authority()
    test_product_host_keeps_native_policy_and_failed_gate()
    print("Native Agent Protocol dependency and engine conformance: PASS")


def create_legacy_base_case(tmp_path, *, production=False):
    """A real synthetic normal merge, with immutable birth and live base anchors."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "base_adapter", ROOT / "tools/agent_protocol_v2.py"
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    native_spec = importlib.util.spec_from_file_location(
        "birth_native", ROOT / "tools/agent_protocol.py"
    )
    native = importlib.util.module_from_spec(native_spec)
    native_spec.loader.exec_module(native)
    repo = tmp_path / "repository"
    repo.mkdir()

    def git(*args, value=None):
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            input=value,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Synthetic")
    git("config", "user.email", "synthetic@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "core.autocrlf", "false")
    git("remote", "add", "origin", "https://github.com/gabned/provelume.git")
    (repo / "marker").write_text("original\n")
    (repo / "scripts").mkdir()
    (repo / "scripts/ai_runtime_report.py").write_text("# synthetic evaluator\n")
    git("add", ".")
    git("commit", "-m", "synthetic birth base")
    original = git("rev-parse", "HEAD")
    git("checkout", "-b", "work")
    workstream_class = "PRODUCT" if production else "PROTOCOL"
    policy = "REPOSITORY_POLICY" if production else "NO_PRODUCTION"
    changed_name = "core/synthetic.txt" if production else "tests/test_agent_protocol_consumer.py"
    changed = repo / changed_name
    changed.parent.mkdir()
    changed.write_text("# synthetic candidate\n")
    git("add", ".")
    git("commit", "-m", "synthetic binding basis")
    basis = git("rev-parse", "HEAD")
    contract = {
        "schema": "agent-policy-contract/v1",
        "repository": adapter.REPOSITORY,
        "source_commit": original,
        "reference": "synthetic accepted operations",
        "routing": "PRODUCT/v2" if production else "PROTOCOL/v1",
    }
    authority = {"production": production, "deploy": False, "migrate": False}
    effect = native.build_effect_report(
        base_sha=original,
        head_sha=basis,
        changed_paths=[changed_name],
        policy=policy,
        source="GITHUB_CONNECTOR",
        complete=True,
    )
    binding = native.build_binding(
        effect,
        active_pr="#7",
        workstream="synthetic-base",
        workstream_class=workstream_class,
        adopted_contract=contract,
        trusted_contract=adapter.digest(contract),
        production_authority=authority,
    )
    git("checkout", "main")
    (repo / "marker").write_text("accepted upstream\n")
    git("add", ".")
    git("commit", "-m", "synthetic accepted advance")
    base = git("rev-parse", "HEAD")
    git("checkout", "work")
    git("merge", "--no-ff", "--no-edit", "main")
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    merge = git("commit-tree", tree, "-p", base, "-p", head, value="synthetic test merge\n")
    repository = {"id": adapter.REPOSITORY_ID, "full_name": adapter.REPOSITORY}
    observations = {
        "schema": "provelume-base-observations/v1",
        "observed_at": native.now_utc(),
        "repository": {**repository, "default_branch": "main"},
        "pr": {
            "number": 7,
            "state": "open",
            "draft": False,
            "mergeable": True,
            "base": {"sha": base, "ref": "main", "repo": repository},
            "head": {"sha": head, "ref": "work", "repo": repository},
            "merge_commit_sha": merge,
            "changed_files": 1,
        },
        "default": {"ref": "refs/heads/main", "object": {"sha": base}},
        "candidate": {
            "sha": head,
            "tree": {"sha": tree},
            "parents": [{"sha": basis}, {"sha": base}],
        },
        "test_merge": {
            "sha": merge,
            "tree": {"sha": tree},
            "parents": [{"sha": base}, {"sha": head}],
        },
        "files": [{"filename": changed_name}],
        "files_complete": True,
    }
    current_contract = {**contract, "source_commit": base}
    snapshot = native.seal(
        {
            "schema_version": 2,
            "protocol_version": "1.2",
            "mode": "SNAPSHOT",
            "source": "GITHUB_CONNECTOR",
            "repository": adapter.REPOSITORY,
            "observed_at": native.now_utc(),
            "default_branch": "main",
            "default_sha": base,
            "owner_pr": "#7",
            "base_sha": base,
            "head_sha": head,
            "binding_basis_sha": basis,
            "effect_report_sha256": binding["effect_report_sha256"],
            "pr_state": "OPEN",
            "draft": "FALSE",
            "checks": "SUCCESS",
            "mergeability": "MERGEABLE",
            "base_ancestry": "TRUE",
            "binding_basis_ancestor": "TRUE",
            "unresolved_threads": 0,
            "review_requirement_source": "NONE",
            "codex_review_state": "NOT_REQUESTED",
            "repository_review": "NOT_APPLICABLE",
            "technical_finding": "NONE",
            "codex_reviewed_head": None,
            "codex_review_withdrawal": None,
            "credentials_accessed": False,
            "production_environment_accessed": False,
            "policy_context": {
                "contract": current_contract,
                "trusted_contract": adapter.digest(current_contract),
                "workstream_class": workstream_class,
                "production_authority": authority,
            },
        }
    )
    effects = native.build_effect_report(
        base_sha=base,
        head_sha=head,
        changed_paths=[changed_name],
        policy=policy,
        source="GITHUB_CONNECTOR",
        complete=True,
    )
    return {
        "adapter": adapter,
        "native": native,
        "repository_path": repo,
        "git": git,
        "snapshot": snapshot,
        "binding": binding,
        "effects": effects,
        "observations": observations,
        "expected_head": head,
        "trusted_binding": binding["report_sha256"],
        "trusted_observations": adapter.digest(observations),
    }


@pytest.fixture
def legacy_base_case(tmp_path, request):
    return create_legacy_base_case(tmp_path, production=getattr(request, "param", False))


def base_preflight(case):
    return case["adapter"].legacy_base_preflight(
        **{k: v for k, v in case.items() if k not in {"adapter", "native", "git"}}
    )


def test_legacy_base_advance_preserves_original_failure_and_all_input_bytes(legacy_base_case):
    case = legacy_base_case
    before = {
        k: json.dumps(case[k], sort_keys=True)
        for k in ("snapshot", "binding", "effects", "observations")
    }
    historical = case["native"].preflight(case["snapshot"], case["binding"])
    assert historical["errors"] == ["snapshot base_sha does not match binding"]
    assert historical["merge_ready"] is False
    result = base_preflight(case)
    assert result["protocol_identity"] == "BASE_ADVANCE_PROVEN"
    assert result["merge_ready"] is True and result["errors"] == []
    assert result["historical_preflight"]["errors"] == historical["errors"]
    assert result["original_base_sha"] == case["binding"]["base_sha"]
    assert result["current_base_sha"] == case["snapshot"]["base_sha"]
    assert result["original_base_sha"] != result["current_base_sha"]
    assert result["new_capabilities"] == [] and result["binding_mutated"] is False
    assert result["lifecycle_v2_activated"] is False
    assert {k: json.dumps(case[k], sort_keys=True) for k in before} == before


def prepare_s07_base_case(case, monkeypatch):
    adapter = case["adapter"]
    # Set synthetic ownership coordinates without replacing or resealing a live BIND.
    workstream = "concordia-s07-cpu-recovery"
    binding = case["native"].seal(
        {
            **case["binding"],
            "active_pr": "#439",
            "workstream": workstream,
            "policy_resolution": {**case["binding"]["policy_resolution"], "workstream": workstream},
        }
    )
    case["binding"] = binding
    case["trusted_binding"] = binding["report_sha256"]
    monkeypatch.setattr(adapter, "S07_BIND", case["trusted_binding"])
    monkeypatch.setattr(
        adapter, "S07_EVALUATOR", case["git"]("rev-parse", "HEAD:scripts/ai_runtime_report.py"),
    )
    case["snapshot"] = case["native"].seal(
        {**case["snapshot"], "owner_pr": "#439", "technical_finding": "CURRENT"}
    )
    observations = case["observations"]
    observations["pr"]["number"] = 439
    observations["schema"] = "provelume-base-observations/v2"
    findings = {
        f"https://github.com/{adapter.REPOSITORY}/actions/runs/{run}/job/{job}": {
            "source_commit": commit, "run_id": run, "job_id": job,
            "result": "FAIL", "status": "CURRENT", "cause": "NOT_DEMONSTRATED",
        }
        for commit, (run, job) in adapter.S07_ORIGINAL_RUNS.items()
    }
    approval = {
        "schema": "provelume-s07-approval/v1",
        "repository": adapter.REPOSITORY,
        "owner_pr": "#439",
        "binding_sha256": case["trusted_binding"],
        "release": "0.15.0",
        "criterion": "QUALIFY_CANDIDATE_AND_MAIN_AT_EXISTING_THRESHOLDS",
        "reference": "synthetic maintainer approval",
        "historical_findings": sorted(findings),
    }
    report = {
        "source_commit": case["expected_head"],
        "status": "PASS",
        "gates": dict.fromkeys(adapter.S07_CPU_GATES, "PASS"),
    }
    matrix_report = {
        "source_commit": case["expected_head"], "automatic": "PASS", "installed_runtime": "PASS",
    }
    evidence = {
        "snapshot_sha256": case["snapshot"]["report_sha256"],
        "findings_complete": True,
        "findings": findings,
        "cpu_jobs": {
            runner: {
                "run_id": 1,
                "attempt": 1,
                "job_id": job,
                "report": {**report, "gates": report["gates"].copy()},
                "report_sha256": adapter.digest(report),
                "workflow_path": ".github/workflows/ai-runtime-candidate.yml",
                "event": "pull_request",
                "job_name": f"measure ({runner})",
                "conclusion": "success",
            }
            for job, runner in enumerate(("ubuntu-24.04", "windows-2025"), start=2)
        },
        "matrix": {"report": matrix_report, "sha256": adapter.digest(matrix_report)},
    }
    observations["s07_qualification"] = {"approval": approval, "evidence": evidence}
    case["trusted_s07_approval"] = adapter.digest(approval)
    seal_s07_evidence(case)
    return case


@pytest.fixture
def s07_base_case(legacy_base_case, monkeypatch):
    return prepare_s07_base_case(legacy_base_case, monkeypatch)


def seal_s07_evidence(case):
    observations = case["observations"]
    case["trusted_observations"] = case["adapter"].digest(observations)
    case["trusted_s07_evidence"] = case["adapter"].digest(
        observations["s07_qualification"]["evidence"]
    )


def prepare_s07_additional_case(case):
    # These fixed coordinates are independent of the adapter's proposed allowlist.
    # All authority and qualification reports in this fixture remain synthetic.
    additional_runs = {
        "f2cb84a60f3e5a268d8547285b5a360cbaef8a47": (42368608397, 128391869733),
        "adb276c663007921658fb5dfc4173b7d62ace31d": (42369730479, 128395169479),
        "3790f8afc50ef3a0c7162894e366b7e19b4ddc34": (42378818835, 128421899209),
        "0cf30899fdf2c5b0607dc1ab6c7a5fe97f37f83f": (42382541331, 128433012483),
        "61e8694dd7904de4de8c9295ca8301edf4a358df": (42389259695, 128453164193),
    }
    additional = {
        f"https://github.com/gabned/provelume/actions/runs/{run}/job/{job}": {
            "source_commit": commit, "run_id": run, "job_id": job,
            "result": "FAIL", "status": "CURRENT", "cause": "NOT_DEMONSTRATED",
        }
        for commit, (run, job) in additional_runs.items()
    }
    qualification = case["observations"]["s07_qualification"]
    approval, evidence = qualification["approval"], qualification["evidence"]
    approval.update(
        schema="provelume-s07-approval/v2",
        reference="synthetic maintainer addendum, not a live approval",
        additional_historical_findings=sorted(additional),
    )
    evidence["findings"].update(additional)
    case["trusted_s07_approval"] = case["adapter"].digest(approval)
    seal_s07_evidence(case)
    return case


@pytest.fixture
def s07_additional_case(s07_base_case):
    return prepare_s07_additional_case(s07_base_case)


S07_TEST_COLD_810_URL = (
    "https://github.com/gabned/provelume/actions/runs/42290059975/job/128140838845"
)
S07_TEST_COLD_810_RECORD = {
    "source_commit": "d5b2cc9f06c14be8c51a082d309dbde0358552e8",
    "driver_commit": "358a19468f1e2db58b72212e8e36c102cbf522f6",
    "run_id": 42290059975,
    "attempt": 1,
    "job_id": 128140838845,
    "event": "workflow_dispatch",
    "workflow_path": ".github/workflows/ai-runtime-candidate.yml",
    "job_name": "concordia-capture-guard",
    "job_conclusion": "success",
    "arm": "A",
    "arm_index": 3,
    "phase": "cold",
    "sample": 810,
    "failed_gate": "s08_performance",
    "qualification_eligible": False,
    "result": "FAIL",
    "status": "CURRENT",
    "cause": "NOT_DEMONSTRATED",
    "artifact_id": 13541917919,
    "artifact_sha256": "5248db15078cf441570f114390e8030dc79e4f0065caa6b87172580f00cc7c2a",
    "report_member": "capture-guard-comparison/arm-3/report.json",
    "report_bytes_sha256": "63bc821aec9ad304da7e0fae0b09e57b4cf13d70758a54bd832d44977bd2ef83",
}


@pytest.fixture(scope="module")
def s07_cold_810_repository(tmp_path_factory):
    return create_legacy_base_case(tmp_path_factory.mktemp("s07-cold-810"))


@pytest.fixture
def s07_cold_810_case(s07_cold_810_repository, monkeypatch):
    # These preflight cases only read Git. Each test owns its mutable evidence.
    case = s07_cold_810_repository.copy()
    for key in ("binding", "snapshot", "effects", "observations"):
        case[key] = deepcopy(case[key])
    observed_at = case["native"].now_utc()
    case["snapshot"]["observed_at"] = observed_at
    case["observations"]["observed_at"] = observed_at
    prepare_s07_base_case(case, monkeypatch)
    prepare_s07_additional_case(case)
    # Pin the original observation independently. The approval is only a test fixture.
    qualification = case["observations"]["s07_qualification"]
    approval, evidence = qualification["approval"], qualification["evidence"]
    approval.update(
        schema="provelume-s07-approval/v3",
        reference="https://github.com/gabned/provelume/issues/383#issuecomment-99999999999",
        cold_810_finding=S07_TEST_COLD_810_URL,
    )
    evidence["findings"][S07_TEST_COLD_810_URL] = S07_TEST_COLD_810_RECORD.copy()
    case["trusted_s07_approval"] = case["adapter"].digest(approval)
    seal_s07_evidence(case)
    return case


@pytest.fixture(params=("v1", "v2"))
def s07_qualified_case(request):
    return request.getfixturevalue(
        "s07_base_case" if request.param == "v1" else "s07_additional_case"
    )


def test_s07_preflight_keeps_original_snapshot_findings_and_refusal(s07_base_case):
    case = s07_base_case
    before = {
        key: json.dumps(case[key], sort_keys=True)
        for key in ("binding", "snapshot", "observations")
    }
    result = base_preflight(case)
    assert result["schema"] == "provelume-legacy-base-preflight/v2"
    assert result["merge_ready"] is True
    assert result["binding_mutated"] is False
    assert result["binding_sha256"] == case["trusted_binding"]
    assert result["snapshot_sha256"] == case["snapshot"]["report_sha256"]
    assert result["s07_qualification"] == {
        "approval_sha256": case["trusted_s07_approval"],
        "evidence_sha256": case["trusted_s07_evidence"],
        "historical_findings": case["observations"]["s07_qualification"]["evidence"]["findings"],
        "remaining_findings": {},
        "candidate_finding": "NONE",
    }
    assert result["historical_preflight"]["merge_ready"] is False
    assert "current technical finding blocks" in result["historical_preflight"]["errors"]
    assert {key: json.dumps(case[key], sort_keys=True) for key in before} == before
    case["native"].verify_seal(result)


@pytest.mark.parametrize("finding", ["CURRENT", "UNKNOWN"])
def test_s07_preflight_blocks_current_or_unknown_candidate_findings(s07_qualified_case, finding):
    case = s07_qualified_case
    evidence = case["observations"]["s07_qualification"]["evidence"]
    current = {"status": finding, "source_commit": case["expected_head"]}
    evidence["findings"]["https://example.invalid/new-finding"] = current
    seal_s07_evidence(case)
    result = base_preflight(case)
    assert result["merge_ready"] is False
    assert result["s07_qualification"]["candidate_finding"] == finding
    assert result["s07_qualification"]["remaining_findings"] == {
        "https://example.invalid/new-finding": current,
    }


@pytest.mark.parametrize(
    "field,value",
    [("checks", "FAILURE"), ("unresolved_threads", 1), ("codex_review_state", "FINDINGS")],
)
def test_s07_preflight_leaves_ordinary_gate_blocking(s07_qualified_case, field, value):
    case = s07_qualified_case
    case["snapshot"] = case["native"].seal({**case["snapshot"], field: value})
    evidence = case["observations"]["s07_qualification"]["evidence"]
    evidence["snapshot_sha256"] = case["snapshot"]["report_sha256"]
    seal_s07_evidence(case)
    assert base_preflight(case)["merge_ready"] is False


def test_s07_preflight_rejects_resealed_observations_with_untrusted_proofs(s07_qualified_case):
    case = s07_qualified_case
    qualification = case["observations"]["s07_qualification"]
    approval, evidence = qualification["approval"], qualification["evidence"]
    approval["reference"] = "unrelated approval"
    for job in evidence["cpu_jobs"].values():
        job["report_sha256"] = "0" * 64
    evidence["matrix"]["sha256"] = "0" * 64
    case["trusted_observations"] = case["adapter"].digest(case["observations"])
    with pytest.raises(ValueError, match="authenticated S07 approval differs"):
        base_preflight(case)
    del case["trusted_s07_approval"]
    with pytest.raises(ValueError, match="authenticated S07 approval differs"):
        base_preflight(case)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("missing_finding", "All four original S07 findings"),
        ("historical_pass", "All four original S07 findings"),
        ("other_binding", "original #439 BIND"),
        ("stale_snapshot", "bind the current snapshot"),
        ("incomplete_inventory", "complete finding inventory"),
        ("other_head", "nonpassing S07 CPU report"),
        ("nonpassing_gate", "nonpassing S07 CPU report"),
        ("diagnostic_run", "nonpassing ordinary S07 CPU job"),
        ("matrix_incomplete", "S07 automatic and installed runtime"),
        ("missing_platform", "Both ordinary S07 CPU jobs"),
        ("changed_evaluator", "evaluator differs"),
        ("changed_digest", "Observed source bytes changed"),
        ("wrong_approval_scope", "approval must cover exactly"),
        ("altered_report", "altered or nonpassing S07 CPU report"),
        ("altered_matrix", "Verified S07 automatic and installed runtime"),
        ("altered_inventory_digest", "authenticated S07 evidence differs"),
    ],
)
def test_s07_preflight_refuses_unbound_or_incomplete_evidence(
    s07_qualified_case, monkeypatch, mutation, expected,
):
    case = s07_qualified_case
    qualification = case["observations"]["s07_qualification"]
    approval, evidence = qualification["approval"], qualification["evidence"]
    linux = evidence["cpu_jobs"]["ubuntu-24.04"]
    matrix = evidence["matrix"]
    if mutation == "missing_finding":
        del evidence["findings"][approval["historical_findings"][0]]
    elif mutation == "historical_pass":
        next(iter(evidence["findings"].values()))["result"] = "PASS"
    elif mutation == "other_binding":
        monkeypatch.setattr(case["adapter"], "S07_BIND", "0" * 64)
    elif mutation == "stale_snapshot":
        evidence["snapshot_sha256"] = "0" * 64
    elif mutation == "incomplete_inventory":
        evidence["findings_complete"] = False
    elif mutation == "other_head":
        linux["report"]["source_commit"] = "0" * 40
        linux["report_sha256"] = case["adapter"].digest(linux["report"])
    elif mutation == "nonpassing_gate":
        linux["report"]["gates"]["network"] = "FAIL"
        linux["report_sha256"] = case["adapter"].digest(linux["report"])
    elif mutation == "diagnostic_run":
        linux["event"] = "workflow_dispatch"
    elif mutation == "matrix_incomplete":
        matrix["report"]["installed_runtime"] = "NOT_RUN"
        matrix["sha256"] = case["adapter"].digest(matrix["report"])
    elif mutation == "missing_platform":
        del evidence["cpu_jobs"]["windows-2025"]
    elif mutation == "changed_evaluator":
        monkeypatch.setattr(case["adapter"], "S07_EVALUATOR", "0" * 40)
    elif mutation == "wrong_approval_scope":
        approval["historical_findings"].append("https://example.invalid/unrelated-finding")
        case["trusted_s07_approval"] = case["adapter"].digest(approval)
    elif mutation == "altered_report":
        linux["report_sha256"] = "0" * 64
    elif mutation == "altered_matrix":
        matrix["sha256"] = "0" * 64
    elif mutation == "altered_inventory_digest":
        evidence["findings"]["https://example.invalid/new-finding"] = {"status": "CURRENT"}

    if mutation == "changed_digest":
        approval["reference"] = "changed after the observations were sealed"
    elif mutation == "altered_inventory_digest":
        case["trusted_observations"] = case["adapter"].digest(case["observations"])
    else:
        seal_s07_evidence(case)
    with pytest.raises(ValueError, match=expected):
        base_preflight(case)


def test_s07_addendum_preserves_binding_nine_findings_and_original_refusal(s07_additional_case):
    case = s07_additional_case
    before = {
        key: json.dumps(case[key], sort_keys=True)
        for key in ("binding", "snapshot", "effects", "observations")
    }
    qualification = case["observations"]["s07_qualification"]
    approval, evidence = qualification["approval"], qualification["evidence"]
    original = {key: evidence["findings"][key] for key in approval["historical_findings"]}
    additional = {
        key: evidence["findings"][key] for key in approval["additional_historical_findings"]
    }
    assert len(original) == 4 and len(additional) == 5
    result = base_preflight(case)
    assert result["merge_ready"] is True and result["errors"] == []
    assert result["s07_qualification"] == {
        "approval_sha256": case["trusted_s07_approval"],
        "evidence_sha256": case["trusted_s07_evidence"],
        "historical_findings": original,
        "additional_historical_findings": additional,
        "remaining_findings": {},
        "candidate_finding": "NONE",
    }
    assert result["binding_sha256"] == case["trusted_binding"]
    assert result["snapshot_sha256"] == case["snapshot"]["report_sha256"]
    assert result["binding_mutated"] is False
    assert result["lifecycle_v2_activated"] is False and result["new_capabilities"] == []
    assert result["historical_preflight"]["merge_ready"] is False
    assert "current technical finding blocks" in result["historical_preflight"]["errors"]
    assert {key: json.dumps(case[key], sort_keys=True) for key in before} == before
    case["native"].verify_seal(result)


def test_s07_v1_keeps_all_five_unapproved_findings_blocking(s07_additional_case):
    case = s07_additional_case
    qualification = case["observations"]["s07_qualification"]
    approval, evidence = qualification["approval"], qualification["evidence"]
    additional = approval.pop("additional_historical_findings")
    approval["schema"] = "provelume-s07-approval/v1"
    case["trusted_s07_approval"] = case["adapter"].digest(approval)
    seal_s07_evidence(case)
    result = base_preflight(case)
    assert result["merge_ready"] is False
    retained = result["s07_qualification"]
    assert retained["candidate_finding"] == "CURRENT"
    assert retained["remaining_findings"] == {key: evidence["findings"][key] for key in additional}
    assert "additional_historical_findings" not in retained


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_commit", "0" * 40), ("run_id", 1), ("job_id", 1),
        ("result", "PASS"), ("status", "RESOLVED"), ("cause", "DEMONSTRATED"),
        ("unapproved_field", False),
    ],
)
def test_s07_addendum_refuses_changed_record_even_with_trusted_digest(
    s07_additional_case, field, value,
):
    case = s07_additional_case
    qualification = case["observations"]["s07_qualification"]
    reference = qualification["approval"]["additional_historical_findings"][0]
    qualification["evidence"]["findings"][reference][field] = value
    seal_s07_evidence(case)
    with pytest.raises(ValueError):
        base_preflight(case)


@pytest.mark.parametrize("field", ["run_id", "job_id"])
def test_s07_addendum_requires_integer_ids(s07_additional_case, field):
    case = s07_additional_case
    qualification = case["observations"]["s07_qualification"]
    reference = qualification["approval"]["additional_historical_findings"][0]
    record = qualification["evidence"]["findings"][reference]
    record[field] = float(record[field])
    seal_s07_evidence(case)
    with pytest.raises(ValueError, match="All five additional S07 findings"):
        base_preflight(case)


def test_s07_addendum_requires_every_fixed_record(s07_additional_case):
    case = s07_additional_case
    qualification = case["observations"]["s07_qualification"]
    reference = qualification["approval"]["additional_historical_findings"][0]
    del qualification["evidence"]["findings"][reference]
    seal_s07_evidence(case)
    with pytest.raises(ValueError):
        base_preflight(case)


@pytest.mark.parametrize(
    "mutation", ["v1", "unknown_schema", "v3_incomplete", "missing", "sixth", "reordered"],
)
def test_s07_addendum_refuses_other_scope_even_when_resealed(s07_additional_case, mutation):
    case = s07_additional_case
    approval = case["observations"]["s07_qualification"]["approval"]
    if mutation == "v1":
        approval["schema"] = "provelume-s07-approval/v1"
    elif mutation == "unknown_schema":
        approval["schema"] = "provelume-s07-approval/v4"
    elif mutation == "v3_incomplete":
        approval["schema"] = "provelume-s07-approval/v3"
    elif mutation == "missing":
        del approval["additional_historical_findings"]
    elif mutation == "sixth":
        approval["additional_historical_findings"].append("https://example.invalid/sixth")
    else:
        approval["additional_historical_findings"].reverse()
    case["trusted_s07_approval"] = case["adapter"].digest(approval)
    seal_s07_evidence(case)
    with pytest.raises(ValueError):
        base_preflight(case)


@pytest.mark.parametrize("finding", ["CURRENT", "UNKNOWN"])
def test_s07_addendum_cannot_exclude_diagnostics_by_metadata(s07_additional_case, finding):
    case = s07_additional_case
    evidence = case["observations"]["s07_qualification"]["evidence"]
    reference = "https://example.invalid/unresolved-diagnostic"
    record = {
        "status": finding, "source_commit": case["expected_head"],
        "qualification_eligible": False, "provenance": "nonqualifying_diagnostic",
        "applicable": False, "disposition": "HISTORY_ONLY",
    }
    evidence["findings"][reference] = record
    seal_s07_evidence(case)
    result = base_preflight(case)
    assert result["merge_ready"] is False
    assert result["s07_qualification"]["candidate_finding"] == finding
    assert result["s07_qualification"]["remaining_findings"] == {reference: record}


@pytest.mark.parametrize("finding", ["CURRENT", "UNKNOWN"])
def test_s07_addendum_does_not_cover_windows_sibling(s07_additional_case, finding):
    case = s07_additional_case
    evidence = case["observations"]["s07_qualification"]["evidence"]
    # Same source/run as an admitted Linux finding, but a different, unapproved job.
    # This synthetic observation preserves acquisition failure without a CPU score.
    reference = "https://github.com/gabned/provelume/actions/runs/42368608397/job/128391870070"
    record = {
        "source_commit": "f2cb84a60f3e5a268d8547285b5a360cbaef8a47",
        "run_id": 42368608397, "job_id": 128391870070,
        "result": "FAIL", "status": finding, "inference": "NOT_RUN",
        "provenance": "ordinary_qualification", "phase": "model_acquisition",
    }
    evidence["findings"][reference] = record
    seal_s07_evidence(case)
    result = base_preflight(case)
    assert result["merge_ready"] is False
    assert result["s07_qualification"]["candidate_finding"] == finding
    assert result["s07_qualification"]["remaining_findings"] == {reference: record}


@pytest.mark.parametrize("conclusion", ["failure", "success"])
def test_s07_addendum_cannot_accept_current_s08_failure(s07_additional_case, conclusion):
    case = s07_additional_case
    linux = case["observations"]["s07_qualification"]["evidence"]["cpu_jobs"]["ubuntu-24.04"]
    linux["conclusion"] = conclusion
    linux["report"]["status"] = "FAIL"
    linux["report"]["gates"]["s08_performance"] = "FAIL"
    linux["report_sha256"] = case["adapter"].digest(linux["report"])
    seal_s07_evidence(case)
    with pytest.raises(ValueError, match="nonpassing"):
        base_preflight(case)


def test_s07_cold_810_preserves_all_ten_records_and_original_refusal(s07_cold_810_case):
    case = s07_cold_810_case
    observations = case["observations"]
    before = {
        key: json.dumps(case[key], sort_keys=True)
        for key in ("binding", "snapshot", "effects", "observations")
    }
    case["observations"] = case["adapter"].parse_legacy_observations(
        json.dumps(observations).encode("utf-8"),
    )
    qualification = observations["s07_qualification"]
    approval, findings = qualification["approval"], qualification["evidence"]["findings"]
    assert len(approval["historical_findings"]) == 4
    assert len(approval["additional_historical_findings"]) == 5
    result = base_preflight(case)
    assert result["merge_ready"] is True and result["errors"] == []
    assert result["s07_qualification"] == {
        "approval_sha256": case["trusted_s07_approval"],
        "evidence_sha256": case["trusted_s07_evidence"],
        "historical_findings": {key: findings[key] for key in approval["historical_findings"]},
        "additional_historical_findings": {
            key: findings[key] for key in approval["additional_historical_findings"]
        },
        "cold_810_finding": {S07_TEST_COLD_810_URL: S07_TEST_COLD_810_RECORD},
        "remaining_findings": {},
        "candidate_finding": "NONE",
    }
    assert result["binding_sha256"] == case["trusted_binding"]
    assert result["snapshot_sha256"] == case["snapshot"]["report_sha256"]
    assert result["binding_mutated"] is False
    assert result["historical_preflight"]["merge_ready"] is False
    assert "current technical finding blocks" in result["historical_preflight"]["errors"]
    assert {key: json.dumps(case[key], sort_keys=True) for key in before} == before
    case["native"].verify_seal(result)


def test_s07_legacy_approvals_keep_cold_810_blocking(s07_qualified_case):
    case = s07_qualified_case
    findings = case["observations"]["s07_qualification"]["evidence"]["findings"]
    findings[S07_TEST_COLD_810_URL] = S07_TEST_COLD_810_RECORD.copy()
    seal_s07_evidence(case)
    result = base_preflight(case)
    assert result["merge_ready"] is False
    assert result["s07_qualification"]["candidate_finding"] == "CURRENT"
    assert result["s07_qualification"]["remaining_findings"] == {
        S07_TEST_COLD_810_URL: S07_TEST_COLD_810_RECORD,
    }
    assert "cold_810_finding" not in result["s07_qualification"]


@pytest.mark.parametrize("status", ["CURRENT", "UNKNOWN"])
def test_s07_cold_810_does_not_cover_another_observation_in_same_job(s07_cold_810_case, status):
    case = s07_cold_810_case
    findings = case["observations"]["s07_qualification"]["evidence"]["findings"]
    reference = S07_TEST_COLD_810_URL + "#another-observation"
    record = {
        "source_commit": S07_TEST_COLD_810_RECORD["source_commit"],
        "run_id": 42290059975, "attempt": 1, "job_id": 128140838845,
        "phase": "warm", "sample": 811, "status": status,
    }
    findings[reference] = record
    seal_s07_evidence(case)
    result = base_preflight(case)
    assert result["merge_ready"] is False
    assert result["s07_qualification"]["candidate_finding"] == status
    assert result["s07_qualification"]["remaining_findings"] == {reference: record}


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_commit", S07_TEST_COLD_810_RECORD["driver_commit"]),
        ("driver_commit", S07_TEST_COLD_810_RECORD["source_commit"]),
        ("attempt", 2), ("arm_index", 0), ("phase", "warm"), ("sample", 811),
        ("failed_gate", "network"), ("result", "PASS"),
        ("report_member", "capture-guard-comparison/arm-0/report.json"),
        ("report_bytes_sha256", "0" * 64),
        ("run_id", 42290059975.0), ("attempt", True), ("job_id", 128140838845.0),
        ("arm_index", 3.0), ("sample", 810.0), ("artifact_id", 13541917919.0),
        ("qualification_eligible", 0),
    ],
)
def test_s07_cold_810_requires_exact_record_even_resealed(s07_cold_810_case, field, value):
    case = s07_cold_810_case
    findings = case["observations"]["s07_qualification"]["evidence"]["findings"]
    findings[S07_TEST_COLD_810_URL][field] = value
    seal_s07_evidence(case)
    with pytest.raises(ValueError, match="The exact S07 cold 810 finding"):
        base_preflight(case)


@pytest.mark.parametrize(
    "reference",
    [
        "https://github.com/gabned/provelume/issues/383#issuecomment-6960833812",
        "https://github.com/gabned/provelume/issues/383#%69ssuecomment-6960833812",
        "https://api.github.com/repos/gabned/provelume/issues/comments/6960833812",
    ],
)
def test_s07_cold_810_needs_a_separate_decision_even_with_trusted_digest(
    s07_cold_810_case, reference,
):
    case = s07_cold_810_case
    approval = case["observations"]["s07_qualification"]["approval"]
    approval["reference"] = reference
    case["trusted_s07_approval"] = case["adapter"].digest(approval)
    seal_s07_evidence(case)
    with pytest.raises(
        ValueError, match="S07 v3 requires a separate authenticated cold 810 decision",
    ):
        base_preflight(case)


def test_s07_cold_810_refuses_duplicate_finding_before_reduction(s07_cold_810_case):
    case = s07_cold_810_case
    raw = json.dumps(case["observations"]).encode("utf-8")
    key = (json.dumps(S07_TEST_COLD_810_URL) + ":").encode("utf-8")
    assert raw.count(key) == 1
    duplicate = raw.replace(key, key + b' {"status": "UNKNOWN"}, ' + key, 1)
    # Ordinary JSON parsing would silently preserve only the authorized record.
    assert json.loads(duplicate) == case["observations"]
    with pytest.raises(ValueError, match="Duplicate JSON keys in S07 v3 observations"):
        case["adapter"].parse_legacy_observations(duplicate)


def test_s07_cold_810_cannot_accept_current_s08_failure(s07_cold_810_case):
    case = s07_cold_810_case
    linux = case["observations"]["s07_qualification"]["evidence"]["cpu_jobs"]["ubuntu-24.04"]
    linux["report"]["status"] = "FAIL"
    linux["report"]["gates"]["s08_performance"] = "FAIL"
    linux["report_sha256"] = case["adapter"].digest(linux["report"])
    seal_s07_evidence(case)
    with pytest.raises(ValueError, match="nonpassing"):
        base_preflight(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("checks", "FAILURE"),
        ("checks", "UNKNOWN"),
        ("base_ancestry", "UNKNOWN"),
        ("binding_basis_ancestor", "FALSE"),
        ("unresolved_threads", 1),
        ("unresolved_threads", False),
        ("credentials_accessed", True),
        ("production_environment_accessed", True),
        ("technical_finding", "CURRENT"),
        ("repository_review", "BLOCKED"),
        ("review_requirement_source", "UNKNOWN"),
        ("codex_review_state", "FINDINGS"),
    ],
)
def test_base_advance_keeps_each_current_gate_blocking(legacy_base_case, field, value):
    case = legacy_base_case
    case["snapshot"] = case["native"].seal({**case["snapshot"], field: value})
    result = base_preflight(case)
    assert result["protocol_identity"] == "BASE_ADVANCE_PROVEN"
    assert result["merge_ready"] is False and result["errors"]


@pytest.mark.parametrize(
    "field,value", [("draft", True), ("state", "closed"), ("mergeable", False)]
)
def test_base_advance_keeps_real_pr_state_blocking(legacy_base_case, field, value):
    case = legacy_base_case
    case["observations"]["pr"][field] = value
    key = {"draft": "draft", "state": "pr_state", "mergeable": "mergeability"}[field]
    actual = {"draft": "TRUE", "state": "CLOSED", "mergeable": "CONFLICTING"}[field]
    case["snapshot"] = case["native"].seal({**case["snapshot"], key: actual})
    case["trusted_observations"] = case["adapter"].digest(case["observations"])
    assert base_preflight(case)["merge_ready"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "binding",
        "expected_head",
        "default",
        "files",
        "files_complete",
        "tree",
        "parents",
        "test_merge",
        "original_ancestry",
        "basis_ancestry",
        "dirty",
        "replace",
        "graft",
        "shallow",
        "branch",
        "origin",
        "stale",
        "snapshot_base",
        "effect_delta",
        "policy",
        "observations_digest",
    ],
)
def test_base_advance_refuses_identity_history_delta_and_policy_changes(legacy_base_case, mutation):
    case = legacy_base_case
    obs = case["observations"]
    if mutation == "binding":
        case["binding"] = case["native"].seal({**case["binding"], "workstream": "other-owner"})
    elif mutation == "expected_head":
        case["expected_head"] = "a" * 40
    elif mutation == "default":
        obs["default"]["object"]["sha"] = case["binding"]["base_sha"]
    elif mutation == "files":
        obs["files"] = []
    elif mutation == "files_complete":
        obs["files_complete"] = False
    elif mutation == "tree":
        obs["candidate"]["tree"]["sha"] = "b" * 40
    elif mutation == "parents":
        obs["candidate"]["parents"].reverse()
    elif mutation == "test_merge":
        obs["test_merge"]["parents"].reverse()
    elif mutation in {"original_ancestry", "basis_ancestry"}:
        unrelated = case["git"]("commit-tree", obs["candidate"]["tree"]["sha"], value="unrelated\n")
        key = "base_sha" if mutation == "original_ancestry" else "binding_basis_sha"
        case["binding"] = case["native"].seal({**case["binding"], key: unrelated})
        case["trusted_binding"] = case["binding"]["report_sha256"]
        if mutation == "basis_ancestry":
            case["snapshot"] = case["native"].seal({**case["snapshot"], key: unrelated})
    elif mutation == "dirty":
        (case["repository_path"] / "untracked").write_text("must refuse")
    elif mutation == "replace":
        case["git"]("replace", case["expected_head"], case["binding"]["binding_basis_sha"])
    elif mutation == "graft":
        (case["repository_path"] / ".git/info/grafts").write_text(case["expected_head"] + "\n")
    elif mutation == "shallow":
        (case["repository_path"] / ".git/shallow").write_text(case["expected_head"] + "\n")
    elif mutation == "branch":
        obs["pr"]["head"]["ref"] = "other-branch"
    elif mutation == "origin":
        case["git"]("remote", "set-url", "origin", "https://example.invalid/unrelated.git")
    elif mutation == "stale":
        obs["observed_at"] = "2000-01-01T00:00:00Z"
    elif mutation == "snapshot_base":
        case["snapshot"] = case["native"].seal(
            {
                **case["snapshot"],
                "base_sha": case["binding"]["base_sha"],
            }
        )
    elif mutation == "effect_delta":
        case["effects"] = case["native"].build_effect_report(
            base_sha=case["snapshot"]["base_sha"],
            head_sha=case["expected_head"],
            changed_paths=["core/synthetic.txt"],
            policy="NO_PRODUCTION",
            source="GITHUB_CONNECTOR",
            complete=True,
        )
    elif mutation == "policy":
        context = {**case["snapshot"]["policy_context"], "workstream_class": "PRODUCT"}
        case["snapshot"] = case["native"].seal({**case["snapshot"], "policy_context": context})
    if mutation != "observations_digest":
        case["trusted_observations"] = case["adapter"].digest(obs)
    else:
        case["trusted_observations"] = "0" * 64
    with pytest.raises(ValueError):
        base_preflight(case)


def test_public_base_preflight_entrypoint_and_append_only_output(legacy_base_case, tmp_path):
    case = legacy_base_case
    args = ["legacy-base-preflight"]
    for name in ("snapshot", "binding", "effects", "observations"):
        file = tmp_path / (name + ".json")
        file.write_text(json.dumps(case[name]), encoding="utf-8")
        args.extend(["--" + name, str(file)])
    output = tmp_path / "receipt.json"
    args.extend(
        [
            "--repository-path",
            str(case["repository_path"]),
            "--expected-head",
            case["expected_head"],
            "--binding-sha256",
            case["trusted_binding"],
            "--observations-sha256",
            case["trusted_observations"],
            "--output",
            str(output),
        ]
    )
    result = command(*args)
    assert result.returncode == 0, result.stderr
    receipt = output.read_bytes()
    assert json.loads(receipt)["protocol_identity"] == "BASE_ADVANCE_PROVEN"
    second = command(*args)
    assert second.returncode == 2 and output.read_bytes() == receipt


@pytest.mark.parametrize("legacy_base_case", [True], indirect=True)
def test_product_production_base_advance_keeps_its_policy_and_findings(legacy_base_case):
    case = legacy_base_case
    assert case["binding"]["effect_policy"] == "REPOSITORY_POLICY"
    assert case["effects"]["effect"] == "PRODUCTION"
    assert base_preflight(case)["merge_ready"] is True
    case["snapshot"] = case["native"].seal(
        {
            **case["snapshot"],
            "draft": "TRUE",
            "technical_finding": "CURRENT",
        }
    )
    case["observations"]["pr"]["draft"] = True
    case["trusted_observations"] = case["adapter"].digest(case["observations"])
    blocked = base_preflight(case)
    assert blocked["protocol_identity"] == "BASE_ADVANCE_PROVEN"
    assert blocked["merge_ready"] is False and len(blocked["errors"]) >= 2


def test_base_advance_refuses_new_capabilities(legacy_base_case):
    case = legacy_base_case
    context = case["snapshot"]["policy_context"]
    context["production_authority"] = {"production": True, "deploy": False, "migrate": False}
    case["snapshot"] = case["native"].seal(case["snapshot"])
    with pytest.raises(ValueError, match="capabilities increased"):
        base_preflight(case)


@pytest.mark.parametrize("driver", ["clean", "smudge", "process", "include"])
def test_base_advance_refuses_executable_filters_before_worktree_reads(
    legacy_base_case, tmp_path, monkeypatch, driver
):
    case = legacy_base_case
    repo = case["repository_path"]
    marker = tmp_path / "candidate-helper-ran"
    helper = repo / ".git/filter-probe.py"
    helper.write_text(
        "import os, pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(\n"
        "    os.getenv('SYNTHETIC_HOST_SENTINEL', 'absent'))\n"
        "sys.stdout.write(sys.stdin.read())\n",
        encoding="utf-8",
    )
    configured = f'"{sys.executable}" "{helper}"'
    if driver == "include":
        included = repo / ".git/filter-config"
        case["git"]("config", "--file", str(included), "filter.probe.clean", configured)
        case["git"]("config", "include.path", str(included))
    else:
        case["git"]("config", f"filter.probe.{driver}", configured)
    (repo / ".git/info/attributes").write_text("marker filter=probe\n", encoding="utf-8")
    # Force stat inspection of a tracked file without changing its accepted bytes.
    tracked = repo / "marker"
    tracked.write_bytes(tracked.read_bytes())
    monkeypatch.setenv("SYNTHETIC_HOST_SENTINEL", "synthetic non-secret value")
    original_binding = json.dumps(case["binding"], sort_keys=True)
    with pytest.raises(ValueError, match="Executable or included Git configuration refused"):
        base_preflight(case)
    assert not marker.exists(), "A candidate helper executed before refusal"
    assert json.dumps(case["binding"], sort_keys=True) == original_binding


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_base_advance_refuses_index_flags_hiding_physical_changes(legacy_base_case, flag):
    case = legacy_base_case
    case["git"]("update-index", flag, "marker")
    (case["repository_path"] / "marker").write_text("uncommitted physical bytes\n")
    assert case["git"]("status", "--porcelain", "--untracked-files=all") == ""
    with pytest.raises(ValueError, match="Masked, sparse or non-file index entry refused"):
        base_preflight(case)


def test_base_advance_does_not_pass_unrelated_host_environment(legacy_base_case, monkeypatch):
    case = legacy_base_case
    monkeypatch.setenv("SYNTHETIC_HOST_SENTINEL", "synthetic non-secret value")
    original = subprocess.run
    git_environments = []

    def observed_run(arguments, **kwargs):
        if Path(arguments[0]).stem == "git":
            git_environments.append(kwargs["env"])
        return original(arguments, **kwargs)

    monkeypatch.setattr(case["adapter"].subprocess, "run", observed_run)
    assert base_preflight(case)["merge_ready"] is True
    assert git_environments
    assert all("SYNTHETIC_HOST_SENTINEL" not in env for env in git_environments)


def public_base_arguments(case, directory, output):
    args = ["legacy-base-preflight"]
    for name in ("snapshot", "binding", "effects", "observations"):
        file = directory / (name + ".json")
        file.write_text(json.dumps(case[name]), encoding="utf-8")
        args.extend(["--" + name, str(file)])
    for name in (
        "repository-path", "expected-head", "binding-sha256", "observations-sha256", "output"
    ):
        value = {
            "repository-path": case["repository_path"],
            "expected-head": case["expected_head"],
            "binding-sha256": case["trusted_binding"],
            "observations-sha256": case["trusted_observations"],
            "output": output,
        }[name]
        args.extend(["--" + name, str(value)])
    return args


@pytest.mark.parametrize(
    "destination", ["receipt.json", ".git/receipt.json", ".agent/receipt.json"]
)
def test_public_base_preflight_refuses_output_that_changes_checked_source(
    legacy_base_case, tmp_path, destination
):
    case = legacy_base_case
    output = case["repository_path"] / destination
    output.parent.mkdir(exist_ok=True)
    result = command(*public_base_arguments(case, tmp_path, output))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Receipt destination" in result.stderr
    assert not output.exists()
    assert case["git"]("status", "--porcelain", "--untracked-files=all") == ""


def test_public_base_preflight_allows_only_ignored_agent_evidence(legacy_base_case, tmp_path):
    case = legacy_base_case
    repo = case["repository_path"]
    (repo / ".git/info/exclude").write_text(".agent/\n", encoding="utf-8")
    output = repo / ".agent/receipt.json"
    output.parent.mkdir()
    result = command(*public_base_arguments(case, tmp_path, output))
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_bytes()) == json.loads(result.stdout)
    assert json.loads(result.stdout)["merge_ready"] is True
    assert case["git"]("status", "--porcelain", "--untracked-files=all") == ""
    receipt = output.read_bytes()
    repeated = command(*public_base_arguments(case, tmp_path, output))
    assert repeated.returncode == 2 and output.read_bytes() == receipt


def test_base_preflight_blocks_source_change_during_receipt_write(
    legacy_base_case, tmp_path, monkeypatch
):
    case = legacy_base_case
    output = tmp_path / "receipt.json"
    original = subprocess.run

    def concurrent_change(arguments, **kwargs):
        if "status" in arguments and output.exists():
            assert json.loads(output.read_bytes())["merge_ready"] is True
            (case["repository_path"] / "concurrent-untracked").write_text("synthetic race\n")
        return original(arguments, **kwargs)

    monkeypatch.setattr(case["adapter"].subprocess, "run", concurrent_change)
    result = case["adapter"].legacy_base_preflight(
        **{k: v for k, v in case.items() if k not in {"adapter", "native", "git"}},
        output_path=output,
    )
    assert result["result"] == "BLOCKED" and result["merge_ready"] is False
    assert "Candidate became dirty while publishing receipt" in result["errors"]
    assert json.loads(output.read_bytes()) == result
    case["native"].verify_seal(result)


def test_public_base_preflight_refuses_receipt_parent_symlink(legacy_base_case, tmp_path):
    case = legacy_base_case
    link = tmp_path / "source-alias"
    try:
        link.symlink_to(case["repository_path"], target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Native symlink capability unavailable: {error}")
    output = link / "receipt.json"
    result = command(*public_base_arguments(case, tmp_path, output))
    assert result.returncode == 2
    assert "Receipt destination must not traverse links" in result.stderr
    assert not output.exists()
    assert case["git"]("status", "--porcelain", "--untracked-files=all") == ""
