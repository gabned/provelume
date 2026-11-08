"""Actual pinned local Gitea/TLS conformance, only fresh synthetic accounts/data."""

from __future__ import annotations

import getpass
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from .google_credentials import GoogleCredentialVault
from .migration_permissions import make_private
from .mirror_contract import MirrorError, fingerprint, require
from .mirror_git_runtime import child_environment
from .mirror_gitea import GiteaMirrors
from .mirror_gitea_contract import VERSION, tls_context
from .mirror_gitea_credentials import GiteaCredentials
from .mirror_gitea_http import GiteaHttp
from .mirror_gitea_qualification import target as synthetic_target
from .mirrors import Mirrors
from .ocr_process import _terminate_process_tree, run_bounded_process
from .productivity_http import _NoRedirect
from .service import ProvelumeInstance
from .tududi_qualification import SyntheticVault

INPUTS = {
    "linux": {
        "bytes": 119947424,
        "sha256": "5f834e8f04986f3b9206cf14743b5a6e6996ceddc238dac6409866ebda2a0686",
    },
    "win32": {
        "bytes": 122948608,
        "sha256": "4003c068ef0a7d8145ef8c85b8aab052bf1bbf9226f2d0058572f013e096ee06",
    },
}
SERVER_SECONDS = 300
SERVER_LOG_BYTES = 4 * 1024 * 1024
COMMAND_EVIDENCE = ContextVar("gitea_fixture_command_evidence", default=None)
COMMAND_SECRETS = ContextVar("gitea_fixture_command_secrets", default=None)


def error_summary(data):
    value = data.decode("utf-8", errors="replace")
    for secret in COMMAND_SECRETS.get() or ():
        if secret:
            value = value.replace(secret, "<redacted>")
    value = re.sub(r"[A-Za-z0-9_+/=-]{16,}", "<redacted>", value)
    value = "".join(char if char.isprintable() or char in "\n\t" else "?" for char in value)
    return value[-512:]


class GiteaQualificationFailure(MirrorError):
    def __init__(self, code, evidence):
        super().__init__(code)
        self.evidence = evidence


def command_kind(arguments):
    for marker, operation in (
        ("--version", "component_version"),
        ("req", "tls_certificate"),
        ("secret", "server_secret"),
        ("migrate", "schema_migrate"),
        ("generate-access-token", "synthetic_token"),
        ("create", "synthetic_user"),
    ):
        if marker in arguments:
            return operation
    return "fixture_command"


def binary_identity(path):
    path = Path(path).absolute()
    expected = INPUTS.get(sys.platform)
    require(
        expected is not None
        and path.is_file()
        and not path.is_symlink()
        and path.stat().st_size == expected["bytes"],
        "gitea_component",
    )
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    require(digest.hexdigest() == expected["sha256"], "gitea_component")
    return {"bytes": expected["bytes"], "sha256": digest.hexdigest(), "version": VERSION}


def command(arguments, *, work, environment):
    protected = COMMAND_SECRETS.get()
    if protected is not None:
        for index, argument in enumerate(arguments[:-1]):
            if argument == "--password":
                protected.append(arguments[index + 1])
    result = run_bounded_process(
        arguments,
        temporary_directory=work,
        timeout_seconds=30,
        stdout_limit=65536,
        stderr_limit=65536,
        environment=environment,
    )
    # Credential-generating stdout is never copied to ordinary evidence/logs.
    sensitive = any(value in arguments for value in ("generate-access-token", "create", "secret"))
    if protected is not None and sensitive:
        protected.extend(result.stdout.decode("utf-8", errors="replace").splitlines())
    stamp = uuid4().hex
    record = {
        "operation": command_kind(arguments),
        "returncode": result.returncode,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
        "sensitive_stdout": sensitive,
    }
    if result.returncode != 0 and not sensitive:
        record["stderr_summary"] = error_summary(result.stderr)
        record["stdout_summary"] = error_summary(result.stdout)
    records = COMMAND_EVIDENCE.get()
    if records is not None:
        require(len(records) < 16, "limit")
        records.append(record)
    (work / (stamp + "-command.json")).write_text(json.dumps(record, indent=2) + "\n")
    if not sensitive and record["operation"] in {"component_version", "tls_certificate"}:
        (work / (stamp + "-stdout-original.log")).write_bytes(result.stdout)
        (work / (stamp + "-stderr-original.log")).write_bytes(result.stderr)
    require(result.returncode == 0, "gitea_fixture_command_" + record["operation"])
    return result.stdout


class Server:
    def __init__(self, arguments, *, work, environment):
        self.work = work
        self.log = work / "server-original.log"
        self.resources = ExitStack()
        self.process = None
        self.closed, self.reason = False, None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        try:
            self.output = self.resources.enter_context(self.log.open("xb"))
            self.incoming = self.resources.enter_context(io.FileIO(os.devnull, "r"))
            if os.name == "nt":
                from .mirror_git_windows import WindowsGitProcess

                self.process = WindowsGitProcess(
                    arguments,
                    cwd=work,
                    environment=environment,
                    incoming=self.incoming,
                    output=self.output,
                    errors=self.output,
                )
            else:
                self.process = subprocess.Popen(
                    arguments,
                    cwd=work,
                    env=environment,
                    stdin=self.incoming,
                    stdout=self.output,
                    stderr=self.output,
                    start_new_session=True,
                    close_fds=True,
                )
            self.watch = threading.Thread(target=self._watch, daemon=True)
            self.watch.start()
        except BaseException:
            self.close()
            raise

    def _watch(self):
        deadline = time.monotonic() + SERVER_SECONDS
        while not self.stop.wait(0.05):
            if time.monotonic() > deadline or self.log.stat().st_size > SERVER_LOG_BYTES:
                self.reason = (
                    "server_deadline" if time.monotonic() > deadline else "server_output_limit"
                )
                self.close()
                return

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.stop.set()
            if self.process is not None:
                if os.name == "nt":
                    self.process.close()
                else:
                    _terminate_process_tree(self.process)
            self.resources.close()


def control(origin, ca, route, *, token=None, body=None, timeout=5):
    """Synthetic fixture control plane only; product workers never gain these POSTs."""
    require(route in {"/version", "/user/repos"}, "gitea_fixture_route")
    require(type(timeout) in {int, float} and 0 < timeout <= 5, "gitea_fixture_readiness")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "token " + token
    request = Request(
        origin + "/api/v1" + route,
        headers=headers,
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
    )
    with build_opener(_NoRedirect(), ProxyHandler({}), HTTPSHandler(context=tls_context(ca))).open(
        request, timeout=timeout
    ) as response:
        require(response.status == (200 if body is None else 201), "gitea_fixture_response")
        data = response.read(2 * 1024 * 1024 + 1)
        require(len(data) <= 2 * 1024 * 1024, "limit")
        return json.loads(data)


def await_server_version(server, origin, ca):
    """A late successful response cannot pass the unchanged 30-second admission."""
    deadline = time.monotonic() + 30
    while True:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "gitea_fixture_readiness")
        require(not server.closed and server.process.poll() is None, "gitea_fixture_startup")
        try:
            version = control(origin, ca, "/version", timeout=min(5, remaining))
        except (OSError, json.JSONDecodeError):
            remaining = deadline - time.monotonic()
            require(remaining > 0, "gitea_fixture_readiness")
            time.sleep(min(0.05, remaining))
            continue
        require(time.monotonic() <= deadline, "gitea_fixture_readiness")
        require(
            type(version) is dict and version.get("version") == VERSION,
            "gitea_profile_not_qualified",
        )
        return


@contextmanager
def fixture_server(root, binary):
    identity = binary_identity(binary)
    root.mkdir()
    make_private(root)
    environment = child_environment(root)
    home = root / "Synthetic Home"
    home.mkdir()
    environment["HOME"] = str(home)
    # Gitea initialises its own Git identity. This fresh fixture config is
    # writable; the product's separate GitSession configuration stays closed.
    environment["GIT_CONFIG_GLOBAL"] = str(home / "synthetic.gitconfig")
    environment["USER"] = getpass.getuser()
    environment["LOGNAME"] = environment["USER"]
    native = (
        command([str(binary), "--version"], work=root, environment=environment).decode().strip()
    )
    require(
        native.lower().startswith("gitea version " + VERSION + " built with "), "gitea_component"
    )
    openssl = shutil.which("openssl")
    require(openssl is not None, "gitea_tls_component")
    key, certificate = root / "synthetic-key.pem", root / "synthetic-ca.pem"
    openssl_config = root / "synthetic-openssl.cnf"
    openssl_config.write_text("[req]\ndistinguished_name = dn\n[dn]\n", encoding="ascii")
    command(
        [
            openssl,
            "req",
            "-config",
            str(openssl_config),
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        work=root,
        environment=environment,
    )
    ca = certificate.read_text(encoding="ascii")
    tls_context(ca)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    origin = "https://127.0.0.1:" + str(port)
    data = root / "data"
    data.mkdir()
    config = root / "app.ini"
    paths = {
        "work": root.as_posix(),
        "data": data.as_posix(),
        "key": key.as_posix(),
        "certificate": certificate.as_posix(),
    }
    secret = (
        command(
            [str(binary), "generate", "secret", "SECRET_KEY"], work=root, environment=environment
        )
        .decode()
        .strip()
    )
    require(re.fullmatch(r"[A-Za-z0-9_+=/.-]{20,4096}", secret), "gitea_fixture_secret")
    config.write_text(
        f"""APP_NAME = Synthetic Concordia qualification
RUN_USER = {environment["USER"]}
RUN_MODE = prod
[server]
PROTOCOL = https
DOMAIN = 127.0.0.1
HTTP_ADDR = 127.0.0.1
HTTP_PORT = {port}
ROOT_URL = {origin}/
DISABLE_SSH = true
APP_DATA_PATH = {paths["data"]}
CERT_FILE = {paths["certificate"]}
KEY_FILE = {paths["key"]}
[database]
DB_TYPE = sqlite3
PATH = {paths["data"]}/synthetic.db
[repository]
ROOT = {paths["data"]}/repositories
[security]
INSTALL_LOCK = true
SECRET_KEY = {secret}
[actions]
ENABLED = false
[cron]
ENABLED = false
[service]
DISABLE_REGISTRATION = true
REQUIRE_SIGNIN_VIEW = false
[mailer]
ENABLED = false
[picture]
DISABLE_GRAVATAR = true
ENABLE_FEDERATED_AVATAR = false
[cron.update_checker]
ENABLED = false
[federation]
ENABLED = false
[log]
MODE = console
LEVEL = Warn
ROOT_PATH = {paths["work"]}/log
""",
        encoding="utf-8",
    )
    common = [str(binary), "--work-path", str(root), "--config", str(config)]
    command(common + ["migrate"], work=root, environment=environment)
    command(
        common
        + [
            "admin",
            "user",
            "create",
            "--username",
            "synthetic",
            "--email",
            "synthetic@example.invalid",
            "--random-password",
            "--must-change-password=false",
        ],
        work=root,
        environment=environment,
    )

    def token(name, scopes):
        value = command(
            common
            + [
                "admin",
                "user",
                "generate-access-token",
                "--username",
                "synthetic",
                "--token-name",
                name,
                "--scopes",
                scopes,
                "--raw",
            ],
            work=root,
            environment=environment,
        )
        selected = value.decode("ascii").strip().splitlines()[-1]
        require(re.fullmatch(r"[A-Za-z0-9_.-]{20,8192}", selected), "gitea_fixture_token")
        return selected

    writable = token("synthetic-write", "read:user,write:repository")
    readonly = token("synthetic-read", "read:user,read:repository")
    bootstrap = token("synthetic-fixture-bootstrap", "write:user,write:repository")
    server = Server(common + ["web"], work=root, environment=environment)
    try:
        await_server_version(server, origin, ca)
        repositories = []
        for private in (True, False):
            name = "concordia-private" if private else "concordia-public"
            repo = control(
                origin,
                ca,
                "/user/repos",
                token=bootstrap,
                body={"name": name, "private": private, "auto_init": False},
            )
            require(
                type(repo.get("id")) is int
                and repo["id"] > 0
                and repo.get("full_name") == "synthetic/" + name
                and repo.get("private") is private,
                "gitea_fixture_response",
            )
            repositories.append(repo)
        yield {
            "origin": origin,
            "ca_pem": ca,
            "writable": writable,
            "readonly": readonly,
            "repositories": repositories,
            "binary": identity,
            "native_version": native,
            "server": server,
        }
        require(server.reason is None, "gitea_fixture_containment")
    finally:
        server.close()


def qualify_gitea_server(root, server_binary, *, api_only=False):
    records = []
    token = COMMAND_EVIDENCE.set(records)
    secret_token = COMMAND_SECRETS.set([])
    try:
        return _qualify_gitea_server(root, server_binary, api_only=api_only)
    except Exception as error:
        code = error.code if isinstance(error, MirrorError) else "gitea_fixture_unavailable"
        evidence = {
            "schema": "concordia-gitea-failure-evidence/v1",
            "result": "NOT_RUN" if code.startswith("gitea_fixture_command_") else "UNKNOWN",
            "mode": "API_ONLY" if api_only else "FULL_NATIVE",
            "commands": records,
            "raw_credential_output": "EXCLUDED",
            "whole_host_network": "NOT_INSTRUMENTED",
        }
        raise GiteaQualificationFailure(code, evidence) from None
    finally:
        COMMAND_SECRETS.reset(secret_token)
        COMMAND_EVIDENCE.reset(token)


def _qualify_gitea_server(root, server_binary, *, api_only=False):
    """Select API_ONLY before admission; full native never falls back to a fake vault."""
    from unittest.mock import patch

    from .mirror_git_runtime import GitSession

    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    binary = Path(server_binary).absolute()
    identity = binary_identity(binary)
    root.mkdir(parents=True)
    make_private(root)
    instance = ProvelumeInstance.initialise(root / "Synthetic Instance")
    vault = (
        SyntheticVault()
        if api_only
        else GoogleCredentialVault(namespace="mirror", forbidden_root=instance.root)
    )
    slot = "mirror_synthetic_preflight_" + uuid4().hex
    # Native secure-store admission precedes starting any full publication trial.
    vault.write(slot, {"value": "synthetic-preflight-only"})
    require(vault.read(slot) == {"value": "synthetic-preflight-only"}, "secure_store_unavailable")
    vault.delete(slot)
    helper_admission = {"result": "NOT_RUN", "mode": "API_ONLY"}
    if not api_only:
        from .mirror_gitea_qualification import qualify_native_vault_helper

        helper_admission = qualify_native_vault_helper(
            root / "Owned helper admission", native_secret_service=True
        )
    mirrors = Mirrors(instance.store, vault=vault)
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    credentials = GiteaCredentials(mirrors, vault=vault)
    mode = "API_ONLY" if api_only else "FULL_NATIVE"
    outcomes = []
    bypass = ",".join(filter(None, [os.environ.get("NO_PROXY", ""), "127.0.0.1", "localhost"]))
    with (
        patch.dict(os.environ, {"NO_PROXY": bypass}),
        fixture_server(root / "Server", binary) as server,
    ):
        tls_refusals = []
        for name, origin, ca in (
            ("untrusted_ca", server["origin"], ""),
            (
                "wrong_hostname",
                server["origin"].replace("127.0.0.1", "localhost"),
                server["ca_pem"],
            ),
        ):
            try:
                GiteaHttp().request(
                    "/version",
                    token="synthetic-negative-only",
                    endpoint=origin,
                    ca_pem=ca,
                    deadline=time.monotonic() + 20,
                )
            except MirrorError as error:
                require(error.code == "gitea_transport", "gitea_fixture_tls_refusal")
                tls_refusals.append({"case": name, "result": "PASS", "code": error.code})
            else:
                require(False, "gitea_fixture_tls_refusal")
        for repo in server["repositories"]:
            selected = {
                **synthetic_target(),
                "repository": repo["full_name"],
                "repository_id": repo["id"],
                "endpoint": server["origin"],
                "ca_pem": server["ca_pem"],
                "namespace": uuid4().hex,
                "visibility": "private" if repo["private"] else "public",
            }
            observed = credentials.observe_token(
                selected,
                token=server["writable"],
                mode="current-token",
                deadline=time.monotonic() + 120,
            )
            readonly_repo = GiteaHttp().request(
                "/repos/" + repo["full_name"],
                token=server["readonly"],
                endpoint=server["origin"],
                ca_pem=server["ca_pem"],
                deadline=time.monotonic() + 120,
            )
            try:
                credentials.observe_token(
                    selected,
                    token=server["readonly"],
                    mode="current-token",
                    deadline=time.monotonic() + 120,
                )
            except MirrorError as error:
                require(error.code == "gitea_write_unproven", "gitea_fixture_readonly")
            else:
                require(False, "gitea_fixture_readonly")
            outcomes.append(
                {
                    "visibility": selected["visibility"],
                    "api": "PASS",
                    "readonly_scope_refusal": "PASS",
                    "readonly_repo_push_flag": readonly_repo.get("permissions", {}).get("push"),
                    "observed_identity_sha256": fingerprint(observed["identity"]),
                    "publication": "NOT_RUN",
                }
            )
            if api_only:
                continue
            inputs = root / ("Private Inputs" if repo["private"] else "Public Inputs")
            inputs.mkdir()
            marker = "PRIVATE_ONLY_SYNTHETIC" if repo["private"] else "PUBLIC_ONLY_SYNTHETIC"
            (inputs / "one.md").write_text("# Synthetic native Gitea\n\n" + marker + "\n")
            previous_ids = {item["id"] for item in instance.store.list_canonical("documents")}
            instance.ingest_run(inputs)
            area = instance.create_hierarchy_node("area", "Synthetic " + selected["visibility"])
            for document in instance.store.list_canonical("documents"):
                if document["id"] not in previous_ids:
                    instance.classify_document(document["id"], area["id"])
            engine = GiteaMirrors(instance.store, mirrors=mirrors, credentials=credentials)
            connected = engine.connect(
                name="Synthetic actual Gitea",
                target=selected,
                token=server["writable"],
                mode="current-token",
                confirmed=True,
            )
            row = mirrors.configure(
                identity_id=connected["identity"]["id"],
                name="Synthetic actual target",
                target=selected,
                scope={"kind": "area", "id": area["id"]},
                include_rules={"originals": [], "attachments": [], "ai_receipts": []},
                mode="manual",
                finding_policy="confirm_sensitive",
                confirmed=True,
            )

            def prepare(row, engine=engine):
                return engine.prepare(row["id"], expected_revision=row["revision"], confirmed=True)

            first = prepare(row)
            if not repo["private"]:
                for entry in first["manifest"]["inventory"]:
                    payload = mirrors.snapshots.root() / first["generation"] / entry["path"]
                    require(
                        b"PRIVATE_ONLY_SYNTHETIC" not in payload.read_bytes(), "gitea_fixture_scope"
                    )
                row = mirrors.configure(
                    identity_id=row["identity_id"],
                    name=row["name"],
                    target=selected,
                    scope=row["scope"],
                    include_rules=row["include_rules"],
                    mode="manual",
                    finding_policy="confirm_sensitive",
                    public_allowlist=first["manifest"]["inventory"],
                    destination_id=row["id"],
                    expected_revision=1,
                    confirmed=True,
                )
                first = prepare(row)

            def publish(plan, engine=engine):
                return engine.publish(
                    plan["id"],
                    expected_plan_sha256=plan["plan_sha256"],
                    expected_git_plan_sha256=plan["git_plan_sha256"],
                    confirmed=True,
                    expected_transfer_sha256=plan["git_plan"]["transfer_sha256"],
                )

            before = mirrors.snapshots.source_fingerprint()
            receipt = publish(first)["receipt"]
            noop = publish(prepare(row))["receipt"]
            require(not noop["transport_proof"]["commit_written"], "gitea_fixture_noop")
            require(mirrors.snapshots.source_fingerprint() == before, "gitea_fixture_canonical")
            outcomes[-1].update(
                publication="PASS",
                first_receipt_sha256=fingerprint(receipt),
                noop="PASS",
                canonical_unchanged=True,
            )
            if repo["private"]:
                (inputs / "two.md").write_text(
                    "# Synthetic second generation\n\nNew finite source.\n"
                )
                previous_ids = {item["id"] for item in instance.store.list_canonical("documents")}
                instance.ingest_run(inputs)
                for document in instance.store.list_canonical("documents"):
                    if document["id"] not in previous_ids:
                        instance.classify_document(document["id"], area["id"])
                plan = prepare(row)
                backup = instance.backup(destination=root / "Before interrupted private send")
                run, sends = GitSession.run, []

                def interrupted(session, arguments, *, run=run, sends=sends, **options):
                    result = run(session, arguments, **options)
                    if arguments[0] == "push":
                        sends.append(True)
                        raise MirrorError("deadline")
                    return result

                with patch.object(GitSession, "run", interrupted):
                    try:
                        publish(plan)
                    except MirrorError as error:
                        require(error.code == "deadline", "gitea_fixture_interruption")
                    else:
                        require(False, "gitea_fixture_interruption")
                require(
                    instance.restore(backup["archive"])["status"] == "restored",
                    "gitea_fixture_restore",
                )
                recovered = engine.reconcile(plan["id"], confirmed=True)
                require(
                    len(sends) == 1
                    and recovered["receipt"]["transport_proof"]["evidence_mode"]
                    == "reconciled_current_state",
                    "gitea_fixture_recovery",
                )
                outcomes[-1]["interruption_restore_readonly_recovery"] = "PASS"
    report = {
        "schema": "concordia-gitea-actual-server/v1",
        "result": "PASS",
        "mode": mode,
        "server_binary": identity,
        "native_version": server["native_version"],
        "native_vault_helper_admission": helper_admission,
        "tls_refusals": tls_refusals,
        "monotonic_clock": time.get_clock_info("monotonic").monotonic,
        "server_process_bound_seconds": SERVER_SECONDS,
        "server_output_bound_bytes": SERVER_LOG_BYTES,
        "server_containment": "CREATION_TIME_WINDOWS_JOB" if os.name == "nt" else "OWNED_SESSION",
        "outcomes": outcomes,
        "driver_endpoint_policy": "OWNED_LOOPBACK_TLS_ONLY",
        "driver_external_network_used": False,
        "whole_host_external_connections": "NOT_INSTRUMENTED",
        "real_accounts": False,
        "synthetic_only": True,
        "native_mirror_publication": "NOT_RUN" if api_only else "PASS",
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
    (root / "qualification-original.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
