"""Installed forced-command namespace authority; no generic remote shell or adoption."""

from __future__ import annotations

import os
import re
import shutil
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .maintenance_local_files import directory_binding, open_local_directory, open_local_file
from .migration_permissions import private_directory
from .mirror_contract import (
    MAX_GENERATIONS,
    MAX_PLANS,
    MirrorError,
    fingerprint,
    identifier,
    parse,
    raw,
    require,
)
from .mirror_folder_files import MAX_TARGET_BYTES, MAX_TARGET_FILES, FolderTree, owned_folder_root
from .mirror_rsync_protocol import HELPER_VERSION, PROFILE, pointer, receiver_arguments, request
from .mirror_rsync_stream import receive
from .mirror_ssh_runtime import NativeSession


def exclude(selected, excluded):
    for ancestor in (selected, *selected.parents):
        require(
            not (ancestor.name.startswith(".") and ancestor.name.endswith(".provelume")),
            "rsync_namespace_boundary",
        )
        for name in ("provelume.yml", "instance-manifest.json", "backup-manifest.json"):
            try:
                (ancestor / name).lstat()
            except FileNotFoundError:
                continue
            raise MirrorError("rsync_namespace_boundary")
    require(
        all(
            not selected.is_relative_to(path) and not path.is_relative_to(selected)
            for path in excluded
        ),
        "rsync_namespace_boundary",
    )


def config_value(value):
    require(
        type(value) is dict
        and set(value)
        == {
            "schema",
            "namespace",
            "root",
            "source",
            "client_public_sha256",
            "excluded_roots",
            "rsync_binary",
            "rsync_sha256",
        },
        "rsync_namespace_configuration",
    )
    require(
        value["schema"] == "provelume-rsync-namespace/v1"
        and type(value["namespace"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", value["namespace"]),
        "rsync_namespace_configuration",
    )
    require(
        type(value["source"]) is dict and set(value["source"]) == {"instance_id", "device_sha256"},
        "rsync_namespace_configuration",
    )
    identifier(value["source"]["instance_id"], "inst")
    for digest in (
        value["source"]["device_sha256"],
        value["client_public_sha256"],
        value["rsync_sha256"],
    ):
        require(
            type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest),
            "rsync_namespace_configuration",
        )
    require(
        type(value["excluded_roots"]) is list and len(value["excluded_roots"]) <= 32,
        "rsync_namespace_configuration",
    )
    for name in (value["root"], value["rsync_binary"], *value["excluded_roots"]):
        require(
            type(name) is str
            and 0 < len(name) <= 4096
            and Path(name).is_absolute()
            and not any(ord(char) < 32 for char in name)
            and ".." not in Path(name).parts,
            "rsync_namespace_configuration",
        )
    return value


def read_config(path):
    path = Path(path)
    private_directory(path.parent)
    with open_local_file(path) as stream:
        info = os.fstat(stream.fileno())
        require(
            os.name == "posix"
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600,
            "rsync_namespace_configuration",
        )
        data = stream.read(16385)
    require(len(data) <= 16384, "limit")
    return config_value(parse(data))


class RemoteNamespace:
    def __init__(self, config_path):
        self.path = Path(config_path)
        self.config = read_config(self.path)
        self.identity = fingerprint(self.config)

    def unchanged(self):
        require(
            fingerprint(read_config(self.path)) == self.identity,
            "rsync_namespace_configuration_changed",
        )

    def admit(self, selected):
        exclude(selected, [self.path.parent, *map(Path, self.config["excluded_roots"])])

    @contextmanager
    def tree(self, *, fresh=False):
        expected = {
            **self.config["source"],
            "destination_sha256": fingerprint(
                [PROFILE, self.config["namespace"], self.config["source"]]
            ),
        }
        with owned_folder_root(
            self.config["root"],
            expected=expected,
            admit=self.admit,
            namespace=self.config["namespace"],
            fresh=fresh,
        ) as tree:
            yield tree

    @contextmanager
    def control(self, *, deadline):
        # Real, separately installed namespace configuration is the authority.
        # This is a low-level guarded control tree, not a fabricated Instance.
        with ExitStack() as stack:
            root, binding = stack.enter_context(open_local_directory(self.path.parent))
            private_directory(root)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, descriptor)
            require(
                directory_binding(descriptor) == binding, "rsync_namespace_configuration_changed"
            )
            control = FolderTree(root, descriptor, binding, deadline=deadline)
            require(len(control.names("operations")) <= MAX_PLANS, "rsync_operation_limit")
            yield control

    def admit_request(self, value):
        request(value)
        require(
            value["namespace"] == self.config["namespace"]
            and value["configuration_sha256"] == self.identity,
            "rsync_namespace_configuration_changed",
        )
        self.unchanged()

    @contextmanager
    def component(self):
        with TemporaryDirectory(prefix="receiver-", dir=self.path.parent) as directory:
            work = Path(directory)
            session = NativeSession(work)
            component = session.component("rsync", binary=self.config["rsync_binary"])
            require(
                component["sha256"] == self.config["rsync_sha256"], "rsync_profile_not_qualified"
            )
            yield component, work

    def description(self, tree, component):
        active, payload = tree.active()
        return {
            "schema": "provelume-rsync-observation/v1",
            "helper": HELPER_VERSION,
            "profile": PROFILE,
            "configuration_sha256": self.identity,
            "namespace": self.config["namespace"],
            "root_sha256": fingerprint(tree.binding),
            "marker": tree.marker,
            "filesystem_profile": tree.profile,
            "rsync": {key: component[key] for key in ("version", "sha256")},
            "active_pointer": active,
            "inventory": payload,
            "storage": tree.audit(),
        }

    def inspect(self, value):
        self.admit_request(value)
        with (
            self.component() as (component, _work),
            self.tree(fresh=value["action"] == "initialize") as tree,
        ):
            result = self.description(tree, component)
            if value["action"] == "operation":
                with self.control(deadline=tree.deadline) as control:
                    name = "operations/" + value["operation_id"] + ".json"
                    state = parse(control.read(name)) if control.exists(name) else None
                    if state is not None:
                        require(
                            state["transport_sha256"] == value["transport_sha256"]
                            and state["operation_id"] == value["operation_id"],
                            "rsync_operation_changed",
                        )
                    result["operation"] = state
            self.unchanged()
            return result

    @staticmethod
    def save(control, name, value, *, first=False):
        if first:
            require(not control.exists(name), "rsync_operation_replay")
            control.write(name, raw(value))
        else:
            temporary = "operations/temporary-" + uuid4().hex + ".json"
            control.write(temporary, raw(value))
            control.rename(temporary, name, replace=True)

    @staticmethod
    def operation_binding(value):
        return {
            "schema": "provelume-rsync-operation/v1",
            "operation_id": value["operation_id"],
            "transport_sha256": value["transport_sha256"],
            "manifest_sha256": fingerprint(value["manifest"]),
            "expected_pointer_sha256": fingerprint(value["expected_pointer"]),
        }

    @staticmethod
    def partial(tree, stage, manifest):
        expected = {row["path"]: row["size_bytes"] for row in manifest["inventory"]}
        require("manifest.json" not in expected, "rsync_incomplete")
        expected["manifest.json"] = len(raw(manifest))
        for name, size in tree.files(stage):
            relative = name[len(stage) + 1 :]
            require(relative in expected and size <= expected[relative], "rsync_unknown_content")

    def transfer(self, value, *, incoming, outgoing):
        self.admit_request(value)
        require(value["action"] in {"receive", "resume"}, "rsync_protocol")
        with (
            self.component() as (component, work),
            self.tree() as tree,
            self.control(deadline=tree.deadline) as control,
        ):
            require(tree.active()[0] == value["expected_pointer"], "destination_changed")
            name = "operations/" + value["operation_id"] + ".json"
            stage = "staging/" + value["operation_id"]
            binding = self.operation_binding(value)
            if value["action"] == "resume":
                state = parse(control.read(name))
                require(
                    all(state.get(key) == item for key, item in binding.items())
                    and state.get("phase") == "TRANSFER_INTERRUPTED"
                    and state.get("activation_started") is False
                    and state.get("native_child_stopped") is True,
                    "rsync_resume_not_proven_safe",
                )
                self.partial(tree, stage, value["manifest"])
            else:
                require(len(control.names("operations")) < MAX_PLANS, "rsync_operation_limit")
                storage = tree.audit()
                require(
                    len(storage["staging"]) + len(storage["generations"]) < MAX_GENERATIONS
                    and storage["files"] + len(value["manifest"]["inventory"]) + 1
                    <= MAX_TARGET_FILES
                    and storage["bytes"]
                    + value["manifest"]["total_bytes"]
                    + len(raw(value["manifest"]))
                    + 4096
                    <= MAX_TARGET_BYTES,
                    "rsync_storage_limit",
                )
                require(
                    shutil.disk_usage(tree.root).free
                    >= value["manifest"]["total_bytes"] + len(raw(value["manifest"])) + 4096,
                    "rsync_disk_full",
                )
                state = {
                    **binding,
                    "phase": "RESERVING",
                    "activation_started": False,
                    "native_child_stopped": True,
                }
                self.save(control, name, state, first=True)
                tree.mkdir(stage)
            state = {**state, "phase": "TRANSFERRING", "native_child_stopped": False}
            self.save(control, name, state)
            outcome = {"native_child_stopped": False}
            try:
                result = receive(
                    receiver_arguments(
                        component["path"], value["bandwidth_kib"], tree.root / stage
                    ),
                    tree=tree,
                    stage=stage,
                    incoming=incoming,
                    outgoing=outgoing,
                    work=work,
                    outcome=outcome,
                )
                require(
                    result["returncode"] == 0 and result["native_child_stopped"],
                    "rsync_transfer_interrupted",
                )
                tree.generation(stage, binding["manifest_sha256"])
                tree.sync_directories(stage)
                self.unchanged()
                self.save(
                    control, name, {**state, "phase": "VERIFIED", "native_child_stopped": True}
                )
                return 0
            except Exception:
                # receive() returns/raises only after its owned native group is
                # stopped. A killed helper never writes this safety proof.
                if outcome["native_child_stopped"]:
                    self.save(
                        control,
                        name,
                        {**state, "phase": "TRANSFER_INTERRUPTED", "native_child_stopped": True},
                    )
                raise

    def activate(self, value):
        self.admit_request(value)
        require(value["action"] == "activate", "rsync_protocol")
        with (
            self.component() as (component, _work),
            self.tree() as tree,
            self.control(deadline=tree.deadline) as control,
        ):
            name = "operations/" + value["operation_id"] + ".json"
            state = parse(control.read(name))
            require(
                all(state.get(key) == item for key, item in self.operation_binding(value).items())
                and state.get("phase") == "VERIFIED"
                and state.get("activation_started") is False
                and state.get("native_child_stopped") is True,
                "rsync_activation_replay",
            )
            require(tree.active()[0] == value["expected_pointer"], "destination_changed")
            stage = "staging/" + value["operation_id"]
            generation = fingerprint(value["manifest"])
            tree.generation(stage, generation)
            self.unchanged()
            self.save(control, name, {**state, "phase": "ACTIVATING", "activation_started": True})
            final = "generations/" + generation
            if tree.exists(final):
                tree.generation(final, generation)
            else:
                tree.rename(stage, final)
            candidate = pointer(value)
            temporary = "staging/activate-" + value["operation_id"] + ".json"
            tree.write(temporary, raw(candidate))
            require(tree.active()[0] == value["expected_pointer"], "destination_changed")
            self.unchanged()
            tree.rename(temporary, "active.json", replace=True)
            result = self.description(tree, component)
            require(result["active_pointer"] == candidate, "outcome_unknown")
            self.save(control, name, {**state, "phase": "ACTIVATED", "activation_started": True})
            return result
