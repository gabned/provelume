"""Fresh local Git transport conformance; no hosted account/destination qualification."""

import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from provelume.migration_permissions import make_private
from provelume.mirror_contract import MirrorError, sha
from provelume.mirror_git import GitMirrors, git_work, remote_ref
from provelume.mirror_git_runtime import GitSession


def publish(git, plan):
    return git.publish(
        plan["id"],
        expected_plan_sha256=plan["plan_sha256"],
        expected_git_plan_sha256=plan["git_plan_sha256"],
        confirmed=True,
    )


def initialized(tmp_path):
    instance, mirrors, git, destination = git_fixture(tmp_path)
    git.initialize_local(
        destination["id"],
        expected_destination_sha256=destination["destination_sha256"],
        confirmed=True,
    )
    return instance, mirrors, git, destination


def test_real_publication_noop_and_historical_receipt_without_resend(tmp_path):
    _instance, mirrors, git, destination = initialized(tmp_path)
    before = mirrors.snapshots.source_fingerprint()
    first = git.prepare(destination["id"], expected_revision=1, confirmed=True)
    result = publish(git, first)
    assert result["live_destination_checked"]
    witness = result["receipt"]["transport_proof"]
    assert witness["commit_written"] is True
    assert witness["commit_sha"] == witness["observed_head"]
    assert mirrors.operation_ledger(destination["id"])["serial"] == 1
    assert publish(git, first) == {
        "receipt": result["receipt"],
        "historical": True,
        "process_used": False,
        "live_destination_checked": False,
    }
    second = git.prepare(destination["id"], expected_revision=1, confirmed=True)
    assert second["generation"] == first["generation"]
    repeat = publish(git, second)
    assert repeat["receipt"]["transport_proof"]["commit_written"] is False
    assert repeat["receipt"]["transport_proof"]["commit_sha"] == witness["commit_sha"]
    assert mirrors.snapshots.source_fingerprint() == before


def test_legacy_branches_directory_is_admitted_only_when_empty(tmp_path, monkeypatch):
    _instance, _mirrors, git, destination = initialized(tmp_path)
    branches = tmp_path / "Destination.git" / "branches"
    branches.mkdir(exist_ok=True)
    assert git.prepare(destination["id"], expected_revision=1, confirmed=True)["publication"]
    unexpected = branches / "unknown-remote"
    unexpected.write_text("https://example.invalid/never-contacted\n")

    def forbidden(*_args, **_kwargs):
        pytest.fail("Legacy branch content reached native Git")

    monkeypatch.setattr(GitSession, "run", forbidden)
    with pytest.raises(MirrorError, match="unsafe_git_target"):
        git.prepare(destination["id"], expected_revision=1, confirmed=True)
    assert unexpected.read_text() == "https://example.invalid/never-contacted\n"


def git_fixture(tmp_path):
    from provelume.mirror_git import GitMirrors
    from provelume.mirrors import Mirrors
    from provelume.service import ProvelumeInstance
    from provelume.tududi_qualification import SyntheticVault

    inputs = tmp_path / "Inputs"
    inputs.mkdir()
    (inputs / "one.md").write_text("# Synthetic Git mirror\n\nBounded readable body.\n")
    instance = ProvelumeInstance.initialise(tmp_path / "Instance")
    instance.ingest_run(inputs)
    mirrors = Mirrors(instance.store, vault=SyntheticVault())
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    identity = mirrors.create_identity(
        name="Synthetic Git identity", profile="git", credential={"reference": ""}, confirmed=True
    )
    destination = mirrors.configure(
        identity_id=identity["id"],
        name="Synthetic Git destination",
        target={
            "transport": "local",
            "repository": str(tmp_path / "Destination.git"),
            "branch": "concordia",
            "path": "knowledge",
            "commit_name": "Synthetic Mirror",
            "commit_email": "mirror@example.invalid",
        },
        scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode="manual",
        confirmed=True,
    )
    return instance, mirrors, GitMirrors(instance.store, mirrors=mirrors), destination


def test_real_private_bare_target_initialization_and_first_readonly_preview(tmp_path):
    instance, mirrors, git, destination = git_fixture(tmp_path)
    before = mirrors.snapshots.source_fingerprint()
    result = git.initialize_local(
        destination["id"],
        expected_destination_sha256=destination["destination_sha256"],
        confirmed=True,
    )
    assert result["status"] == "initialized" and not result["network_used"]
    assert (tmp_path / "Destination.git/HEAD").is_file()
    plan = git.prepare(destination["id"], expected_revision=1, confirmed=True)
    assert plan["git_plan"]["head"] is None
    assert plan["git_plan"]["branch"] == "concordia"
    assert plan["observation"]["visibility"] == "private"
    assert plan["observation"]["inventory"] == []
    assert mirrors.snapshots.source_fingerprint() == before
    assert mirrors.operation_ledger(destination["id"])["serial"] == 0
    assert instance.store.list_canonical("documents")


def test_native_git_version_bare_objects_and_bounded_input(tmp_path):
    make_private(tmp_path)
    session = GitSession(tmp_path)
    observed = session.run(["--version"])[1].decode("ascii").strip()
    print(json.dumps({"optional_git_runtime": observed, "binary": session.binary}))
    assert session.probe() in {"2.51.1", "2.52.0", "2.56.0", "2.56.0.windows.4"}
    session.initialize_work()
    _code, oid = session.run(
        ["hash-object", "-w", "--stdin", "--no-filters"],
        input_bytes=b"synthetic local Git payload\n",
    )
    assert len(oid.strip()) == 40
    assert session.blob(oid.strip().decode()) == b"synthetic local Git payload\n"


@contextmanager
def observe(tmp_path, git, destination):
    from provelume.mirror_git_target import local_target

    _row, _authority, target = git.context(destination["id"])
    with (
        local_target(target, store=git.store, device=git.mirrors.device()) as pinned,
        git_work(descriptors=pinned["descriptors"]) as session,
    ):
        session.probe()
        session.initialize_work()
        yield session, pinned, target


@pytest.mark.parametrize("restore", [False, True])
def test_interruption_after_native_push_reconciles_without_resend_even_after_same_root_restore(
    tmp_path, monkeypatch, restore
):
    instance, mirrors, git, destination = initialized(tmp_path)
    plan = git.prepare(destination["id"], expected_revision=1, confirmed=True)
    backup = instance.backup(destination=tmp_path / "Before send") if restore else None
    original = GitSession.run
    sends = []

    def interrupted(session, arguments, **options):
        result = original(session, arguments, **options)
        if arguments[0] == "push":
            sends.append(True)
            raise MirrorError("deadline")
        return result

    monkeypatch.setattr(GitSession, "run", interrupted)
    with pytest.raises(MirrorError, match="deadline"):
        publish(git, plan)
    assert sends == [True]
    if restore:
        assert instance.restore(backup["archive"])["status"] == "restored"
        assert mirrors.plan(plan["id"])["state"] == "prepared"
        assert mirrors._load("git/operations/" + plan["id"] + ".json") is None
    restarted = GitMirrors(instance.store, mirrors=mirrors)
    with pytest.raises(MirrorError):
        publish(restarted, plan)
    recovered = restarted.reconcile(plan["id"], confirmed=True)
    assert recovered["receipt"]["generation"] == plan["generation"]
    assert recovered["receipt"]["transport_proof"]["commit_written"]
    assert recovered["live_destination_checked"] and not recovered["resend_allowed"]
    assert recovered["receipt"]["transport_proof"]["evidence_mode"] == "reconciled_current_state"
    assert recovered["receipt"]["transport_proof"]["publication_time"] is None
    assert sends == [True]
    assert restarted.reconcile(plan["id"], confirmed=True)["historical"]
    assert sends == [True]


def test_interruption_before_send_stays_unknown_and_never_replays(tmp_path, monkeypatch):
    _instance, mirrors, git, destination = initialized(tmp_path)
    plan = git.prepare(destination["id"], expected_revision=1, confirmed=True)
    original = GitSession.run
    sends = []

    def interrupted(session, arguments, **options):
        if arguments[0] == "push":
            sends.append(True)
            raise MirrorError("deadline")
        return original(session, arguments, **options)

    monkeypatch.setattr(GitSession, "run", interrupted)
    with pytest.raises(MirrorError, match="deadline"):
        publish(git, plan)
    result = git.reconcile(plan["id"], confirmed=True)
    assert result["outcome"] == "UNKNOWN" and not result["resend_allowed"]
    with pytest.raises(MirrorError):
        publish(git, plan)
    with pytest.raises(MirrorError):
        git.prepare(destination["id"], expected_revision=1, confirmed=True)
    assert sends == [True]
    assert mirrors.operation_ledger(destination["id"])["inflight"]["operation_id"] == plan["id"]


def test_native_ref_lease_rejects_competing_writer_and_new_preview_preserves_its_history(
    tmp_path, monkeypatch
):
    _instance, mirrors, git, destination = initialized(tmp_path)
    plan = git.prepare(destination["id"], expected_revision=1, confirmed=True)
    original = GitSession.run
    competing = []

    def compete(session, arguments, **options):
        if arguments[0] == "push" and not competing:
            # Independent synthetic actor changes the actual native ref after claim.
            root = tmp_path / "Destination.git"
            session.environment.update(
                {
                    "GIT_AUTHOR_NAME": "Other Actor",
                    "GIT_AUTHOR_EMAIL": "other@example.invalid",
                    "GIT_COMMITTER_NAME": "Other Actor",
                    "GIT_COMMITTER_EMAIL": "other@example.invalid",
                }
            )
            oid = original(
                session,
                ["hash-object", "-w", "--stdin"],
                input_bytes=b"Retained unrelated content\n",
                git_directory=root,
            )[1].strip()
            tree = (
                original(
                    session,
                    ["mktree"],
                    input_bytes=b"100644 blob " + oid + b"\tREADME.md\n",
                    git_directory=root,
                )[1]
                .strip()
                .decode()
            )
            commit = (
                original(
                    session,
                    ["commit-tree", tree],
                    input_bytes=b"Independent concurrent change\n",
                    git_directory=root,
                )[1]
                .strip()
                .decode()
            )
            original(session, ["update-ref", "refs/heads/concordia", commit], git_directory=root)
            competing.append(commit)
        return original(session, arguments, **options)

    monkeypatch.setattr(GitSession, "run", compete)
    result = publish(git, plan)
    assert result["receipt"]["schema"] == "provelume-mirror-not-applied/v1"
    assert result["receipt"]["reason"] == "conflict"
    assert mirrors.operation_ledger(destination["id"])["inflight"] is None
    with observe(tmp_path, git, destination) as (session, pinned, target):
        assert remote_ref(session, pinned["uri"], target["branch"]) == competing[0]
    fresh = git.prepare(destination["id"], expected_revision=1, confirmed=True)
    assert fresh["git_plan"]["head"] == competing[0]
    success = publish(git, fresh)
    with observe(tmp_path, git, destination) as (session, pinned, target):
        from provelume.mirror_git import fetch_ref

        head = success["receipt"]["transport_proof"]["commit_sha"]
        entries = fetch_ref(session, pinned["uri"], target["branch"], head)
        assert session.blob(entries["README.md"]["oid"]) == b"Retained unrelated content\n"
        header = session.run(["cat-file", "-p", head])[1].decode().split("\n\n", 1)[0]
        assert "parent " + competing[0] in header


def test_candidate_verification_failure_precedes_claim_and_ref_update(tmp_path, monkeypatch):
    _instance, mirrors, git, destination = initialized(tmp_path)
    plan = git.prepare(destination["id"], expected_revision=1, confirmed=True)

    def incomplete(*_args, **_kwargs):
        raise MirrorError("git_incomplete")

    monkeypatch.setattr(GitSession, "verify_blobs", incomplete)
    with pytest.raises(MirrorError, match="git_incomplete"):
        publish(git, plan)
    assert mirrors.operation_ledger(destination["id"])["serial"] == 0
    with observe(tmp_path, git, destination) as (session, pinned, target):
        assert remote_ref(session, pinned["uri"], target["branch"]) is None


@pytest.mark.parametrize("damage", ["hook", "alternate", "config", "marker", "privacy"])
def test_unsafe_or_replaced_targets_fail_before_any_native_operation(tmp_path, monkeypatch, damage):
    if damage == "privacy" and os.name == "nt":
        pytest.skip("POSIX mode case; Windows private DACL is independently native-qualified")
    _instance, mirrors, git, destination = initialized(tmp_path)
    root = tmp_path / "Destination.git"
    if damage == "hook":
        (root / "hooks/pre-receive").write_text("exit 0\n")
    elif damage == "alternate":
        (root / "objects/info/alternates").write_text(str(tmp_path / "Unknown") + "\n")
    elif damage == "config":
        with (root / "config").open("a") as stream:
            stream.write("\n[credential]\n\thelper = unsafe\n")
    elif damage == "marker":
        marker = json.loads((root / "provelume-mirror-target.json").read_text())
        marker["root_sha256"] = "0" * 64
        (root / "provelume-mirror-target.json").write_text(json.dumps(marker))
    else:
        root.chmod(0o755)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Unsafe root reached Git")

    monkeypatch.setattr(GitSession, "run", forbidden)
    with pytest.raises((MirrorError, ValueError)):
        git.prepare(destination["id"], expected_revision=1, confirmed=True)
    assert mirrors.operation_ledger(destination["id"])["serial"] == 0


def test_disabled_transport_and_passive_status_do_not_read_credentials_or_spawn(
    tmp_path, monkeypatch
):
    _instance, mirrors, git, destination = initialized(tmp_path)
    mirrors.set_access(
        enabled=False, github=False, rsync=False, expected_revision=1, confirmed=True
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("Passive/disabled path touched credentials or Git")

    monkeypatch.setattr(mirrors.vault, "read", forbidden)
    monkeypatch.setattr(GitSession, "run", forbidden)
    assert git.status()["process_used"] is False
    assert mirrors.view()["access"]["enabled"] is False
    with pytest.raises(MirrorError, match="local_only"):
        git.prepare(destination["id"], expected_revision=1, confirmed=True)


def test_batch_verification_rejects_changed_payload_and_oversized_object(tmp_path):
    make_private(tmp_path)
    session = GitSession(tmp_path)
    session.initialize_work()
    data = b"Synthetic verified bytes\n"
    oid = session.run(["hash-object", "-w", "--stdin"], input_bytes=data)[1].strip().decode()
    row = {"oid": oid, "size_bytes": len(data), "sha256": sha(data)}
    session.verify_blobs([row, row])
    with pytest.raises(MirrorError, match="git_incomplete"):
        session.verify_blobs([{**row, "sha256": "0" * 64}])
    with pytest.raises(MirrorError, match="git_incomplete"):
        session.verify_blobs([{**row, "size_bytes": 1}])


@pytest.mark.parametrize(
    "observed",
    [
        b"git version 2.43.0\n",
        b"git version 2.99.0\n",
        b"git version 2.56.1\n",
        b"git version unknown\n",
    ],
)
def test_unqualified_git_versions_remain_rejected_before_operations(
    tmp_path, monkeypatch, observed
):
    make_private(tmp_path)
    session = GitSession(tmp_path)
    monkeypatch.setattr(session, "run", lambda *_args, **_kwargs: (0, observed))
    with pytest.raises(MirrorError, match="git_version_unsupported"):
        session.probe()


@pytest.mark.parametrize("mutation", ["source", "revision", "revoke", "credentials"])
def test_material_changes_fail_before_claim_and_preserve_ref(tmp_path, mutation):
    instance, mirrors, git, destination = initialized(tmp_path)
    plan = git.prepare(destination["id"], expected_revision=1, confirmed=True)
    identity = mirrors.identity(destination["identity_id"])
    if mutation == "source":
        (tmp_path / "Inputs/two.md").write_text("# New source observation\n")
        instance.ingest_run(tmp_path / "Inputs")
    elif mutation == "revision":
        mirrors.disable(destination["id"], expected_revision=1, confirmed=True)
    elif mutation == "revoke":
        mirrors.revoke(identity["id"], expected_revision=1, confirmed=True)
    else:
        grant = mirrors._grant(identity)
        grant["credential"] = {"reference": "SyntheticExternalReference"}
        mirrors.vault.write(mirrors.slot(identity["id"]), grant)
    with pytest.raises(MirrorError):
        publish(git, plan)
    assert not (tmp_path / "Destination.git/refs/heads/concordia").exists()
    # Revocation deliberately erases external operation authority; no claim was made.
    if mutation != "revoke":
        assert mirrors.operation_ledger(destination["id"])["serial"] == 0


def test_actual_scheduler_publishes_only_consented_local_git_and_respects_interval(tmp_path):
    from provelume.mirror_jobs import MirrorJobs

    instance, mirrors, git, destination = initialized(tmp_path)
    identity = mirrors.identity(destination["identity_id"])
    destination = mirrors.configure(
        identity_id=identity["id"],
        name=destination["name"],
        target=mirrors._grant(identity)["destinations"][destination["id"]]["target"],
        scope=destination["scope"],
        include_rules=destination["include_rules"],
        mode="scheduled",
        interval_seconds=300,
        destination_id=destination["id"],
        expected_revision=1,
        confirmed=True,
    )
    bridge = MirrorJobs(instance.store, mirrors=mirrors)
    policy = bridge.policy()
    instance.scheduler._mirror_manager_factory = lambda _store: bridge
    job = bridge.scheduler.run_now(policy["id"])["job"]
    result = instance.scheduler.run_one(job_id=job["id"])
    assert result["status"] == "succeeded"
    plans = mirrors.plans()
    assert len(plans) == 1 and plans[0]["scheduled"] and plans[0]["state"] == "completed"
    assert (
        mirrors._load("scheduled/" + destination["id"] + ".json")["publication"]
        == "COMPLETED_GIT_LOCAL"
    )
    job = bridge.scheduler.run_now(policy["id"], request_key="Synthetic next interval")["job"]
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "succeeded"
    assert mirrors.operation_ledger(destination["id"])["serial"] == 1


def test_real_http_closed_csrf_git_preview_publication_and_passive_receipt(tmp_path, monkeypatch):
    import re

    from fastapi.testclient import TestClient

    from provelume.web import create_app

    instance, mirrors, git, destination = initialized(tmp_path)
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._mirrors_manager = mirrors
    client = TestClient(app)
    page = client.get("/mirrors?lang=it")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert (
        client.post("/mirrors", data={"action": "git-prepare", "confirm": "yes"}).status_code == 403
    )
    prepared = client.post(
        "/mirrors?lang=it",
        data={
            "csrf_token": csrf,
            "action": "git-prepare",
            "destination_id": destination["id"],
            "revision": "1",
            "confirm": "yes",
        },
    )
    assert prepared.status_code == 200 and 'id="mirror-git-plan"' in prepared.text
    assert "mirror.git_branch" not in prepared.text and "mirror@example.invalid" in prepared.text
    plan, git_plan = git.git_plan(mirrors.plans()[0]["id"])
    from provelume.mirror_contract import fingerprint

    form = {
        "csrf_token": csrf,
        "action": "git-publish",
        "plan_id": plan["id"],
        "plan_sha256": fingerprint(plan),
        "git_plan_sha256": fingerprint(git_plan),
        "confirm": "yes",
    }
    denied = client.post("/mirrors", data={**form, "public_confirmed": "yes"})
    assert denied.status_code == 200 and mirrors.operation_ledger(destination["id"])["serial"] == 0
    result = client.post("/mirrors?lang=it", data=form)
    assert result.status_code == 200 and 'id="mirror-git-receipt"' in result.text
    assert mirrors.plan(plan["id"])["state"] == "completed"
    reads = mirrors.vault.reads

    def forbidden(*_args, **_kwargs):
        pytest.fail("Passive Git preview ran a process")

    monkeypatch.setattr(GitSession, "run", forbidden)
    for lang in ["en", "it", "de", "fr", "es", "pt", "ro"]:
        response = client.get("/mirrors?lang=" + lang + "&plan=" + plan["id"])
        assert response.status_code == 200 and 'id="mirror-git-receipt"' in response.text
        assert "mirror.git_state_" not in response.text
    assert mirrors.vault.reads == reads


def test_scheduler_native_conflict_fence_survives_real_backup_restore(tmp_path, monkeypatch):
    from provelume.mirror_contract import fingerprint
    from provelume.mirror_jobs import MirrorJobs

    instance, mirrors, _git, destination = initialized(tmp_path)
    identity = mirrors.identity(destination["identity_id"])
    destination = mirrors.configure(
        identity_id=identity["id"],
        name=destination["name"],
        target=mirrors._grant(identity)["destinations"][destination["id"]]["target"],
        scope=destination["scope"],
        include_rules=destination["include_rules"],
        mode="scheduled",
        interval_seconds=300,
        destination_id=destination["id"],
        expected_revision=1,
        confirmed=True,
    )
    bridge = MirrorJobs(instance.store, mirrors=mirrors)
    policy = bridge.policy()
    instance.scheduler._mirror_manager_factory = lambda _store: bridge
    backup = instance.backup(destination=tmp_path / "Before conflict")
    native = GitSession.run
    competing = []

    def compete(session, arguments, **options):
        if arguments[0] == "push" and not competing:
            root = tmp_path / "Destination.git"
            tree = (
                native(session, ["mktree"], input_bytes=b"", git_directory=root)[1].strip().decode()
            )
            commit = (
                native(
                    session,
                    ["commit-tree", tree],
                    input_bytes=b"Synthetic competing writer\n",
                    git_directory=root,
                )[1]
                .strip()
                .decode()
            )
            native(session, ["update-ref", "refs/heads/concordia", commit], git_directory=root)
            competing.append(commit)
        return native(session, arguments, **options)

    monkeypatch.setattr(GitSession, "run", compete)
    job = bridge.scheduler.run_now(policy["id"])["job"]
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "manual_intervention"
    operations = mirrors.operation_ledger(destination["id"])
    assert operations["last_receipt"]["schema"] == "provelume-mirror-not-applied/v1"
    assert operations["schedule_fence"] == fingerprint(destination)
    assert operations["inflight"] is None
    assert instance.restore(backup["archive"])["status"] == "restored"
    assert mirrors._load("scheduled/" + destination["id"] + ".json") is None

    def forbidden(*_args, **_kwargs):
        pytest.fail("Restoring a checkpoint retried scheduled Git after conflict")

    monkeypatch.setattr(GitSession, "run", forbidden)
    policy = bridge.policy()
    job = bridge.scheduler.run_now(policy["id"], request_key="Synthetic after restore")["job"]
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "manual_intervention"
    assert mirrors.operation_ledger(destination["id"])["serial"] == 1


def test_source_frozen_entry_qualifies_actual_git_and_preserves_manual_status(tmp_path):
    from provelume.ocr_desktop import run_ocr_command

    result = tmp_path / "git-result.json"
    assert run_ocr_command(["git-mirror-qualify", str(tmp_path / "Fresh native Git")], result) == 0
    report = json.loads(result.read_bytes())
    assert report["result"] == "PASS" and report["transport_process_used"]
    assert report["execution_adapter"] == "native_git_file" and not report["network_used"]
    assert report["same_root_restore_readonly_reconciliation"] == "PASS"
    assert report["windows_11_home_pro_25h2_manual"] == "DEFERRED_BY_MAINTAINER / NOT_RUN"


def test_cli_and_frozen_status_have_no_git_process(tmp_path, monkeypatch, capsys):
    from provelume.cli import main
    from provelume.ocr_desktop import run_ocr_command

    instance, _mirrors, _git, _destination = initialized(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Status ran Git")

    monkeypatch.setattr(GitSession, "run", forbidden)
    assert main(["mirror-git-status", str(instance.root)]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["git"] == "OPTIONAL_NOT_PROBED"
    result = tmp_path / "git-status.json"
    assert run_ocr_command(["mirror-git-status", str(instance.root)], result) == 0
    assert json.loads(result.read_bytes())["result"]["process_used"] is False


def test_git_target_cannot_feed_back_into_observed_source_or_replace_canonical_data(tmp_path):
    instance, mirrors, git, destination = git_fixture(tmp_path)
    identity = mirrors.identity(destination["identity_id"])
    original = mirrors._grant(identity)["destinations"][destination["id"]]["target"]
    for target in [
        tmp_path / "Inputs/Feedback.git",
        instance.root / "Nested.git",
        instance.root.parent,
    ]:
        row = mirrors.configure(
            identity_id=identity["id"],
            name="Synthetic unsafe target",
            target={**original, "repository": str(target)},
            scope=destination["scope"],
            include_rules=destination["include_rules"],
            mode="manual",
            confirmed=True,
        )
        with pytest.raises(MirrorError, match="unsafe_git_target"):
            git.initialize_local(
                row["id"], expected_destination_sha256=row["destination_sha256"], confirmed=True
            )
    assert not (tmp_path / "Inputs/Feedback.git").exists()


def test_lifecycle_join_rejects_another_thread_and_expired_copied_context(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    from provelume.instance_lifecycle import (
        InstanceLifecycleBusy,
        InstanceLifecycleManager,
        lifecycle_guard,
    )
    from provelume.service import ProvelumeInstance

    instance = ProvelumeInstance.initialise(tmp_path / "Instance")
    manager = InstanceLifecycleManager(instance.store)

    def enter():
        with lifecycle_guard(instance.store, purpose="synthetic Git joining"):
            return True

    with manager._hold(purpose="synthetic scheduler"):
        assert enter()
        active_copy = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(InstanceLifecycleBusy):
            pool.submit(active_copy.run, enter).result()
        expired_copy = copy_context()
    with manager._hold(purpose="different live ownership"), pytest.raises(InstanceLifecycleBusy):
        expired_copy.run(enter)


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX process-group cleanup")
def test_native_deadline_terminates_owned_git_process_and_descendant(tmp_path):
    make_private(tmp_path)
    marker = tmp_path / "child-pid"
    executable = tmp_path / "synthetic-git"
    executable.write_text("#!/bin/sh\n/bin/sleep 60 &\necho $! > '" + str(marker) + "'\nwait\n")
    executable.chmod(0o700)
    session = GitSession(tmp_path, deadline=time.monotonic() + 0.3)
    session.binary = str(executable)
    with pytest.raises(MirrorError, match="deadline"):
        session.run(["--version"])
    child = int(marker.read_text().strip())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = Path("/proc") / str(child) / "stat"
        if not state.exists() or state.read_text().split(")", 1)[1].strip().startswith("Z"):
            break
        time.sleep(0.01)
    else:
        pytest.fail("Owned Git descendant survived cleanup")
    assert not list(tmp_path.glob("*.out")) and not list(tmp_path.glob("*.err"))


@pytest.mark.skipif(os.name != "nt", reason="Native Windows creation-time Job containment")
@pytest.mark.parametrize("shared_log", [False, True])
def test_native_windows_job_kills_descendant_after_parent_exit(tmp_path, shared_log):
    import ctypes as c

    from provelume.ai_windows_api import B, D, H, libraries
    from provelume.mirror_git_runtime import child_environment
    from provelume.mirror_git_windows import WindowsGitProcess

    marker = tmp_path / "child-pid"
    script = (
        "import subprocess,sys,pathlib;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "pathlib.Path(" + repr(str(marker)) + ").write_text(str(child.pid))"
    )
    kernel, *_ = libraries()
    query = c.WinDLL("kernel32", use_last_error=True).OpenProcess
    query.argtypes, query.restype = [D, B, D], H
    with (
        open(os.devnull, "rb") as incoming,
        (tmp_path / "out").open("wb") as output,
        (tmp_path / "err").open("wb") as errors,
    ):
        process = WindowsGitProcess(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            environment=child_environment(tmp_path),
            incoming=incoming,
            output=output,
            errors=output if shared_log else errors,
        )
        child = None
        try:
            deadline = time.monotonic() + 10
            while (not marker.exists() or process.poll() is None) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert marker.exists() and process.poll() == 0
            child = query(0x100000 | 0x1000, False, int(marker.read_text()))
            assert child
            member = B()
            assert kernel.IsProcessInJob(child, process.job, c.byref(member)) and member.value
            process.close()
            assert kernel.WaitForSingleObject(child, 2000) == 0
        finally:
            process.close()
            if child:
                kernel.CloseHandle(child)
