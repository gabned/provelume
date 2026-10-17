"""Synthetic data-safety qualification of the explicit Entitas storage boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from provelume import atomic_commit, object_migration
from provelume.instance_backup import BackupError, create_backup, verify_backup
from provelume.instance_lifecycle import InstanceLifecycleError, InstanceLifecycleManager
from provelume.instance_schema import MIGRATION_1_TO_2, MIGRATION_2_TO_3, build_instance_manifest
from provelume.instance_validation import inspect_instance
from provelume.knowledge_object_contract import (
    MAX_RECORD_BYTES,
    OBJECT_CANONICAL_KINDS,
    KnowledgeObjectError,
    record_digest,
)
from provelume.knowledge_object_store import persist_object_locked, revision_record
from provelume.object_migration import tree_inventory
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore

TIME = "2026-10-17T12:00:00Z"


def _entity(store, *, digit="a", **changes):
    return {
        "schema_version": 1,
        "id": "obj_" + digit * 32,
        "instance_id": store.read_config()["instance"]["id"],
        "kind": "entity",
        "revision": 1,
        "previous_sha256": None,
        "title": "Synthetic",
        "aliases": [],
        "state": "active",
        "body": {"description": "<inert>"},
        "evidence_ids": [],
        "origin": {"kind": "manual", "proposal_id": None},
        "created_at": TIME,
        "updated_at": TIME,
        **changes,
    }


def _persist(store, value, *, expected=None, **kwargs):
    with InstanceLifecycleManager(store)._hold(purpose="synthetic-object-storage"):
        persist_object_locked(store, value, expected_sha256=expected, **kwargs)


def _evidence(store):
    version = store.list_canonical("versions")[0]
    row = {
        "schema_version": 1,
        "instance_id": store.read_config()["instance"]["id"],
        "document_id": version["document_id"],
        "version_id": version["id"],
        "original_id": version["original_id"],
        "original_sha256": version["content_hash"],
        "selector": {"kind": "original"},
    }
    return {**row, "id": "evd_" + record_digest(row)}


def _relation(store, source, target, *, digit="c", kind="relates_to"):
    return {
        "schema_version": 1,
        "id": "rel_" + digit * 32,
        "instance_id": store.read_config()["instance"]["id"],
        "revision": 1,
        "previous_sha256": None,
        "relation_type": kind,
        "source": {
            "id": source["id"],
            "revision": source["revision"],
            "sha256": record_digest(source),
        },
        "target": {
            "id": target["id"],
            "revision": target["revision"],
            "sha256": record_digest(target),
        },
        "state": "active",
        "evidence_ids": [],
        "created_at": TIME,
        "updated_at": TIME,
    }


def _legacy(tmp_path, schema=2):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.md").write_text("# Original\n\nSynthetic evidence.\n", encoding="utf-8")
    instance.ingest(source)
    area = instance.create_hierarchy_node("area", "Existing area")
    project = instance.create_hierarchy_node("project", "Existing project", parent_id=area["id"])
    collection = instance.create_hierarchy_node("collection", "Existing collection")
    for kind in OBJECT_CANONICAL_KINDS:
        shutil.rmtree(instance.store.paths.canonical_dir(kind))
    config = instance.store.read_config()
    config["schema_version"] = schema
    config["ui"]["language"] = "it"
    instance.store.write_config(config)
    if schema == 1:
        instance.store.paths.manifest.unlink()
    else:
        manifest = {
            **build_instance_manifest(config),
            "operator_extension": {"synthetic_preference": "retained"},
        }
        instance.store._atomic_json(instance.store.paths.manifest, manifest)
    retained = instance.root / "state" / "synthetic-preferences.json"
    retained.write_bytes(b'{"language":"it","interface":"current","ai":false}\n')
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    return instance, (project["id"], collection["id"])


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("entry", ["open", "initialise"])
def test_ordinary_open_refuses_older_schema_without_changing_any_instance_byte(
    tmp_path, schema, entry
):
    instance, _ = _legacy(tmp_path, schema)
    before = tree_inventory(instance.root)
    with pytest.raises(InstanceLifecycleError, match="explicit object migration"):
        if entry == "open":
            ProvelumeInstance(instance.root)
        else:
            InstanceStore.initialise(instance.root)
    assert tree_inventory(instance.root) == before
    assert not (InstanceLifecycleManager(instance.store).control_root / "backups").exists()


@pytest.mark.parametrize("schema", [1, 2])
def test_explicit_migration_preserves_ids_payload_settings_and_ordered_history(tmp_path, schema):
    instance, ids = _legacy(tmp_path, schema)
    before = {
        r["path"]: r
        for r in tree_inventory(instance.root)
        if not r["path"].startswith(("indexes/", "library/"))
        and r["path"] not in {"provelume.yml", "instance-manifest.json"}
    }
    config_before = instance.store.read_config()
    manager = InstanceLifecycleManager(instance.store)
    result = manager.prepare(migrate_objects=True)
    assert result["status"] == "migrated"
    assert verify_backup(result["backup"]["archive"])["instance_schema_version"] == schema
    assert result["migration"]["promoted_hierarchy_ids"] == sorted(ids)
    after = {r["path"]: r for r in tree_inventory(instance.root)}
    assert all(after[path] == row for path, row in before.items())
    assert {**instance.store.read_config(), "schema_version": schema} == config_before
    if schema == 2:
        assert instance.store.read_manifest()["operator_extension"] == {
            "synthetic_preference": "retained"
        }
    assert {v["id"] for v in instance.store.list_canonical("objects")} == set(ids)
    migrations = instance.store.read_manifest()["migrations"]
    assert [m["id"] for m in migrations] == (
        [MIGRATION_1_TO_2, MIGRATION_2_TO_3] if schema == 1 else [MIGRATION_2_TO_3]
    )
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    stable = tree_inventory(instance.root)
    assert manager.prepare(migrate_objects=True)["status"] == "ready"
    assert tree_inventory(instance.root) == stable


def test_hierarchy_updates_one_identity_with_immutable_object_history(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    project = instance.create_hierarchy_node("project", "Before")
    first = instance.store.read_canonical("objects", project["id"])
    instance.rename_hierarchy_node(project["id"], "After")
    current = instance.store.read_canonical("objects", project["id"])
    assert current["id"] == first["id"] and current["title"] == "After"
    assert current["previous_sha256"] == record_digest(first)
    assert current["revision"] == 2
    assert (
        instance.store.read_canonical("object-revisions", revision_record(first)["id"])["record"]
        == first
    )
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_stale_object_write_refuses_all_evidence_and_revision_side_effects(tmp_path):
    store = ProvelumeInstance.initialise(tmp_path / "instance").store
    first = _entity(store)
    _persist(store, first)
    second = {**first, "revision": 2, "previous_sha256": record_digest(first), "title": "Second"}
    _persist(store, second, expected=record_digest(first))
    before = tree_inventory(store.paths.root)
    with pytest.raises(KnowledgeObjectError):
        _persist(store, {**second, "title": "Stale writer"}, expected=record_digest(first))
    assert tree_inventory(store.paths.root) == before
    assert inspect_instance(store.paths.root, deep=True)["status"] == "valid"


@pytest.mark.parametrize("damage", ["cycle", "stale", "dangling", "wrong_type"])
def test_relation_write_rejects_invalid_graph_or_revision_before_mutation(tmp_path, damage):
    store = ProvelumeInstance.initialise(tmp_path / "instance").store
    first, second = _entity(store), _entity(store, digit="b")
    _persist(store, first)
    _persist(store, second)
    _persist(store, _relation(store, first, second, kind="depends_on"), relation=True)
    candidate = _relation(store, second, first, digit="d", kind="depends_on")
    if damage == "stale":
        newer = {**second, "revision": 2, "previous_sha256": record_digest(second)}
        _persist(store, newer, expected=record_digest(second))
    elif damage == "dangling":
        candidate["source"]["id"] = "obj_" + "f" * 32
    elif damage == "wrong_type":
        candidate["relation_type"] = "scheduled_for"
    before = tree_inventory(store.paths.root)
    with pytest.raises(KnowledgeObjectError):
        _persist(store, candidate, relation=True)
    assert tree_inventory(store.paths.root) == before


def test_legacy_hierarchy_move_cannot_create_a_cycle_through_typed_relations(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    first = instance.create_hierarchy_node("project", "First")
    second = instance.create_hierarchy_node("project", "Second")
    a, b = (instance.store.read_canonical("objects", n["id"]) for n in (first, second))
    _persist(instance.store, _relation(instance.store, a, b, kind="part_of"), relation=True)
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError):
        instance.move_hierarchy_node(second["id"], first["id"])
    assert tree_inventory(instance.root) == before


@pytest.mark.parametrize(
    "damage",
    [
        "missing_revision",
        "head_changed",
        "foreign_revision",
        "duplicate_key",
        "oversize",
        "nested",
        "wrong_filename",
    ],
)
def test_deep_inspection_rejects_corrupted_or_unbounded_object_storage(tmp_path, damage):
    store = ProvelumeInstance.initialise(tmp_path / "instance").store
    row = _entity(store)
    _persist(store, row)
    head = store.paths.canonical_dir("objects") / f"{row['id']}.json"
    revision = store.paths.canonical_dir("object-revisions") / f"{revision_record(row)['id']}.json"
    if damage == "missing_revision":
        revision.unlink()
    elif damage == "head_changed":
        store._atomic_json(head, {**row, "title": "Unrecorded mutation"})
    elif damage == "foreign_revision":
        value = json.loads(revision.read_text())
        value["record"]["instance_id"] = "inst_" + "f" * 32
        store._atomic_json(revision, value)
    elif damage == "duplicate_key":
        head.write_text('{"id":"first",' + head.read_text()[1:])
    elif damage == "oversize":
        head.write_bytes(b" " * (MAX_RECORD_BYTES + 2))
    elif damage == "nested":
        (head.parent / "unexpected").mkdir()
    else:
        head.rename(head.with_name("wrong.json"))
    before = tree_inventory(store.paths.root)
    assert inspect_instance(store.paths.root, deep=True)["status"] == "invalid"
    assert tree_inventory(store.paths.root) == before
    with pytest.raises(BackupError):
        create_backup(store)


@pytest.mark.parametrize("mode", ["include", "rebuild"])
def test_object_history_evidence_relations_survive_portable_and_backup_round_trip(tmp_path, mode):
    source = ProvelumeInstance.initialise(tmp_path / "source")
    originals = tmp_path / "originals"
    originals.mkdir()
    (originals / "source.md").write_text("# Retained evidence\n\nSynthetic.\n", encoding="utf-8")
    source.ingest(originals)
    evidence = _evidence(source.store)
    first = _entity(source.store)
    other = _entity(source.store, digit="b")
    _persist(source.store, first)
    _persist(source.store, other)
    claim = _entity(
        source.store,
        digit="e",
        kind="claim",
        state="asserted",
        body={"statement": "A synthetic attributed assertion."},
        evidence_ids=[evidence["id"]],
    )
    _persist(source.store, claim, evidence=[evidence])
    (originals / "source.md").write_text("# Later document Version\n", encoding="utf-8")
    source.ingest(originals)
    assert source.store.read_canonical("object-evidence", evidence["id"]) == evidence
    relation = {
        "schema_version": 1,
        "id": "rel_" + "c" * 32,
        "instance_id": first["instance_id"],
        "revision": 1,
        "previous_sha256": None,
        "relation_type": "relates_to",
        "source": {"id": first["id"], "revision": 1, "sha256": record_digest(first)},
        "target": {"id": other["id"], "revision": 1, "sha256": record_digest(other)},
        "state": "active",
        "evidence_ids": [],
        "created_at": TIME,
        "updated_at": TIME,
    }
    _persist(source.store, relation, relation=True)
    second = {**first, "revision": 2, "previous_sha256": record_digest(first), "title": "Edited"}
    _persist(source.store, second, expected=record_digest(first))
    source.rebuild_index()
    source.rebuild_library()
    expected = {
        r["path"]: r for r in tree_inventory(source.root) if r["path"].startswith("knowledge/")
    }
    original_fp = source.validate_instance()["content_fingerprint"]
    source.export_portable(tmp_path / "portable.zip", derived_state=mode)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    imported = target.import_portable(tmp_path / "portable.zip")
    assert imported["content_fingerprint"] == original_fp
    assert {
        r["path"]: r for r in tree_inventory(target.root) if r["path"].startswith("knowledge/")
    } == expected
    backup = target.backup()
    _persist(target.store, _entity(target.store, digit="d"))
    restored = target.restore(backup["archive"])
    assert restored["content_fingerprint"] == original_fp
    assert (
        verify_backup(restored["rollback_backup"]["archive"])["content_fingerprint"] != original_fp
    )


def test_interrupted_atomic_object_write_is_recovered_before_next_hierarchy_writer(
    tmp_path, monkeypatch
):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    original = atomic_commit.AtomicInstanceCommit._publish_entries

    def interrupted(self, stage, manifest, flushers):
        replace = self._replace

        def stop(source, target):
            replace(source, target)
            raise KeyboardInterrupt("synthetic process death after one canonical replacement")

        self._replace = stop
        original(self, stage, manifest, flushers)

    monkeypatch.setattr(atomic_commit.AtomicInstanceCommit, "_publish_entries", interrupted)
    with pytest.raises(KeyboardInterrupt):
        instance.create_hierarchy_node("project", "Interrupted")
    monkeypatch.setattr(atomic_commit.AtomicInstanceCommit, "_publish_entries", original)
    assert inspect_instance(instance.root, deep=True)["status"] == "invalid"
    live = instance.create_hierarchy_node("project", "After recovery")
    assert [v["id"] for v in instance.store.list_canonical("objects")] == [live["id"]]
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


@pytest.mark.parametrize("damage", ["missing", "wrong_document", "altered_original"])
def test_new_evidence_must_bind_retained_original_bytes_before_any_write(tmp_path, damage):
    instance, _ = _legacy(tmp_path)
    InstanceLifecycleManager(instance.store).prepare(migrate_objects=True)
    ev = _evidence(instance.store)
    if damage == "missing":
        ev["version_id"] = "ver_" + "f" * 32
    elif damage == "wrong_document":
        ev["document_id"] = "doc_" + "f" * 32
    else:
        original = instance.store.read_canonical("originals", ev["original_id"])
        (instance.root / original["storage_ref"]).write_bytes(b"tampered")
    ev["id"] = "evd_" + record_digest({k: v for k, v in ev.items() if k != "id"})
    row = _entity(instance.store, evidence_ids=[ev["id"]])
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError):
        _persist(instance.store, row, evidence=[ev])
    assert tree_inventory(instance.root) == before


def test_explicit_document_purge_keeps_attribution_as_unavailable_without_retargeting(tmp_path):
    instance, _ = _legacy(tmp_path)
    InstanceLifecycleManager(instance.store).prepare(migrate_objects=True)
    ev = _evidence(instance.store)
    row = _entity(
        instance.store,
        kind="claim",
        state="asserted",
        evidence_ids=[ev["id"]],
        body={"statement": "Synthetic attributed statement, not verified truth."},
    )
    _persist(instance.store, row, evidence=[ev])
    instance.trash_document(ev["document_id"])
    preview = instance.purge_document_preview(ev["document_id"])
    instance.purge_document(
        ev["document_id"], preview["confirmation_token"], acknowledge_boundaries=True
    )
    assert instance.store.read_canonical("object-evidence", ev["id"]) == ev
    assert instance.store.read_canonical("objects", row["id"]) == row
    report = inspect_instance(instance.root, deep=True)
    assert report["status"] == "valid"
    assert "object_evidence_unavailable" in {w["code"] for w in report["warnings"]}


@pytest.mark.parametrize("phase", ["before_publish", "between_renames", "after_publish"])
def test_real_process_death_settles_bound_image_without_replaying_migration(tmp_path, phase):
    instance, ids = _legacy(tmp_path)
    script = """
import os, sys
from pathlib import Path
from provelume import instance_lifecycle
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.storage import InstanceStore
root = Path(sys.argv[1])
phase = sys.argv[2]
real = instance_lifecycle.os.replace
def stop(source, target):
    source, target = Path(source), Path(target)
    if source == root and phase == "before_publish":
        os._exit(73)
    real(source, target)
    if source == root and phase == "between_renames":
        os._exit(73)
    if target == root and ".restore-stage-" in source.name and phase == "after_publish":
        os._exit(73)
instance_lifecycle.os.replace = stop
InstanceLifecycleManager(InstanceStore(root)).prepare(migrate_objects=True)
"""
    child = subprocess.run([sys.executable, "-c", script, str(instance.root), phase], timeout=60)
    assert child.returncode == 73
    manager = InstanceLifecycleManager(InstanceStore(instance.root))
    assert manager.pending_path.is_file()
    recovered = manager.prepare(allow_legacy=True)
    assert recovered["recovery"]["status"] == "recovered"
    expected_schema = 3 if phase == "after_publish" else 2
    assert recovered["instance_schema_version"] == expected_schema
    assert not manager.pending_path.exists()
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    if expected_schema == 3:
        assert {v["id"] for v in manager.store.list_canonical("objects")} == set(ids)
    stable = tree_inventory(instance.root)
    manager.prepare(allow_legacy=True)
    assert tree_inventory(instance.root) == stable


@pytest.mark.parametrize("foreign", [False, True])
def test_migration_recovery_refuses_newer_or_foreign_root_and_preserves_pending(
    tmp_path, monkeypatch, foreign
):
    instance, _ = _legacy(tmp_path)
    real = InstanceLifecycleManager._replace_from_archive

    def interrupted(manager, archive, **kwargs):
        real(manager, archive, **kwargs)
        raise KeyboardInterrupt("synthetic process termination after publication")

    monkeypatch.setattr(InstanceLifecycleManager, "_replace_from_archive", interrupted)
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(KeyboardInterrupt):
        manager.prepare(migrate_objects=True)
    monkeypatch.setattr(InstanceLifecycleManager, "_replace_from_archive", real)
    if foreign:
        replacement = ProvelumeInstance.initialise(tmp_path / "foreign")
        shutil.rmtree(instance.root)
        shutil.copytree(replacement.root, instance.root)
    else:
        (instance.root / "state" / "after-crash.txt").write_text("retain newer bytes")
    before = tree_inventory(instance.root)
    pending = manager.pending_path.read_bytes()
    with pytest.raises(InstanceLifecycleError, match="changed or foreign"):
        manager.prepare()
    assert tree_inventory(instance.root) == before
    assert manager.pending_path.read_bytes() == pending


def test_changed_source_before_publication_is_preserved_and_cannot_be_blindly_rolled_back(
    tmp_path, monkeypatch
):
    instance, _ = _legacy(tmp_path)
    original = object_migration.upgrade_objects_stage

    def concurrent_writer(*args, **kwargs):
        result = original(*args, **kwargs)
        (instance.root / "state" / "uncooperative-writer.txt").write_text("newer settings")
        return result

    monkeypatch.setattr(object_migration, "upgrade_objects_stage", concurrent_writer)
    manager = InstanceLifecycleManager(instance.store)
    with pytest.raises(InstanceLifecycleError, match="source image changed"):
        manager.prepare(migrate_objects=True)
    assert (instance.root / "state" / "uncooperative-writer.txt").read_text() == "newer settings"
    assert instance.store.read_config()["schema_version"] == 2
    assert manager.pending_path.is_file()


def test_explicit_backup_rollback_retains_later_changes_in_a_separate_archive(tmp_path):
    instance, _ = _legacy(tmp_path)
    manager = InstanceLifecycleManager(instance.store)
    migrated = manager.prepare(migrate_objects=True)
    _persist(instance.store, _entity(instance.store))
    later_fp = manager.validate()["content_fingerprint"]
    restored = manager.restore(migrated["backup"]["archive"], preserve_source_schema=True)
    assert restored["instance_schema_version"] == 2
    assert verify_backup(restored["rollback_backup"]["archive"])["content_fingerprint"] == later_fp
    assert not instance.store.list_canonical("objects")
    with pytest.raises(InstanceLifecycleError, match="explicit object migration"):
        ProvelumeInstance(instance.root)


def test_failed_publication_and_failed_rollback_retain_the_only_previous_directory(
    tmp_path, monkeypatch
):
    import os
    from pathlib import Path

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = InstanceLifecycleManager(instance.store)
    backup = manager.backup()
    (instance.root / "state" / "retain.txt").write_bytes(b"latest preimage")
    before = tree_inventory(instance.root)
    replace = os.replace

    def failed_renames(source, target):
        if Path(target) == instance.root and any(
            part in Path(source).name for part in (".restore-stage-", ".restore-previous-")
        ):
            raise OSError("synthetic replacement and rollback failure")
        replace(source, target)

    monkeypatch.setattr(os, "replace", failed_renames)
    with pytest.raises(OSError):
        manager._replace_from_archive(
            Path(backup["archive"]), expected_instance_id=backup["instance_id"]
        )
    assert not instance.root.exists()
    previous = list(instance.root.parent.glob(".instance.restore-previous-*"))
    assert len(previous) == 1
    assert tree_inventory(previous[0]) == before


def test_unrepresentable_legacy_hierarchy_is_rejected_without_inventing_identity_or_time(tmp_path):
    instance, ids = _legacy(tmp_path)
    path = instance.store.paths.canonical_dir("hierarchy") / f"{ids[0]}.json"
    value = json.loads(path.read_text())
    value["created_at"] = "legacy opaque time"
    instance.store._atomic_json(path, value)
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    before = {row["path"]: row for row in tree_inventory(instance.root)}
    with pytest.raises(InstanceLifecycleError, match="pre-migration image was retained"):
        InstanceLifecycleManager(instance.store).prepare(migrate_objects=True)
    after = {row["path"]: row for row in tree_inventory(instance.root)}
    assert all(after[path] == row for path, row in before.items())
    assert instance.store.read_config()["schema_version"] == 2


def test_frozen_operator_explicit_migration_and_backup_rollback_without_gui_or_server(
    tmp_path, monkeypatch
):
    from provelume import desktop
    from provelume.shell_settings import default_settings

    instance, _ = _legacy(tmp_path)
    monkeypatch.setattr(desktop, "load_settings", default_settings)
    monkeypatch.setattr(desktop, "run_ui", lambda **kw: pytest.fail("operator command opened GUI"))
    monkeypatch.setattr(desktop.uvicorn, "run", lambda *a, **kw: pytest.fail("unexpected server"))
    with pytest.raises(InstanceLifecycleError, match="explicit object migration"):
        desktop.main(["--serve", str(instance.root), "--port", "8123"])
    before = tree_inventory(instance.root)
    validate = tmp_path / "validate.json"
    assert (
        desktop.main(
            [
                "--instance-result-file",
                str(validate),
                "--instance-command",
                "validate",
                str(instance.root),
            ]
        )
        == 0
    )
    assert json.loads(validate.read_text())["migration_required"] is True
    assert tree_inventory(instance.root) == before
    result = tmp_path / "migration.json"
    assert (
        desktop.main(
            [
                "--instance-result-file",
                str(result),
                "--instance-command",
                "migrate",
                str(instance.root),
            ]
        )
        == 0
    )
    migration = json.loads(result.read_text())
    assert migration["status"] == "migrated" and migration["instance_schema_version"] == 3
    assert ProvelumeInstance(instance.root).instance_summary()["schema_version"] == 3
    backup_result = tmp_path / "backup-result.json"
    assert (
        desktop.main(
            [
                "--instance-result-file",
                str(backup_result),
                "--instance-command",
                "backup",
                str(instance.root),
            ]
        )
        == 0
    )
    assert verify_backup(json.loads(backup_result.read_text())["archive"])["status"] == "valid"
    _persist(instance.store, _entity(instance.store))
    later = inspect_instance(instance.root, deep=True)["content_fingerprint"]
    restore = tmp_path / "restore.json"
    assert (
        desktop.main(
            [
                "--instance-result-file",
                str(restore),
                "--instance-command",
                "restore",
                str(instance.root),
                migration["backup"]["archive"],
                "--preserve-source-schema",
            ]
        )
        == 0
    )
    restored = json.loads(restore.read_text())
    assert restored["instance_schema_version"] == 2
    assert verify_backup(restored["rollback_backup"]["archive"])["content_fingerprint"] == later


@pytest.mark.parametrize("destination", ["inside_instance", "existing_file", "missing_parent"])
def test_frozen_operator_requires_a_new_external_report_before_mutating(tmp_path, destination):
    from provelume.desktop import main

    instance, _ = _legacy(tmp_path)
    report = tmp_path / "result.json"
    if destination == "inside_instance":
        report = instance.root / "result.json"
    elif destination == "existing_file":
        report.write_bytes(b"retained prior receipt")
    else:
        report = tmp_path / "absent" / "result.json"
    before = tree_inventory(instance.root)
    assert (
        main(
            [
                "--instance-result-file",
                str(report),
                "--instance-command",
                "migrate",
                str(instance.root),
            ]
        )
        == 2
    )
    assert tree_inventory(instance.root) == before
    if destination == "existing_file":
        assert report.read_bytes() == b"retained prior receipt"


@pytest.mark.parametrize("arguments", [["serve", "instance"], ["check-update"], []])
def test_frozen_operator_cannot_dispatch_unrelated_commands(tmp_path, arguments):
    from provelume.desktop import main

    report = tmp_path / "result.json"
    assert main(["--instance-result-file", str(report), "--instance-command", *arguments]) == 2
    assert not report.exists()
