"""Explicit, backup-bound schema transition; never an ordinary-open side effect."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from .atomic_commit import _fsync_directory
from .instance_backup import (
    BACKUP_MANIFEST_NAME,
    MAX_BACKUP_ENTRIES,
    _entry_manifest,
    _file_identity,
    _payload_files,
    create_backup,
    extract_backup,
    verify_backup,
)
from .instance_lifecycle import InstanceLifecycleError, InstanceLifecycleManager
from .instance_schema import (
    CURRENT_INSTANCE_SCHEMA_VERSION,
    MIGRATION_2_TO_3,
)
from .instance_validation import inspect_instance
from .knowledge_object_store import hierarchy_object, promote_hierarchy
from .migration_permissions import (
    MAX_PROFILE_BYTES,
    canonical,
    capture_permissions,
    permission_fingerprint,
    planned_permissions,
    prepare_private_directories,
    private_directory,
    validate_profile,
)
from .storage import InstanceStore, utc_now


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def tree_inventory(root: Path):
    """Full bytes, including preferences, consent and derived state, for CAS/recovery."""
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise InstanceLifecycleError("migration image is not a regular Instance directory")
    if any(parent.is_symlink() or parent.is_junction() for parent in root.parents):
        raise InstanceLifecycleError("migration image cannot traverse linked parents")
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise InstanceLifecycleError("migration image cannot traverse links")
        if path.is_dir():
            continue
        if not path.is_file() or len(entries) >= MAX_BACKUP_ENTRIES:
            raise InstanceLifecycleError("migration image has unsupported entries")
        size, digest = _file_identity(path)
        entries.append(
            {"path": path.relative_to(root).as_posix(), "size_bytes": size, "sha256": digest}
        )
    return entries


def _verified_backup(backup):
    verified = verify_backup(backup["archive"])
    if (
        verified["archive_sha256"] != backup["archive_sha256"]
        or verified["instance_id"] != backup["instance_id"]
    ):
        raise InstanceLifecycleError("migration backup identity changed")
    return verified


def _backup_entries(backup):
    _verified_backup(backup)
    with zipfile.ZipFile(backup["archive"]) as archive:
        return json.loads(archive.read(BACKUP_MANIFEST_NAME))["entries"]


def upgrade_objects_stage(store, *, backup, backup_directory):
    """Transform a private, validated stage; return both retained migration receipts."""
    before = inspect_instance(store.paths.root, deep=True)
    source = _verified_backup(backup)
    if (
        before["status"] != "valid"
        or before["instance_id"] != source["instance_id"]
        or before["instance_schema_version"] != source["instance_schema_version"]
        or before["content_fingerprint"] != source["content_fingerprint"]
    ):
        raise InstanceLifecycleError("migration stage does not match its verified source")
    schema = before["instance_schema_version"]
    if schema == CURRENT_INSTANCE_SCHEMA_VERSION:
        return []
    if schema not in (1, 2):
        raise InstanceLifecycleError("unsupported object migration source")
    # Validate every promotion before writing even the private stage. Never repair
    # legacy timestamps, names or IDs by inventing replacement values.
    for node in store.list_canonical("hierarchy"):
        if node["kind"] in {"project", "collection"}:
            hierarchy_object(node, before["instance_id"])
    original_config = store.read_config()
    preserved = {
        row["path"]: row
        for row in _entry_manifest(_payload_files(store))
        if row["path"] not in {"provelume.yml", "instance-manifest.json"}
    }
    receipts = []
    if schema == 1:
        receipts.append(InstanceLifecycleManager(store)._apply_migration_1_to_2(backup=backup))
        backup = create_backup(
            store, destination=backup_directory, reason="pre_object_schema_2_to_3"
        )
    _verified_backup(backup)
    config = store.read_config()
    old_manifest = store.read_manifest()
    if any(m.get("id") == MIGRATION_2_TO_3 for m in old_manifest["migrations"]):
        raise InstanceLifecycleError("object migration receipt already exists on an old schema")
    started_at = utc_now()
    promoted = promote_hierarchy(store)
    completed_at = utc_now()
    receipt_ref = f"state/migrations/receipts/{MIGRATION_2_TO_3}.json"
    updated = dict(config)
    updated["schema_version"] = CURRENT_INSTANCE_SCHEMA_VERSION
    store.write_config(updated)
    store._atomic_json(
        store.paths.manifest,
        {
            **old_manifest,
            "instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
            "migrations": [
                *old_manifest["migrations"],
                {"id": MIGRATION_2_TO_3, "applied_at": completed_at, "receipt": receipt_ref},
            ],
        },
    )
    after = inspect_instance(store.paths.root, deep=True)
    if after["status"] != "valid" or after["instance_id"] != before["instance_id"]:
        raise InstanceLifecycleError("migrated stage failed deep validation")
    current_rows = {row["path"]: row for row in _entry_manifest(_payload_files(store))}
    if any(current_rows.get(path) != row for path, row in preserved.items()) or {
        k: v for k, v in store.read_config().items() if k != "schema_version"
    } != {k: v for k, v in original_config.items() if k != "schema_version"}:
        raise InstanceLifecycleError("migration changed retained source bytes or preferences")
    receipt = {
        "schema_version": 1,
        "migration_id": MIGRATION_2_TO_3,
        "status": "completed",
        "from_instance_schema_version": 2,
        "to_instance_schema_version": 3,
        "instance_id": before["instance_id"],
        "started_at": started_at,
        "completed_at": completed_at,
        "preflight_content_fingerprint": backup["content_fingerprint"],
        "content_fingerprint": after["content_fingerprint"],
        "preserved_payload_sha256": _digest(sorted(preserved.values(), key=lambda r: r["path"])),
        "promoted_hierarchy_ids": promoted,
        "backup": {
            "archive_name": Path(backup["archive"]).name,
            "sha256": backup["archive_sha256"],
            "size_bytes": backup["size_bytes"],
        },
        "derived_state": {"indexes": "rebuild", "library": "rebuild"},
        "network_used": False,
        "ai_used": False,
    }
    store._atomic_json(store.paths.root / receipt_ref, receipt)
    receipts.append(receipt)
    return receipts


def _save_pending(manager, pending):
    manager.store._atomic_json(manager.pending_path, pending)
    _fsync_directory(manager.control_root)


def _clear_pending(manager):
    manager._clear_pending()
    _fsync_directory(manager.control_root)


def _permission_path(manager, token, role):
    if re.fullmatch(r"[0-9a-f]{32}", token) is None or role not in {"source", "rollback", "post"}:
        raise InstanceLifecycleError("object migration metadata identity is invalid")
    directory = manager.control_root / "permission-profiles"
    private_directory(directory)
    return directory / f"{token}-{role}.json"


def _write_permissions(manager, pending, role, profile):
    validate_profile(profile)
    path = _permission_path(manager, pending["operation_id"], role)
    document = {
        "schema_version": 1,
        "operation_id": pending["operation_id"],
        "instance_id": pending["instance_id"],
        "role": role,
        "profile": profile,
    }
    raw = canonical(document)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fingerprint": permission_fingerprint(profile),
    }


def _read_permissions(manager, pending, role):
    binding = pending.get("permission_profiles", {}).get(role)
    if type(binding) is not dict or set(binding) != {"sha256", "fingerprint"} or any(
        not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
        for v in binding.values()
    ):
        raise InstanceLifecycleError(
            "object migration access metadata is unbound; inspection required"
        )
    path = _permission_path(manager, pending["operation_id"], role)
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise InstanceLifecycleError("object migration access metadata is unavailable")
    with path.open("rb") as stream:
        raw = stream.read(MAX_PROFILE_BYTES + 4097)
    if len(raw) > MAX_PROFILE_BYTES + 4096 or hashlib.sha256(raw).hexdigest() != binding["sha256"]:
        raise InstanceLifecycleError("object migration access metadata changed; retained")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate metadata key")
            result[key] = value
        return result

    try:
        document = json.loads(raw, object_pairs_hook=pairs)
        if document != {
            "schema_version": 1,
            "operation_id": pending["operation_id"],
            "instance_id": pending["instance_id"],
            "role": role,
            "profile": document["profile"],
        } or type(document["schema_version"]) is not int:
            raise ValueError("metadata identity")
        profile = document["profile"]
        validate_profile(profile)
        if permission_fingerprint(profile) != binding["fingerprint"]:
            raise ValueError("metadata fingerprint")
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise InstanceLifecycleError("object migration access metadata is invalid") from exc
    return profile


def migrate_objects_instance(manager):
    prepared = manager.prepare(allow_legacy=True)
    with manager._hold(purpose="instance-schema-migration"):
        before = manager.validate(deep=True)
        if before["status"] != "valid":
            raise InstanceLifecycleError("Instance validation failed before migration")
        if before["instance_schema_version"] == CURRENT_INSTANCE_SCHEMA_VERSION:
            return {
                "schema_version": 1,
                "status": "ready",
                "migration": None,
                "instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
            }
        root = manager.store.paths.root
        inventory = tree_inventory(root)
        source_permissions = capture_permissions(root)
        source_fingerprint = permission_fingerprint(source_permissions)
        backup = create_backup(manager.store, reason="pre_object_migration")
        if tree_inventory(root) != inventory or (
            permission_fingerprint(capture_permissions(root)) != source_fingerprint
        ):
            raise InstanceLifecycleError("Instance changed while migration backup was built")
        token = uuid4().hex
        source_binding = _write_permissions(
            manager, {"operation_id": token, "instance_id": before["instance_id"]},
            "source", source_permissions,
        )
        manager._write_pending(
            operation="object-migration",
            rollback=backup,
            binding={
                "operation_id": token,
                "permission_schema": 1,
                "permission_profiles": {"source": source_binding, "rollback": None, "post": None},
                "preimage_sha256": _digest(inventory),
                "backup_image_sha256": _digest(_backup_entries(backup)),
                "postimage_sha256": None,
                "stage_name": None,
                "previous_name": None,
            },
        )
        _fsync_directory(manager.control_root)
        pending = manager._read_json(manager.pending_path)
        try:
            with tempfile.TemporaryDirectory(
                prefix="object-build-", dir=manager.control_root
            ) as tmp:
                stage = Path(tmp) / "instance"
                extract_backup(backup["archive"], stage, private=True)
                prepare_private_directories(stage, source_permissions)
                rollback_permissions = planned_permissions(stage, source_permissions)
                pending["permission_profiles"]["rollback"] = _write_permissions(
                    manager, pending, "rollback", rollback_permissions,
                )
                _save_pending(manager, pending)
                receipts = upgrade_objects_stage(
                    InstanceStore(stage),
                    backup=backup,
                    backup_directory=manager.control_root / "backups",
                )
                receipts[-1]["filesystem_access_permissions"] = {
                    "scope": "SAME_HOST_MIGRATION",
                    "provider": source_permissions["provider"],
                    "source_sha256": source_fingerprint,
                    "rollback_sha256": pending["permission_profiles"]["rollback"]["fingerprint"],
                }
                manager.store._atomic_json(
                    stage / "state/migrations/receipts" / (MIGRATION_2_TO_3 + ".json"),
                    receipts[-1],
                )
                publication = create_backup(
                    InstanceStore(stage),
                    destination=manager.control_root / "backups",
                    reason="verified_object_migration_stage",
                )

                def bind(stage_path, previous_path):
                    if tree_inventory(root) != inventory or (
                        permission_fingerprint(capture_permissions(root)) != source_fingerprint
                    ):
                        raise InstanceLifecycleError(
                            "Instance changed before migration publication"
                        )
                    pending["permission_profiles"]["post"] = _write_permissions(
                        manager, pending, "post", capture_permissions(stage_path),
                    )
                    pending.update(
                        postimage_sha256=_digest(tree_inventory(stage_path)),
                        stage_name=stage_path.name,
                        previous_name=previous_path.name,
                    )
                    _save_pending(manager, pending)

                published = manager._replace_from_archive(
                    Path(publication["archive"]),
                    expected_instance_id=before["instance_id"],
                    prepare_ai=False,
                    before_publish=bind,
                    permission_profile=source_permissions,
                )
            _clear_pending(manager)
        except Exception as exc:
            # Refuse to restore over an unrecognized/newer image. The pending
            # operation and backups remain available for operator diagnosis.
            try:
                recovery = recover_object_migration(manager, pending)
            except Exception as recovery_exc:
                raise InstanceLifecycleError(
                    "object migration stopped; source image changed, recovery requires inspection"
                ) from recovery_exc
            image = "post-migration" if "post_operation" in recovery["action"] else "pre-migration"
            raise InstanceLifecycleError(
                f"object migration failed; verified {image} image was retained"
            ) from exc
        return {
            "schema_version": 1,
            "status": "migrated",
            "instance_schema_version": 3,
            "migration": receipts[-1],
            "migrations": receipts,
            "backup": backup,
            "recovery": prepared.get("recovery"),
            "publication_backup": publication,
            "content_fingerprint": publication["content_fingerprint"],
            "filesystem_access_permissions": {
                **receipts[-1]["filesystem_access_permissions"],
                "post_sha256": pending["permission_profiles"]["post"]["fingerprint"],
                "retained_preimage": published["retained_preimage"],
            },
        }


def recover_object_migration(manager, pending):
    """Settle only the exact pre/postimages, never replay over newer/foreign bytes."""
    token = pending.get("operation_id")
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{32}", token) is None:
        raise InstanceLifecycleError("object migration recovery identity is incomplete")
    if type(pending.get("permission_schema")) is not int or pending["permission_schema"] != 1:
        raise InstanceLifecycleError(
            "legacy object migration access metadata is UNKNOWN; inspection required"
        )
    source_permissions = _read_permissions(manager, pending, "source")
    for key in ("preimage_sha256", "backup_image_sha256"):
        if (
            not isinstance(pending.get(key), str)
            or re.fullmatch(r"[0-9a-f]{64}", pending[key]) is None
        ):
            raise InstanceLifecycleError("object migration image binding is incomplete")
    post = pending.get("postimage_sha256")
    if post is not None and (
        not isinstance(post, str) or re.fullmatch(r"[0-9a-f]{64}", post) is None
    ):
        raise InstanceLifecycleError("object migration postimage binding is invalid")
    post_permissions = _read_permissions(manager, pending, "post") if post is not None else None
    backup = {
        "archive": pending.get("rollback_archive"),
        "archive_sha256": pending.get("rollback_archive_sha256"),
        "instance_id": pending.get("instance_id"),
    }
    verified = _verified_backup(backup)
    if _digest(_backup_entries(backup)) != pending["backup_image_sha256"]:
        raise InstanceLifecycleError("object migration backup image does not match")
    root = manager.store.paths.root
    owned = []
    for field, prefix, expected, metadata in (
        ("stage_name", f".{root.name}.object-stage-", post, post_permissions),
        (
            "previous_name", f".{root.name}.object-previous-",
            pending["preimage_sha256"], source_permissions,
        ),
    ):
        name = pending.get(field)
        if name is None and post is None:
            continue
        if (
            not isinstance(name, str)
            or re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}", name) is None
        ):
            raise InstanceLifecycleError("object migration staging ownership is invalid")
        path = root.parent / name
        if path.exists() or path.is_symlink():
            if _digest(tree_inventory(path)) != expected or (
                permission_fingerprint(capture_permissions(path))
                != permission_fingerprint(metadata)
            ):
                raise InstanceLifecycleError("object migration staging image changed; retained")
            owned.append(path)
    receipt_directory = manager.control_root / "object-recovery-receipts"
    private_directory(receipt_directory)
    receipt_path = receipt_directory / f"recovery_object_{token}.json"
    if not root.exists() and not root.is_symlink():

        def require_absent(stage, previous):
            if root.exists() or root.is_symlink() or root.is_junction():
                raise InstanceLifecycleError("object migration recovery target appeared; retained")

        manager._replace_from_archive(
            Path(backup["archive"]),
            expected_instance_id=verified["instance_id"],
            prepare_ai=False,
            before_publish=require_absent,
            permission_profile=_read_permissions(manager, pending, "rollback"),
        )
    inventory = tree_inventory(root)
    existing_receipt = manager._read_json(receipt_path)
    digest = _digest(inventory)
    metadata = permission_fingerprint(capture_permissions(root))
    if (
        digest == pending["preimage_sha256"]
        and metadata == permission_fingerprint(source_permissions)
    ) or (
        digest == pending["backup_image_sha256"]
        and metadata == permission_fingerprint(_read_permissions(manager, pending, "rollback"))
    ):
        action = "settled_verified_pre_operation_image"
    elif (
        post is not None and digest == post
        and metadata == permission_fingerprint(post_permissions)
    ):
        action = "settled_verified_post_operation_image"
    else:
        raise InstanceLifecycleError(
            "object migration recovery refuses changed or foreign Instance bytes or access metadata"
        )
    report = manager.validate(deep=True)
    if report["status"] != "valid" or report["instance_id"] != verified["instance_id"]:
        raise InstanceLifecycleError("object migration recovered identity failed validation")
    receipt = {
        "schema_version": 1,
        "id": "recovery_object_" + token,
        "status": "completed",
        "operation": "object-migration",
        "action": action,
        "recovered_at": pending["started_at"],
        "rollback_archive_sha256": verified["archive_sha256"],
        "filesystem_access_permissions_sha256": metadata,
        "receipt_location": "EXTERNAL_LIFECYCLE_CONTROL",
    }
    if existing_receipt is not None and existing_receipt != receipt:
        raise InstanceLifecycleError("object migration recovery receipt conflicts")
    manager.store._atomic_json(receipt_path, receipt)
    _fsync_directory(receipt_path.parent)
    _clear_pending(manager)
    for path in owned:
        # An interrupted best-effort cleanup can leave an inert residue, but
        # cannot put a settled live image back behind a recovery barrier.
        shutil.rmtree(path, ignore_errors=True)
    return {**receipt, "status": "recovered", "receipt": str(receipt_path),
            "retained_workdirs": [str(path) for path in owned if path.exists()]}
