"""Same-host access metadata is independent of canonical payload byte equality."""

from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
from copy import deepcopy

import pytest

from provelume import migration_permissions, object_migration
from provelume.instance_lifecycle import InstanceLifecycleError, InstanceLifecycleManager
from provelume.instance_schema import build_instance_manifest
from provelume.knowledge_object_contract import OBJECT_CANONICAL_KINDS
from provelume.migration_permissions import capture_permissions, permission_fingerprint
from provelume.service import ProvelumeInstance


def _legacy(tmp_path, schema=2):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    for kind in OBJECT_CANONICAL_KINDS:
        shutil.rmtree(instance.store.paths.canonical_dir(kind))
    config = instance.store.read_config()
    config["schema_version"] = schema
    instance.store.write_config(config)
    if schema == 1:
        instance.store.paths.manifest.unlink()
    else:
        instance.store._atomic_json(instance.store.paths.manifest, build_instance_manifest(config))
    retained = instance.root / "state/operator.txt"
    retained.write_bytes(b"Synthetic retained payload")
    empty = instance.root / "state/operator-empty"
    empty.mkdir()
    if os.name != "nt":
        instance.root.chmod(0o700)
        (instance.root / "state").chmod(0o700)
        retained.chmod(0o640)
        empty.chmod(0o750)
    return instance, retained


def _assert_retained_metadata(before, root):
    after = capture_permissions(root)
    if os.name == "nt":
        before = deepcopy(before)
        for profile in (before, after):
            for row in profile["entries"]:
                row["path"] = row["path"].casefold()
            profile["entries"].sort(key=lambda row: row["path"])
    names = {r["path"] for r in before["entries"]}
    after["entries"] = [r for r in after["entries"] if r["path"] in names]
    assert permission_fingerprint(before) == permission_fingerprint(after)


def _report_gate(pytestconfig, gate, status):
    # Keep a small original machine observation in CI's otherwise quiet Linux log.
    reporter = pytestconfig.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True))
        reporter.write_line(
            "ENTITAS_FILESYSTEM_GATE="
            + json.dumps(
                {
                    "gate": gate,
                    "status": status,
                    "execution_commit": head,
                    "dirty_checkout": dirty,
                    "synthetic_data_only": True,
                },
                sort_keys=True,
            )
        )


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("mask", [0o022, 0o077])
def test_migration_preserves_existing_access_metadata_and_empty_directories(tmp_path, schema, mask):
    saved = os.umask(mask)
    try:
        instance, retained = _legacy(tmp_path, schema)
        before = capture_permissions(instance.root)
        result = InstanceLifecycleManager(instance.store).prepare(migrate_objects=True)
        assert result["status"] == "migrated"
        assert retained.read_bytes() == b"Synthetic retained payload"
        _assert_retained_metadata(before, instance.root)
        assert result["filesystem_access_permissions"]["scope"] == "SAME_HOST_MIGRATION"
        if os.name != "nt":
            assert stat.S_IMODE(instance.root.stat().st_mode) == 0o700
            assert stat.S_IMODE(retained.stat().st_mode) == 0o640
    finally:
        os.umask(saved)


@pytest.mark.skipif(os.name == "nt", reason="POSIX access ACL and extended-attribute profile")
def test_migration_preserves_posix_acl_and_extended_attribute(tmp_path, pytestconfig):
    instance, retained = _legacy(tmp_path)
    acl = struct.pack("<I", 2) + b"".join(
        struct.pack("<HHI", tag, mode, identity)
        for tag, mode, identity in [
            (1, 6, 0xFFFFFFFF),
            (4, 0, 0xFFFFFFFF),
            (8, 4, os.getgid()),
            (16, 4, 0xFFFFFFFF),
            (32, 0, 0xFFFFFFFF),
        ]
    )
    try:
        os.setxattr(retained, "system.posix_acl_access", acl)
        os.setxattr(retained, "user.entitas-qualification", b"synthetic-metadata")
    except OSError as exc:
        if exc.errno in {errno.ENOTSUP, errno.EOPNOTSUPP}:
            _report_gate(pytestconfig, "posix_acl_and_xattr", "NOT_SUPPORTED_BY_HOST_FILESYSTEM")
            pytest.skip("the current filesystem does not implement POSIX ACL/xattr storage")
        raise
    before = capture_permissions(instance.root)
    InstanceLifecycleManager(instance.store).prepare(migrate_objects=True)
    _assert_retained_metadata(before, instance.root)
    assert os.getxattr(retained, "system.posix_acl_access") == acl
    assert os.getxattr(retained, "user.entitas-qualification") == b"synthetic-metadata"
    _report_gate(pytestconfig, "posix_acl_and_xattr", "PASS")


@pytest.mark.skipif(os.name != "nt", reason="native Windows owner/group/DACL/read-only profile")
def test_migration_preserves_windows_protected_dacl_and_readonly_file(tmp_path, pytestconfig):
    instance, retained = _legacy(tmp_path)
    migration_permissions.make_private(instance.root)
    migration_permissions.make_private(instance.root / "state")
    migration_permissions.make_private(retained)
    retained.chmod(stat.S_IREAD)
    before = capture_permissions(instance.root)
    result = InstanceLifecycleManager(instance.store).prepare(migrate_objects=True)
    _assert_retained_metadata(before, instance.root)
    assert next(
        r
        for r in capture_permissions(instance.root)["entries"]
        if r["path"] == "state/operator.txt"
    )["metadata"]["readonly"]
    assert (
        result["filesystem_access_permissions"]["provider"]
        == "windows-owner-group-dacl-readonly/v1"
    )
    _report_gate(pytestconfig, "windows_owner_group_dacl_readonly", "PASS")


@pytest.mark.parametrize("phase", ["before_publish", "between_renames", "after_publish"])
def test_process_death_recovery_preserves_access_metadata_without_live_receipt_writes(
    tmp_path, phase
):
    instance, _retained = _legacy(tmp_path)
    before = capture_permissions(instance.root)
    script = """
import os, sys
from pathlib import Path
from provelume import instance_lifecycle
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.storage import InstanceStore
root, phase = Path(sys.argv[1]), sys.argv[2]
real = instance_lifecycle.os.replace
def stop(source, target):
    source, target = Path(source), Path(target)
    if source == root and phase == 'before_publish': os._exit(73)
    real(source, target)
    if source == root and phase == 'between_renames': os._exit(73)
    if target == root and '.object-stage-' in source.name and phase == 'after_publish': os._exit(73)
instance_lifecycle.os.replace = stop
InstanceLifecycleManager(InstanceStore(root)).prepare(migrate_objects=True)
"""
    child = subprocess.run([sys.executable, "-c", script, str(instance.root), phase], timeout=60)
    assert child.returncode == 73
    manager = InstanceLifecycleManager(instance.store)
    report = manager.prepare(allow_legacy=True)
    assert report["recovery"]["status"] == "recovered"
    assert report["recovery"]["receipt_location"] == "EXTERNAL_LIFECYCLE_CONTROL"
    assert not manager.pending_path.exists()
    _assert_retained_metadata(before, instance.root)
    stable = object_migration.tree_inventory(instance.root)
    metadata = permission_fingerprint(capture_permissions(instance.root))
    manager.prepare(allow_legacy=True)
    assert object_migration.tree_inventory(instance.root) == stable
    assert permission_fingerprint(capture_permissions(instance.root)) == metadata


@pytest.mark.skipif(os.name != "nt", reason="native Windows case-insensitive config alias")
def test_windows_canonical_config_spelling_keeps_alias_access_metadata(tmp_path):
    instance, _retained = _legacy(tmp_path)
    config = instance.store.paths.config
    alias = config.with_name("PrOvElUmE.YmL")
    os.replace(config, alias)
    alias.chmod(stat.S_IREAD)
    before = capture_permissions(instance.root)
    InstanceLifecycleManager(instance.store).prepare(migrate_objects=True)
    _assert_retained_metadata(before, instance.root)
    assert next(
        row
        for row in capture_permissions(instance.root)["entries"]
        if row["path"].casefold() == "provelume.yml"
    )["metadata"]["readonly"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission-only concurrent change")
def test_permission_only_change_before_publication_is_retained_and_refused(tmp_path, monkeypatch):
    instance, retained = _legacy(tmp_path)
    before = object_migration.tree_inventory(instance.root)
    original = object_migration.upgrade_objects_stage

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        retained.chmod(0o600)
        return result

    monkeypatch.setattr(object_migration, "upgrade_objects_stage", changed)
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(InstanceLifecycleError, match="source image changed"):
        manager.prepare(migrate_objects=True)
    assert stat.S_IMODE(retained.stat().st_mode) == 0o600
    assert object_migration.tree_inventory(instance.root) == before
    assert manager.pending_path.is_file()


def _interrupt_after_publication(monkeypatch):
    original = InstanceLifecycleManager._replace_from_archive

    def interrupted(manager, archive, **kwargs):
        original(manager, archive, **kwargs)
        raise KeyboardInterrupt("synthetic interruption after bound publication")

    monkeypatch.setattr(InstanceLifecycleManager, "_replace_from_archive", interrupted)
    return original


def test_permission_only_postpublication_change_cannot_be_repaired_by_recovery(
    tmp_path, monkeypatch
):
    instance, retained = _legacy(tmp_path)
    original = _interrupt_after_publication(monkeypatch)
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(KeyboardInterrupt):
        manager.prepare(migrate_objects=True)
    monkeypatch.setattr(InstanceLifecycleManager, "_replace_from_archive", original)
    retained.chmod(stat.S_IREAD if os.name == "nt" else 0o600)
    before, metadata = (
        object_migration.tree_inventory(instance.root),
        permission_fingerprint(capture_permissions(instance.root)),
    )
    pending = manager.pending_path.read_bytes()
    with pytest.raises(InstanceLifecycleError, match="changed or foreign"):
        manager.prepare()
    assert object_migration.tree_inventory(instance.root) == before
    assert permission_fingerprint(capture_permissions(instance.root)) == metadata
    assert manager.pending_path.read_bytes() == pending


def test_failed_stage_metadata_application_leaves_all_live_bytes_and_permissions_intact(
    tmp_path, monkeypatch
):
    instance, _retained = _legacy(tmp_path)
    before, metadata = (
        object_migration.tree_inventory(instance.root),
        permission_fingerprint(capture_permissions(instance.root)),
    )
    original = migration_permissions.apply_permissions

    def failed(*args, **kwargs):
        original(*args, **kwargs)
        raise migration_permissions.PermissionProfileError(
            "synthetic failure after stage metadata application"
        )

    monkeypatch.setattr(migration_permissions, "apply_permissions", failed)
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(InstanceLifecycleError, match="pre-migration image was retained"):
        manager.prepare(migrate_objects=True)
    assert object_migration.tree_inventory(instance.root) == before
    assert permission_fingerprint(capture_permissions(instance.root)) == metadata
    assert not manager.pending_path.exists()


@pytest.mark.parametrize("damage", ["corrupt_profile", "legacy_without_metadata_schema"])
def test_untrusted_or_unbound_recovery_metadata_is_preserved_without_mutation(
    tmp_path, monkeypatch, damage
):
    instance, _retained = _legacy(tmp_path)
    original = _interrupt_after_publication(monkeypatch)
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(KeyboardInterrupt):
        manager.prepare(migrate_objects=True)
    monkeypatch.setattr(InstanceLifecycleManager, "_replace_from_archive", original)
    pending = json.loads(manager.pending_path.read_text())
    if damage == "corrupt_profile":
        path = (
            manager.control_root
            / "permission-profiles"
            / (pending["operation_id"] + "-source.json")
        )
        path.write_bytes(path.read_bytes() + b" ")
    else:
        pending.pop("permission_schema")
        manager.store._atomic_json(manager.pending_path, pending)
    before, metadata = (
        object_migration.tree_inventory(instance.root),
        permission_fingerprint(capture_permissions(instance.root)),
    )
    pending_bytes = manager.pending_path.read_bytes()
    with pytest.raises(InstanceLifecycleError, match="metadata"):
        manager.prepare()
    assert object_migration.tree_inventory(instance.root) == before
    assert permission_fingerprint(capture_permissions(instance.root)) == metadata
    assert manager.pending_path.read_bytes() == pending_bytes


def test_foreign_target_appearing_between_renames_is_never_overwritten(tmp_path, monkeypatch):
    instance, _retained = _legacy(tmp_path)
    foreign = ProvelumeInstance.initialise(tmp_path / "foreign")
    expected = object_migration.tree_inventory(foreign.root)
    metadata = permission_fingerprint(capture_permissions(foreign.root))
    real = os.replace

    def appeared(source, target):
        real(source, target)
        if os.fspath(source) == os.fspath(instance.root):
            real(foreign.root, instance.root)

    monkeypatch.setattr(os, "replace", appeared)
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(InstanceLifecycleError, match="source image changed"):
        manager.prepare(migrate_objects=True)
    assert object_migration.tree_inventory(instance.root) == expected
    assert permission_fingerprint(capture_permissions(instance.root)) == metadata
    assert manager.pending_path.is_file()
    pending = json.loads(manager.pending_path.read_text())
    assert (instance.root.parent / pending["previous_name"]).is_dir()


def test_newer_payload_after_publication_survives_final_validation_failure(tmp_path, monkeypatch):
    instance, _retained = _legacy(tmp_path)
    real = os.replace
    newer = instance.root / "state/newer-operation.txt"

    def changed(source, target):
        real(source, target)
        if os.fspath(target) == os.fspath(instance.root) and ".object-stage-" in os.fspath(source):
            newer.write_bytes(b"Retain a newer operation")

    monkeypatch.setattr(os, "replace", changed)
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(InstanceLifecycleError, match="source image changed"):
        manager.prepare(migrate_objects=True)
    assert newer.read_bytes() == b"Retain a newer operation"
    assert instance.store.read_config()["schema_version"] == 3
    assert manager.pending_path.is_file()


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        struct.pack("<BBHIIII", 1, 0, 0x8000, 20, 20, 0, 0) + b"\x01\x10" + b"\0" * 6,
        struct.pack("<BBHIIII", 1, 0, 0x8004, 20, 20, 0, 28)
        + b"\x01\0"
        + b"\0" * 6
        + struct.pack("<BBHHH", 2, 0, 4096, 0, 0),
    ],
    ids=["empty", "sid-range", "acl-range"],
)
def test_malformed_relative_descriptor_ranges_never_enter_a_native_api(monkeypatch, raw):
    def forbidden():
        raise AssertionError("malformed input must be refused before native access")

    monkeypatch.setattr(migration_permissions, "_windows", forbidden)
    with pytest.raises(migration_permissions.PermissionProfileError):
        migration_permissions._descriptor_parts(raw)
