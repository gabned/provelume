from __future__ import annotations

import json
import os
import shutil
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from .instance_backup import (
    BackupError,
    create_backup,
    extract_backup,
    verify_backup,
)
from .instance_schema import (
    CURRENT_INSTANCE_SCHEMA_VERSION,
    LEGACY_INSTANCE_SCHEMA_VERSION,
    MIGRATION_1_TO_2,
    MIGRATION_RECEIPT_SCHEMA_VERSION,
    build_instance_manifest,
)
from .instance_validation import inspect_instance
from .storage import InstanceStore, utc_now

LIFECYCLE_STATE_SCHEMA_VERSION = 1


class InstanceLifecycleError(RuntimeError):
    pass


class InstanceLifecycleBusy(InstanceLifecycleError):
    pass


def _acquire_os_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise InstanceLifecycleBusy(
                "another Instance lifecycle operation is active"
            ) from exc
        return

    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError) as exc:
        raise InstanceLifecycleBusy(
            "another Instance lifecycle operation is active"
        ) from exc


def _release_os_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


class InstanceLifecycleManager:
    """Version, backup, recovery and restore boundary for one local Instance."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.control_root = (
            store.paths.root.parent / f".{store.paths.root.name}.provelume"
        )
        self.lock_path = self.control_root / "lifecycle.lock.json"
        self.pending_path = self.control_root / "pending-operation.json"

    def validate(self, *, deep: bool = True) -> dict[str, Any]:
        return inspect_instance(self.store.paths.root, deep=deep)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeError):
            return None
        return value if isinstance(value, dict) else None

    @contextmanager
    def _hold(self, *, purpose: str) -> Iterator[dict[str, Any]]:
        selected_purpose = purpose.strip()[:120]
        if not selected_purpose:
            raise ValueError("lifecycle purpose is required")
        self.control_root.mkdir(parents=True, exist_ok=True)
        token = f"lifecycle_{uuid4().hex}"
        owner = {
            "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
            "token": token,
            "purpose": selected_purpose,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "acquired_at": utc_now(),
        }
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise InstanceLifecycleError("lifecycle lock file cannot be opened") from exc
        locked = False
        try:
            _acquire_os_lock(descriptor)
            locked = True
            with os.fdopen(
                descriptor,
                "r+",
                encoding="utf-8",
                newline="\n",
                closefd=False,
            ) as handle:
                handle.seek(0)
                json.dump(owner, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())
            yield owner
        finally:
            try:
                if locked:
                    _release_os_lock(descriptor)
            finally:
                os.close(descriptor)

    def _write_pending(
        self,
        *,
        operation: str,
        rollback: dict[str, Any] | None,
        requested_archive_sha256: str | None = None,
    ) -> None:
        self.control_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
            "operation": operation,
            "started_at": utc_now(),
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "instance_id": (
                rollback.get("instance_id") if isinstance(rollback, dict) else None
            ),
            "rollback_archive": (
                rollback.get("archive") if isinstance(rollback, dict) else None
            ),
            "rollback_archive_sha256": (
                rollback.get("archive_sha256") if isinstance(rollback, dict) else None
            ),
            "requested_archive_sha256": requested_archive_sha256,
        }
        self.store._atomic_json(self.pending_path, payload)

    def _clear_pending(self) -> None:
        self.pending_path.unlink(missing_ok=True)

    def _cleanup_abandoned_workdirs(self) -> None:
        parent = self.store.paths.root.parent
        name = self.store.paths.root.name
        for prefix in (
            f".{name}.restore-stage-",
            f".{name}.restore-previous-",
        ):
            for path in parent.glob(f"{prefix}*"):
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path, ignore_errors=True)

    def _record_recovery(
        self,
        *,
        operation: str,
        action: str,
        rollback_archive_sha256: str | None,
    ) -> dict[str, Any]:
        receipt_id = f"recovery_{uuid4().hex}"
        receipt_ref = f"state/lifecycle/recovery-receipts/{receipt_id}.json"
        receipt = {
            "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
            "id": receipt_id,
            "status": "completed",
            "operation": operation,
            "action": action,
            "recovered_at": utc_now(),
            "rollback_archive_sha256": rollback_archive_sha256,
        }
        self.store._atomic_json(
            self.store.paths.lifecycle_recovery_receipts / f"{receipt_id}.json",
            receipt,
        )
        return {
            "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
            "status": "recovered",
            "operation": operation,
            "action": action,
            "rollback_archive_sha256": rollback_archive_sha256,
            "receipt": receipt_ref,
        }

    def _recover_pending(self) -> dict[str, Any] | None:
        if not self.pending_path.exists():
            return None
        pending = self._read_json(self.pending_path)
        if pending is None or pending.get("schema_version") != LIFECYCLE_STATE_SCHEMA_VERSION:
            raise InstanceLifecycleError("pending lifecycle recovery record is invalid")
        operation = pending.get("operation")
        if operation not in {"backup", "migration", "restore"}:
            raise InstanceLifecycleError("pending lifecycle operation is unsupported")
        if operation == "backup":
            for path in (self.control_root / "backups").glob(".*.tmp"):
                path.unlink(missing_ok=True)
            result = self._record_recovery(
                operation="backup",
                action="discarded_incomplete_read_only_operation",
                rollback_archive_sha256=None,
            )
            self._clear_pending()
            return result
        archive = pending.get("rollback_archive")
        digest = pending.get("rollback_archive_sha256")
        instance_id = pending.get("instance_id")
        if not all(isinstance(value, str) and value for value in (archive, digest, instance_id)):
            raise InstanceLifecycleError("pending lifecycle rollback evidence is incomplete")
        verified = verify_backup(archive)
        if verified["archive_sha256"] != digest or verified["instance_id"] != instance_id:
            raise InstanceLifecycleError("pending lifecycle rollback evidence does not match")
        self._replace_from_archive(Path(archive), expected_instance_id=instance_id)
        self._cleanup_abandoned_workdirs()
        result = self._record_recovery(
            operation=str(operation),
            action="restored_verified_pre_operation_backup",
            rollback_archive_sha256=str(digest),
        )
        self._clear_pending()
        return result

    def _replace_from_archive(
        self,
        archive: Path,
        *,
        expected_instance_id: str,
    ) -> dict[str, Any]:
        verified = verify_backup(archive)
        if verified["instance_id"] != expected_instance_id:
            raise InstanceLifecycleError(
                "backup belongs to a different Provelume Instance"
            )
        root = self.store.paths.root
        root.parent.mkdir(parents=True, exist_ok=True)
        stage = root.parent / f".{root.name}.restore-stage-{uuid4().hex}"
        previous = root.parent / f".{root.name}.restore-previous-{uuid4().hex}"
        moved_previous = False
        installed_stage = False
        try:
            extract_backup(archive, stage)
            staged = inspect_instance(stage, deep=True)
            if staged["status"] != "valid" or staged["instance_id"] != expected_instance_id:
                raise InstanceLifecycleError(
                    "restored staging Instance failed validation"
                )
            if root.exists():
                os.replace(root, previous)
                moved_previous = True
            os.replace(stage, root)
            installed_stage = True
            installed = inspect_instance(root, deep=True)
            if installed["status"] != "valid":
                raise InstanceLifecycleError("restored Instance failed final validation")
            if moved_previous:
                shutil.rmtree(previous)
                moved_previous = False
            return {
                "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
                "status": "restored",
                "instance_id": expected_instance_id,
                "instance_schema_version": installed["instance_schema_version"],
                "content_fingerprint": installed["content_fingerprint"],
                "files": verified["files"],
                "derived_state": verified["derived_state"],
            }
        except Exception:
            if installed_stage and root.exists():
                shutil.rmtree(root, ignore_errors=True)
            if moved_previous and previous.exists():
                os.replace(previous, root)
                moved_previous = False
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            if moved_previous:
                shutil.rmtree(previous, ignore_errors=True)

    def _apply_migration_1_to_2(
        self,
        *,
        backup: dict[str, Any],
    ) -> dict[str, Any]:
        config = self.store.read_config()
        if config.get("schema_version") != LEGACY_INSTANCE_SCHEMA_VERSION:
            raise InstanceLifecycleError("schema-1 migration precondition changed")
        started_at = utc_now()
        completed_at = utc_now()
        receipt_ref = f"state/migrations/receipts/{MIGRATION_1_TO_2}.json"
        receipt = {
            "schema_version": MIGRATION_RECEIPT_SCHEMA_VERSION,
            "migration_id": MIGRATION_1_TO_2,
            "status": "completed",
            "from_instance_schema_version": LEGACY_INSTANCE_SCHEMA_VERSION,
            "to_instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
            "instance_id": backup["instance_id"],
            "started_at": started_at,
            "completed_at": completed_at,
            "preflight_content_fingerprint": backup["content_fingerprint"],
            "backup": {
                "archive_name": Path(str(backup["archive"])).name,
                "sha256": backup["archive_sha256"],
                "size_bytes": backup["size_bytes"],
            },
            "changes": [
                "set provelume.yml schema_version to 2",
                "create versioned instance-manifest.json",
                "record explicit derived-state policy",
            ],
        }
        updated_config = dict(config)
        updated_config["schema_version"] = CURRENT_INSTANCE_SCHEMA_VERSION
        self.store.write_config(updated_config)
        self.store._atomic_json(
            self.store.paths.migration_receipts / f"{MIGRATION_1_TO_2}.json",
            receipt,
        )
        self.store._atomic_json(
            self.store.paths.manifest,
            build_instance_manifest(
                updated_config,
                migrations=[
                    {
                        "id": MIGRATION_1_TO_2,
                        "applied_at": completed_at,
                        "receipt": receipt_ref,
                    }
                ],
            ),
        )
        return receipt

    def prepare(self) -> dict[str, Any]:
        recovery = None
        if self.pending_path.exists():
            with self._hold(purpose="instance-lifecycle-recovery"):
                recovery = self._recover_pending()
        report = self.validate(deep=False)
        if report["status"] != "valid":
            raise InstanceLifecycleError("Instance validation failed before open")
        schema = report["instance_schema_version"]
        if schema == CURRENT_INSTANCE_SCHEMA_VERSION:
            self.store.validate()
            return {
                "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
                "status": "ready",
                "instance_schema_version": schema,
                "migration": None,
                "recovery": recovery,
            }
        if schema != LEGACY_INSTANCE_SCHEMA_VERSION:
            raise InstanceLifecycleError("Instance schema has no supported migration path")

        with self._hold(purpose="instance-schema-migration"):
            current = self.validate(deep=True)
            if current["status"] != "valid":
                raise InstanceLifecycleError("Instance migration preflight failed")
            if current["instance_schema_version"] == CURRENT_INSTANCE_SCHEMA_VERSION:
                self.store.validate()
                return {
                    "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
                    "status": "ready",
                    "instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
                    "migration": None,
                    "recovery": recovery,
                }
            backup = create_backup(self.store, reason="pre_migration_1_to_2")
            self._write_pending(operation="migration", rollback=backup)
            try:
                receipt = self._apply_migration_1_to_2(backup=backup)
                final = self.validate(deep=True)
                if final["status"] != "valid" or final[
                    "instance_schema_version"
                ] != CURRENT_INSTANCE_SCHEMA_VERSION:
                    raise InstanceLifecycleError("Instance migration verification failed")
                self._clear_pending()
            except Exception as exc:
                try:
                    self._replace_from_archive(
                        Path(str(backup["archive"])),
                        expected_instance_id=str(backup["instance_id"]),
                    )
                    self._clear_pending()
                except Exception as rollback_exc:
                    raise InstanceLifecycleError(
                        "Instance migration failed and rollback could not be verified"
                    ) from rollback_exc
                raise InstanceLifecycleError(
                    "Instance migration failed; the verified pre-migration backup was restored"
                ) from exc
        self.store.validate()
        return {
            "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
            "status": "migrated",
            "instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
            "migration": receipt,
            "backup": backup,
            "recovery": recovery,
        }

    def backup(
        self,
        *,
        destination: Path | str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]:
        self.prepare()
        with self._hold(purpose="instance-backup"):
            self._write_pending(operation="backup", rollback=None)
            try:
                result = create_backup(
                    self.store,
                    destination=destination,
                    reason=reason,
                )
                self._clear_pending()
                return result
            except Exception:
                self._clear_pending()
                raise

    def restore(self, archive: Path | str) -> dict[str, Any]:
        self.prepare()
        requested = verify_backup(archive)
        current = self.validate(deep=True)
        instance_id = current.get("instance_id")
        if not isinstance(instance_id, str) or requested["instance_id"] != instance_id:
            raise InstanceLifecycleError(
                "restore archive belongs to a different Provelume Instance"
            )
        with self._hold(purpose="instance-restore"):
            rollback = create_backup(self.store, reason="pre_restore")
            self._write_pending(
                operation="restore",
                rollback=rollback,
                requested_archive_sha256=requested["archive_sha256"],
            )
            try:
                restored = self._replace_from_archive(
                    Path(archive).expanduser().resolve(),
                    expected_instance_id=instance_id,
                )
                migration = None
                if (
                    restored["instance_schema_version"]
                    == LEGACY_INSTANCE_SCHEMA_VERSION
                ):
                    migration = self._apply_migration_1_to_2(backup=requested)
                final = self.validate(deep=True)
                if final["status"] != "valid" or final[
                    "instance_schema_version"
                ] != CURRENT_INSTANCE_SCHEMA_VERSION:
                    raise InstanceLifecycleError("restored Instance failed verification")
                self._clear_pending()
            except Exception as exc:
                try:
                    self._replace_from_archive(
                        Path(str(rollback["archive"])),
                        expected_instance_id=instance_id,
                    )
                    self._clear_pending()
                except Exception as rollback_exc:
                    raise InstanceLifecycleError(
                        "Instance restore failed and rollback could not be verified"
                    ) from rollback_exc
                raise InstanceLifecycleError(
                    "Instance restore failed; the verified pre-restore backup was restored"
                ) from exc
        self.store.validate()
        return {
            "schema_version": LIFECYCLE_STATE_SCHEMA_VERSION,
            "status": "restored",
            "instance_id": instance_id,
            "instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
            "requested_archive_sha256": requested["archive_sha256"],
            "rollback_backup": rollback,
            "migration": migration,
            "derived_state": requested["derived_state"],
            "content_fingerprint": final["content_fingerprint"],
        }


__all__ = [
    "BackupError",
    "InstanceLifecycleBusy",
    "InstanceLifecycleError",
    "InstanceLifecycleManager",
]
