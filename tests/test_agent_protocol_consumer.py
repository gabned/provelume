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


@pytest.fixture
def legacy_base_case(tmp_path, request):
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
    git("add", ".")
    git("commit", "-m", "synthetic birth base")
    original = git("rev-parse", "HEAD")
    git("checkout", "-b", "work")
    production = getattr(request, "param", False)
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
