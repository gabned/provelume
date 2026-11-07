"""Fresh synthetic API + native file Git conformance. No real GitHub qualification."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from .mirror_contract import MirrorError, require
from .mirror_git import git_work
from .mirror_github import GitHubMirrors
from .mirror_github_contract import API_VERSION, PROBE_OID
from .mirror_github_credentials import GitHubCredentials
from .mirrors import Mirrors
from .service import ProvelumeInstance
from .tududi_qualification import SyntheticVault


def target():
    return {
        "transport": "github",
        "repository": "synthetic/qualification",
        "repository_id": 17,
        "visibility": "private",
        "api_version": API_VERSION,
        "namespace": "a" * 32,
        "branch": "concordia",
        "path": "knowledge",
        "commit_name": "Synthetic Mirror",
        "commit_email": "mirror@example.invalid",
    }


class SyntheticApi:
    def __init__(self):
        self.calls = []
        self.identity = {"id": 23, "login": "synthetic"}
        self.repo = {
            "id": 17,
            "full_name": "synthetic/qualification",
            "private": True,
            "visibility": "private",
            "clone_url": "https://github.com/synthetic/qualification.git",
            "archived": False,
            "disabled": False,
            "permissions": {"push": True},
        }
        self.writable = True
        self.total, self.installation_rows = 1, [deepcopy(self.repo)]

    def request(self, route, *, token, probe=False, deadline=None):
        self.calls.append((route, probe))
        if token == "synthetic-expired":
            raise MirrorError("authorization_required")
        if probe:
            if not self.writable:
                raise MirrorError("authorization_required")
            return {"sha": PROBE_OID}
        if route == "/user":
            return deepcopy(self.identity)
        if route.startswith("/installation/repositories?"):
            return {"total_count": self.total, "repositories": deepcopy(self.installation_rows)}
        return deepcopy(self.repo)


class SyntheticNativeGitHub(GitHubMirrors):
    """Qualification seam substitutes the endpoint, never claims HTTPS/SaaS evidence."""

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
            from provelume.mirror_github_contract import marker

            yield (
                {
                    "uri": self.synthetic_remote.as_uri(),
                    "binding": binding,
                    "marker": marker(clean),
                },
                session,
            )


def synthetic_fixture(tmp_path, *, public=False, mode="user"):
    inputs = tmp_path / "Inputs"
    inputs.mkdir()
    (inputs / "one.md").write_text("# Synthetic hosted mirror\n\nFinite readable content.\n")
    instance = ProvelumeInstance.initialise(tmp_path / "Instance")
    instance.ingest_run(inputs)
    vault = SyntheticVault()
    mirrors = Mirrors(instance.store, vault=vault)
    mirrors.set_access(enabled=True, github=True, rsync=False, expected_revision=0, confirmed=True)
    api = SyntheticApi()
    selected = target()
    if public:
        selected["visibility"] = api.repo["visibility"] = "public"
        api.repo["private"] = False
    credentials = GitHubCredentials(mirrors, vault=vault, http=api)
    engine = SyntheticNativeGitHub(instance.store, mirrors=mirrors, credentials=credentials)
    connection = engine.connect(
        name="Synthetic Github",
        target=selected,
        token="synthetic-valid",
        mode=mode,
        confirmed=True,
        probe_confirmed=True,
        public_probe_confirmed=public,
    )
    remote = tmp_path / "Synthetic Remote.git"
    with git_work() as session:
        session.run(["init", "--bare", "--object-format=sha1", str(remote)])
    engine.synthetic_remote = remote
    destination = mirrors.configure(
        identity_id=connection["identity"]["id"],
        name="Synthetic GitHub target",
        target=selected,
        scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode="manual",
        confirmed=True,
    )
    return instance, mirrors, engine, destination, api


def qualify_github_mirror(root):
    """Permanent source/frozen test using no real account, credential or remote."""
    import os
    import subprocess
    import sys
    from unittest.mock import patch

    from .build_info import current_build_info
    from .mirror_git_runtime import GitSession
    from .mirror_github_helper import credential_response

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
    probes = sum(probe for _route, probe in api.calls)
    receipt = engine.reconcile(plan["id"], confirmed=True)["receipt"]
    require(
        receipt["transport_proof"]["evidence_mode"] == "reconciled_current_state"
        and len(sends) == 1
        and sum(probe for _route, probe in api.calls) == probes
        and mirrors.snapshots.source_fingerprint() == before,
        "qualification",
    )
    require(
        credential_response(
            b"protocol=https\nhost=github.com\npath=synthetic/qualification.git\n\n",
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
        command = [sys.executable, "--internal-github-http-worker"]
    else:
        command = [sys.executable, "-m", "provelume.mirror_github_http"]
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
        "schema": "provelume-github-synthetic-qualification/v1",
        "result": "PASS",
        "commit": current_build_info().get("commit"),
        "frozen_executable": frozen,
        "api": "SYNTHETIC_RESPONSES",
        "git_transport": "NATIVE_FILE",
        "credential_protocol": "SYNTHETIC_PIPE",
        "http_worker_refusal": "PASS",
        "interruption_restore_readonly_recovery": "PASS",
        "resends": 0,
        "canonical_unchanged": True,
        "network_used": False,
        "real_github": "NOT_RUN",
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
