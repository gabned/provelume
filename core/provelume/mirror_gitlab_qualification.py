"""Synthetic GitLab API and native file Git; never real GitLab.com evidence."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from .mirror_contract import MirrorError, require
from .mirror_git import git_work
from .mirror_gitlab import GitLabMirrors
from .mirror_gitlab_credentials import GitLabCredentials
from .mirrors import Mirrors
from .service import ProvelumeInstance
from .tududi_qualification import SyntheticVault


def target():
    return {
        "transport": "gitlab",
        "repository": "synthetic/group/qualification",
        "repository_id": 31,
        "visibility": "private",
        "api_version": "v4",
        "namespace": "c" * 32,
        "branch": "concordia",
        "path": "knowledge",
        "commit_name": "Synthetic GitLab Mirror",
        "commit_email": "mirror@example.invalid",
    }


class SyntheticApi:
    def __init__(self):
        self.calls = []
        self.remote_writes = 0
        self.user = {"id": 41, "username": "synthetic", "state": "active"}
        self.token = {
            "id": 51,
            "user_id": 41,
            "active": True,
            "revoked": False,
            "scopes": ["read_api", "write_repository"],
            "expires_at": "2099-01-01",
            "granular_scopes": [],
        }
        self.repo = {
            "id": 31,
            "path_with_namespace": "synthetic/group/qualification",
            "http_url_to_repo": "https://gitlab.com/synthetic/group/qualification.git",
            "web_url": "https://gitlab.com/synthetic/group/qualification",
            "visibility": "private",
            "archived": False,
            "repository_access_level": "enabled",
            "permissions": {"project_access": {"access_level": 30}, "group_access": None},
        }
        self.version = {"version": "19.5.1", "revision": "a" * 40}

    def request(self, route, *, token, probe=False, deadline=None):
        if probe:
            raise AssertionError("GitLab capability proof unexpectedly mutated a remote")
        self.calls.append(route)
        if token == "synthetic-expired":
            raise MirrorError("authorization_required")
        return deepcopy(
            {
                "/user": self.user,
                "/personal_access_tokens/self": self.token,
                "/projects/31": self.repo,
                "/version": self.version,
            }[route]
        )


class SyntheticNativeGitLab(GitLabMirrors):
    @contextmanager
    def target_session(self, selected, *, deadline=None, inspection_operation=None):
        with git_work(deadline=deadline) as session:
            session.probe()
            clean = self.clean_target(selected)
            binding = self.credentials.observe(
                selected["_reference"], clean, deadline=session.deadline
            )
            if inspection_operation is None:
                self.credentials.verify_write(
                    selected["_reference"], clean, deadline=session.deadline
                )
            yield (
                {
                    "uri": self.synthetic_remote.as_uri(),
                    "binding": binding,
                    "marker": self.marker(clean),
                },
                session,
            )


def synthetic_fixture(root, *, public=False):
    inputs = root / "Inputs"
    inputs.mkdir()
    (inputs / "one.md").write_text("# Synthetic GitLab content\n\nFinite source.\n")
    instance = ProvelumeInstance.initialise(root / "Instance")
    instance.ingest_run(inputs)
    vault = SyntheticVault()
    mirrors = Mirrors(instance.store, vault=vault)
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    api, selected = SyntheticApi(), target()
    if public:
        selected["visibility"] = api.repo["visibility"] = "public"
    credentials = GitLabCredentials(mirrors, vault=vault, http=api)
    engine = SyntheticNativeGitLab(instance.store, mirrors=mirrors, credentials=credentials)
    identity = engine.connect(
        name="Synthetic GitLab",
        target=selected,
        token="synthetic-valid",
        mode="classic-pat",
        confirmed=True,
    )["identity"]
    engine.synthetic_remote = root / "Synthetic GitLab.git"
    with git_work() as session:
        session.run(["init", "--bare", "--object-format=sha1", str(engine.synthetic_remote)])
    destination = mirrors.configure(
        identity_id=identity["id"],
        name="Synthetic GitLab target",
        target=selected,
        scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode="manual",
        confirmed=True,
    )
    return instance, mirrors, engine, destination, api


def qualify_gitlab_mirror(root):
    """Permanent source/frozen test using no real account, credential or remote."""
    import os
    import subprocess
    import sys
    from unittest.mock import patch

    from .build_info import current_build_info
    from .mirror_git_runtime import GitSession
    from .mirror_gitlab_helper import credential_response

    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    instance, mirrors, engine, destination, api = synthetic_fixture(root)
    before = mirrors.snapshots.source_fingerprint()

    def prepare():
        return engine.prepare(destination["id"], expected_revision=1, confirmed=True)

    def publish(plan):
        return engine.publish(
            plan["id"],
            expected_plan_sha256=plan["plan_sha256"],
            expected_git_plan_sha256=plan["git_plan_sha256"],
            confirmed=True,
        )

    first = publish(prepare())["receipt"]
    repeat = publish(prepare())["receipt"]
    require(
        first["transport_proof"]["commit_written"]
        and not repeat["transport_proof"]["commit_written"],
        "qualification",
    )
    (root / "Inputs" / "two.md").write_text("# Synthetic second generation\n\nNew content.\n")
    instance.ingest_run(root / "Inputs")
    before = mirrors.snapshots.source_fingerprint()
    plan = prepare()
    backup = instance.backup(destination=root / "Synthetic before send")
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
    probes = api.remote_writes
    receipt = engine.reconcile(plan["id"], confirmed=True)["receipt"]
    require(
        receipt["transport_proof"]["evidence_mode"] == "reconciled_current_state"
        and len(sends) == 1
        and api.remote_writes == probes
        and mirrors.snapshots.source_fingerprint() == before,
        "qualification",
    )
    require(
        credential_response(
            b"protocol=https\nhost=gitlab.com\npath=synthetic/group/qualification.git\n\n",
            target=target(),
            credential={"token": "synthetic-pipe-only"},
        )
        == b"username=x-access-token\npassword=synthetic-pipe-only\n\n",
        "qualification",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "HOME", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}
    }
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        command = [sys.executable, "--internal-gitlab-http-worker"]
    else:
        command = [sys.executable, "-m", "provelume.mirror_gitlab_http"]
        environment["PYTHONPATH"] = str(Path(__file__).absolute().parent.parent)
    output = root / "invalid-worker-response.json"
    result = subprocess.run(
        command + [str(output)],
        input=b'{"route":"https://evil.invalid"}',
        env=environment,
        capture_output=True,
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    require(
        result.returncode == 2 and not result.stdout and not result.stderr and not output.exists(),
        "qualification",
    )
    return {
        "schema": "provelume-gitlab-synthetic-qualification/v1",
        "result": "PASS",
        "commit": current_build_info().get("commit"),
        "frozen_executable": frozen,
        "api": "SYNTHETIC_RESPONSES",
        "git_transport": "NATIVE_FILE",
        "credential_protocol": "SYNTHETIC_PIPE",
        "native_vault_helper": qualify_native_vault_helper(root / "Native Vault Trial"),
        "http_worker_refusal": "PASS",
        "interruption_restore_readonly_recovery": "PASS",
        "resends": 0,
        "canonical_unchanged": True,
        "network_used": False,
        "real_gitlab": "NOT_RUN",
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }


def qualify_native_vault_helper(root):
    """Actual DPAPI -> native Git -> actual owned source/frozen helper on Windows.

    All slots and values are newly synthetic, under an isolated LOCALAPPDATA.
    The raw credential reply stays in the private qualification pipe/memory and
    is compared without being included in any report. No remote is contacted.
    """
    import os
    import sys
    from unittest.mock import patch

    from .mirror_gitlab_helper import configure_session

    if os.name != "nt":
        return {"result": "NOT_RUN", "reason": "NATIVE_WINDOWS_ONLY"}
    root = Path(root).absolute()
    require(not root.exists(), "target_not_fresh")
    root.mkdir()
    host = root / "Synthetic Host"
    with patch.dict(os.environ, {"LOCALAPPDATA": str(host)}):
        instance = ProvelumeInstance.initialise(root / "Synthetic Instance")
        mirrors = Mirrors(instance.store)
        mirrors.set_access(
            enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True
        )
        engine = GitLabMirrors(
            instance.store,
            mirrors=mirrors,
            credentials=GitLabCredentials(mirrors, http=SyntheticApi()),
        )
        connection = engine.connect(
            name="Synthetic native vault",
            target=target(),
            token="synthetic-native-vault-only",
            mode="classic-pat",
            confirmed=True,
        )
        identity = connection["identity"]
        destination = mirrors.configure(
            identity_id=identity["id"],
            name="Synthetic credential pipe",
            target=target(),
            scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
            include_rules={"originals": [], "attachments": [], "ai_receipts": []},
            mode="manual",
            confirmed=True,
        )
        reference = mirrors._grant(identity)["credential"]["reference"]
        credential = engine.credentials.read(reference)
        with git_work() as session:
            version = session.probe()
            configure_session(
                session,
                store=instance.store,
                destination_id=destination["id"],
                reference=reference,
                binding={"credential_epoch": credential["epoch"]},
            )
            response = session.run(
                ["credential", "fill"],
                input_bytes=(
                    b"protocol=https\nhost=gitlab.com\npath=synthetic/group/qualification.git\n\n"
                ),
            )[1]
            fields = dict(line.split(b"=", 1) for line in response.splitlines() if line)
            require(
                fields.get(b"username") == b"x-access-token"
                and fields.get(b"password") == b"synthetic-native-vault-only",
                "qualification",
            )
        engine.disconnect(identity["id"], expected_revision=1, confirmed=True)
    return {
        "result": "PASS",
        "backend": "NATIVE_CURRENT_USER_DPAPI",
        "git_version": version,
        "owned_helper": "ACTUAL_FROZEN" if getattr(sys, "frozen", False) else "ACTUAL_SOURCE",
        "credential_reply_logged": False,
        "synthetic_only": True,
        "network_used": False,
    }
