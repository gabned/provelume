"""Versioned closed SSH subsystem control and one fixed rsync receiver profile."""

from __future__ import annotations

import os
import re
import select
import struct
import time

from .mirror_contract import (
    MAX_MANIFEST_BYTES,
    fingerprint,
    identifier,
    includes,
    inventory,
    parse,
    raw,
    require,
    selection,
)

PROFILE = "rsync-ssh/3.5.2/v1"
HELPER_VERSION = "provelume-mirror-helper/1"
SHORT_OPTIONS = "-rce.iLsfxCIvu"
ACTIONS = {"inspect", "initialize", "receive", "resume", "activate", "operation"}


def frame(value):
    data = raw(value)
    return struct.pack(">I", len(data)) + data


def read_frame(descriptor, *, deadline=None):
    # Raw fd reads are intentional: buffered stdin may prefetch rsync bytes that
    # must subsequently remain available to its native receiver.
    deadline = min(deadline or float("inf"), time.monotonic() + 5)

    def exact(length):
        value = bytearray()
        while len(value) < length:
            remaining = deadline - time.monotonic()
            require(
                remaining > 0 and select.select([descriptor], [], [], remaining)[0],
                "rsync_protocol_deadline",
            )
            chunk = os.read(descriptor, min(65536, length - len(value)))
            require(chunk, "rsync_protocol")
            value.extend(chunk)
        return bytes(value)

    size = struct.unpack(">I", exact(4))[0]
    require(0 < size <= MAX_MANIFEST_BYTES, "limit")
    return parse(exact(size))


def request(value):
    require(
        type(value) is dict
        and value.get("schema") == "provelume-rsync-request/v1"
        and value.get("action") in ACTIONS
        and type(value.get("namespace")) is str
        and re.fullmatch(r"[0-9a-f]{32}", value["namespace"]),
        "rsync_protocol",
    )
    require(
        type(value.get("configuration_sha256")) is str
        and re.fullmatch(r"[0-9a-f]{64}", value["configuration_sha256"]),
        "rsync_protocol",
    )
    common = {"schema", "action", "namespace", "configuration_sha256"}
    if value["action"] in {"inspect", "initialize"}:
        require(set(value) == common, "rsync_protocol")
    elif value["action"] == "operation":
        require(set(value) == common | {"operation_id", "transport_sha256"}, "rsync_protocol")
    else:
        require(
            set(value)
            == common
            | {"operation_id", "transport_sha256", "manifest", "expected_pointer", "bandwidth_kib"},
            "rsync_protocol",
        )
        manifest = value["manifest"]
        require(
            type(manifest) is dict
            and set(manifest)
            == {
                "schema",
                "scope",
                "include_rules",
                "source_fingerprint",
                "inventory",
                "findings",
                "total_bytes",
                "canonical",
                "complete",
            }
            and manifest.get("schema") == "provelume-mirror-generation/v1"
            and manifest.get("complete") is True
            and manifest.get("canonical") is False,
            "rsync_incomplete",
        )
        inventory(manifest["inventory"])
        selection(manifest["scope"])
        includes(manifest["include_rules"])
        require(
            type(manifest["total_bytes"]) is int
            and manifest["total_bytes"] == sum(row["size_bytes"] for row in manifest["inventory"]),
            "rsync_incomplete",
        )
        require(
            type(value["bandwidth_kib"]) is int and 1 <= value["bandwidth_kib"] <= 102400,
            "rsync_bandwidth",
        )
        require(
            value["expected_pointer"] is None or type(value["expected_pointer"]) is dict,
            "rsync_protocol",
        )
    if "operation_id" in value:
        identifier(value["operation_id"], "mirplan")
        require(
            type(value["transport_sha256"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", value["transport_sha256"]),
            "rsync_protocol",
        )
    return value


def receiver_arguments(binary, bandwidth_kib, path):
    require(type(bandwidth_kib) is int and 1 <= bandwidth_kib <= 102400, "rsync_bandwidth")
    return [
        binary,
        "--server",
        SHORT_OPTIONS,
        "--timeout=15",
        "--bwlimit=" + str(bandwidth_kib),
        "--inplace",
        ".",
        str(path),
    ]


def expected_rsh_arguments(target):
    # Observed from the independently built, signed upstream 3.5.2 sender. No
    # caller-selected remote executable, shell, option, destination or source path.
    return [
        "-l",
        target["username"],
        target["host"],
        "rsync",
        "--server",
        SHORT_OPTIONS,
        "--timeout=15",
        "--bwlimit=" + str(target["bandwidth_kib"]),
        "--inplace",
        ".",
        "generation",
    ]


def pointer(value):
    return {
        "schema": "provelume-folder-active/v1",
        "generation": fingerprint(value["manifest"]),
        "manifest_sha256": fingerprint(value["manifest"]),
        "inventory_sha256": fingerprint(value["manifest"]["inventory"]),
        "operation_id": value["operation_id"],
        "previous_pointer_sha256": fingerprint(value["expected_pointer"]),
    }


def validate_transport_proof(value, observation):
    require(
        type(value) is dict
        and set(value)
        == {
            "profile",
            "root_sha256",
            "namespace",
            "configuration_sha256",
            "host_key_sha256",
            "active_pointer_sha256",
            "activation_written",
            "filesystem_profile",
            "native_rsync",
            "native_ssh",
            "evidence_mode",
            "publication_time",
        },
        "rsync_proof",
    )
    require(
        value["profile"] == PROFILE
        and observation["visibility"] == "private"
        and type(value["activation_written"]) is bool
        and value["filesystem_profile"] == "linux-local-renameat2/v1"
        and value["evidence_mode"] in {"direct_verified", "reconciled_current_state"}
        and value["publication_time"] is None
        and type(value["namespace"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", value["namespace"]),
        "rsync_proof",
    )
    for key in ("root_sha256", "configuration_sha256", "host_key_sha256", "active_pointer_sha256"):
        require(
            type(value[key]) is str and re.fullmatch(r"[0-9a-f]{64}", value[key]), "rsync_proof"
        )
    from .mirror_ssh_runtime import SSH_VERSION

    for key, version in (("native_rsync", "3.5.2"), ("native_ssh", SSH_VERSION.decode("ascii"))):
        component = value[key]
        require(
            type(component) is dict
            and set(component) == {"version", "sha256"}
            and component["version"] == version
            and type(component["sha256"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", component["sha256"]),
            "rsync_proof",
        )


RSYNC_DIAGNOSTICS = frozenset(
    (
        "rsync_activation_not_proven_safe",
        "rsync_activation_replay",
        "rsync_bandwidth",
        "rsync_binding_changed",
        "rsync_child_outcome_unknown",
        "rsync_command",
        "rsync_component_unavailable",
        "rsync_disabled",
        "rsync_disk_full",
        "rsync_forced_command_required",
        "rsync_helper_unavailable",
        "rsync_incomplete",
        "rsync_namespace",
        "rsync_namespace_boundary",
        "rsync_namespace_configuration",
        "rsync_namespace_configuration_changed",
        "rsync_namespace_exists",
        "rsync_observation",
        "rsync_operation_changed",
        "rsync_operation_limit",
        "rsync_operation_replay",
        "rsync_output_limit",
        "rsync_plan",
        "rsync_profile_not_qualified",
        "rsync_proof",
        "rsync_protocol",
        "rsync_protocol_deadline",
        "rsync_resume_not_proven_safe",
        "rsync_rsh_arguments",
        "rsync_rsh_context",
        "rsync_server_profile_not_qualified",
        "rsync_source_changed",
        "rsync_source_path",
        "rsync_storage_limit",
        "rsync_stream",
        "rsync_stream_limit",
        "rsync_target",
        "rsync_transfer_interrupted",
        "rsync_unknown_content",
        "rsync_window",
        "rsync_window_closed",
        "ssh_agent_containment",
        "ssh_agent_deadline",
        "ssh_agent_forwarding",
        "ssh_agent_identity",
        "ssh_agent_pipe",
        "ssh_agent_request",
        "ssh_agent_session",
        "ssh_agent_unavailable",
        "ssh_command_failed",
        "ssh_component_path",
        "ssh_credentials",
        "ssh_crypto_unavailable",
        "ssh_host_key",
        "ssh_identity",
        "ssh_key",
        "ssh_profile_not_qualified",
    )
)
