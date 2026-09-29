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
        "release_artifacts": {
            name: accepted
            for name in (
                "source.tar.gz",
                "source-manifest.json",
                "SHA256SUMS",
                "conformance.json",
                "agent_protocol_core-1.5.0-py3-none-any.whl",
            )
        },
    }
    with pytest.raises(ValueError, match="Cached artifact differs"):
        adapter.acquire(pin, offline=True)
    assert damaged.read_bytes() == b"retain damaged artifact for diagnosis"


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
