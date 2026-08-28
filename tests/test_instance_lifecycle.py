from __future__ import annotations

import json
import socket
import zipfile
from pathlib import Path

import pytest
import yaml

from provelume.cli import main
from provelume.instance_backup import BackupError, create_backup, verify_backup
from provelume.instance_lifecycle import (
    InstanceLifecycleError,
    InstanceLifecycleManager,
)
from provelume.instance_schema import (
    CURRENT_INSTANCE_SCHEMA_VERSION,
    DERIVED_STATE_POLICY,
    MIGRATION_1_TO_2,
)
from provelume.instance_validation import inspect_instance
from provelume.service import ProvelumeInstance
from provelume.storage import CANONICAL_KINDS, InstanceStore


def _legacy_instance(instance: ProvelumeInstance) -> None:
    config = instance.store.read_config()
    config["schema_version"] = 1
    instance.store.write_config(config)
    instance.store.paths.manifest.unlink()


def _seed(tmp_path: Path, *, name: str = "Lifecycle fixture") -> tuple[ProvelumeInstance, Path]:
    source = tmp_path / "source"
    source.mkdir()
    note = source / "note.md"
    note.write_text("# Alpha\n\nPortable recovery.\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name=name)
    instance.ingest(source)
    return instance, note


def _canonical_snapshot(store: InstanceStore) -> dict[str, list[dict[str, object]]]:
    return {kind: store.list_canonical(kind) for kind in CANONICAL_KINDS}


def test_initialise_writes_current_manifest_and_deep_validation(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Manifest fixture")

    config = instance.store.read_config()
    manifest = instance.store.read_manifest()
    report = instance.validate_instance()

    assert config["schema_version"] == CURRENT_INSTANCE_SCHEMA_VERSION
    assert manifest == {
        "schema_version": 1,
        "instance_schema_version": CURRENT_INSTANCE_SCHEMA_VERSION,
        "instance": {
            "id": config["instance"]["id"],
            "created_at": config["instance"]["created_at"],
        },
        "derived_state": DERIVED_STATE_POLICY,
        "migrations": [],
    }
    assert report["status"] == "valid"
    assert report["migration_required"] is False
    assert report["content_fingerprint"] == (
        "e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )
    assert report["counts"] == {"canonical_records": 0, "original_files": 0}
    assert instance.instance_summary()["derived_state"] == DERIVED_STATE_POLICY
    assert instance.instance_summary()["manifest_schema_version"] == 1


def test_validation_is_read_only_and_detects_tampered_original(tmp_path: Path) -> None:
    instance, _note = _seed(tmp_path)
    config_before = instance.store.paths.config.read_bytes()
    manifest_before = instance.store.paths.manifest.read_bytes()
    original = instance.store.list_canonical("originals")[0]
    original_path = instance.root / original["storage_ref"]
    original_path.write_bytes(b"tampered")

    fast = inspect_instance(instance.root, deep=False)
    report = inspect_instance(instance.root, deep=True)

    assert fast["status"] == "valid"
    assert report["status"] == "invalid"
    assert report["content_fingerprint"] is None
    assert {item["code"] for item in report["errors"]} == {
        "original_integrity_mismatch"
    }
    assert instance.store.paths.config.read_bytes() == config_before
    assert instance.store.paths.manifest.read_bytes() == manifest_before


def test_opening_current_schema_does_not_hash_every_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _note = _seed(tmp_path)

    def forbidden_deep_original_validation(*args, **kwargs):
        raise AssertionError("ordinary open performed deep Original validation")

    monkeypatch.setattr(
        "provelume.instance_validation._validate_originals",
        forbidden_deep_original_validation,
    )

    assert ProvelumeInstance(instance.root).instance_summary()["id"] == (
        instance.instance_summary()["id"]
    )


def test_open_migrates_schema_1_after_verified_backup(tmp_path: Path) -> None:
    instance, _note = _seed(tmp_path)
    before = _canonical_snapshot(instance.store)
    instance_id = instance.instance_summary()["id"]
    _legacy_instance(instance)

    result = InstanceLifecycleManager(InstanceStore(instance.root)).prepare()

    reopened = InstanceStore(instance.root)
    reopened.validate()
    backup = verify_backup(result["backup"]["archive"])
    receipt_path = reopened.paths.migration_receipts / f"{MIGRATION_1_TO_2}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    manifest = reopened.read_manifest()
    assert result["status"] == "migrated"
    assert backup["status"] == "valid"
    assert backup["instance_schema_version"] == 1
    assert backup["instance_id"] == instance_id
    assert reopened.read_config()["schema_version"] == 2
    assert manifest["instance"]["id"] == instance_id
    assert manifest["migrations"] == [
        {
            "id": MIGRATION_1_TO_2,
            "applied_at": receipt["completed_at"],
            "receipt": f"state/migrations/receipts/{MIGRATION_1_TO_2}.json",
        }
    ]
    assert receipt["backup"]["sha256"] == backup["archive_sha256"]
    assert receipt["preflight_content_fingerprint"] == backup[
        "content_fingerprint"
    ]
    assert _canonical_snapshot(reopened) == before
    assert not InstanceLifecycleManager(reopened).pending_path.exists()
    assert not InstanceLifecycleManager(reopened).lock_path.exists()


def test_unknown_future_schema_fails_before_backup_or_mutation(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    config = instance.store.read_config()
    config["schema_version"] = CURRENT_INSTANCE_SCHEMA_VERSION + 1
    instance.store.write_config(config)
    before = instance.store.paths.config.read_bytes()

    report = inspect_instance(instance.root)
    with pytest.raises(InstanceLifecycleError, match="validation failed before open"):
        InstanceLifecycleManager(InstanceStore(instance.root)).prepare()

    assert report["status"] == "invalid"
    assert report["errors"][0]["code"] == "unsupported_future_schema"
    assert instance.store.paths.config.read_bytes() == before
    control = InstanceLifecycleManager(instance.store).control_root
    assert not (control / "backups").exists()


def test_failed_migration_restores_schema_1_and_canonical_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _note = _seed(tmp_path)
    _legacy_instance(instance)
    root = instance.root
    canonical_before = _canonical_snapshot(instance.store)

    def fail_after_first_write(self, *, backup):
        config = self.store.read_config()
        config["schema_version"] = 2
        self.store.write_config(config)
        raise OSError("synthetic migration interruption")

    monkeypatch.setattr(
        InstanceLifecycleManager,
        "_apply_migration_1_to_2",
        fail_after_first_write,
    )
    manager = InstanceLifecycleManager(InstanceStore(root))
    with pytest.raises(
        InstanceLifecycleError,
        match="verified pre-migration backup was restored",
    ):
        manager.prepare()

    restored = InstanceStore(root)
    assert restored.read_config()["schema_version"] == 1
    assert not restored.paths.manifest.exists()
    assert _canonical_snapshot(restored) == canonical_before
    assert not manager.pending_path.exists()
    assert not manager.lock_path.exists()
    archives = sorted((manager.control_root / "backups").glob("*.zip"))
    assert len(archives) == 1
    assert verify_backup(archives[0])["status"] == "valid"


def test_pending_migration_is_rolled_back_then_retried(tmp_path: Path) -> None:
    instance, _note = _seed(tmp_path)
    _legacy_instance(instance)
    manager = InstanceLifecycleManager(instance.store)
    rollback = create_backup(instance.store, reason="synthetic_interruption")
    config = instance.store.read_config()
    config["schema_version"] = 2
    instance.store.write_config(config)
    manager._write_pending(operation="migration", rollback=rollback)
    pending = json.loads(manager.pending_path.read_text(encoding="utf-8"))
    pending["pid"] = 2_000_000_000
    pending["hostname"] = socket.gethostname()
    instance.store._atomic_json(manager.pending_path, pending)

    result = InstanceLifecycleManager(InstanceStore(instance.root)).prepare()

    assert result["status"] == "migrated"
    recovery = result["recovery"]
    assert recovery["schema_version"] == 1
    assert recovery["status"] == "recovered"
    assert recovery["operation"] == "migration"
    assert recovery["action"] == "restored_verified_pre_operation_backup"
    assert recovery["rollback_archive_sha256"] == rollback["archive_sha256"]
    assert (instance.root / recovery["receipt"]).is_file()
    InstanceStore(instance.root).validate()


def test_backup_restore_round_trip_rebuilds_excluded_index(tmp_path: Path) -> None:
    instance, note = _seed(tmp_path)
    document_id = instance.list_documents()[0]["id"]
    backup = instance.backup(destination=tmp_path / "snapshots")
    assert verify_backup(backup["archive"])["excluded_prefixes"] == [
        "indexes/",
        "library/",
        "state/locks/",
    ]

    note.write_text("# Beta\n\nChanged after the backup.\n", encoding="utf-8")
    instance.ingest(note.parent)
    assert len(instance.versions(document_id)) == 2

    restored = instance.restore(backup["archive"])

    assert restored["status"] == "restored"
    assert Path(restored["rollback_backup"]["archive"]).is_file()
    assert len(instance.versions(document_id)) == 1
    assert instance.search("portable recovery")[0]["document_id"] == document_id
    assert instance.search("changed after") == []
    assert inspect_instance(instance.root)["status"] == "valid"


def test_backup_and_verification_stream_files_without_path_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    retained = instance.root / "state" / "retained.bin"
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_bytes(b"streamed-state" * 100_000)

    def forbidden_read_bytes(self):
        raise AssertionError(f"Path.read_bytes loaded a complete file: {self}")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    backup = instance.backup(destination=tmp_path / "streamed.zip")

    assert verify_backup(backup["archive"])["status"] == "valid"


def test_backup_refuses_to_overwrite_existing_archive(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"operator-owned")

    with pytest.raises(BackupError, match="already exists"):
        instance.backup(destination=destination)

    assert destination.read_bytes() == b"operator-owned"


def test_restore_rejects_backup_from_another_instance_without_mutation(
    tmp_path: Path,
) -> None:
    first = ProvelumeInstance.initialise(tmp_path / "first")
    backup = first.backup(destination=tmp_path / "first.zip")
    second = ProvelumeInstance.initialise(tmp_path / "second")
    before = second.store.paths.config.read_bytes()

    with pytest.raises(InstanceLifecycleError, match="different Provelume Instance"):
        second.restore(backup["archive"])

    assert second.store.paths.config.read_bytes() == before
    assert inspect_instance(second.root)["status"] == "valid"


def test_backup_verifier_rejects_unsafe_manifest_path(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    backup = instance.backup(destination=tmp_path / "safe.zip")
    hostile = tmp_path / "hostile.zip"
    with zipfile.ZipFile(backup["archive"], "r") as source:
        values = {info.filename: source.read(info) for info in source.infolist()}
    manifest = json.loads(values["backup-manifest.json"])
    manifest["entries"].append(
        {"path": "../escape", "sha256": "0" * 64, "size_bytes": 0}
    )
    values["backup-manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode()
    with zipfile.ZipFile(hostile, "w") as target:
        for name, data in values.items():
            target.writestr(name, data)

    with pytest.raises(BackupError, match="path is unsafe"):
        verify_backup(hostile)


def test_failed_restore_reinstalls_verified_pre_restore_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, note = _seed(tmp_path)
    old_backup = instance.backup(destination=tmp_path / "old.zip")
    document_id = instance.list_documents()[0]["id"]
    note.write_text("# New state\n\nMust survive failed restore.\n", encoding="utf-8")
    instance.ingest(note.parent)
    current = _canonical_snapshot(instance.store)
    original_replace = InstanceLifecycleManager._replace_from_archive
    calls = 0

    def fail_after_requested_install(self, archive, *, expected_instance_id):
        nonlocal calls
        calls += 1
        result = original_replace(
            self,
            archive,
            expected_instance_id=expected_instance_id,
        )
        if calls == 1:
            raise OSError("synthetic failure after requested archive install")
        return result

    monkeypatch.setattr(
        InstanceLifecycleManager,
        "_replace_from_archive",
        fail_after_requested_install,
    )
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(
        InstanceLifecycleError,
        match="verified pre-restore backup was restored",
    ):
        manager.restore(old_backup["archive"])

    assert calls == 2
    assert _canonical_snapshot(instance.store) == current
    assert len(instance.versions(document_id)) == 2
    assert inspect_instance(instance.root)["status"] == "valid"
    assert not manager.pending_path.exists()
    assert not manager.lock_path.exists()


def test_lifecycle_cli_validate_migrate_backup_and_restore(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    _legacy_instance(instance)

    assert main(["validate", str(instance.root)]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["status"] == "valid"
    assert validation["migration_required"] is True
    assert yaml.safe_load(instance.store.paths.config.read_text())["schema_version"] == 1

    assert main(["migrate", str(instance.root)]) == 0
    migration = json.loads(capsys.readouterr().out)
    assert migration["status"] == "migrated"

    output = tmp_path / "cli-backup.zip"
    assert main(["backup", str(instance.root), "--output", str(output)]) == 0
    backup = json.loads(capsys.readouterr().out)
    assert backup["archive"] == str(output.resolve())
    assert output.is_file()

    assert main(["restore", str(instance.root), str(output)]) == 0
    restored = json.loads(capsys.readouterr().out)
    assert restored["status"] == "restored"


def test_public_lifecycle_documentation_states_authority_and_limits() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = (root / "docs" / "architecture" / "portable-instance.md").read_text(
        encoding="utf-8"
    )
    readme = (root / "README.md").read_text(encoding="utf-8")

    for required in (
        "Read-only validation",
        "Forward-only schema migration",
        "Backup contract",
        "Restore, rollback and crash recovery",
        "does not rewrite canonical JSON or acquired Original bytes",
        "same-Instance operation, not cross-Instance import",
        "Configured Source, Drop or managed-copy directories",
        "state/lifecycle/recovery-receipts/",
        "remain `0.6/S05`",
    ):
        assert required in contract
    for command in (
        "provelume validate",
        "provelume migrate",
        "provelume backup",
        "provelume restore",
    ):
        assert command in readme
