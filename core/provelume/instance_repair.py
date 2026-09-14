"""Explicit one-file repair with retained backup, quarantine and crash compensation."""

from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .instance_lifecycle import InstanceLifecycleManager
from .instance_repair_backup import (
    create_capsule,
    payload_paths,
    read_regular,
    safe_path,
    sync_directory,
    verify_capsule,
)
from .instance_repair_model import (
    MAX_REPAIR_ARCHIVE_BYTES,
    MAX_REPAIR_ENTRIES,
    REPAIR_BACKUP_SCOPE,
    REPAIR_PROFILE,
    InstanceRepairError,
    artifact_target,
    binding_revision,
    digest,
    encoded,
    identifier,
    pending_recovery_outcome,
    request_identifier,
    validate_pending_repair,
    validate_recovery_binding,
    validate_recovery_request,
    validate_repair_receipt,
)
from .instance_schema import CURRENT_INSTANCE_SCHEMA_VERSION
from .instance_validation import inspect_instance
from .maintenance_model import validate_reindex_run
from .scheduler import SchedulerStore, _receipt_matches_terminal_job
from .scheduler_model import validate_job_record, validate_receipt_record
from .storage import InstanceStore, utc_now


class InstanceRepairManager:
    """Constructing this manager and previewing never open/prepare the Instance."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.lifecycle = InstanceLifecycleManager(store)
        self.root = self.lifecycle.control_root / "repairs"
        self.pending_path = self.root / "pending.json"
        self.blocked_path = self.root / "blocked.json"

    @contextmanager
    def _hold(self):
        safe_path(self.lifecycle.control_root, missing=True)
        safe_path(self.store.paths.root)
        with self.lifecycle._hold(purpose="instance-repair"), SchedulerStore(self.store).hold():
            yield

    def _write(self, path: Path, value: dict[str, Any], *, once: bool = False) -> None:
        safe_path(path, missing=True)
        if once and path.exists():
            if read_regular(path) != encoded(value):
                raise InstanceRepairError("receipt_conflict")
            return
        self.store._atomic_bytes(path, encoded(value))
        sync_directory(path.parent)

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(read_regular(path))
        except (ValueError, OSError) as exc:
            raise InstanceRepairError("unreadable_record") from exc
        if not isinstance(value, dict):
            raise InstanceRepairError("invalid_record")
        return value

    def _path(self, relative: str) -> Path:
        return safe_path(self.store.paths.root / relative, missing=True)

    def _inventory(self, directory: Path) -> list[dict[str, str]]:
        safe_path(directory)
        entries = []
        total_bytes = 0
        with os.scandir(directory) as iterator:
            for entry in iterator:
                if len(entries) >= MAX_REPAIR_ENTRIES:
                    raise InstanceRepairError("inventory_incomplete")
                data = read_regular(Path(entry.path))
                total_bytes += len(data)
                if total_bytes > MAX_REPAIR_ARCHIVE_BYTES:
                    raise InstanceRepairError("inventory_incomplete")
                entries.append({"name": entry.name, "sha256": digest(data)})
        return sorted(entries, key=lambda item: item["name"])

    def _inventories(self) -> dict[str, list[dict[str, str]]]:
        return {
            key: self._inventory(self._path(relative))
            for key, relative in (
                ("runs", "state/maintenance/reindex-runs"),
                ("jobs", "state/scheduler/jobs"),
                ("receipts", "state/scheduler/receipts"),
            )
        }

    def _check_other_pending(self) -> None:
        control = self.lifecycle.control_root
        safe_path(control, missing=True)
        self._blocked_receipt()
        for path in (self.lifecycle.pending_path, control / "retention/pending-purge.json"):
            if path.exists() or path.is_symlink():
                raise InstanceRepairError("other_recovery_pending")
        transactions = control / "transactions"
        if transactions.exists() or transactions.is_symlink():
            safe_path(transactions)
            # Any retained atomic transaction needs its own owner's adjudication.
            if not transactions.is_dir() or next(transactions.iterdir(), None) is not None:
                raise InstanceRepairError("other_recovery_pending")

    def _snapshot(self, relative_path: str) -> dict[str, Any]:
        target = artifact_target(relative_path)
        self._check_other_pending()
        inventory = self._inventories()
        run_bytes = read_regular(self._path(target))
        affected = read_regular(self._path(relative_path))
        if affected != run_bytes:
            raise InstanceRepairError("artifact_not_identical")
        try:
            run = validate_reindex_run(json.loads(run_bytes))
            if (
                target != f"state/maintenance/reindex-runs/{run['id']}.json"
                or run["status"] != "completed"
            ):
                raise InstanceRepairError("run_not_completed")
            job_path = f"state/scheduler/jobs/{run['job_id']}.json"
            receipt_path = (
                "state/scheduler/receipts/receipt_" + run["job_id"].removeprefix("job_") + ".json"
            )
            job = validate_job_record(self._json(self._path(job_path)))
            receipt = validate_receipt_record(self._json(self._path(receipt_path)))
            if (
                job["status"] != "succeeded"
                or job["lease"] is not None
                or not _receipt_matches_terminal_job(receipt, job)
            ):
                raise InstanceRepairError("terminal_evidence_mismatch")
            for row in inventory["jobs"]:
                candidate = validate_job_record(
                    self._json(self._path("state/scheduler/jobs/" + row["name"]))
                )
                if candidate["lease"] is not None:
                    raise InstanceRepairError("writer_active")
        except (ValueError, KeyError, TypeError) as exc:
            raise InstanceRepairError("invalid_producer_evidence") from exc
        report = inspect_instance(self.store.paths.root, deep=True)
        errors = report["errors"]
        if (
            report["status"] != "invalid"
            or report["instance_schema_version"] != CURRENT_INSTANCE_SCHEMA_VERSION
            or report["migration_required"]
            or len(errors) != 1
            or errors[0].get("code") != "maintenance_record_invalid"
            or errors[0].get("path") != relative_path
        ):
            raise InstanceRepairError("unsupported_validation_findings")
        if job["scope"] != {"kind": "instance", "id": report["instance_id"]} or job[
            "job_kind"
        ] not in {"search.reindex", "search.reindex.incremental"}:
            raise InstanceRepairError("terminal_evidence_mismatch")
        context = []
        for path in (target, job_path, receipt_path, "provelume.yml", "instance-manifest.json"):
            data = read_regular(self._path(path))
            context.append({"path": path, "size": len(data), "sha256": digest(data)})
        if (
            inventory != self._inventories()
            or read_regular(self._path(relative_path)) != affected
            or read_regular(self._path(target)) != run_bytes
        ):
            raise InstanceRepairError("snapshot_changed")
        return {
            "profile": REPAIR_PROFILE,
            "instance_id": report["instance_id"],
            "instance_root": str(self.store.paths.root.resolve()),
            "relative_path": relative_path,
            "target_path": target,
            "affected_files": [
                {"path": relative_path, "size": len(affected), "sha256": digest(affected)}
            ],
            "context": context,
            "finding": errors[0],
            "validation_report": report,
            "inventory": inventory,
        }

    def preview(self, profile: str, relative_path: str) -> dict[str, Any]:
        """Pure observation; no lock, backup, migration, recovery, or persisted plan."""
        try:
            if profile != REPAIR_PROFILE:
                raise InstanceRepairError("unsupported_profile")
            safe_path(self.root, missing=True)
            if self.pending_path.exists():
                raise InstanceRepairError("repair_recovery_pending")
            binding = self._snapshot(relative_path)
            revision = binding_revision(binding)
            required = (
                sum(row["size"] for row in binding["affected_files"] + binding["context"])
                + len(encoded(binding)) * 2
                + 65536
            )
            free = shutil.disk_usage(self.store.paths.root.parent).free
            return {
                "schema_version": 1,
                "status": "eligible" if free >= required else "unavailable",
                "reason": None if free >= required else "insufficient_space",
                "profile": profile,
                "instance_id": binding["instance_id"],
                "plan_id": "plan_" + revision,
                "input_revision": revision,
                "relative_path": relative_path,
                "target_path": binding["target_path"],
                "affected_files": binding["affected_files"],
                "context": binding["context"],
                "finding": binding["finding"],
                "binding": binding,
                "quarantine_path": str(self.root / "<backup_id>" / "quarantine.bin"),
                "recovery_backup_scope": REPAIR_BACKUP_SCOPE,
                "required_bytes": required,
                "free_bytes": free,
                "complete": True,
                "authority": "explicit_local_repair",
                "reversible": True,
                "rollback_effect": "restores_known_invalid_state",
            }
        except InstanceRepairError as exc:
            return {
                "schema_version": 1,
                "status": "unavailable",
                "profile": profile,
                "reason": exc.reason,
                "complete": False,
            }
        except (OSError, ValueError, RuntimeError) as exc:
            return {
                "schema_version": 1,
                "status": "unavailable",
                "profile": profile,
                "reason": "unreadable_or_invalid_evidence",
                "complete": False,
                "error_type": type(exc).__name__,
            }

    def _backup(
        self, backup_id: str, expected_sha: str | None = None
    ) -> tuple[dict[str, Any], dict[str, bytes]]:
        identifier(backup_id, "backup")
        verified, payloads = verify_capsule(self.root / backup_id / "before.zip")
        if expected_sha is not None and verified["archive_sha256"] != expected_sha:
            raise InstanceRepairError("backup_hash_mismatch")
        binding = verified["manifest"]["binding"]
        if binding["instance_root"] != str(self.store.paths.root.resolve()):
            raise InstanceRepairError("foreign_backup")
        return verified, payloads

    def prepare_backup(self, plan: dict[str, Any], request_id: str) -> dict[str, Any]:
        request_identifier(request_id)
        if not isinstance(plan, dict) or plan.get("status") != "eligible":
            raise InstanceRepairError("invalid_plan")
        with self._hold():
            if self.pending_path.exists():
                raise InstanceRepairError("repair_recovery_pending")
            current = self.preview(REPAIR_PROFILE, plan.get("relative_path", ""))
            if (
                current["status"] != "eligible"
                or current["input_revision"] != plan.get("input_revision")
                or current["binding"] != plan.get("binding")
            ):
                raise InstanceRepairError("stale_plan")
            binding = current["binding"]
            backup_id = "backup_" + digest(encoded([current["input_revision"], request_id]))[:32]
            directory = safe_path(self.root / backup_id, missing=True)
            directory.mkdir(parents=True, exist_ok=True)
            archive = directory / "before.zip"
            if not archive.exists():
                payloads = {
                    name: read_regular(self._path(path))
                    for name, path in payload_paths(binding).items()
                }
                payloads["validation.json"] = encoded(binding["validation_report"])
                create_capsule(archive, binding, payloads)
            verified, _ = self._backup(backup_id)
            if verified["manifest"]["binding"] != binding:
                raise InstanceRepairError("backup_context_mismatch")
            result = {
                "schema_version": 1,
                "backup_id": backup_id,
                "archive_path": str(archive),
                "archive_sha256": verified["archive_sha256"],
                "plan_id": current["plan_id"],
                "input_revision": current["input_revision"],
                "verified": True,
                "scope": REPAIR_BACKUP_SCOPE,
                "quarantine_path": str(directory / "quarantine.bin"),
                "request_id": request_id,
            }
            self._write(directory / "prepared.json", result, once=True)
            return result

    def _context_matches(self, binding: dict[str, Any], *, source_present: bool) -> dict[str, Any]:
        self._check_other_pending()
        for row in binding["context"]:
            data = read_regular(self._path(row["path"]))
            if len(data) != row["size"] or digest(data) != row["sha256"]:
                raise InstanceRepairError("context_changed")
        inventory = self._inventories()
        expected = {key: list(rows) for key, rows in binding["inventory"].items()}
        if not source_present:
            expected["runs"] = [
                row
                for row in expected["runs"]
                if row["name"] != Path(binding["relative_path"]).name
            ]
        if inventory != expected:
            raise InstanceRepairError("context_changed")
        report = inspect_instance(self.store.paths.root, deep=True)
        if source_present:
            if report != binding["validation_report"]:
                raise InstanceRepairError("precondition_changed")
        elif report["status"] != "valid" or report["instance_id"] != binding["instance_id"]:
            raise InstanceRepairError("postcondition_failed")
        return report

    def _position(self, backup_id: str, binding: dict[str, Any], *, source_present: bool) -> str:
        source = self._path(binding["relative_path"])
        quarantine = safe_path(self.root / backup_id / "quarantine.bin", missing=True)
        present, absent = (source, quarantine) if source_present else (quarantine, source)
        if absent.exists() or absent.is_symlink():
            raise InstanceRepairError("destination_exists")
        data = read_regular(present)
        if digest(data) != binding["affected_files"][0]["sha256"]:
            raise InstanceRepairError("affected_hash_mismatch")
        report = self._context_matches(binding, source_present=source_present)
        return digest(
            encoded(
                {
                    "input_revision": binding_revision(binding),
                    "source_present": source_present,
                    "validation_report": report,
                }
            )
        )

    def _move(self, source: Path, target: Path) -> None:
        safe_path(source)
        safe_path(target, missing=True)
        if target.exists() or target.is_symlink():
            raise InstanceRepairError("destination_exists")
        if source.stat().st_dev != target.parent.stat().st_dev:
            raise InstanceRepairError("cross_device_quarantine")
        os.replace(source, target)
        sync_directory(source.parent)
        sync_directory(target.parent)

    def _after_move(self, operation: str) -> None:
        """Failure-injection boundary, after durable rename and before verification."""

    def _receipt_path(self, receipt_id: str) -> Path:
        return self.root / "receipts" / (identifier(receipt_id, "receipt") + ".json")

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        path = self._receipt_path(receipt_id)
        if not path.exists():
            return None
        result = validate_repair_receipt(self._json(path))
        if result["receipt_id"] != receipt_id:
            raise InstanceRepairError("invalid_receipt")
        return result

    def has_recovery_barrier(self) -> bool:
        return any(
            path.exists() or path.is_symlink() for path in (self.pending_path, self.blocked_path)
        )

    def _blocked_receipt(self) -> dict[str, Any] | None:
        if self.blocked_path.exists() or self.blocked_path.is_symlink():
            blocked = self._json(self.blocked_path)
            if (
                set(blocked) != {"schema_version", "receipt_id", "receipt_sha256"}
                or type(blocked["schema_version"]) is not int
                or blocked["schema_version"] != 1
            ):
                raise InstanceRepairError("invalid_repair_barrier")
            receipt = self.get_receipt(blocked["receipt_id"])
            if (
                receipt is None
                or digest(encoded(receipt)) != blocked["receipt_sha256"]
                or receipt["resulting_validation_status"] != "invalid"
            ):
                raise InstanceRepairError("invalid_repair_barrier")
            config = self.store.read_config()
            if config.get("instance", {}).get("id") != receipt["instance_id"]:
                raise InstanceRepairError("invalid_repair_barrier")
            return receipt
        return None

    def assert_mutation_ready(self) -> None:
        if self.pending_path.exists() or self.pending_path.is_symlink():
            raise InstanceRepairError("repair_recovery_pending")
        receipt = self._blocked_receipt()
        if receipt is not None:
            report = inspect_instance(self.store.paths.root, deep=True)
            if report["status"] != "valid" or report["instance_id"] != receipt["instance_id"]:
                raise InstanceRepairError("known_invalid_repair_state")

    def _finish(self, pending: dict[str, Any]) -> dict[str, Any]:
        receipt = validate_repair_receipt(pending["receipt"])
        self._write(self._receipt_path(receipt["receipt_id"]), receipt, once=True)
        if receipt["resulting_validation_status"] == "invalid":
            self._write(
                self.blocked_path,
                {
                    "schema_version": 1,
                    "receipt_id": receipt["receipt_id"],
                    "receipt_sha256": digest(encoded(receipt)),
                },
            )
        else:
            safe_path(self.blocked_path, missing=True)
            self.blocked_path.unlink(missing_ok=True)
        self.pending_path.unlink()
        sync_directory(self.root)
        return receipt

    def _recover_pending_locked(
        self, *, expected_pending_sha256: str | None = None
    ) -> dict[str, Any] | None:
        """Caller holds lifecycle then scheduler; uncertain recovery remains pending."""
        if not self.pending_path.exists() and not self.pending_path.is_symlink():
            return None
        if expected_pending_sha256 is None:
            pending = self._json(self.pending_path)
        else:
            raw = read_regular(self.pending_path)
            if digest(raw) != expected_pending_sha256:
                raise InstanceRepairError("stale_pending_recovery")
            try:
                pending = validate_pending_repair(json.loads(raw))
            except (ValueError, TypeError) as exc:
                raise InstanceRepairError("invalid_pending_repair") from exc
        if (
            set(pending) != {"schema_version", "kind", "phase", "receipt"}
            or pending["schema_version"] != 1
            or pending["kind"] != "provelume-pending-state-repair"
            or pending["phase"] not in {"prepared", "committed"}
        ):
            raise InstanceRepairError("invalid_pending_repair")
        receipt = validate_repair_receipt(
            pending["receipt"], prepared=pending["phase"] == "prepared"
        )
        verified, _ = self._backup(receipt["backup_id"], receipt["archive_sha256"])
        binding = verified["manifest"]["binding"]
        if (
            receipt.get("instance_id") != binding["instance_id"]
            or receipt.get("relative_path") != binding["relative_path"]
            or receipt.get("affected_sha256") != binding["affected_files"][0]["sha256"]
        ):
            raise InstanceRepairError("invalid_pending_repair")
        apply = receipt["operation"] == "apply"
        if apply and receipt["input_revision"] != binding_revision(binding):
            raise InstanceRepairError("invalid_pending_repair")
        if not apply:
            origin = self.get_receipt(receipt["rollback_of"])
            if (
                origin is None
                or origin["status"] != "repaired"
                or origin["backup_id"] != receipt["backup_id"]
                or origin["archive_sha256"] != receipt["archive_sha256"]
                or origin["output_revision"] != receipt["input_revision"]
            ):
                raise InstanceRepairError("invalid_pending_repair")
        if pending["phase"] == "committed":
            if (
                self._position(receipt["backup_id"], binding, source_present=not apply)
                != receipt["output_revision"]
            ):
                raise InstanceRepairError("committed_state_changed")
            return self._finish(pending)
        source = self._path(binding["relative_path"])
        quarantine = self.root / receipt["backup_id"] / "quarantine.bin"
        before, after = (source, quarantine) if apply else (quarantine, source)
        if before.exists() and not after.exists():
            self._position(receipt["backup_id"], binding, source_present=apply)
        elif after.exists() and not before.exists():
            self._position(receipt["backup_id"], binding, source_present=not apply)
            self._move(after, before)
        else:
            raise InstanceRepairError("uncertain_repair_effect")
        receipt["output_revision"] = self._position(
            receipt["backup_id"], binding, source_present=apply
        )
        receipt["status"] = "repair_failed_restored" if apply else "rollback_failed_compensated"
        receipt["resulting_validation_status"] = "invalid" if apply else "valid"
        receipt["error"] = receipt.get("error") or "interrupted_before_commit"
        # This terminal receipt is durable before clearing the recovery barrier.
        return self._finish(pending)

    def recover_pending(self) -> dict[str, Any] | None:
        if not self.pending_path.exists() and not self.pending_path.is_symlink():
            return None
        with self._hold():
            return self._recover_pending_locked()

    def _pending_recovery_binding(self) -> dict[str, Any]:
        """Read the exact pending/capsule/position guarded again by the recovery owner."""
        if not self.pending_path.exists() and not self.pending_path.is_symlink():
            raise InstanceRepairError("no_pending_repair")
        raw = read_regular(self.pending_path)
        try:
            pending = validate_pending_repair(json.loads(raw))
        except (ValueError, TypeError) as exc:
            raise InstanceRepairError("invalid_pending_repair") from exc
        receipt = pending["receipt"]
        verified, _ = self._backup(receipt["backup_id"], receipt["archive_sha256"])
        binding = verified["manifest"]["binding"]
        apply = receipt["operation"] == "apply"
        if apply:
            if receipt["input_revision"] != binding_revision(binding):
                raise InstanceRepairError("invalid_pending_repair")
        else:
            origin = self.get_receipt(receipt["rollback_of"])
            if (
                origin is None or origin["status"] != "repaired"
                or origin["backup_id"] != receipt["backup_id"]
                or origin["archive_sha256"] != receipt["archive_sha256"]
                or origin["output_revision"] != receipt["input_revision"]
            ):
                raise InstanceRepairError("invalid_pending_repair")
        source = self._path(binding["relative_path"])
        quarantine = safe_path(self.root / receipt["backup_id"] / "quarantine.bin", missing=True)
        source_present = source.exists()
        if source_present == quarantine.exists():
            raise InstanceRepairError("uncertain_repair_effect")
        position = self._position(receipt["backup_id"], binding, source_present=source_present)
        if pending["phase"] == "committed" and (
            source_present == apply or position != receipt["output_revision"]
        ):
            raise InstanceRepairError("committed_state_changed")
        observed = validate_recovery_binding({
            "pending": pending, "pending_sha256": digest(raw), "backup_binding": binding,
            "archive_sha256": verified["archive_sha256"], "source_present": source_present,
            "position_revision": position,
            "expected_receipt": pending_recovery_outcome(pending, binding),
        })
        # Bracket the capsule and live position as well as the pending bytes.
        again, _ = self._backup(receipt["backup_id"], receipt["archive_sha256"])
        if (
            again != verified or read_regular(self.pending_path) != raw
            or self._position(receipt["backup_id"], binding, source_present=source_present)
            != position
        ):
            raise InstanceRepairError("snapshot_changed")
        return observed

    def preview_pending_recovery(self) -> dict[str, Any]:
        """Pure, bounded observation; pending corruption never creates authority."""
        try:
            binding = self._pending_recovery_binding()
            pending, receipt = binding["pending"], binding["pending"]["receipt"]
            committed, apply = pending["phase"] == "committed", receipt["operation"] == "apply"
            effect = (
                ("finalizes_committed_repair" if apply else "finalizes_committed_rollback")
                if committed else
                ("restores_known_invalid_state" if apply else "restores_repaired_state")
            )
            return {
                "schema_version": 1, "status": "eligible", "phase": pending["phase"],
                "receipt_id": receipt["receipt_id"], "operation": receipt["operation"],
                "instance_id": receipt["instance_id"], "backup_id": receipt["backup_id"],
                "archive_sha256": receipt["archive_sha256"],
                "input_revision": digest(encoded(binding)),
                "effect": effect,
                "resulting_validation_status": binding["expected_receipt"][
                    "resulting_validation_status"
                ],
                "binding": binding,
            }
        except InstanceRepairError as exc:
            return {
                "schema_version": 1,
                "status": "none" if exc.reason == "no_pending_repair" else "unavailable",
                "reason": exc.reason,
            }
        except OSError:
            return {"schema_version": 1, "status": "unavailable", "reason": "unreadable_record"}

    def recover_pending_reviewed(
        self, expected_revision: str, request_id: str, *, confirm: bool = False
    ) -> dict[str, Any]:
        """Confirm one observed pending; retain its original operation/receipt identity."""
        if confirm is not True:
            raise InstanceRepairError("explicit_confirmation_required")
        request_identifier(request_id)
        if not isinstance(expected_revision, str) or len(expected_revision) != 64 or any(
            c not in "0123456789abcdef" for c in expected_revision
        ):
            raise InstanceRepairError("invalid_recovery_revision")
        request_path = self.root / "recovery-requests" / (digest(encoded(request_id)) + ".json")
        with self._hold():
            safe_path(request_path, missing=True)
            previous = (
                validate_recovery_request(self._json(request_path))
                if request_path.exists() else None
            )
            if previous is not None:
                if (
                    previous["request_id"] != request_id
                    or previous["input_revision"] != expected_revision
                ):
                    raise InstanceRepairError("request_conflict")
                bound = previous["binding"]
                if (
                    bound["backup_binding"]["instance_root"] != str(self.store.paths.root.resolve())
                    or bound["backup_binding"]["instance_id"]
                    != self.store.read_config()["instance"]["id"]
                ):
                    raise InstanceRepairError("foreign_recovery_request")
                terminal = self.get_receipt(bound["expected_receipt"]["receipt_id"])
                if terminal is not None and terminal != bound["expected_receipt"]:
                    raise InstanceRepairError("receipt_conflict")
                if terminal is not None and (
                    not self.pending_path.exists()
                    or digest(read_regular(self.pending_path)) != bound["pending_sha256"]
                ):
                    return terminal  # Historical replay cannot act on another pending.
            current = self._pending_recovery_binding()
            if previous is None:
                if digest(encoded(current)) != expected_revision:
                    raise InstanceRepairError("stale_pending_recovery")
                previous = validate_recovery_request({
                    "schema_version": 1, "kind": "provelume-reviewed-repair-recovery",
                    "request_id": request_id, "input_revision": expected_revision,
                    "binding": current,
                })
                self._write(request_path, previous, once=True)
            elif any(
                current[key] != previous["binding"][key]
                for key in (
                    "pending", "pending_sha256", "backup_binding", "archive_sha256",
                    "expected_receipt",
                )
            ):
                raise InstanceRepairError("stale_pending_recovery")
            # A replay may observe compensation already moved the same exact file.
            # The retained authorization binds all other inputs and the final receipt.
            result = self._recover_pending_locked(
                expected_pending_sha256=previous["binding"]["pending_sha256"]
            )
            if result != previous["binding"]["expected_receipt"]:
                raise InstanceRepairError("recovery_result_mismatch")
            return result

    def _execute(
        self,
        backup_id: str,
        expected_revision: str,
        request_id: str,
        archive_sha256: str,
        *,
        operation: str,
        confirm: bool,
        rollback_of: str | None = None,
    ) -> dict[str, Any]:
        if confirm is not True:
            raise InstanceRepairError("explicit_confirmation_required")
        request_identifier(request_id)
        receipt_id = "receipt_" + digest(encoded([operation, request_id]))[:32]
        with self._hold():
            self._recover_pending_locked()
            previous = self.get_receipt(receipt_id)
            if previous is not None:
                if (
                    previous["backup_id"] != backup_id
                    or previous["input_revision"] != expected_revision
                    or previous["archive_sha256"] != archive_sha256
                    or previous["rollback_of"] != rollback_of
                ):
                    raise InstanceRepairError("request_conflict")
                return previous
            verified, _ = self._backup(backup_id, archive_sha256)
            binding = verified["manifest"]["binding"]
            applying = operation == "apply"
            position = self._position(backup_id, binding, source_present=applying)
            if expected_revision != (binding_revision(binding) if applying else position):
                raise InstanceRepairError("stale_plan")
            if applying and self._snapshot(binding["relative_path"]) != binding:
                raise InstanceRepairError("stale_plan")
            receipt = {
                "schema_version": 1,
                "kind": "provelume-state-repair-receipt",
                "receipt_id": receipt_id,
                "request_id": request_id,
                "operation": operation,
                "backup_id": backup_id,
                "archive_sha256": archive_sha256,
                "input_revision": expected_revision,
                "output_revision": None,
                "instance_id": binding["instance_id"],
                "profile": REPAIR_PROFILE,
                "relative_path": binding["relative_path"],
                "affected_sha256": binding["affected_files"][0]["sha256"],
                "status": "repaired" if applying else "rolled_back_to_pre_repair_invalid_state",
                "resulting_validation_status": "valid" if applying else "invalid",
                "created_at": utc_now(),
                "error": None,
                "rollback_of": rollback_of,
            }
            pending = {
                "schema_version": 1,
                "kind": "provelume-pending-state-repair",
                "phase": "prepared",
                "receipt": receipt,
            }
            self._write(self.pending_path, pending)
            source = self._path(binding["relative_path"])
            quarantine = self.root / backup_id / "quarantine.bin"
            try:
                self._move(source, quarantine) if applying else self._move(quarantine, source)
                self._after_move(operation)
                receipt["output_revision"] = self._position(
                    backup_id, binding, source_present=not applying
                )
                pending["phase"] = "committed"
                self._write(self.pending_path, pending)
            except Exception:
                # Compensation is exact; if it cannot be proved, keep the barrier.
                # Re-read durable phase: an atomic commit write may have succeeded
                # before its flush/reporting raised. Never undo a committed result.
                observed = self._json(self.pending_path)
                if observed.get("phase") == "prepared":
                    observed["receipt"]["error"] = "operation_failed_before_commit"
                    self._write(self.pending_path, observed)
                recovered = self._recover_pending_locked()
                if recovered is None:
                    raise InstanceRepairError("uncertain_repair_effect") from None
                return recovered
            return self._finish(pending)

    def apply(
        self,
        backup_id: str,
        expected_revision: str,
        request_id: str,
        confirmed_backup_sha256: str,
        *,
        confirm: bool = False,
    ) -> dict[str, Any]:
        return self._execute(
            backup_id,
            expected_revision,
            request_id,
            confirmed_backup_sha256,
            operation="apply",
            confirm=confirm,
        )

    def preview_rollback(self, receipt_id: str) -> dict[str, Any]:
        receipt = self.get_receipt(receipt_id)
        if receipt is None or receipt["status"] != "repaired":
            raise InstanceRepairError("rollback_unavailable")
        if self.pending_path.exists():
            raise InstanceRepairError("repair_recovery_pending")
        verified, _ = self._backup(receipt["backup_id"], receipt["archive_sha256"])
        current = self._position(
            receipt["backup_id"], verified["manifest"]["binding"], source_present=False
        )
        if current != receipt["output_revision"]:
            raise InstanceRepairError("stale_rollback")
        return {
            "status": "eligible",
            "receipt_id": receipt_id,
            "input_revision": current,
            "effect": "restores_known_invalid_state",
            "resulting_validation_status": "invalid",
            "affected_files": verified["manifest"]["binding"]["affected_files"],
            "archive_sha256": receipt["archive_sha256"],
        }

    def rollback(
        self, receipt_id: str, expected_revision: str, request_id: str, *, confirm: bool = False
    ) -> dict[str, Any]:
        receipt = self.get_receipt(receipt_id)
        if (
            receipt is None
            or receipt["status"] != "repaired"
            or expected_revision != receipt["output_revision"]
        ):
            raise InstanceRepairError("rollback_unavailable")
        return self._execute(
            receipt["backup_id"],
            expected_revision,
            request_id,
            receipt["archive_sha256"],
            operation="rollback",
            confirm=confirm,
            rollback_of=receipt_id,
        )


__all__ = ["InstanceRepairManager", "InstanceRepairError", "REPAIR_PROFILE"]
