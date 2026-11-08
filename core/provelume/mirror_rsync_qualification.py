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
import tarfile
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from .google_credentials import GoogleCredentialVault
from .migration_permissions import make_private
from .mirror_contract import MirrorError, fingerprint, raw, require
from .mirror_rsync import RsyncMirrors
from .mirror_rsync_transport import native_work
from .mirror_ssh_agent import public_blob
from .mirror_ssh_crypto import public_key
from .mirror_ssh_runtime import SSH_VERSION, NativeSession, ssh_call
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


def remote_python(container, program, *, incoming=None):
    return docker(
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


def fixture_preflight(root, *, image, expected_source_commit):
    require(os.name == "posix" and os.uname().sysname == "Linux", "rsync_fixture_platform")
    require(shutil.disk_usage(root).free >= 256 * 1024 * 1024, "rsync_fixture_host_space")
    require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", image)
        and re.fullmatch(r"[0-9a-f]{40}", expected_source_commit),
        "rsync_fixture_identity",
    )
    info = json.loads(docker("image", "inspect", image).stdout)[0]
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
    session.component("ssh")
    session.component("rsync")
    return info


@contextmanager
def fixture(root, *, image, expected_source_commit, identity, instance, mirrors, records):
    work = root / "Fixture"
    work.mkdir(mode=0o700)
    session = NativeSession(work)
    host = work / "host"
    session.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host)])
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
    network = None
    created = False
    try:
        network = docker("network", "create", "--internal", name).stdout.decode().strip()
        # Mark ownership before start: failed creation is still removed in finally.
        docker(
            "create",
            "--name",
            name,
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
        created = True
        docker("start", name)
        package = io.BytesIO()
        with tarfile.open(fileobj=package, mode="w") as archive:
            for filename, value in {
                "host": host.read_bytes(),
                "authorized": ("restrict " + identity["public_key"] + "\n").encode(),
                "sshd_config": config.encode(),
            }.items():
                entry = tarfile.TarInfo(filename)
                entry.mode, entry.size = 0o600, len(value)
                archive.addfile(entry, io.BytesIO(value))
        # No docker cp/rootfs mutation; stdin extraction writes only fresh tmpfs.
        remote_python(
            name,
            "import sys,tarfile\n"
            "with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:\n"
            " archive.extractall('/fixture',filter='data')",
            incoming=package.getvalue(),
        )
        host.unlink()
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
            remote_python(
                name,
                "import json,sys\nfrom provelume.mirror_rsync_remote_main import enroll_helper\n"
                "print(json.dumps(enroll_helper(**json.load(sys.stdin))))",
                incoming=raw(options),
            )
        )
        state = json.loads(docker("inspect", name).stdout)[0]
        address = state["NetworkSettings"]["Networks"][name]["IPAddress"]
        require(
            re.fullmatch(r"172\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}", address), "rsync_fixture_network"
        )
        remote_python(name, "from pathlib import Path\nPath('/fixture/ready').touch()")
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection((address, 2222), timeout=0.1):
                    break
            except OSError:
                require(time.monotonic() < deadline, "rsync_fixture_readiness")
                time.sleep(0.05)
        version = docker("exec", name, "/usr/sbin/sshd", "-V")
        require(version.stderr.startswith(SSH_VERSION + b", OpenSSL "), "ssh_profile_not_qualified")
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
                "network": "OWNED_INTERNAL_DOCKER_NO_EGRESS_NO_PUBLISHED_PORT",
                "account": "FRESH_SYNTHETIC_CONTAINER_ACCOUNT",
            }
        )
        yield name, target
    finally:
        host.unlink(missing_ok=True)
        if created:
            logs = docker("logs", name, check=False)
            (work / "server-stdout-original.log").write_bytes(logs.stdout)
            (work / "server-stderr-original.log").write_bytes(logs.stderr)
            docker("rm", "--force", name, check=False)
        if network:
            docker("network", "rm", name, check=False)


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
    from .mirror_rsync_protocol import frame

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


def qualify_rsync_mirror(root, *, image, expected_source_commit):
    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    make_private(root)
    fixture_preflight(root, image=image, expected_source_commit=expected_source_commit)
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
        vault = GoogleCredentialVault(namespace="mirror", forbidden_root=instance.root)
        mirrors = Mirrors(instance.store, vault=vault)
        mirrors.set_access(
            enabled=True, github=False, rsync=True, expected_revision=0, confirmed=True
        )
        engine = RsyncMirrors(instance.store, mirrors=mirrors)
        identity = engine.create_identity(name="Synthetic dedicated native SSH", confirmed=True)
        with fixture(
            selected,
            image=image,
            expected_source_commit=expected_source_commit,
            identity=identity,
            instance=instance,
            mirrors=mirrors,
            records=fixtures,
        ) as (container, target):
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
                cases.append(
                    {
                        "case": "complete-generation-and-noop",
                        "result": "PASS",
                        "receipt_sha256": fingerprint(first),
                        "canonical_unchanged": True,
                    }
                )
                cases.extend(authentication_refusals(engine, target))
                pending = prepare()
                engine.disconnect(identity["identity"]["id"], expected_revision=1, confirmed=True)
                with patch.object(
                    NativeSession, "run", side_effect=AssertionError("revoked process")
                ):
                    require_failure(lambda pending=pending: publish(pending))
                cases.append(
                    {
                        "case": "revoked-grant-before-native-process",
                        "result": "PASS",
                        "native_process_calls": 0,
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
                remote_python(
                    container,
                    "import sys\nfrom pathlib import Path\n"
                    "Path('/fixture/transfer-fault.json').write_bytes(sys.stdin.buffer.read())",
                    incoming=raw({"operation_id": plan["id"], "consumed": False}),
                )
                require_failure(lambda plan=plan: publish(plan))
                observed = json.loads(
                    remote_python(
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
                        "canonical_unchanged": mirrors.snapshots.source_fingerprint() == canonical,
                    }
                )
                continue
            if fault in {"disk-full", "replaced-root"}:
                if fault == "disk-full":
                    evidence = json.loads(
                        remote_python(
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
                    remote_python(
                        container,
                        "import shutil,os\n"
                        "shutil.copytree('/fixture/payload','/fixture/replacement')\n"
                        "os.rename('/fixture/payload','/fixture/original-payload')\n"
                        "os.rename('/fixture/replacement','/fixture/payload')",
                    )
                    evidence = {"replacement": "ACTUAL_COPIED_MARKER_DIFFERENT_PHYSICAL_ROOT"}
                error = require_failure(lambda plan=plan: publish(plan))
                active = remote_python(
                    container,
                    "from pathlib import Path\nprint(Path('/fixture/"
                    + ("original-payload" if fault == "replaced-root" else "payload")
                    + "/active.json').read_text())",
                )
                require(
                    json.loads(active)["generation"] == first["generation"], "rsync_qualification"
                )
                if fault == "disk-full":
                    remote_python(
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
            remote_python(
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
                remote_python(
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
        "qualification_scope": "NATIVE_LINUX_TRANSPORT_RECOVERY_SECURITY_PREPARATION",
        "s22_acceptance": "NOT_ACCEPTED",
        "declared_expected_source_commit": expected_source_commit,
        "fixtures": fixtures,
        "cases": cases,
        "native_vault": "NATIVE_SECRET_SERVICE",
        "credential_values_logged": False,
        "live_accounts": "NOT_RUN",
        "whole_host_network": "NOT_INSTRUMENTED",
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
    (root / "qualification-original.json").write_bytes(raw(report))
    return report
