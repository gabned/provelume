"""Independent synthetic Gitea API/native file Git. Actual server evidence is separate."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from .mirror_contract import MirrorError, require
from .mirror_git import git_work
from .mirror_gitea import GiteaMirrors
from .mirror_gitea_contract import VERSION
from .mirror_gitea_credentials import GiteaCredentials
from .mirrors import Mirrors
from .service import ProvelumeInstance
from .tududi_qualification import SyntheticVault


def target():
    return {
        "transport": "gitea",
        "repository": "synthetic/qualification",
        "repository_id": 11,
        "endpoint": "https://127.0.0.1:30443",
        "ca_pem": "",
        "visibility": "private",
        "api_version": "v1",
        "server_version": VERSION,
        "namespace": "d" * 32,
        "branch": "concordia",
        "path": "knowledge",
        "commit_name": "Synthetic Gitea Mirror",
        "commit_email": "mirror@example.invalid",
    }


class SyntheticApi:
    def __init__(self):
        self.calls = []
        self.remote_writes = 0
        self.user = {"id": 1, "login": "synthetic"}
        self.token = {
            "id": 1,
            "user": deepcopy(self.user),
            "scopes": ["read:user", "write:repository"],
        }
        self.repo = {
            "id": 11,
            "full_name": "synthetic/qualification",
            "private": True,
            "internal": False,
            "archived": False,
            "permissions": {"push": True},
            "clone_url": "https://127.0.0.1:30443/synthetic/qualification.git",
            "html_url": "https://127.0.0.1:30443/synthetic/qualification",
        }
        self.version = {"version": VERSION}

    def request(self, route, *, token, endpoint, ca_pem, deadline=None):
        self.calls.append(route)
        if token == "synthetic-revoked":
            raise MirrorError("authorization_required")
        return deepcopy(
            {
                "/version": self.version,
                "/user": self.user,
                "/token": self.token,
                "/repos/synthetic/qualification": self.repo,
            }[route]
        )


class SyntheticNativeGitea(GiteaMirrors):
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
    (inputs / "one.md").write_text("# Synthetic Gitea content\n\nFinite source.\n")
    instance = ProvelumeInstance.initialise(root / "Instance")
    instance.ingest_run(inputs)
    vault = SyntheticVault()
    mirrors = Mirrors(instance.store, vault=vault)
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    api, selected = SyntheticApi(), target()
    if public:
        selected["visibility"], api.repo["private"] = "public", False
    engine = SyntheticNativeGitea(
        instance.store,
        mirrors=mirrors,
        credentials=GiteaCredentials(mirrors, vault=vault, http=api),
    )
    identity = engine.connect(
        name="Synthetic Gitea",
        target=selected,
        token="synthetic-valid",
        mode="current-token",
        confirmed=True,
    )["identity"]
    engine.synthetic_remote = root / "Synthetic Gitea.git"
    with git_work() as session:
        session.run(["init", "--bare", "--object-format=sha1", str(engine.synthetic_remote)])
    destination = mirrors.configure(
        identity_id=identity["id"],
        name="Synthetic Gitea target",
        target=selected,
        scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode="manual",
        confirmed=True,
    )
    return instance, mirrors, engine, destination, api


class GiteaMirrorQualificationFailure(MirrorError):
    """Closed diagnostic context; no credential, path or subprocess output."""

    def __init__(self, error, phase):
        # Keep the existing operator code; only the additional public context
        # uses closed vocabularies, never exception messages or private paths.
        code = getattr(error, "code", "invalid_kit")
        super().__init__(code)
        safe_codes = {
            "qualification", "target_not_fresh", "authorization_required", "local_only",
            "credential_context", "deadline", "git_unavailable", "git_command_failed",
            "git_containment", "git_output_limit", "git_version_unsupported",
            "gitea_credential_changed", "gitea_identity_changed", "gitea_credential_query",
            "secure_store_unavailable", "invalid_kit",
            "stale", "destination_changed", "outcome_unknown", "gitea_transfer_changed",
            "gitea_access_changed", "git_incomplete", "git_version_changed",
        }
        phases = {
            "initialization", "publication_and_noop", "second_generation",
            "interrupted_publication", "restore_and_readonly_recovery",
            "credential_protocol", "http_worker_refusal", "native_vault_helper",
            "interrupted_publication_error", "interrupted_publication_missing_error",
            "vault_initialization", "vault_connection", "vault_destination",
            "vault_read", "vault_git_probe", "vault_credential_reply", "vault_revocation",
        }
        self.evidence = {
            "schema": "concordia-gitea-mirror-failure/v1",
            "result": "UNKNOWN",
            "phase": phase if phase in phases else "OTHER",
            "error_code": code if code in safe_codes else "OTHER",
            "prior_error_code": (
                error.__context__.code
                if isinstance(error.__context__, MirrorError)
                and error.__context__.code in safe_codes else "OTHER"
            ),
            "raw_credential_output": "EXCLUDED",
        }


def qualify_gitea_mirror(root):
    phase = ["initialization"]
    try:
        return _qualify_gitea_mirror(root, phase)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise GiteaMirrorQualificationFailure(error, phase[0]) from None


def _qualify_gitea_mirror(root, phase):
    """Permanent source/frozen test using no real account, credential or remote."""
    import os
    import subprocess
    import sys
    from unittest.mock import patch

    from .build_info import current_build_info
    from .mirror_git_runtime import GitSession
    from .mirror_gitea_helper import credential_response

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

    phase[0] = "publication_and_noop"
    first = publish(prepare())["receipt"]
    repeat = publish(prepare())["receipt"]
    require(
        first["transport_proof"]["commit_written"]
        and not repeat["transport_proof"]["commit_written"],
        "qualification",
    )
    phase[0] = "second_generation"
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

    phase[0] = "interrupted_publication"
    with patch.object(GitSession, "run", interrupted):
        try:
            publish(plan)
        except MirrorError as error:
            phase[0] = "interrupted_publication_error"
            require(error.code == "deadline", "qualification")
        else:
            phase[0] = "interrupted_publication_missing_error"
            require(False, "qualification")
    phase[0] = "restore_and_readonly_recovery"
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
    phase[0] = "credential_protocol"
    require(
        credential_response(
            b"protocol=https\nhost=127.0.0.1:30443\npath=synthetic/qualification.git\n\n",
            target=target(),
            credential={
                "token": "synthetic-pipe-only",
                "identity": {"principal": {"login": "synthetic"}},
            },
        )
        == b"username=synthetic\npassword=synthetic-pipe-only\n\n",
        "qualification",
    )
    phase[0] = "http_worker_refusal"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "HOME", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}
    }
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        command = [sys.executable, "--internal-gitea-http-worker"]
    else:
        command = [sys.executable, "-m", "provelume.mirror_gitea_http"]
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
    phase[0] = "native_vault_helper"
    return {
        "schema": "provelume-gitea-synthetic-qualification/v1",
        "result": "PASS",
        "commit": current_build_info().get("commit"),
        "frozen_executable": frozen,
        "api": "SYNTHETIC_RESPONSES",
        "git_transport": "NATIVE_FILE",
        "credential_protocol": "SYNTHETIC_PIPE",
        "native_vault_helper": qualify_native_vault_helper(
            root / "Native Vault Trial", _phase=phase,
        ),
        "http_worker_refusal": "PASS",
        "interruption_restore_readonly_recovery": "PASS",
        "resends": 0,
        "canonical_unchanged": True,
        "network_used": False,
        "real_gitea": "NOT_RUN",
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }


def qualify_native_vault_helper(root, *, native_secret_service=False, _phase=None):
    """Native OS vault -> Git -> actual owned source/frozen helper, synthetic only.

    All slots and values are newly synthetic, under an isolated LOCALAPPDATA.
    The raw credential reply stays in the private qualification pipe/memory and
    is compared without being included in any report. No remote is contacted.
    """
    import os
    import sys
    from unittest.mock import patch

    from .mirror_gitea_helper import configure_session

    if os.name != "nt" and not native_secret_service:
        return {"result": "NOT_RUN", "reason": "NATIVE_WINDOWS_ONLY"}
    if _phase is not None:
        _phase[0] = "vault_initialization"
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
        engine = GiteaMirrors(
            instance.store,
            mirrors=mirrors,
            credentials=GiteaCredentials(mirrors, http=SyntheticApi()),
        )
        if _phase is not None:
            _phase[0] = "vault_connection"
        connection = engine.connect(
            name="Synthetic native vault",
            target=target(),
            token="synthetic-native-vault-only",
            mode="current-token",
            confirmed=True,
        )
        identity = connection["identity"]
        if _phase is not None:
            _phase[0] = "vault_destination"
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
        if _phase is not None:
            _phase[0] = "vault_read"
        credential = engine.credentials.read(reference)
        with git_work() as session:
            if _phase is not None:
                _phase[0] = "vault_git_probe"
            version = session.probe()
            configure_session(
                session,
                store=instance.store,
                destination_id=destination["id"],
                reference=reference,
                binding={"credential_epoch": credential["epoch"]},
            )
            if _phase is not None:
                _phase[0] = "vault_credential_reply"
            response = session.run(
                ["credential", "fill"],
                input_bytes=(
                    b"protocol=https\nhost=127.0.0.1:30443\npath=synthetic/qualification.git\n\n"
                ),
            )[1]
            fields = dict(line.split(b"=", 1) for line in response.splitlines() if line)
            require(
                fields.get(b"username") == b"synthetic"
                and fields.get(b"password") == b"synthetic-native-vault-only",
                "qualification",
            )
        if _phase is not None:
            _phase[0] = "vault_revocation"
        engine.disconnect(identity["id"], expected_revision=1, confirmed=True)
    return {
        "result": "PASS",
        "backend": "NATIVE_CURRENT_USER_DPAPI" if os.name == "nt" else "NATIVE_SECRET_SERVICE",
        "git_version": version,
        "owned_helper": "ACTUAL_FROZEN" if getattr(sys, "frozen", False) else "ACTUAL_SOURCE",
        "credential_reply_logged": False,
        "synthetic_only": True,
        "network_used": False,
    }
