"""Native Git file transport on fresh synthetic roots; never a hosted qualification."""

from pathlib import Path
from unittest.mock import patch

from .mirror_contract import MirrorError, require
from .mirror_git import GitMirrors
from .mirror_git_runtime import GitSession
from .mirrors import Mirrors
from .service import ProvelumeInstance
from .tududi_qualification import SyntheticVault


def qualify_git_mirror(root):
    from .build_info import current_build_info

    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    inputs = root / "Synthetic Inputs"
    inputs.mkdir()
    (inputs / "one.md").write_text(
        "# Synthetic Git mirror\n\nReadable first generation.\n", encoding="utf-8"
    )
    instance = ProvelumeInstance.initialise(root / "Synthetic Space")
    instance.ingest_run(inputs)
    mirrors = Mirrors(instance.store, vault=SyntheticVault())
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    identity = mirrors.create_identity(
        name="Synthetic native Git", profile="git", credential={"reference": ""}, confirmed=True
    )
    destination = mirrors.configure(
        identity_id=identity["id"],
        name="Synthetic private bare Git",
        target={
            "transport": "local",
            "repository": str(root / "Synthetic Destination.git"),
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
    git = GitMirrors(instance.store, mirrors=mirrors)
    initialized = git.initialize_local(
        destination["id"],
        expected_destination_sha256=destination["destination_sha256"],
        confirmed=True,
    )

    def prepare():
        return git.prepare(destination["id"], expected_revision=1, confirmed=True)

    def publish(plan):
        return git.publish(
            plan["id"],
            expected_plan_sha256=plan["plan_sha256"],
            expected_git_plan_sha256=plan["git_plan_sha256"],
            confirmed=True,
        )

    before = mirrors.snapshots.source_fingerprint()
    first = publish(prepare())["receipt"]
    repeat = publish(prepare())["receipt"]
    require(
        first["transport_proof"]["commit_written"]
        and not repeat["transport_proof"]["commit_written"]
        and first["transport_proof"]["commit_sha"] == repeat["transport_proof"]["commit_sha"],
        "qualification",
    )
    require(mirrors.snapshots.source_fingerprint() == before, "qualification")
    (inputs / "two.md").write_text(
        "# Second synthetic generation\n\nNew explicitly acquired knowledge.\n", encoding="utf-8"
    )
    instance.ingest_run(inputs)
    before = mirrors.snapshots.source_fingerprint()
    plan = prepare()
    require(plan["generation"] != first["generation"], "qualification")
    backup = instance.backup(destination=root / "Synthetic before send backup")
    run, sends = GitSession.run, []

    def interrupted(session, arguments, **options):
        result = run(session, arguments, **options)
        if arguments[0] == "push":
            sends.append(True)
            raise MirrorError("deadline")
        return result

    with patch.object(GitSession, "run", interrupted):
        try:
            publish(plan)
        except MirrorError as error:
            require(error.code == "deadline", "qualification")
        else:
            require(False, "qualification")
        require(instance.restore(backup["archive"])["status"] == "restored", "qualification")
        require(mirrors._load("git/operations/" + plan["id"] + ".json") is None, "qualification")
        recovered = git.reconcile(plan["id"], confirmed=True)
        require(
            recovered["receipt"]["generation"] == plan["generation"]
            and recovered["live_destination_checked"]
            and sends == [True],
            "qualification",
        )
        require(publish(plan)["historical"] and sends == [True], "qualification")
    require(mirrors.snapshots.source_fingerprint() == before, "qualification")
    mirrors.set_access(
        enabled=False, github=False, rsync=False, expected_revision=1, confirmed=True
    )
    with patch.object(GitSession, "run", side_effect=AssertionError("Disabled Git ran")):
        require(not git.status()["process_used"], "qualification")
        try:
            prepare()
        except MirrorError as error:
            require(error.code == "local_only", "qualification")
        else:
            require(False, "qualification")
    return {
        "schema": "provelume-git-mirror-qualification/v1",
        "result": "PASS",
        "build": current_build_info(),
        "execution_adapter": "native_git_file",
        "git_version": initialized["git_version"],
        "network_used": False,
        "transport_process_used": True,
        "first_generation": "PASS",
        "repeat_no_commit": "PASS",
        "new_generation_preserves_history": "PASS",
        "same_root_restore_readonly_reconciliation": "PASS",
        "single_native_send": "PASS",
        "disabled_no_process": "PASS",
        "canonical_unchanged_by_transport": True,
        "hosted_profiles": "NOT_RUN",
        "windows_11_home_pro_25h2_manual": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
