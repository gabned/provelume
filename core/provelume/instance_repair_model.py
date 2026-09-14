"""Closed contract for one explicitly confirmed, local state repair."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

REPAIR_PROFILE = "repair.maintenance_redundant_atomic_artifact"
REPAIR_SCHEMA = 1
MAX_REPAIR_FILE_BYTES = 8 * 1024 * 1024
MAX_REPAIR_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_REPAIR_ENTRIES = 10_000
REPAIR_BACKUP_SCOPE = "one_file_write_set_and_read_only_context_not_full_instance"
_ARTIFACT = re.compile(
    r"state/maintenance/reindex-runs/\.(reindex_[0-9a-f]{32}\.json)\.[A-Za-z0-9_-]{1,64}\Z"
)
_IDENTIFIER = re.compile(r"(?:backup|receipt)_[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class InstanceRepairError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def encoded(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_target(relative_path: str) -> str:
    match = _ARTIFACT.fullmatch(relative_path) if isinstance(relative_path, str) else None
    if match is None:
        raise InstanceRepairError("unsupported_artifact_path")
    return "state/maintenance/reindex-runs/" + match.group(1)


def identifier(value: str, prefix: str) -> str:
    if (
        not isinstance(value, str)
        or not _IDENTIFIER.fullmatch(value)
        or not value.startswith(prefix + "_")
    ):
        raise InstanceRepairError("invalid_identifier")
    return value


def request_identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise InstanceRepairError("invalid_request_id")
    return value


def validate_binding(value: Any) -> dict[str, Any]:
    fields = {
        "profile",
        "instance_id",
        "instance_root",
        "relative_path",
        "target_path",
        "affected_files",
        "context",
        "finding",
        "validation_report",
        "inventory",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value.get("profile") != REPAIR_PROFILE
    ):
        raise InstanceRepairError("invalid_plan")
    if artifact_target(value["relative_path"]) != value["target_path"]:
        raise InstanceRepairError("invalid_plan")
    if not isinstance(value["instance_root"], str) or not re.fullmatch(
        r"inst_[0-9a-f]{32}", str(value["instance_id"])
    ):
        raise InstanceRepairError("invalid_plan")
    run_id = value["target_path"].split("/")[-1][:-5]
    suffix = run_id.removeprefix("reindex_")
    expected = [
        value["target_path"],
        f"state/scheduler/jobs/job_{suffix}.json",
        f"state/scheduler/receipts/receipt_{suffix}.json",
        "provelume.yml",
        "instance-manifest.json",
    ]
    for rows, paths in (
        (value["affected_files"], [value["relative_path"]]),
        (value["context"], expected),
    ):
        if not isinstance(rows, list) or len(rows) != len(paths):
            raise InstanceRepairError("invalid_plan")
        for row, path in zip(rows, paths, strict=True):
            if (
                not isinstance(row, dict)
                or set(row) != {"path", "size", "sha256"}
                or row["path"] != path
                or type(row["size"]) is not int
                or not 0 <= row["size"] <= MAX_REPAIR_FILE_BYTES
                or not _DIGEST.fullmatch(str(row["sha256"]))
            ):
                raise InstanceRepairError("invalid_plan")
    report = value["validation_report"]
    if (
        not isinstance(report, dict)
        or report.get("status") != "invalid"
        or report.get("instance_id") != value["instance_id"]
        or report.get("content_fingerprint") is not None
        or report.get("errors") != [value["finding"]]
    ):
        raise InstanceRepairError("invalid_plan")
    finding = value["finding"]
    if (
        not isinstance(finding, dict)
        or finding.get("code") != "maintenance_record_invalid"
        or finding.get("path") != value["relative_path"]
    ):
        raise InstanceRepairError("invalid_plan")
    inventory = value["inventory"]
    if not isinstance(inventory, dict) or set(inventory) != {"runs", "jobs", "receipts"}:
        raise InstanceRepairError("invalid_plan")
    for rows in inventory.values():
        if (
            not isinstance(rows, list)
            or len(rows) > MAX_REPAIR_ENTRIES
            or any(
                not isinstance(row, dict)
                or set(row) != {"name", "sha256"}
                or not isinstance(row["name"], str)
                or "/" in row["name"]
                or "\\" in row["name"]
                or not _DIGEST.fullmatch(str(row["sha256"]))
                for row in rows
            )
        ):
            raise InstanceRepairError("invalid_plan")
    return value


def binding_revision(binding: dict[str, Any]) -> str:
    return digest(encoded(validate_binding(binding)))


def validate_repair_receipt(value: Any, *, prepared: bool = False) -> dict[str, Any]:
    fields = {
        "schema_version",
        "kind",
        "receipt_id",
        "request_id",
        "operation",
        "backup_id",
        "archive_sha256",
        "input_revision",
        "output_revision",
        "instance_id",
        "profile",
        "relative_path",
        "affected_sha256",
        "status",
        "resulting_validation_status",
        "created_at",
        "error",
        "rollback_of",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise InstanceRepairError("invalid_receipt")
    expected_status = {
        "repaired": ("apply", "valid"),
        "repair_failed_restored": ("apply", "invalid"),
        "rolled_back_to_pre_repair_invalid_state": ("rollback", "invalid"),
        "rollback_failed_compensated": ("rollback", "valid"),
    }
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["kind"] != "provelume-state-repair-receipt"
        or value["profile"] != REPAIR_PROFILE
        or expected_status.get(str(value["status"]))
        != (value["operation"], value["resulting_validation_status"])
    ):
        raise InstanceRepairError("invalid_receipt")
    identifier(value["receipt_id"], "receipt")
    identifier(value["backup_id"], "backup")
    request_identifier(value["request_id"])
    if (
        value["receipt_id"]
        != "receipt_" + digest(encoded([value["operation"], value["request_id"]]))[:32]
    ):
        raise InstanceRepairError("invalid_receipt")
    artifact_target(value["relative_path"])
    for key in ("archive_sha256", "input_revision", "affected_sha256"):
        if not isinstance(value[key], str) or not _DIGEST.fullmatch(value[key]):
            raise InstanceRepairError("invalid_receipt")
    if not (prepared and value["output_revision"] is None) and not _DIGEST.fullmatch(
        str(value["output_revision"])
    ):
        raise InstanceRepairError("invalid_receipt")
    if not re.fullmatch(r"inst_[0-9a-f]{32}", str(value["instance_id"])):
        raise InstanceRepairError("invalid_receipt")
    if value["operation"] == "rollback":
        identifier(value["rollback_of"], "receipt")
    elif value["rollback_of"] is not None:
        raise InstanceRepairError("invalid_receipt")
    if value["error"] not in {None, "interrupted_before_commit", "operation_failed_before_commit"}:
        raise InstanceRepairError("invalid_receipt")
    try:
        if datetime.fromisoformat(value["created_at"]).tzinfo is None:
            raise ValueError
    except (TypeError, ValueError):
        raise InstanceRepairError("invalid_receipt") from None
    return value


def validate_pending_repair(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "kind", "phase", "receipt"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["kind"] != "provelume-pending-state-repair"
        or not isinstance(value["phase"], str)
        or value["phase"] not in {"prepared", "committed"}
    ):
        raise InstanceRepairError("invalid_pending_repair")
    try:
        validate_repair_receipt(value["receipt"], prepared=value["phase"] == "prepared")
    except (TypeError, ValueError, KeyError) as exc:
        raise InstanceRepairError("invalid_pending_repair") from exc
    return value


def pending_recovery_outcome(pending: dict, binding: dict) -> dict:
    """Predict the existing owner's terminal receipt without moving any file."""
    validate_pending_repair(pending)
    validate_binding(binding)
    result = dict(pending["receipt"])
    if pending["phase"] == "prepared":
        apply = result["operation"] == "apply"
        result["output_revision"] = (
            digest(encoded({
                "input_revision": binding_revision(binding),
                "source_present": True,
                "validation_report": binding["validation_report"],
            })) if apply else result["input_revision"]
        )
        result["status"] = "repair_failed_restored" if apply else "rollback_failed_compensated"
        result["resulting_validation_status"] = "invalid" if apply else "valid"
        result["error"] = result["error"] or "interrupted_before_commit"
    return validate_repair_receipt(result)


def validate_recovery_binding(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "pending", "pending_sha256", "backup_binding", "archive_sha256",
        "source_present", "position_revision", "expected_receipt",
    }:
        raise InstanceRepairError("invalid_recovery_binding")
    pending = validate_pending_repair(value["pending"])
    binding = validate_binding(value["backup_binding"])
    for key in ("pending_sha256", "archive_sha256", "position_revision"):
        if not isinstance(value[key], str) or not _DIGEST.fullmatch(value[key]):
            raise InstanceRepairError("invalid_recovery_binding")
    receipt = pending["receipt"]
    if (
        type(value["source_present"]) is not bool
        or receipt["archive_sha256"] != value["archive_sha256"]
        or receipt["instance_id"] != binding["instance_id"]
        or receipt["relative_path"] != binding["relative_path"]
        or receipt["affected_sha256"] != binding["affected_files"][0]["sha256"]
        or value["expected_receipt"] != pending_recovery_outcome(pending, binding)
    ):
        raise InstanceRepairError("invalid_recovery_binding")
    return value


def validate_recovery_request(value: Any) -> dict:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "kind", "request_id", "input_revision", "binding"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["kind"] != "provelume-reviewed-repair-recovery"
    ):
        raise InstanceRepairError("invalid_recovery_request")
    request_identifier(value["request_id"])
    binding = validate_recovery_binding(value["binding"])
    if value["input_revision"] != digest(encoded(binding)):
        raise InstanceRepairError("invalid_recovery_request")
    return value
