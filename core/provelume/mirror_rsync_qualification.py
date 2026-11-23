"""Actual native Linux SSH/rsync fixture, isolated from live accounts and destinations."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from contextlib import ExitStack, contextmanager, nullcontext
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from .build_info import current_build_info
from .google_credentials import GoogleCredentialVault
from .migration_permissions import make_private
from .mirror_contract import MirrorError, fingerprint, parse, raw, require
from .mirror_rsync import RsyncMirrors
from .mirror_rsync_protocol import frame
from .mirror_rsync_transport import native_work
from .mirror_ssh_agent import public_blob
from .mirror_ssh_crypto import public_key
from .mirror_ssh_runtime import (
    LEGACY_LINUX_SSH_VERSION,
    WINDOWS_SSH_FILES,
    NativeSession,
    ssh_call,
)
from .mirrors import Mirrors
from .service import ProvelumeInstance


def docker(*arguments, incoming=None, check=True):
    environment = dict(os.environ)
    for name in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        environment.pop(name, None)
    result = subprocess.run(
        ["docker", "--host=unix:///var/run/docker.sock", *arguments],
        env=environment,
        input=incoming,
        capture_output=True,
        timeout=30,
    )
    require(
        len(result.stdout) <= 2 * 1024 * 1024 and len(result.stderr) <= 65536, "rsync_fixture_limit"
    )
    require(not check or result.returncode == 0, "rsync_fixture_command")
    return result


def remote_python(container, program, *, incoming=None, docker_runner=None):
    return (docker_runner or docker)(
        "exec",
        "-i",
        "-e",
        "PYTHONPATH=/opt/product/core",
        container,
        "/opt/python/bin/python3.12",
        "-c",
        program,
        incoming=incoming,
    ).stdout


def cleanup_fixture(work, name, owner, *, docker_runner=None):
    """Reconcile a possibly completed create; never remove an unowned resource."""
    records = []
    run = docker_runner or docker
    for resource in ("container", "network"):
        command = [] if resource == "container" else ["network"]
        record = {"resource": resource, "name": name, "result": "UNKNOWN"}
        records.append(record)
        try:
            observed = run(*command, "inspect", name, check=False)
            record["inspect_exit"] = observed.returncode
            if observed.returncode != 0:
                continue
            value = json.loads(observed.stdout)[0]
            labels = value["Config"].get("Labels", {}) if not command else value["Labels"]
            if labels.get("org.provelume.qualification.owner") != owner:
                record["result"] = "OWNERSHIP_REFUSED"
                continue
            if resource == "container":
                record["observed_state"] = value["State"]["Status"]
                logs = run("logs", name, check=False)
                (work / "server-stdout-original.log").write_bytes(logs.stdout)
                (work / "server-stderr-original.log").write_bytes(logs.stderr)
            removed = run(
                *command, "rm", *(["--force"] if not command else []), name, check=False
            )
            record["remove_exit"] = removed.returncode
            if removed.returncode == 0:
                record["result"] = "OWNED_REMOVAL_CONFIRMED"
        except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as error:
            record["exception"] = type(error).__name__
    (work / "cleanup-original.json").write_bytes(raw(records))
    require(all(row["result"] == "OWNED_REMOVAL_CONFIRMED" for row in records),
            "rsync_fixture_cleanup_unconfirmed")


def fixture_preflight(root, *, image, expected_source_commit, windows_backend=None):
    require(
        (os.name == "nt" and windows_backend is not None)
        or (os.name == "posix" and os.uname().sysname == "Linux" and windows_backend is None),
        "rsync_fixture_platform",
    )
    require(shutil.disk_usage(root).free >= 256 * 1024 * 1024, "rsync_fixture_host_space")
    require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", image)
        and re.fullmatch(r"[0-9a-f]{40}", expected_source_commit),
        "rsync_fixture_identity",
    )
    run = windows_backend.docker if windows_backend is not None else docker
    info = json.loads(run("image", "inspect", image).stdout)[0]
    labels = info["Config"].get("Labels", {})
    require(
        info["Id"] == image
        and labels.get("org.provelume.fixture") == "concordia-rsync-ssh-v1"
        and labels.get("org.provelume.source.commit") == expected_source_commit,
        "rsync_fixture_identity",
    )
    work = root / "Component preflight"
    work.mkdir(mode=0o700)
    session = NativeSession(work)
    components = {}
    for name in ("ssh", "rsync"):
        component = session.component(name)
        components[name] = {key: component[key] for key in ("version", "sha256")}
    return components


@contextmanager
def fixture(root, *, image, identity, instance, mirrors, records, windows_backend=None):
    work = root / "Fixture"
    work.mkdir(mode=0o700)
    run = windows_backend.docker if windows_backend is not None else docker
    remote = partial(remote_python, docker_runner=run)
    host = work / "host"
    if windows_backend is None:
        NativeSession(work).run(
            ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host)]
        )
        host_key = host.with_suffix(".pub").read_text().split()[1]
    config = (
        "\n".join(
            [
                "Port 2222",
                "ListenAddress 0.0.0.0",
                "HostKey /fixture/host",
                "PidFile /fixture/sshd.pid",
                "AuthorizedKeysFile /fixture/authorized",
                "AuthenticationMethods publickey",
                "PubkeyAuthentication yes",
                "PasswordAuthentication no",
                "KbdInteractiveAuthentication no",
                "UsePAM no",
                "PermitRootLogin no",
                "AllowUsers synthetic",
                "StrictModes yes",
                "LogLevel ERROR",
                "UseDNS no",
                "AllowAgentForwarding no",
                "AllowTcpForwarding no",
                "X11Forwarding no",
                "PermitTunnel no",
                "PermitTTY no",
                "PermitUserRC no",
                "SetEnv PYTHONPATH=/opt/fixture_hooks:/opt/product/core "
                "LD_LIBRARY_PATH=/opt/python/lib PYTHONDONTWRITEBYTECODE=1",
                "ForceCommand /opt/python/bin/python3.12 -m provelume.mirror_rsync_remote_main "
                "/fixture/control/namespace.json",
                "Subsystem provelume-mirror-v1 provelume-mirror-v1",
                "LoginGraceTime 15",
                "MaxAuthTries 1",
            ]
        )
        + "\n"
    )
    namespace = uuid4().hex
    name = "concordia-rsync-" + uuid4().hex[:12]
    ownership = "org.provelume.qualification.owner=" + namespace
    try:
        run("network", "create", "--internal", "--label", ownership, name)
        # A timed-out CLI create can still complete inside Docker. Its label,
        # rather than the CLI return, determines cleanup ownership in finally.
        run(
            "create",
            "--name",
            name,
            "--label",
            ownership,
            "--user",
            "1000:1000",
            "--network",
            name,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "32",
            "--memory",
            "256m",
            "--tmpfs",
            "/fixture:rw,uid=1000,gid=1000,mode=0700,size=32m",
            "--tmpfs",
            "/tmp:rw,mode=1777,size=16m",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            'n=0; while [ ! -f /fixture/ready ] && [ "$n" -lt 100 ]; '
            "do n=$((n+1)); sleep 0.1; done; "
            "exec /usr/sbin/sshd -D -e -f /fixture/sshd_config",
        )
        run("start", name)
        package = io.BytesIO()
        with tarfile.open(fileobj=package, mode="w") as archive:
            files = {
                "authorized": ("restrict " + identity["public_key"] + "\n").encode(),
                "sshd_config": config.encode(),
            }
            if windows_backend is None:
                files["host"] = host.read_bytes()
            for filename, value in files.items():
                entry = tarfile.TarInfo(filename)
                entry.mode, entry.size = 0o600, len(value)
                archive.addfile(entry, io.BytesIO(value))
        # No docker cp/rootfs mutation; stdin extraction writes only fresh tmpfs.
        remote(
            name,
            "import sys,tarfile\n"
            "with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:\n"
            " archive.extractall('/fixture',filter='data')",
            incoming=package.getvalue(),
        )
        if windows_backend is None:
            host.unlink()
        else:
            run(
                "exec", name, "/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                "-f", "/fixture/host",
            )
            host_key = remote(
                name, "from pathlib import Path\nprint(Path('/fixture/host.pub').read_text())"
            ).decode("ascii").split()[1]
        options = {
            "config_directory": "/fixture/control",
            "root": "/fixture/payload",
            "source": {
                "instance_id": instance.store.read_config()["instance"]["id"],
                "device_sha256": mirrors.device(),
            },
            "namespace": namespace,
            "client_public_sha256": identity["public_sha256"],
            "rsync_binary": "/opt/rsync/rsync",
            "excluded_roots": [],
        }
        enrolled = json.loads(
            remote(
                name,
                "import json,sys\nfrom provelume.mirror_rsync_remote_main import enroll_helper\n"
                "print(json.dumps(enroll_helper(**json.load(sys.stdin))))",
                incoming=raw(options),
            )
        )
        state = json.loads(run("inspect", name).stdout)[0]
        address = state["NetworkSettings"]["Networks"][name]["IPAddress"]
        require(
            re.fullmatch(r"172\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}", address), "rsync_fixture_network"
        )
        require(not state["HostConfig"]["PortBindings"], "rsync_fixture_network")
        network = json.loads(run("network", "inspect", name).stdout)[0]
        require(network["Internal"] is True, "rsync_fixture_network")
        remote(name, "from pathlib import Path\nPath('/fixture/ready').touch()")
        if windows_backend is not None:
            ready = remote(
                name,
                "import socket,time\n"
                "deadline=time.monotonic()+5\n"
                "while True:\n"
                " try:\n"
                "  with socket.create_connection(('127.0.0.1',2222),timeout=0.1): break\n"
                " except OSError:\n"
                "  assert time.monotonic()<deadline\n"
                "  time.sleep(0.05)\n"
                "print('READY')\n",
            )
            require(ready == b"READY\n", "rsync_fixture_readiness")
        version = run("exec", name, "/usr/sbin/sshd", "-V")
        require(
            version.stderr.startswith(LEGACY_LINUX_SSH_VERSION + b", OpenSSL "),
            "ssh_profile_not_qualified",
        )
        target = {
            "transport": "rsync-ssh",
            "host": address,
            "port": 2222,
            "username": "synthetic",
            "host_key": host_key,
            "namespace": namespace,
            "configuration_sha256": enrolled["configuration_sha256"],
            "bandwidth_kib": 1024,
            "window_start_minute_utc": 0,
            "window_end_minute_utc": 1440,
        }
        records.append(
            {
                "fixture_image": image,
                "native_server": version.stderr.decode().strip(),
                "server_rsync": enrolled["rsync"],
                "strict_modes": True,
                "network": (
                    "OWNED_INTERNAL_DOCKER_VIA_WINDOWS_LOOPBACK_RELAY"
                    if windows_backend is not None else
                    "OWNED_INTERNAL_DOCKER_NO_EGRESS_NO_PUBLISHED_PORT"
                ),
                "account": "FRESH_SYNTHETIC_CONTAINER_ACCOUNT",
            }
        )
        endpoint = (
            windows_backend.endpoint(name, address, 2222)
            if windows_backend is not None else nullcontext((address, 2222))
        )
        with endpoint as (host_address, port):
            if windows_backend is not None:
                require(host_address == "127.0.0.1", "rsync_fixture_network")
            else:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with socket.create_connection((host_address, port), timeout=0.1):
                            break
                    except OSError:
                        require(time.monotonic() < deadline, "rsync_fixture_readiness")
                        time.sleep(0.05)
            yield name, {**target, "host": host_address, "port": port}
    finally:
        host.unlink(missing_ok=True)
        cleanup_fixture(work, name, namespace, docker_runner=run)


def require_failure(call, codes=None):
    try:
        call()
    except MirrorError as error:
        require(codes is None or error.code in codes, "rsync_qualification")
        return error.code
    require(False, "rsync_qualification")


class CaseEvidence(list):
    def __init__(self, root):
        super().__init__()
        self.path = root / "case-results-original.jsonl"

    def append(self, value):
        with self.path.open("ab") as stream:
            stream.write(raw(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)


@contextmanager
def retain_trial_failure(cases, fault):
    try:
        yield
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        evidence = {
            "case": "native-fixture-" + (fault or "complete-generation"),
            "result": "INCOMPLETE",
            "closed_code": error.code if isinstance(error, MirrorError) else type(error).__name__,
        }
        if isinstance(error, MirrorError) and hasattr(error, "agent_evidence"):
            evidence["owned_agent"] = error.agent_evidence
        cases.append(evidence)
        raise


def authentication_refusals(engine, target):
    reference = engine.mirrors._grant(engine.mirrors.state()["identities"][0])["credential"][
        "reference"
    ]
    credential = engine.credentials.read(reference)
    seed = base64.b64decode(credential["seed"], validate=True)
    wrong_host = dict(
        target, host_key=base64.b64encode(public_blob(public_key(secrets.token_bytes(32)))).decode()
    )
    request = engine.request(target, "inspect")
    with native_work() as session:
        host_error = require_failure(
            lambda: ssh_call(session, wrong_host, seed, frame(request)), {"ssh_host_key"}
        )
    yield {"case": "actual-native-wrong-host-key", "result": "PASS", "error": host_error}
    with native_work() as session:
        credential_error = require_failure(
            lambda: ssh_call(session, target, secrets.token_bytes(32), frame(request)),
            {"ssh_credentials"},
        )
    yield {"case": "actual-native-unauthorized-key", "result": "PASS", "error": credential_error}


def inspect_authenticated(engine, target, reference, components):
    credential = engine.credentials.read(reference)
    seed = base64.b64decode(credential["seed"], validate=True)
    with native_work() as session:
        response, proof = ssh_call(session, target, seed, frame(engine.request(target, "inspect")))
    report = proof["agent"]
    require(
        parse(response)["namespace"] == target["namespace"]
        and {name: proof["component"][name] for name in ("sha256", "version")}
        == components["ssh"]
        and report["host_bound"] is True
        and report["signatures"] == 1
        and report["private_key_logged"] is False,
        "rsync_qualification",
    )
    return {
        "case": "actual-native-host-bound-authentication",
        "result": "PASS",
        "signatures": report["signatures"],
        "host_bound": True,
        "private_key_logged": False,
    }


@contextmanager
def qualification_identity(selected, instance):
    with ExitStack() as resources:
        windows_root = None
        if os.name == "nt":
            windows_root = Path(resources.enter_context(
                TemporaryDirectory(prefix="pv-rsync-vault-", dir=selected)
            ))
            make_private(windows_root)
        vault = GoogleCredentialVault(
            namespace="mirror", forbidden_root=instance.root, windows_root=windows_root
        )
        mirrors = Mirrors(instance.store, vault=vault)
        mirrors.set_access(
            enabled=True, github=False, rsync=True, expected_revision=0, confirmed=True
        )
        engine = RsyncMirrors(instance.store, mirrors=mirrors)
        identity = engine.create_identity(name="Synthetic dedicated native SSH", confirmed=True)
        reference = mirrors._grant(identity["identity"])["credential"]["reference"]
        try:
            yield mirrors, engine, identity, reference
        finally:
            vault.delete(reference)
            require(vault.read(reference) is None, "rsync_fixture_cleanup_unconfirmed")


def independently_read_generation(remote, container, manifest, receipt):
    observed = json.loads(
        remote(
            container,
            "import hashlib,json,stat\nfrom pathlib import Path\n"
            "base=Path('/fixture/payload')\n"
            "pointer=json.loads((base/'active.json').read_bytes())\n"
            "root=base/'generations'/pointer['generation']\n"
            "assert root.is_dir() and not root.is_symlink()\n"
            "files={}\n"
            "for item in root.rglob('*'):\n"
            " kind=item.lstat().st_mode\n"
            " if stat.S_ISDIR(kind): continue\n"
            " assert stat.S_ISREG(kind)\n"
            " with item.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256')\n"
            " files[item.relative_to(root).as_posix()]=[item.stat().st_size,digest.hexdigest()]\n"
            "print(json.dumps({'pointer':pointer,'files':files}))\n",
        )
    )
    allowed = {row["path"]: [row["size_bytes"], row["sha256"]] for row in manifest["inventory"]}
    expected_manifest = raw(manifest)
    allowed["manifest.json"] = [len(expected_manifest), receipt["generation"]]
    require(allowed == observed["files"], "rsync_qualification")
    pointer = observed["pointer"]
    require(
        pointer["generation"] == receipt["generation"]
        and pointer["manifest_sha256"] == receipt["generation"]
        and pointer["inventory_sha256"] == fingerprint(manifest["inventory"])
        and fingerprint(pointer) == receipt["transport_proof"]["active_pointer_sha256"],
        "rsync_qualification",
    )
    return {
        "generation_sha256": receipt["generation"],
        "inventory_sha256": pointer["inventory_sha256"],
        "active_pointer_sha256": fingerprint(pointer),
        "files_read": len(allowed),
    }


def qualify_rsync_mirror(root, *, image, expected_source_commit, windows_backend=None):
    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    make_private(root)
    components = fixture_preflight(
        root, image=image, expected_source_commit=expected_source_commit,
        windows_backend=windows_backend,
    )
    windows = windows_backend is not None
    frozen = getattr(sys, "frozen", False)
    installed_commit = current_build_info().get("commit") if windows and frozen else None
    if windows and frozen:
        require(installed_commit == expected_source_commit, "rsync_fixture_identity")
    remote = (
        partial(remote_python, docker_runner=windows_backend.docker) if windows else remote_python
    )
    cases, fixtures = CaseEvidence(root), []
    for fault in (None, "before", "after", "disconnect", "disk-full", "replaced-root"):
        selected = root / (fault or "Complete generation")
        selected.mkdir()
        source = selected / "Inputs"
        source.mkdir()
        (source / "one.md").write_text(
            "# Synthetic native SSH mirror\n\nFinite independently verified payload.\n"
        )
        instance = ProvelumeInstance.initialise(selected / "Instance")
        instance.ingest_run(source)
        with (
            retain_trial_failure(cases, fault),
            qualification_identity(selected, instance) as (mirrors, engine, identity, reference),
            fixture(
                selected, image=image, identity=identity, instance=instance, mirrors=mirrors,
                records=fixtures, windows_backend=windows_backend,
            ) as (container, target),
        ):
            if fault == "disconnect":
                target["bandwidth_kib"] = 32
            row = mirrors.configure(
                identity_id=identity["identity"]["id"],
                name="Synthetic isolated SSH namespace",
                target=target,
                scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
                include_rules={"originals": [], "attachments": [], "ai_receipts": []},
                mode="manual",
                confirmed=True,
            )
            engine.initialize(
                row["id"], expected_destination_sha256=row["destination_sha256"], confirmed=True
            )

            def prepare(engine=engine, row=row):
                return engine.prepare(row["id"], expected_revision=row["revision"], confirmed=True)

            def publish(plan, engine=engine):
                return engine.publish(
                    plan["id"],
                    expected_plan_sha256=plan["plan_sha256"],
                    expected_rsync_plan_sha256=plan["rsync_plan_sha256"],
                    confirmed=True,
                )

            canonical = mirrors.snapshots.source_fingerprint()
            first = publish(prepare())["receipt"]
            noop = publish(prepare())["receipt"]
            require(not noop["transport_proof"]["activation_written"], "rsync_qualification")
            require(mirrors.snapshots.source_fingerprint() == canonical, "rsync_qualification")
            if fault is None:
                require(first["transport_proof"]["activation_written"], "rsync_qualification")
                require(
                    all(
                        first["transport_proof"]["native_" + name] == component
                        for name, component in components.items()
                    ),
                    "rsync_qualification",
                )
                generation = mirrors.snapshots.verify(first["generation"])
                independent = independently_read_generation(remote, container, generation, first)
                cases.append(
                    {
                        "case": "complete-generation-and-noop",
                        "result": "PASS",
                        "receipt_sha256": fingerprint(first),
                        "independent_server_inventory": independent,
                        "canonical_unchanged": True,
                    }
                )
                cases.append(inspect_authenticated(engine, target, reference, components))
                cases.extend(authentication_refusals(engine, target))
                pending = prepare()
                engine.disconnect(identity["identity"]["id"], expected_revision=1, confirmed=True)
                require(mirrors.vault.read(reference) is None, "rsync_qualification")
                with patch.object(
                    NativeSession, "run", side_effect=AssertionError("revoked process")
                ):
                    require_failure(lambda pending=pending: publish(pending))
                cases.append(
                    {
                        "case": "revoked-grant-before-native-process",
                        "result": "PASS",
                        "native_process_calls": 0, "credential_removed": True,
                    }
                )
                continue
            if fault == "disconnect":
                (source / "partial.md").write_text(
                    "# Synthetic finite partial transfer\n"
                    + "".join(
                        "Synthetic public fixture row " + secrets.token_hex(16) + "\n"
                        for _ in range(4096)
                    )
                )
            else:
                (source / "two.md").write_text(
                    "# Synthetic second generation for declared interruption\n"
                )
            instance.ingest_run(source)
            if fault == "disconnect":
                document = next(
                    item for item in instance.list_documents() if item["title"] == "partial.md"
                )
                version = instance.store.read_canonical("versions", document["current_version_id"])
                row.update(
                    mirrors.configure(
                        identity_id=identity["identity"]["id"],
                        name=row["name"],
                        target=target,
                        scope=row["scope"],
                        include_rules={
                            "originals": [version["original_id"]],
                            "attachments": [],
                            "ai_receipts": [],
                        },
                        destination_id=row["id"],
                        expected_revision=row["revision"],
                        mode="manual",
                        confirmed=True,
                    )
                )
            canonical = mirrors.snapshots.source_fingerprint()
            plan = prepare()
            backup = instance.backup(destination=selected / "Before interrupted publication")
            if fault == "disconnect":
                remote(
                    container,
                    "import sys\nfrom pathlib import Path\n"
                    "Path('/fixture/transfer-fault.json').write_bytes(sys.stdin.buffer.read())",
                    incoming=raw({"operation_id": plan["id"], "consumed": False}),
                )
                require_failure(lambda plan=plan: publish(plan))
                observed = json.loads(
                    remote(
                        container,
                        "from pathlib import Path\n"
                        "print(Path('/fixture/transfer-fault.json').read_text())",
                    )
                )
                manifest = mirrors.snapshots.verify(plan["generation"])
                complete_bytes = manifest["total_bytes"] + len(raw(manifest))
                require(
                    observed.get("consumed") is True
                    and 65536 <= observed.get("observed_partial_bytes", 0) < complete_bytes,
                    "rsync_qualification",
                )
                require(
                    instance.restore(backup["archive"])["status"] == "restored",
                    "rsync_qualification",
                )
                recovered = engine.reconcile(plan["id"], confirmed=True)
                require(
                    recovered["outcome"] == "UNKNOWN" and recovered["explicit_resume_available"],
                    "rsync_qualification",
                )
                receipt = engine.resume(
                    plan["id"], expected_rsync_plan_sha256=plan["rsync_plan_sha256"], confirmed=True
                )["receipt"]
                require(
                    receipt["transport_proof"]["activation_written"]
                    and publish(plan)["historical"],
                    "rsync_qualification",
                )
                independent = independently_read_generation(remote, container, manifest, receipt)
                require(mirrors.snapshots.source_fingerprint() == canonical, "rsync_qualification")
                cases.append(
                    {
                        "case": "actual-native-partial-disconnect-explicit-resume-root-restore",
                        "result": "PASS",
                        "partial_bytes_observed": observed["observed_partial_bytes"],
                        "expected_complete_bytes": complete_bytes,
                        "incomplete_payload_proved": True,
                        "receiver_stop": "DURABLY_CONFIRMED",
                        "activation_attempts": 1,
                        "automatic_resume": False,
                        "independent_server_inventory": independent,
                        "canonical_unchanged": True,
                    }
                )
                continue
            if fault in {"disk-full", "replaced-root"}:
                if fault == "disk-full":
                    evidence = json.loads(
                        remote(
                            container,
                            "import json,os,errno\nwritten=0\n"
                            "with open('/fixture/physical-fill.bin','xb',buffering=0) as stream:\n"
                            " try:\n  while True: written+=stream.write(b'F'*4096)\n"
                            " except OSError as error:\n  assert error.errno==errno.ENOSPC\n"
                            "state=os.statvfs('/fixture')\n"
                            "print(json.dumps({'errno':errno.ENOSPC,'filled_bytes':written,"
                            "'available_bytes':state.f_bavail*state.f_frsize}))",
                        )
                    )
                    require(
                        evidence["errno"] == 28 and evidence["available_bytes"] == 0,
                        "rsync_qualification",
                    )
                else:
                    remote(
                        container,
                        "import shutil,os\n"
                        "shutil.copytree('/fixture/payload','/fixture/replacement')\n"
                        "os.rename('/fixture/payload','/fixture/original-payload')\n"
                        "os.rename('/fixture/replacement','/fixture/payload')",
                    )
                    evidence = {"replacement": "ACTUAL_COPIED_MARKER_DIFFERENT_PHYSICAL_ROOT"}
                error = require_failure(lambda plan=plan: publish(plan))
                active = remote(
                    container,
                    "from pathlib import Path\nprint(Path('/fixture/"
                    + ("original-payload" if fault == "replaced-root" else "payload")
                    + "/active.json').read_text())",
                )
                require(
                    json.loads(active)["generation"] == first["generation"], "rsync_qualification"
                )
                if fault == "disk-full":
                    remote(
                        container,
                        "from pathlib import Path\nPath('/fixture/physical-fill.bin').unlink()",
                    )
                cases.append(
                    {
                        "case": "actual-native-" + fault,
                        "result": "PASS",
                        "evidence": evidence,
                        "error": error,
                        "previous_generation_preserved": True,
                        "retry": False,
                    }
                )
                continue
            marker = {"phase": fault, "operation_id": plan["id"], "consumed": False}
            remote(
                container,
                "import sys\nfrom pathlib import Path\n"
                "Path('/fixture/activation-fault.json').write_bytes(sys.stdin.buffer.read())",
                incoming=raw(marker),
            )
            try:
                publish(plan)
            except MirrorError:
                pass
            else:
                require(False, "rsync_qualification")
            actual = json.loads(
                remote(
                    container,
                    "from pathlib import Path\n"
                    "print(Path('/fixture/activation-fault.json').read_text())",
                )
            )
            require(
                actual["consumed"] and actual["native_rename_performed"] == (fault == "after"),
                "rsync_qualification",
            )
            require(
                instance.restore(backup["archive"])["status"] == "restored", "rsync_qualification"
            )
            from .mirror_rsync_transport import RsyncTransport

            with patch.object(
                RsyncTransport, "transfer", side_effect=AssertionError("recovery resend")
            ):
                recovered = engine.reconcile(plan["id"], confirmed=True)
                if fault == "after":
                    require(
                        recovered["receipt"]["transport_proof"]["evidence_mode"]
                        == "reconciled_current_state"
                        and publish(plan)["historical"],
                        "rsync_qualification",
                    )
                else:
                    require(
                        recovered["outcome"] == "UNKNOWN"
                        and not recovered["explicit_resume_available"],
                        "rsync_qualification",
                    )
            require(mirrors.snapshots.source_fingerprint() == canonical, "rsync_qualification")
            cases.append(
                {
                    "case": fault + "-activation-and-actual-root-restore",
                    "result": "PASS",
                    "actual_root_restore": "PASS",
                    "resends": 0,
                    "activation_attempts": 1,
                    "expected_outcome": "COMPLETED" if fault == "after" else "UNKNOWN",
                    "canonical_unchanged": True,
                }
            )
    report = {
        "schema": "concordia-rsync-native-qualification/v1",
        "result": "PASS",
        "qualification_scope": (
            "NATIVE_WINDOWS_CLIENT_LINUX_HELPER_TRANSPORT_RECOVERY_SECURITY"
            if windows else "NATIVE_LINUX_TRANSPORT_RECOVERY_SECURITY_PREPARATION"
        ),
        "s22_acceptance": "NOT_ACCEPTED",
        "declared_expected_source_commit": expected_source_commit,
        "client_components": components,
        "fixtures": fixtures,
        "cases": cases,
        "native_vault": "WINDOWS_CURRENT_USER_DPAPI" if windows else "NATIVE_SECRET_SERVICE",
        "synthetic_credential_cleanup": "CONFIRMED",
        "isolated_fixture_cleanup": "CONFIRMED",
        "credential_values_logged": False,
        "live_accounts": "NOT_RUN",
        "whole_host_network": "NOT_INSTRUMENTED",
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
    if windows:
        report["windows_client"] = {
            "version": tuple(sys.getwindowsversion()[:3]),
            "execution": "FROZEN" if frozen else "SOURCE",
            "installed_commit": installed_commit,
            "ssh_files": {name: {"size": size, "sha256": digest}
                          for name, (size, digest) in WINDOWS_SSH_FILES.items()},
            "native_ssh_authentication": "PASS",
            "native_rsync_over_ssh": "PASS",
        }
    (root / "qualification-original.json").write_bytes(raw(report))
    return report
