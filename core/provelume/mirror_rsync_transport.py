"""Actual native sender and read-only remote observations; no ambient SSH agent."""

from __future__ import annotations

import base64
import os
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .maintenance_local_files import directory_binding, open_local_directory, open_local_file
from .migration_permissions import make_private
from .mirror_contract import MAX_FILE_BYTES, fingerprint, inventory, parse, raw, require, sha
from .mirror_folder_files import FolderTree
from .mirror_rsync_protocol import HELPER_VERSION, PROFILE, frame, request
from .mirror_ssh_agent import public_blob
from .mirror_ssh_agent_process import AgentWorker
from .mirror_ssh_crypto import public_key
from .mirror_ssh_runtime import NativeSession, configuration, ssh_call


@contextmanager
def native_work(*, deadline=None):
    with TemporaryDirectory(prefix="pv-rsync-") as name:
        work = Path(name)
        make_private(work)
        yield NativeSession(work, deadline=deadline)


def observation(value, target, *, instance_id, device):
    configuration(target)
    require(
        type(value) is dict
        and set(value)
        in (
            {
                "schema",
                "helper",
                "profile",
                "configuration_sha256",
                "namespace",
                "root_sha256",
                "marker",
                "filesystem_profile",
                "rsync",
                "active_pointer",
                "inventory",
                "storage",
            },
            {
                "schema",
                "helper",
                "profile",
                "configuration_sha256",
                "namespace",
                "root_sha256",
                "marker",
                "filesystem_profile",
                "rsync",
                "active_pointer",
                "inventory",
                "storage",
                "operation",
            },
        ),
        "rsync_observation",
    )
    require(
        value["schema"] == "provelume-rsync-observation/v1"
        and value["helper"] == HELPER_VERSION
        and value["profile"] == PROFILE
        and value["configuration_sha256"] == target["configuration_sha256"]
        and value["namespace"] == target["namespace"]
        and value["filesystem_profile"] == "linux-local-renameat2/v1"
        and value["rsync"]["version"] == "3.5.2",
        "rsync_profile_not_qualified",
    )
    require(
        value["marker"]
        == {
            "schema": "provelume-folder-target/v1",
            "namespace": target["namespace"],
            "instance_id": instance_id,
            "device_sha256": device,
            "root_sha256": value["root_sha256"],
            "destination_sha256": fingerprint(
                [
                    PROFILE,
                    target["namespace"],
                    {"instance_id": instance_id, "device_sha256": device},
                ]
            ),
        },
        "rsync_namespace",
    )
    inventory(value["inventory"])
    require(
        value["active_pointer"] is None or type(value["active_pointer"]) is dict,
        "rsync_observation",
    )
    return value


class RsyncTransport:
    def __init__(self, session, target, credential, *, instance_id, device):
        self.session, self.target, self.credential = session, configuration(target), credential
        self.instance_id, self.device = instance_id, device
        self.components = {name: session.component(name) for name in ("ssh", "rsync")}
        self.seed = base64.b64decode(credential["seed"], validate=True)

    def rpc(self, value):
        request(value)
        data, _proof = ssh_call(self.session, self.target, self.seed, frame(value))
        return observation(
            parse(data), self.target, instance_id=self.instance_id, device=self.device
        )

    def copy_generation(self, mirrors, plan):
        manifest = mirrors.snapshots.verify(plan["generation"])
        with ExitStack() as resources:
            root, binding = resources.enter_context(open_local_directory(self.session.work))
            descriptor = None
            if os.name != "nt":
                descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                resources.callback(os.close, descriptor)
                require(directory_binding(descriptor) == binding, "rsync_source_changed")
            tree = FolderTree(root, descriptor, binding, deadline=self.session.deadline)
            tree.mkdir("payload")
            for row in manifest["inventory"]:
                source = mirrors.snapshots.root() / plan["generation"] / row["path"]
                with (
                    open_local_file(source) as incoming,
                    tree.file("payload/" + row["path"], create=True) as outgoing,
                ):
                    count = 0
                    while data := incoming.read(1024 * 1024):
                        tree.check()
                        count += len(data)
                        require(count <= row["size_bytes"] <= MAX_FILE_BYTES, "integrity")
                        outgoing.write(data)
                    require(count == row["size_bytes"], "integrity")
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
            tree.write("payload/manifest.json", raw(manifest))
            tree.generation("payload", plan["generation"])
        return manifest

    def transfer(self, value, *, mirrors, plan):
        request(value)
        self.copy_generation(mirrors, plan)
        work = self.session.work
        identity = public_blob(public_key(self.seed))
        public, known = work / "identity.pub", work / "known_hosts"
        public.write_bytes(b"ssh-ed25519 " + base64.b64encode(identity) + b"\n")
        known_host = (
            self.target["host"]
            if self.target["port"] == 22
            else "[" + self.target["host"] + "]:" + str(self.target["port"])
        )
        known.write_text(
            known_host + " ssh-ed25519 " + self.target["host_key"] + "\n", encoding="ascii"
        )
        deadline = min(self.session.deadline, time.monotonic() + 30)
        with AgentWorker(
            self.seed,
            host_public_blob=base64.b64decode(self.target["host_key"], validate=True),
            username=self.target["username"],
            deadline=deadline,
        ) as agent:
            context = work / (uuid4().hex + "-rsh.json")
            context.write_bytes(
                raw(
                    {
                        "schema": "provelume-rsync-rsh/v1",
                        "target": self.target,
                        "ssh": self.components["ssh"],
                        "agent": agent.endpoint,
                        "request": value,
                        "deadline": deadline,
                    }
                )
            )
            if getattr(sys, "frozen", False):
                adapter = [sys.executable, "--internal-rsync-rsh", str(context)]
            else:
                adapter = [sys.executable, "-m", "provelume.mirror_rsync_rsh", str(context)]
                self.session.environment["PYTHONPATH"] = str(
                    Path(__file__).absolute().parent.parent
                )
                self.session.environment["PYTHONNOUSERSITE"] = "1"
            # rsync parses this string itself, without cmd.exe or a POSIX shell.
            # Its documented parser uses quote doubling, not backslash escapes.
            rsh = " ".join('"' + argument.replace('"', '""') + '"' for argument in adapter)
            source_path = str(work / "payload")
            if os.name == "nt":
                # NativeSession fixes cwd to this exact private work directory.
                # The minimal MSYS2 input has no admitted drive-mount table;
                # this fixed relative child needs neither a mount nor a colon.
                source_path = "./payload"
            arguments = [
                self.components["rsync"]["path"],
                "--recursive",
                "--checksum",
                "--no-links",
                "--no-devices",
                "--no-specials",
                "--no-owner",
                "--no-group",
                "--no-perms",
                "--chmod=Du=rwx,Dgo=,Fu=rw,Fgo=",
                "--inplace",
                "--partial",
                "--bwlimit=" + str(self.target["bandwidth_kib"]),
                "--timeout=15",
                "--rsh=" + rsh,
                source_path + "/",
                self.target["username"] + "@" + self.target["host"] + ":generation",
            ]
            self.session.run(arguments)
        return {
            "native_rsync": {key: self.components["rsync"][key] for key in ("version", "sha256")},
            "native_ssh": {key: self.components["ssh"][key] for key in ("version", "sha256")},
            "agent": agent.report,
            "source_manifest_sha256": sha(raw(value["manifest"])),
        }
