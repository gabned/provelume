"""Exact explicit backup verification; scheduler owns execution and receipts."""

from __future__ import annotations

import re

from .instance_backup import BackupError, inspect_backup_stream
from .maintenance_targets import SHA, LocalTargetRegistry, MaintenanceTargetError, revision
from .storage import InstanceStore, utc_now

PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "instance_id",
        "target_ref",
        "target_revision",
        "archive_sha256",
        "size_bytes",
        "backup_id",
        "instance_schema_version",
        "content_fingerprint",
        "files",
        "plan_revision",
    }
)


class BackupVerificationService:
    def __init__(self, store: InstanceStore):
        self.targets = LocalTargetRegistry(store)

    def _metadata(self, handle, *, verify_payload=False):
        try:
            result = inspect_backup_stream(handle, verify_payload=verify_payload)
        except (BackupError, ValueError, TypeError, KeyError, OSError) as exc:
            raise MaintenanceTargetError("archive_invalid") from exc
        if result["instance_id"] != self.targets.instance_id:
            raise MaintenanceTargetError("instance_mismatch")
        if (
            not re.fullmatch(r"backup_[A-Za-z0-9_]{1,100}", result["backup_id"])
            or not isinstance(result["content_fingerprint"], str)
            or not SHA.fullmatch(result["content_fingerprint"])
        ):
            raise MaintenanceTargetError("archive_invalid")
        return {
            key: result[key]
            for key in (
                "instance_id",
                "backup_id",
                "instance_schema_version",
                "content_fingerprint",
                "files",
            )
        }

    def plan(self, parameters):
        if not isinstance(parameters, dict) or set(parameters) != {"target_ref", "target_revision"}:
            raise MaintenanceTargetError("invalid_input")
        with self.targets.archive(parameters["target_ref"], parameters["target_revision"]) as (
            handle,
            target,
        ):
            metadata = self._metadata(handle)
            plan = {
                "schema_version": 1,
                "kind": "maintenance.backup_verify",
                **parameters,
                "archive_sha256": target["archive_sha256"],
                "size_bytes": target["size_bytes"],
                **metadata,
            }
        plan["plan_revision"] = revision(plan)
        return plan

    def verify(self, plan):
        if (
            not isinstance(plan, dict)
            or set(plan) != PLAN_FIELDS
            or type(plan["schema_version"]) is not int
            or plan["schema_version"] != 1
            or plan["kind"] != "maintenance.backup_verify"
            or plan["plan_revision"]
            != revision({k: v for k, v in plan.items() if k != "plan_revision"})
        ):
            raise MaintenanceTargetError("invalid_input")
        if plan["instance_id"] != self.targets.instance_id:
            raise MaintenanceTargetError("instance_mismatch")
        with self.targets.archive(plan["target_ref"], plan["target_revision"]) as (handle, target):
            metadata = self._metadata(handle, verify_payload=True)
            if (
                any(plan[key] != value for key, value in metadata.items())
                or plan["archive_sha256"] != target["archive_sha256"]
                or plan["size_bytes"] != target["size_bytes"]
            ):
                raise MaintenanceTargetError("target_stale")
        return {
            "status": "verified",
            **metadata,
            "archive_sha256": target["archive_sha256"],
            "size_bytes": target["size_bytes"],
            "verified_at": utc_now(),
        }
