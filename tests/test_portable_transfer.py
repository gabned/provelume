from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest

from provelume import portable_transfer
from provelume.cli import main
from provelume.instance_backup import create_backup, verify_backup
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.instance_validation import inspect_instance
from provelume.portable_transfer import (
    PORTABLE_MANIFEST_NAME,
    PortableInstanceTransfer,
    PortableTransferError,
    verify_portable_bundle,
)
from provelume.service import ProvelumeInstance
from provelume.storage import CANONICAL_KINDS, InstanceStore


def _seed(
    root: Path,
    *,
    name: str = "Portable fixture",
) -> ProvelumeInstance:
    source = root.parent / f"{root.name}-source"
    source.mkdir()
    (source / "guide.md").write_text(
        "# Portable guide\n\nOriginal bytes and provenance stay authoritative.\n",
        encoding="utf-8",
    )
    instance = ProvelumeInstance.initialise(root, name=name)
    instance.ingest(source, source_name="Portable source")
    document_id = instance.store.list_canonical("documents")[0]["id"]
    area = instance.create_hierarchy_node(kind="area", name="Research")
    project = instance.create_hierarchy_node(
        kind="project",
        name="Cross Platform",
        parent_id=area["id"],
    )
    collection = instance.create_hierarchy_node(
        kind="collection",
        name="Reference",
    )
    instance.classify_document(
        document_id,
        primary_node_id=project["id"],
        secondary_node_ids=[collection["id"]],
    )
    instance.archive_document(document_id)
    instance.rebuild_index()
    instance.rebuild_library()
    return instance


def _canonical_snapshot(store: InstanceStore) -> dict[str, list[dict[str, Any]]]:
    return {kind: store.list_canonical(kind) for kind in CANONICAL_KINDS}


def _original_snapshot(store: InstanceStore) -> dict[str, bytes]:
    return {
        str(item["id"]): store.original_bytes(str(item["id"]))
        for item in store.list_canonical("originals")
    }


def _bundle_parts(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read(PORTABLE_MANIFEST_NAME))
        payloads = {
            str(row["path"]): bundle.read(f"instance/{row['path']}")
            for row in manifest["entries"]
        }
    return manifest, payloads


def _manifest_id(manifest: dict[str, Any]) -> str:
    unsigned = dict(manifest)
    unsigned.pop("export_id", None)
    encoded = (
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    return "export_" + hashlib.sha256(encoded).hexdigest()


def _info(name: str, *, symlink: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = (stat.S_IFLNK | 0o777) if symlink else (stat.S_IFREG | 0o600)
    info.external_attr = mode << 16
    return info


def _write_bundle(
    path: Path,
    manifest: dict[str, Any],
    payloads: dict[str, bytes],
    *,
    symlink_path: str | None = None,
    extra: tuple[str, bytes] | None = None,
    omit: str | None = None,
    reseal: bool = True,
) -> None:
    manifest = json.loads(json.dumps(manifest))
    manifest["entries"] = sorted(manifest["entries"], key=lambda row: row["path"])
    manifest["entry_count"] = len(manifest["entries"])
    manifest["total_size_bytes"] = sum(
        int(row["size_bytes"]) for row in manifest["entries"]
    )
    if reseal:
        manifest["export_id"] = _manifest_id(manifest)
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(
            _info(PORTABLE_MANIFEST_NAME),
            (
                json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
                + "\n"
            ).encode("utf-8"),
        )
        for row in manifest["entries"]:
            selected = str(row["path"])
            if selected == omit:
                continue
            bundle.writestr(
                _info(f"instance/{selected}", symlink=selected == symlink_path),
                payloads[selected],
            )
        if extra is not None:
            bundle.writestr(_info(extra[0]), extra[1])


def _mutated_path_bundle(
    source: Path,
    output: Path,
    replacement: str,
) -> None:
    manifest, payloads = _bundle_parts(source)
    selected = next(
        row for row in manifest["entries"] if row["path"].startswith("knowledge/documents/")
    )
    original = str(selected["path"])
    selected["path"] = replacement
    payloads[replacement] = payloads.pop(original)
    _write_bundle(output, manifest, payloads)


def test_default_export_is_deterministic_readable_and_rebuild_explicit(
    tmp_path: Path,
) -> None:
    instance = _seed(tmp_path / "instance")
    (instance.root / "unacquired-local.txt").write_text(
        "outside the portable allowlist",
        encoding="utf-8",
    )
    first = instance.export_portable(tmp_path / "first.zip")
    second = instance.export_portable(tmp_path / "second.zip")

    assert first["archive_sha256"] == second["archive_sha256"]
    assert (tmp_path / "first.zip").read_bytes() == (tmp_path / "second.zip").read_bytes()
    assert first["status"] == "completed"
    assert first["network_used"] is False
    assert first["ai_used"] is False
    assert first["derived_state"] == {
        "mode": "rebuild",
        "indexes": "rebuild",
        "library": "rebuild",
        "state_artifacts": "include",
    }
    verified = verify_portable_bundle(tmp_path / "first.zip")
    manifest, _payloads = _bundle_parts(tmp_path / "first.zip")
    paths = [row["path"] for row in manifest["entries"]]
    assert verified["status"] == "valid"
    assert verified["content_fingerprint"] == instance.validate_instance()[
        "content_fingerprint"
    ]
    assert "exported_at" not in manifest
    assert "unacquired-local.txt" not in paths
    assert not any(path.startswith(("indexes/", "library/", "state/locks/")) for path in paths)
    assert any(path.startswith("state/derived/") for path in paths)
    assert manifest["omitted_prefixes"] == [
        "state/locks/",
        "indexes/",
        "library/",
    ]


def test_include_mode_preserves_current_derived_bytes(tmp_path: Path) -> None:
    source = _seed(tmp_path / "source")
    result = source.export_portable(
        tmp_path / "included.zip",
        derived_state="include",
    )
    manifest, _payloads = _bundle_parts(tmp_path / "included.zip")
    paths = [str(row["path"]) for row in manifest["entries"]]
    assert paths == sorted(paths)
    assert any(path.startswith("indexes/") for path in paths)
    assert any(path.startswith("library/") for path in paths)
    assert result["derived_state"] == {
        "mode": "include",
        "indexes": "include",
        "library": "include",
        "state_artifacts": "include",
    }

    target = ProvelumeInstance.initialise(tmp_path / "target")
    imported = target.import_portable(tmp_path / "included.zip")

    assert imported["derived_state"]["indexes"] == "included_as_exported"
    assert imported["derived_state"]["library"] == "included_as_exported"
    assert (target.root / "indexes" / "search.sqlite3").read_bytes() == (
        source.root / "indexes" / "search.sqlite3"
    ).read_bytes()
    assert (target.root / "library" / ".provelume-library.json").read_bytes() == (
        source.root / "library" / ".provelume-library.json"
    ).read_bytes()


def test_include_mode_requires_ready_derived_state(tmp_path: Path) -> None:
    instance = _seed(tmp_path / "instance")
    instance.store.paths.indexes.joinpath("search.sqlite3").unlink()

    with pytest.raises(PortableTransferError, match="requires a ready"):
        instance.export_portable(
            tmp_path / "included.zip",
            derived_state="include",
        )

    assert not (tmp_path / "included.zip").exists()


def test_include_mode_rejects_missing_derived_state(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    with pytest.raises(PortableTransferError, match="ready search index"):
        instance.export_portable(
            tmp_path / "included.zip",
            derived_state="include",
        )

    assert not (tmp_path / "included.zip").exists()


def test_import_round_trip_preserves_authoritative_state_and_rebuilds_views(
    tmp_path: Path,
) -> None:
    source = _seed(tmp_path / "source")
    expected_records = _canonical_snapshot(source.store)
    expected_originals = _original_snapshot(source.store)
    expected_validation = source.validate_instance()
    bundle = source.export_portable(tmp_path / "portable.zip")

    target = _seed(tmp_path / "target", name="Replaced target")
    replaced = target.validate_instance()
    result = target.import_portable(tmp_path / "portable.zip")
    reopened = ProvelumeInstance(target.root)

    assert result["status"] == "imported"
    assert result["instance_id"] == expected_validation["instance_id"]
    assert result["replaced_instance_id"] == replaced["instance_id"]
    assert result["archive_sha256"] == bundle["archive_sha256"]
    assert result["network_used"] is False
    assert result["ai_used"] is False
    assert _canonical_snapshot(reopened.store) == expected_records
    assert _original_snapshot(reopened.store) == expected_originals
    assert reopened.validate_instance()["content_fingerprint"] == expected_validation[
        "content_fingerprint"
    ]
    assert reopened.library_status()["status"] == "ready"
    assert (reopened.root / "indexes" / "search.sqlite3").is_file()
    assert (reopened.root / result["receipt"]).is_file()
    rollback = verify_backup(result["rollback_backup"]["archive"])
    assert rollback["instance_id"] == replaced["instance_id"]
    assert rollback["content_fingerprint"] == replaced["content_fingerprint"]


def test_export_migrates_n_minus_one_before_portable_snapshot(tmp_path: Path) -> None:
    instance = _seed(tmp_path / "instance")
    originals_before = _original_snapshot(instance.store)
    config = instance.store.read_config()
    config["schema_version"] = 1
    instance.store.write_config(config)
    instance.store.paths.manifest.unlink()

    result = PortableInstanceTransfer(InstanceStore(instance.root)).export(
        tmp_path / "migrated.zip"
    )
    verified = verify_portable_bundle(tmp_path / "migrated.zip")

    assert result["status"] == "completed"
    assert verified["instance_schema_version"] == 2
    assert InstanceStore(instance.root).read_config()["schema_version"] == 2
    assert _original_snapshot(InstanceStore(instance.root)) == originals_before
    assert list(instance.store.paths.migration_receipts.glob("*.json"))


def test_import_migrates_a_valid_n_minus_one_portable_payload_in_staging(
    tmp_path: Path,
) -> None:
    source = _seed(tmp_path / "source")
    expected_originals = _original_snapshot(source.store)
    config = source.store.read_config()
    config["schema_version"] = 1
    source.store.write_config(config)
    source.store.paths.manifest.unlink()
    validation = inspect_instance(source.root, deep=True)
    rows, omitted = portable_transfer._payload_files(
        source.store,
        derived_state="rebuild",
    )
    manifest = portable_transfer._build_manifest(
        validation=validation,
        derived_state="rebuild",
        rows=rows,
        omitted_files=omitted,
    )
    portable_transfer._write_bundle(tmp_path / "legacy.zip", manifest, rows)

    target = ProvelumeInstance.initialise(tmp_path / "target")
    imported = target.import_portable(tmp_path / "legacy.zip")
    migrated_backup = Path(imported["migration"]["backup"]["archive"])

    assert imported["migration"]["status"] == "migrated"
    assert migrated_backup.is_file()
    assert verify_backup(migrated_backup)["instance_schema_version"] == 1
    assert inspect_instance(target.root, deep=True)["instance_schema_version"] == 2
    assert _original_snapshot(InstanceStore(target.root)) == expected_originals


@pytest.mark.parametrize(
    "replacement",
    (
        "../escape.json",
        "/absolute.json",
        "C:/absolute.json",
        "knowledge\\documents\\escape.json",
        "knowledge/documents/CON.json",
        "knowledge/documents/CON .json",
        "knowledge/documents/COM¹.txt",
        "knowledge/documents/trailing..json.",
        "knowledge/documents/e\u0301.json",
    ),
)
def test_verify_rejects_nonportable_or_reserved_paths(
    tmp_path: Path,
    replacement: str,
) -> None:
    instance = _seed(tmp_path / "instance")
    instance.export_portable(tmp_path / "valid.zip")
    _mutated_path_bundle(tmp_path / "valid.zip", tmp_path / "hostile.zip", replacement)

    with pytest.raises(PortableTransferError, match="path"):
        verify_portable_bundle(tmp_path / "hostile.zip")


@pytest.mark.parametrize("collision", ("case", "file_directory"))
def test_verify_rejects_cross_platform_path_collisions(
    tmp_path: Path,
    collision: str,
) -> None:
    instance = _seed(tmp_path / "instance")
    instance.export_portable(tmp_path / "valid.zip")
    manifest, payloads = _bundle_parts(tmp_path / "valid.zip")
    template = next(
        row for row in manifest["entries"] if row["path"].startswith("knowledge/documents/")
    )
    first = dict(template)
    second = dict(template)
    if collision == "case":
        first["path"] = "knowledge/documents/Portable.json"
        second["path"] = "knowledge/documents/portable.json"
    else:
        first["path"] = "knowledge/conflict"
        second["path"] = "knowledge/conflict/document.json"
    data = payloads[str(template["path"])]
    first["size_bytes"] = second["size_bytes"] = len(data)
    first["sha256"] = second["sha256"] = hashlib.sha256(data).hexdigest()
    manifest["entries"] = [
        row for row in manifest["entries"] if row is not template
    ] + [first, second]
    payloads.pop(str(template["path"]))
    payloads[str(first["path"])] = data
    payloads[str(second["path"])] = data
    _write_bundle(tmp_path / "collision.zip", manifest, payloads)

    with pytest.raises(PortableTransferError, match="collide"):
        verify_portable_bundle(tmp_path / "collision.zip")


def test_verify_rejects_symlinks_hash_mismatch_extra_and_partial_bundles(
    tmp_path: Path,
) -> None:
    instance = _seed(tmp_path / "instance")
    instance.export_portable(tmp_path / "valid.zip")
    manifest, payloads = _bundle_parts(tmp_path / "valid.zip")
    selected = str(manifest["entries"][-1]["path"])

    _write_bundle(
        tmp_path / "symlink.zip",
        manifest,
        payloads,
        symlink_path=selected,
    )
    with pytest.raises(PortableTransferError, match="special"):
        verify_portable_bundle(tmp_path / "symlink.zip")

    changed = dict(payloads)
    changed[selected] += b"tampered"
    _write_bundle(tmp_path / "hash.zip", manifest, changed)
    with pytest.raises(PortableTransferError, match="size|hash"):
        verify_portable_bundle(tmp_path / "hash.zip")

    _write_bundle(
        tmp_path / "extra.zip",
        manifest,
        payloads,
        extra=("undeclared.txt", b"surprise"),
    )
    with pytest.raises(PortableTransferError, match="count"):
        verify_portable_bundle(tmp_path / "extra.zip")

    _write_bundle(
        tmp_path / "partial.zip",
        manifest,
        payloads,
        omit=selected,
    )
    with pytest.raises(PortableTransferError, match="count"):
        verify_portable_bundle(tmp_path / "partial.zip")


def test_import_failure_after_target_move_restores_exact_previous_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _seed(tmp_path / "source")
    source.export_portable(tmp_path / "portable.zip")
    target = _seed(tmp_path / "target", name="Rollback target")
    target_before = target.validate_instance()
    records_before = _canonical_snapshot(target.store)
    originals_before = _original_snapshot(target.store)
    original_replace = os.replace

    def fail_stage_install(source_path: Any, destination_path: Any) -> None:
        source = Path(source_path)
        destination = Path(destination_path)
        if ".import-stage-" in source.name and destination == target.root:
            raise OSError("injected import install failure")
        original_replace(source_path, destination_path)

    monkeypatch.setattr(portable_transfer.os, "replace", fail_stage_install)
    with pytest.raises(PortableTransferError, match="backup was restored"):
        target.import_portable(tmp_path / "portable.zip")

    restored = inspect_instance(target.root, deep=True)
    assert restored["instance_id"] == target_before["instance_id"]
    assert restored["content_fingerprint"] == target_before["content_fingerprint"]
    assert _canonical_snapshot(InstanceStore(target.root)) == records_before
    assert _original_snapshot(InstanceStore(target.root)) == originals_before
    assert not InstanceLifecycleManager(InstanceStore(target.root)).pending_path.exists()


def test_hostile_bundle_is_rejected_before_target_backup_or_mutation(
    tmp_path: Path,
) -> None:
    source = _seed(tmp_path / "source")
    source.export_portable(tmp_path / "valid.zip")
    manifest, payloads = _bundle_parts(tmp_path / "valid.zip")
    selected = str(manifest["entries"][-1]["path"])
    payloads[selected] += b"tampered"
    _write_bundle(tmp_path / "hostile.zip", manifest, payloads)

    target = _seed(tmp_path / "target")
    before = target.validate_instance()
    records_before = _canonical_snapshot(target.store)
    lifecycle = InstanceLifecycleManager(target.store)
    backups_before = list((lifecycle.control_root / "backups").glob("*.zip"))

    with pytest.raises(PortableTransferError, match="size|hash"):
        target.import_portable(tmp_path / "hostile.zip")

    after = target.validate_instance()
    assert after["instance_id"] == before["instance_id"]
    assert after["content_fingerprint"] == before["content_fingerprint"]
    assert _canonical_snapshot(target.store) == records_before
    assert list((lifecycle.control_root / "backups").glob("*.zip")) == backups_before
    assert not lifecycle.pending_path.exists()


def test_interrupted_import_pending_record_restores_verified_target_backup(
    tmp_path: Path,
) -> None:
    target = _seed(tmp_path / "target")
    before = target.validate_instance()
    lifecycle = InstanceLifecycleManager(target.store)
    rollback = create_backup(target.store, reason="interrupted_import_test")
    lifecycle._write_pending(
        operation="import",
        rollback=rollback,
        requested_archive_sha256="a" * 64,
    )
    original = target.store.list_canonical("originals")[0]
    (target.root / original["storage_ref"]).write_bytes(b"interrupted replacement")

    recovered = InstanceLifecycleManager(InstanceStore(target.root)).prepare()
    restored = inspect_instance(target.root, deep=True)

    assert recovered["recovery"]["operation"] == "import"
    assert recovered["recovery"]["action"] == "restored_verified_pre_operation_backup"
    assert restored["instance_id"] == before["instance_id"]
    assert restored["content_fingerprint"] == before["content_fingerprint"]


def test_import_rejects_bundle_inside_target_without_mutation(tmp_path: Path) -> None:
    source = _seed(tmp_path / "source")
    source.export_portable(tmp_path / "external.zip")
    target = _seed(tmp_path / "target")
    before = target.validate_instance()
    inside = target.root / "portable.zip"
    shutil.copyfile(tmp_path / "external.zip", inside)

    with pytest.raises(PortableTransferError, match="outside"):
        target.import_portable(inside)

    after = target.validate_instance()
    assert after["instance_id"] == before["instance_id"]
    assert after["content_fingerprint"] == before["content_fingerprint"]


def test_cli_export_and_import_match_application_service(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _seed(tmp_path / "source")
    expected = source.validate_instance()
    assert main(
        [
            "export",
            str(source.root),
            "--output",
            str(tmp_path / "cli.zip"),
        ]
    ) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["status"] == "completed"

    target = ProvelumeInstance.initialise(tmp_path / "target")
    assert main(["import", str(target.root), str(tmp_path / "cli.zip")]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["status"] == "imported"
    assert imported["content_fingerprint"] == expected["content_fingerprint"]
    assert inspect_instance(target.root, deep=True)["instance_id"] == expected[
        "instance_id"
    ]


def test_export_contract_remains_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _seed(tmp_path / "instance")

    def forbidden_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("portable transfer attempted network access")

    monkeypatch.setattr("socket.create_connection", forbidden_network)
    result = instance.export_portable(tmp_path / "offline.zip")
    target = ProvelumeInstance.initialise(tmp_path / "target")
    imported = target.import_portable(tmp_path / "offline.zip")

    assert result["network_used"] is False
    assert imported["network_used"] is False


def test_public_portable_contract_states_authority_and_boundaries() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = (root / "docs" / "architecture" / "portable-export-import.md").read_text(
        encoding="utf-8"
    )
    readme = (root / "README.md").read_text(encoding="utf-8")
    roadmap = (root / "docs" / "roadmap.md").read_text(encoding="utf-8")

    for required in (
        "Two exports of unchanged Instance bytes",
        "Configured Source, Drop and managed-copy content",
        "validates the complete portable bundle",
        "reserved device names",
        "creates and independently verifies a full pre-import target backup",
        "restores the exact previous directory or its verified backup",
        "There is no HTTP upload, export or import mutation route",
        "network_used: false",
        "ai_used: false",
    ):
        assert required in contract
    assert "provelume export" in readme
    assert "provelume import" in readme
    assert "`S01`, `S02`, `S03`, `S04` and `S05` are implemented" in roadmap
