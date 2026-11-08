"""Synthetic wire/credential fixtures; native local state, never native SSH proof."""

import base64
import errno
import os
import secrets
from unittest.mock import patch

import pytest

from provelume.mirror_contract import MirrorError, fingerprint, raw, sha
from provelume.mirror_folder_files import FolderTree
from provelume.mirror_rsync import RsyncMirrors
from provelume.mirror_rsync_protocol import frame, read_frame
from provelume.mirror_rsync_remote import RemoteNamespace
from provelume.mirror_rsync_remote_main import enroll_helper
from provelume.mirror_ssh_agent import public_blob
from provelume.mirror_ssh_crypto import public_key
from provelume.mirror_ssh_runtime import SSH_VERSION, configuration
from provelume.mirrors import Mirrors
from provelume.service import ProvelumeInstance
from provelume.tududi_qualification import SyntheticVault


def configuration_fixture():
    return {
        "transport": "rsync-ssh",
        "host": "synthetic.example.test",
        "port": 2222,
        "username": "synthetic",
        "host_key": base64.b64encode(public_blob(public_key(secrets.token_bytes(32)))).decode(),
        "namespace": "a" * 32,
        "configuration_sha256": "b" * 64,
        "bandwidth_kib": 1024,
        "window_start_minute_utc": 0,
        "window_end_minute_utc": 1440,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"port": True},
        {"host": "-unsafe"},
        {"host": "host/other"},
        {"host_key": "invalid"},
        {"username": "user name"},
        {"window_end_minute_utc": 0},
        {"window_start_minute_utc": -1},
        {"bandwidth_kib": 0},
        {"configuration_sha256": "unknown"},
    ],
)
def test_closed_configuration_rejects_unbound_authority_before_process_or_vault(change):
    value = configuration_fixture() | change
    with pytest.raises(MirrorError):
        configuration(value)


@pytest.mark.skipif(
    os.name == "nt", reason="Linux remote-helper fd protocol; Windows client is separate"
)
def test_control_frame_never_prefetches_or_loses_following_rsync_bytes():
    reader, writer = os.pipe()
    value = {"schema": "synthetic-bounded-control"}
    try:
        os.write(writer, frame(value) + b"SYNTHETIC_RSYNC_WIRE")
        os.close(writer)
        writer = None
        assert read_frame(reader) == value
        assert os.read(reader, 100) == b"SYNTHETIC_RSYNC_WIRE"
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)


def fixture(root, monkeypatch):
    if os.name == "nt":
        pytest.skip("Linux remote filesystem authority; no Windows server support inferred")
    from provelume import mirror_rsync_remote as remote_module
    from provelume.mirror_ssh_runtime import NativeSession

    source = root / "Inputs"
    source.mkdir()
    (source / "one.md").write_text("# Synthetic rsync generation\n\nFinite data.\n")
    instance = ProvelumeInstance.initialise(root / "Instance")
    instance.ingest_run(source)
    mirrors = Mirrors(instance.store, vault=SyntheticVault())
    mirrors.set_access(enabled=True, github=False, rsync=True, expected_revision=0, confirmed=True)
    binary = root / "Synthetic component NOT EXECUTED"
    binary.write_bytes(b"SYNTHETIC_COMPONENT_BYTES_NOT_NATIVE_PROOF")

    def component(_session, name, **_options):
        return {
            "path": str(binary),
            "version": "3.5.2" if name == "rsync" else SSH_VERSION.decode(),
            "sha256": sha(binary.read_bytes()),
        }

    monkeypatch.setattr(NativeSession, "component", component)
    counters = {"transfers": 0, "rpcs": 0, "interrupt": None, "native_child_stopped": True}
    remote_holder = {}

    class SyntheticNoNetworkTransport:
        def __init__(self, session, target, credential, **_options):
            self.target = target
            self.components = {name: component(session, name) for name in ("ssh", "rsync")}

        def rpc(self, value):
            counters["rpcs"] += 1
            remote = remote_holder["namespace"]
            return (
                remote.activate(value) if value["action"] == "activate" else remote.inspect(value)
            )

        def transfer(self, value, *, mirrors, plan):
            counters["transfers"] += 1

            def receive(_args, *, tree, stage, outcome, **_options):
                outcome["native_child_stopped"] = counters["native_child_stopped"]
                if counters["interrupt"]:
                    raise OSError(errno.ENOSPC, "Synthetic stopped transfer")
                for row in value["manifest"]["inventory"]:
                    data = (
                        mirrors.snapshots.root() / plan["generation"] / row["path"]
                    ).read_bytes()
                    tree.write(stage + "/" + row["path"], data)
                tree.write(stage + "/manifest.json", raw(value["manifest"]))
                return {"returncode": 0, "native_child_stopped": True}

            with patch.object(remote_module, "receive", receive):
                return remote_holder["namespace"].transfer(value, incoming=-1, outgoing=-1)

    engine = RsyncMirrors(
        instance.store, mirrors=mirrors, transport_factory=SyntheticNoNetworkTransport
    )
    generated = engine.create_identity(name="Synthetic dedicated identity", confirmed=True)
    target = configuration_fixture()
    enrolled = enroll_helper(
        root / "Remote control",
        root=root / "Remote payload",
        source={
            "instance_id": instance.store.read_config()["instance"]["id"],
            "device_sha256": mirrors.device(),
        },
        namespace=target["namespace"],
        client_public_sha256=generated["public_sha256"],
        rsync_binary=str(binary),
        excluded_roots=[
            str(instance.store.paths.root),
            str(
                instance.store.paths.root.parent
                / ("." + instance.store.paths.root.name + ".provelume")
            ),
        ],
    )
    target["configuration_sha256"] = enrolled["configuration_sha256"]
    remote_holder["namespace"] = RemoteNamespace(root / "Remote control" / "namespace.json")
    row = mirrors.configure(
        identity_id=generated["identity"]["id"],
        name="Synthetic remote namespace",
        target=target,
        scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode="manual",
        confirmed=True,
    )
    engine.initialize(
        row["id"], expected_destination_sha256=row["destination_sha256"], confirmed=True
    )
    return instance, mirrors, engine, row, root / "Remote payload", counters


def prepare(engine, row):
    return engine.prepare(row["id"], expected_revision=1, confirmed=True)


def publish(engine, plan):
    return engine.publish(
        plan["id"],
        expected_plan_sha256=plan["plan_sha256"],
        expected_rsync_plan_sha256=plan["rsync_plan_sha256"],
        confirmed=True,
    )


def test_complete_generation_noop_and_historical_receipt_do_not_repeat_transfer(
    tmp_path, monkeypatch
):
    _instance, mirrors, engine, row, target, counters = fixture(tmp_path, monkeypatch)
    before = mirrors.snapshots.source_fingerprint()
    plan = prepare(engine, row)
    first = publish(engine, plan)["receipt"]
    assert first["transport_proof"]["activation_written"]
    pointer = (target / "active.json").read_bytes()
    assert publish(engine, plan)["historical"]
    noop = publish(engine, prepare(engine, row))["receipt"]
    assert not noop["transport_proof"]["activation_written"]
    assert (target / "active.json").read_bytes() == pointer
    assert counters["transfers"] == 1
    assert mirrors.snapshots.source_fingerprint() == before


@pytest.mark.parametrize("revoked", [False, True])
def test_stale_or_revoked_grant_refuses_before_any_native_transport(tmp_path, monkeypatch, revoked):
    _instance, mirrors, engine, row, _target, counters = fixture(tmp_path, monkeypatch)
    plan = prepare(engine, row)
    if revoked:
        engine.disconnect(row["identity_id"], expected_revision=1, confirmed=True)
    else:
        _row, _authority, target, _reference = engine.context(row["id"])
        mirrors.configure(
            identity_id=row["identity_id"],
            name="Explicit changed destination grant",
            target=target,
            scope=row["scope"],
            include_rules=row["include_rules"],
            destination_id=row["id"],
            expected_revision=1,
            mode="manual",
            confirmed=True,
        )
    observed = dict(counters)
    with pytest.raises(MirrorError):
        publish(engine, plan)
    assert counters == observed


def test_replaced_remote_root_with_copied_ownership_marker_is_refused(tmp_path, monkeypatch):
    import shutil

    _instance, _mirrors, engine, row, target, counters = fixture(tmp_path, monkeypatch)
    plan = prepare(engine, row)
    publish(engine, plan)
    previous = (target / "active.json").read_bytes()
    target.rename(tmp_path / "Original destination")
    shutil.copytree(tmp_path / "Original destination", target)
    with pytest.raises(MirrorError):
        prepare(engine, row)
    assert (tmp_path / "Original destination" / "active.json").read_bytes() == previous
    assert counters["transfers"] == 1


@pytest.mark.parametrize("after_activation", [False, True])
def test_actual_root_restore_and_unknown_activation_only_allow_readonly_recovery(
    tmp_path, monkeypatch, after_activation
):
    instance, _mirrors, engine, row, _target, counters = fixture(tmp_path, monkeypatch)
    plan = prepare(engine, row)
    backup = instance.backup(destination=tmp_path / "Before send")
    original = FolderTree.rename
    activations = []

    def interrupted(tree, source, destination, **options):
        if destination != "active.json":
            return original(tree, source, destination, **options)
        activations.append(True)
        if after_activation:
            original(tree, source, destination, **options)
        raise OSError(errno.ENOSPC, "Synthetic activation interruption")

    with patch.object(FolderTree, "rename", interrupted), pytest.raises((OSError, ValueError)):
        publish(engine, plan)
    assert len(activations) == 1 and counters["transfers"] == 1
    assert instance.restore(backup["archive"])["status"] == "restored"
    with (
        patch.object(FolderTree, "write", side_effect=AssertionError("recovery write")),
        patch.object(FolderTree, "rename", side_effect=AssertionError("activation replay")),
    ):
        result = engine.reconcile(plan["id"], confirmed=True)
        if after_activation:
            assert (
                result["receipt"]["transport_proof"]["evidence_mode"] == "reconciled_current_state"
            )
            assert publish(engine, plan)["historical"]
        else:
            assert result["outcome"] == "UNKNOWN" and not result["explicit_resume_available"]
            with pytest.raises(MirrorError):
                engine.resume(
                    plan["id"], expected_rsync_plan_sha256=plan["rsync_plan_sha256"], confirmed=True
                )
    assert len(activations) == 1 and counters["transfers"] == 1


@pytest.mark.parametrize("stopped", [False, True])
def test_resume_requires_durable_proof_receiver_stopped_and_activation_never_started(
    tmp_path, monkeypatch, stopped
):
    _instance, _mirrors, engine, row, _target, counters = fixture(tmp_path, monkeypatch)
    plan = prepare(engine, row)
    counters.update(interrupt=True, native_child_stopped=stopped)
    with pytest.raises((OSError, ValueError)):
        publish(engine, plan)
    result = engine.reconcile(plan["id"], confirmed=True)
    assert result["outcome"] == "UNKNOWN" and result["explicit_resume_available"] is stopped
    counters["interrupt"] = False
    if stopped:
        assert engine.resume(
            plan["id"], expected_rsync_plan_sha256=plan["rsync_plan_sha256"], confirmed=True
        )["receipt"]["transport_proof"]["activation_written"]
        assert counters["transfers"] == 2
    else:
        with pytest.raises(MirrorError):
            engine.resume(
                plan["id"], expected_rsync_plan_sha256=plan["rsync_plan_sha256"], confirmed=True
            )
        assert counters["transfers"] == 1


def test_disabled_no_rsync_and_passive_status_have_no_component_vault_or_target_access(
    tmp_path, monkeypatch
):
    _instance, mirrors, engine, row, _target, _counters = fixture(tmp_path, monkeypatch)
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=1, confirmed=True)
    with (
        patch.object(
            engine, "transport", side_effect=AssertionError("disabled native/credential access")
        ),
        patch.object(mirrors, "_grant", side_effect=AssertionError("disabled vault access")),
    ):
        assert not engine.status()["target_probed"]
        with pytest.raises(MirrorError, match="rsync_disabled"):
            prepare(engine, row)


def test_csrf_ui_uses_the_same_backend_and_all_catalogue_gets_are_passive(tmp_path, monkeypatch):
    import re

    from fastapi.testclient import TestClient

    from provelume.web import create_app

    instance, mirrors, engine, row, _target, counters = fixture(tmp_path, monkeypatch)
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._mirrors_manager = mirrors
    monkeypatch.setattr(app.state.provelume, "rsync_mirrors", lambda: engine)
    client = TestClient(app)
    page = client.get("/mirrors?lang=it")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert client.post("/mirrors", data={"action": "rsync-prepare"}).status_code == 403
    result = client.post(
        "/mirrors?lang=it",
        data={
            "csrf_token": csrf,
            "action": "rsync-prepare",
            "destination_id": row["id"],
            "revision": "1",
            "confirm": "yes",
        },
    )
    assert result.status_code == 200 and 'id="mirror-rsync-plan"' in result.text
    plan, rsync_plan = engine.rsync_plan(mirrors.plans()[0]["id"])
    result = client.post(
        "/mirrors?lang=it",
        data={
            "csrf_token": csrf,
            "action": "rsync-publish",
            "plan_id": plan["id"],
            "plan_sha256": fingerprint(plan),
            "rsync_plan_sha256": fingerprint(rsync_plan),
            "confirm": "yes",
        },
    )
    assert result.status_code == 200 and 'id="mirror-rsync-receipt"' in result.text
    reads, rpcs = mirrors.vault.reads, counters["rpcs"]
    with patch.object(
        engine, "transport", side_effect=AssertionError("passive process/credential/remote access")
    ):
        for language in ["en", "it", "de", "fr", "es", "pt", "ro"]:
            assert (
                client.get("/mirrors?lang=" + language + "&plan=" + plan["id"]).status_code == 200
            )
    assert mirrors.vault.reads == reads and counters["rpcs"] == rpcs


@pytest.mark.parametrize("inside_window", [False, True])
def test_scheduler_honors_window_and_never_retries_a_failed_rsync_operation(
    tmp_path, monkeypatch, inside_window
):
    from provelume import mirror_rsync, mirror_ssh_runtime
    from provelume.mirror_jobs import MirrorJobs

    instance, mirrors, engine, row, _target, counters = fixture(tmp_path, monkeypatch)
    identity = mirrors.identity(row["identity_id"])
    mirrors.configure(
        identity_id=identity["id"],
        name=row["name"],
        target=mirrors._grant(identity)["destinations"][row["id"]]["target"],
        scope=row["scope"],
        include_rules=row["include_rules"],
        mode="scheduled",
        interval_seconds=300,
        destination_id=row["id"],
        expected_revision=1,
        confirmed=True,
    )
    monkeypatch.setattr(mirror_rsync, "RsyncMirrors", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(mirror_ssh_runtime, "window_open", lambda *_args: inside_window)
    bridge = MirrorJobs(instance.store, mirrors=mirrors)
    policy = bridge.policy()
    instance.scheduler._mirror_manager_factory = lambda _store: bridge
    counters["interrupt"] = True
    before = counters["rpcs"]
    job = bridge.scheduler.run_now(policy["id"])["job"]
    executed = instance.scheduler.run_one(job_id=job["id"])
    if not inside_window:
        assert executed["status"] == "succeeded"
        assert counters["rpcs"] == before and counters["transfers"] == 0
        assert not mirrors.operation_ledger(row["id"]).get("schedule_fence")
        return
    assert executed["status"] == "manual_intervention" and counters["transfers"] == 1
    assert mirrors.operation_ledger(row["id"])["schedule_fence"]
    counters["interrupt"] = False
    job = bridge.scheduler.run_now(policy["id"], request_key="synthetic-no-automatic-resume")["job"]
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "manual_intervention"
    assert counters["transfers"] == 1
