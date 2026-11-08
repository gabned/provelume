"""Native folder activation, corruption and interruption boundaries on synthetic data."""

import errno
import json
import os
from unittest.mock import patch

import pytest

from provelume.maintenance_local_files import MaintenanceTargetError
from provelume.mirror_contract import MirrorError
from provelume.mirror_folder import FolderMirrors
from provelume.mirror_folder_files import FolderTree
from provelume.mirrors import Mirrors
from provelume.service import ProvelumeInstance
from provelume.tududi_qualification import SyntheticVault


def fixture(root):
    inputs = root / "Inputs"
    inputs.mkdir()
    (inputs / "one.md").write_text("# Synthetic local folder\n\nOne bounded input.\n")
    instance = ProvelumeInstance.initialise(root / "Instance")
    instance.ingest_run(inputs)
    mirrors = Mirrors(instance.store, vault=SyntheticVault())
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    identity = mirrors.create_identity(
        name="Synthetic folder", profile="folder", credential={"reference": ""}, confirmed=True
    )
    target = root / "Fresh destination"
    row = mirrors.configure(
        identity_id=identity["id"],
        name="Synthetic folder destination",
        target={"transport": "folder", "path": str(target)},
        scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode="manual",
        confirmed=True,
    )
    engine = FolderMirrors(instance.store, mirrors=mirrors)
    return instance, mirrors, engine, row, target


def initialize(engine, row):
    return engine.initialize_local(
        row["id"], expected_destination_sha256=row["destination_sha256"], confirmed=True
    )


def prepare(engine, row):
    return engine.prepare(row["id"], expected_revision=row["revision"], confirmed=True)


def publish(engine, plan):
    return engine.publish(
        plan["id"],
        expected_plan_sha256=plan["plan_sha256"],
        expected_folder_plan_sha256=plan["folder_plan_sha256"],
        confirmed=True,
    )


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_native_folder_complete_generation_noop_history_and_canonical_unchanged(tmp_path):
    _instance, mirrors, engine, row, target = fixture(tmp_path)
    before = mirrors.snapshots.source_fingerprint()
    assert initialize(engine, row)["status"] == "initialized"
    first_plan = prepare(engine, row)
    first = publish(engine, first_plan)["receipt"]
    assert first["transport_proof"]["profile"] == "folder-local/v1"
    assert first["transport_proof"]["activation_written"]
    assert first["source_manifest_sha256"] == first["destination_manifest_sha256"]
    assert not first["backup_proof"] and not first["destination_deletion"]
    complete = snapshot(target)
    assert publish(engine, first_plan)["historical"]
    second = publish(engine, prepare(engine, row))["receipt"]
    assert not second["transport_proof"]["activation_written"]
    assert snapshot(target) == complete
    assert mirrors.snapshots.source_fingerprint() == before


@pytest.mark.parametrize("after_activation", [False, True])
def test_interrupt_and_real_root_restore_never_replay_and_preserve_old_generation(
    tmp_path, after_activation
):
    instance, mirrors, engine, row, target = fixture(tmp_path)
    initialize(engine, row)
    publish(engine, prepare(engine, row))
    old_pointer = (target / "active.json").read_bytes()
    old_generation = json.loads(old_pointer)["generation"]
    (tmp_path / "Inputs" / "two.md").write_text("# Synthetic second generation\n")
    instance.ingest_run(tmp_path / "Inputs")
    plan = prepare(engine, row)
    backup = instance.backup(destination=tmp_path / "Before send")
    original, activations = FolderTree.rename, []

    def interrupted(tree, source, destination, **options):
        if destination != "active.json":
            return original(tree, source, destination, **options)
        activations.append(True)
        if after_activation:
            original(tree, source, destination, **options)
        raise OSError(errno.ENOSPC, "Synthetic activation fault")

    with (
        patch.object(FolderTree, "rename", interrupted),
        pytest.raises((OSError, MaintenanceTargetError)),
    ):
        publish(engine, plan)
    assert len(activations) == 1
    assert (target / "generations" / old_generation / "manifest.json").is_file()
    if not after_activation:
        assert (target / "active.json").read_bytes() == old_pointer
    assert instance.restore(backup["archive"])["status"] == "restored"
    with (
        patch.object(FolderTree, "write", side_effect=AssertionError("recovery wrote")),
        patch.object(FolderTree, "rename", side_effect=AssertionError("recovery activated")),
    ):
        result = engine.reconcile(plan["id"], confirmed=True)
        assert not result["resend_allowed"]
        if after_activation:
            assert (
                result["receipt"]["transport_proof"]["evidence_mode"] == "reconciled_current_state"
            )
            assert publish(engine, plan)["historical"]
        else:
            assert result["outcome"] == "UNKNOWN"
            with pytest.raises(MirrorError, match="outcome_unknown"):
                publish(engine, plan)


def test_unknown_existing_destination_is_not_adopted(tmp_path):
    _instance, _mirrors, engine, row, target = fixture(tmp_path)
    target.mkdir()
    unknown = target / "do-not-touch.txt"
    unknown.write_bytes(b"unrelated synthetic content")
    with pytest.raises(MirrorError, match="folder_exists"):
        initialize(engine, row)
    assert unknown.read_bytes() == b"unrelated synthetic content"
    assert set(target.iterdir()) == {unknown}


def test_modified_manifest_or_payload_is_refused_before_another_claim(tmp_path):
    _instance, mirrors, engine, row, target = fixture(tmp_path)
    initialize(engine, row)
    publish(engine, prepare(engine, row))
    pointer = json.loads((target / "active.json").read_bytes())
    generation = target / "generations" / pointer["generation"]
    manifest = json.loads((generation / "manifest.json").read_bytes())
    (generation / manifest["inventory"][0]["path"]).write_bytes(b"changed")
    serial = mirrors.operation_ledger(row["id"])["serial"]
    with pytest.raises(MirrorError, match="folder_incomplete"):
        prepare(engine, row)
    assert mirrors.operation_ledger(row["id"])["serial"] == serial


@pytest.mark.skipif(
    os.name == "nt", reason="Native POSIX symlink fixture; Windows reparse is separate"
)
@pytest.mark.parametrize("hardlink", [False, True])
def test_hostile_alias_never_reads_or_changes_unrelated_target(tmp_path, hardlink):
    _instance, mirrors, engine, row, target = fixture(tmp_path)
    initialize(engine, row)
    canary = tmp_path / "Unrelated synthetic canary"
    canary.write_bytes(b"unrelated synthetic bytes")
    alias = target / "staging" / "hostile"
    if hardlink:
        os.link(canary, alias)
    else:
        alias.symlink_to(canary)
    with pytest.raises((MirrorError, OSError)):
        prepare(engine, row)
    assert canary.read_bytes() == b"unrelated synthetic bytes"
    assert mirrors.operation_ledger(row["id"])["serial"] == 0


def test_disabled_local_only_and_passive_status_do_not_touch_the_target(tmp_path):
    _instance, mirrors, engine, row, _target = fixture(tmp_path)
    mirrors.set_access(
        enabled=False, github=False, rsync=False, expected_revision=1, confirmed=True
    )
    with patch.object(engine, "tree", side_effect=AssertionError("disabled target probe")):
        assert not engine.status()["target_probed"]
        with pytest.raises(MirrorError, match="local_only"):
            initialize(engine, row)
        with pytest.raises(MirrorError, match="local_only"):
            prepare(engine, row)


def test_transport_plan_graft_is_rejected_by_external_claim_before_target_access(tmp_path):
    _instance, mirrors, engine, row, _target = fixture(tmp_path)
    initialize(engine, row)
    plan = prepare(engine, row)
    with (
        patch.object(engine, "transfer", side_effect=MirrorError("deadline")),
        pytest.raises(MirrorError, match="deadline"),
    ):
        publish(engine, plan)
    folder_plan = mirrors._load("folder/plans/" + plan["id"] + ".json")
    folder_plan["inventory_sha256"] = "a" * 64
    mirrors._save("folder/plans/" + plan["id"] + ".json", folder_plan)
    with (
        patch.object(engine, "tree", side_effect=AssertionError("grafted target access")),
        pytest.raises(MirrorError, match="stale"),
    ):
        engine.reconcile(plan["id"], confirmed=True)


def test_native_namespace_lock_refuses_concurrent_writer(tmp_path):
    _instance, _mirrors, engine, row, _target = fixture(tmp_path)
    initialize(engine, row)
    _row, _authority, target = engine.context(row["id"])
    with (
        engine.tree(row, target),
        pytest.raises((OSError, MaintenanceTargetError)),
        engine.tree(row, target),
    ):
        pytest.fail("second namespace writer admitted")


def test_canonical_and_registered_source_paths_are_never_enrolled(tmp_path):
    _instance, mirrors, engine, row, _target = fixture(tmp_path)
    identity = mirrors.identity(row["identity_id"])
    for selected in [tmp_path / "Instance" / "forbidden", tmp_path / "Inputs" / "forbidden"]:
        row = mirrors.configure(
            identity_id=identity["id"],
            name=row["name"],
            target={"transport": "folder", "path": str(selected)},
            scope=row["scope"],
            include_rules=row["include_rules"],
            mode="manual",
            destination_id=row["id"],
            expected_revision=row["revision"],
            confirmed=True,
        )
        with pytest.raises(MirrorError, match="unsafe_git_target"):
            initialize(engine, row)
        assert not selected.exists()


def test_source_frozen_operator_and_cli_passive_status(tmp_path, monkeypatch, capsys):
    from provelume.cli import main
    from provelume.ocr_desktop import run_ocr_command

    output = tmp_path / "result.json"
    root = tmp_path / "Fresh operator"
    assert run_ocr_command(["folder-mirror-qualify", str(root)], output) == 0
    report = json.loads(output.read_bytes())
    assert report["result"] == "PASS" and report["filesystem"] == "ACTUAL_NATIVE"
    assert not report["network_used"] and not report["process_used"]
    assert all(
        case["activation_attempts"] == 1 and case["resends"] == 0 for case in report["cases"]
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("Passive folder status touched the destination")

    monkeypatch.setattr(FolderMirrors, "tree", forbidden)
    assert main(["mirror-folder-status", str(root / "Before activation" / "Instance")]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["profile"] == "folder-local/v1"


def test_local_csrf_ui_publishes_through_folder_backend_and_get_is_passive(tmp_path, monkeypatch):
    import re

    from fastapi.testclient import TestClient

    from provelume.mirror_contract import fingerprint
    from provelume.web import create_app

    instance, mirrors, engine, row, _target = fixture(tmp_path)
    initialize(engine, row)
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._mirrors_manager = mirrors
    monkeypatch.setattr(app.state.provelume, "folder_mirrors", lambda: engine)
    client = TestClient(app)
    page = client.get("/mirrors?lang=it")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert client.post("/mirrors", data={"action": "folder-prepare"}).status_code == 403
    result = client.post(
        "/mirrors?lang=it",
        data={
            "csrf_token": csrf,
            "action": "folder-prepare",
            "destination_id": row["id"],
            "revision": "1",
            "confirm": "yes",
        },
    )
    assert result.status_code == 200 and 'id="mirror-folder-plan"' in result.text
    plan, folder_plan = engine.folder_plan(mirrors.plans()[0]["id"])
    result = client.post(
        "/mirrors?lang=it",
        data={
            "csrf_token": csrf,
            "action": "folder-publish",
            "plan_id": plan["id"],
            "plan_sha256": fingerprint(plan),
            "folder_plan_sha256": fingerprint(folder_plan),
            "confirm": "yes",
        },
    )
    assert result.status_code == 200 and 'id="mirror-folder-receipt"' in result.text
    reads = mirrors.vault.reads
    with patch.object(engine, "tree", side_effect=AssertionError("passive target visit")):
        for language in ["en", "it", "de", "fr", "es", "pt", "ro"]:
            assert (
                client.get("/mirrors?lang=" + language + "&plan=" + plan["id"]).status_code == 200
            )
    assert mirrors.vault.reads == reads


@pytest.mark.parametrize("enrolled", [True, False])
def test_scheduled_native_folder_respects_interval_disable_and_failure_fence(tmp_path, enrolled):
    from provelume.mirror_jobs import MirrorJobs

    instance, mirrors, engine, row, target = fixture(tmp_path)
    identity = mirrors.identity(row["identity_id"])
    row = mirrors.configure(
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
    if enrolled:
        initialize(engine, row)
    bridge = MirrorJobs(instance.store, mirrors=mirrors)
    policy = bridge.policy()
    instance.scheduler._mirror_manager_factory = lambda _store: bridge
    assert policy["state"] == "enabled" and policy["retry"]["max_attempts"] == 1
    backup = instance.backup(destination=tmp_path / "Before scheduled attempt")
    job = bridge.scheduler.run_now(policy["id"])["job"]
    executed = instance.scheduler.run_one(job_id=job["id"])
    if not enrolled:
        assert executed["status"] == "manual_intervention"
        assert not target.exists() and mirrors.operation_ledger(row["id"])["serial"] == 0
        assert mirrors.operation_ledger(row["id"])["schedule_fence"]
        assert instance.restore(backup["archive"])["status"] == "restored"
        job = bridge.scheduler.run_now(policy["id"], request_key="synthetic-after-restore")["job"]
        assert instance.scheduler.run_one(job_id=job["id"])["status"] == "manual_intervention"
        assert not target.exists() and mirrors.operation_ledger(row["id"])["serial"] == 0
        return
    assert executed["status"] == "succeeded"
    assert len(mirrors.plans()) == 1 and mirrors.plans()[0]["scheduled"]
    assert (target / "active.json").is_file()
    job = bridge.scheduler.run_now(policy["id"], request_key="synthetic-next")["job"]
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "succeeded"
    assert len(mirrors.plans()) == 1
    mirrors.disable(row["id"], expected_revision=2, confirmed=True)
    assert bridge.policy()["state"] == "disabled"
    assert (target / "active.json").is_file()
