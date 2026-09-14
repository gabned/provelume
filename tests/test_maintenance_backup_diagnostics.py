from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile

import pytest

from provelume.instance_backup import create_backup, verify_backup
from provelume.maintenance_backups import BackupVerificationService
from provelume.maintenance_diagnostics import DiagnosticExportService
from provelume.maintenance_local_files import MaintenanceTargetError, absolute_local_path
from provelume.maintenance_targets import LocalTargetRegistry
from provelume.storage import InstanceStore


@pytest.fixture
def selected(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    archive = tmp_path / "backup.zip"
    create_backup(store, destination=archive)
    target = LocalTargetRegistry(store).register_archive(archive)
    return store, archive, target


def parameters(target):
    return {key: target[key] for key in ("target_ref", "target_revision")}


def test_exact_backup_plan_restart_and_stream_facade(selected):
    store, archive, target = selected
    before = {
        p.relative_to(store.paths.root): p.read_bytes()
        for p in store.paths.root.rglob("*")
        if p.is_file()
    }
    plan = BackupVerificationService(store).plan(parameters(target))
    result = BackupVerificationService(InstanceStore(store.paths.root)).verify(plan)
    assert result["status"] == "verified"
    assert result["archive_sha256"] == verify_backup(archive)["archive_sha256"]
    assert result["instance_id"] == target["instance_id"]
    assert str(archive) not in json.dumps([target, plan, result])
    assert "archive" not in result
    assert {
        p.relative_to(store.paths.root): p.read_bytes()
        for p in store.paths.root.rglob("*")
        if p.is_file()
    } == before


def test_replaced_archive_cannot_satisfy_original_plan(selected):
    store, archive, target = selected
    plan = BackupVerificationService(store).plan(parameters(target))
    raw = archive.read_bytes()
    archive.unlink()
    archive.write_bytes(raw)
    with pytest.raises(MaintenanceTargetError, match="target_stale"):
        BackupVerificationService(store).verify(plan)


def test_modified_archive_and_revocation_are_closed(selected):
    store, archive, target = selected
    plan = BackupVerificationService(store).plan(parameters(target))
    archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(MaintenanceTargetError, match="target_stale"):
        BackupVerificationService(store).verify(plan)
    result = LocalTargetRegistry(store).revoke(target["target_ref"], target["target_revision"])
    assert not result["file_deleted"] and archive.exists()
    with pytest.raises(MaintenanceTargetError, match="target_missing"):
        BackupVerificationService(store).verify(plan)


def test_foreign_instance_archive_never_becomes_this_instances_proof(selected, tmp_path):
    store, archive, _ = selected
    foreign = InstanceStore.initialise(tmp_path / "foreign")
    target = LocalTargetRegistry(foreign).register_archive(archive)
    with pytest.raises(MaintenanceTargetError, match="instance_mismatch"):
        BackupVerificationService(foreign).plan(parameters(target))
    assert store.read_config()["instance"]["id"] != foreign.read_config()["instance"]["id"]


@pytest.mark.parametrize(
    "value",
    [
        "relative.zip",
        "https://example.invalid/archive",
        "//host/share/backup.zip",
        "\\\\host\\share\\backup.zip",
    ],
)
def test_external_and_relative_selections_are_rejected(value):
    with pytest.raises(MaintenanceTargetError):
        absolute_local_path(value)


def test_linked_archive_parent_is_rejected(selected, tmp_path):
    store, archive, _ = selected
    link = tmp_path / "linked"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"local symlink capability unavailable: {type(exc).__name__}")
    with pytest.raises(MaintenanceTargetError):
        LocalTargetRegistry(store).register_archive(link / archive.name)


def test_backup_payload_verification_is_not_claimed_by_plan(selected, tmp_path):
    store, archive, _ = selected
    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(damaged, "w") as output:
        changed = False
        for info in source.infolist():
            data = source.read(info)
            if info.filename.startswith("payload/") and data and not changed:
                data = bytes([data[0] ^ 1]) + data[1:]
                changed = True
            output.writestr(info, data)
    assert changed
    target = LocalTargetRegistry(store).register_archive(damaged)
    plan = BackupVerificationService(store).plan(parameters(target))
    assert "status" not in plan
    with pytest.raises(MaintenanceTargetError, match="archive_invalid"):
        BackupVerificationService(store).verify(plan)


def test_reviewed_diagnostics_are_stable_and_replay_exact(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    service = DiagnosticExportService(store)
    plan = service.preview(["operations_summary"])
    # Later producer changes cannot change the already reviewed bytes.
    operations = store.paths.state / "operations/records"
    operations.mkdir(parents=True, exist_ok=True)
    (operations / "op_bad.json").write_text("{invalid", encoding="utf-8")
    target = LocalTargetRegistry(store).register_output(tmp_path / "diagnostics.zip")
    result = DiagnosticExportService(store).export(
        plan["plan_ref"],
        plan["revision"],
        target["target_ref"],
        target["target_revision"],
        confirm=True,
        request_key="first",
    )
    replay = DiagnosticExportService(store).export(
        plan["plan_ref"],
        plan["revision"],
        target["target_ref"],
        target["target_revision"],
        confirm=True,
        request_key="first",
    )
    assert replay["replayed"] and {k: v for k, v in replay.items() if k != "replayed"} == {
        k: v for k, v in result.items() if k != "replayed"
    }
    with zipfile.ZipFile(tmp_path / "diagnostics.zip") as archive:
        payload = json.loads(archive.read("operations_summary.json"))
        manifest = json.loads(archive.read("manifest.json"))
    assert payload["coverage"] == "unavailable"
    assert manifest["observed_at"] == plan["observed_at"]
    assert manifest["not_a_backup"]
    assert service.preview(["operations_summary"])["coverage"] == {"operations_summary": "partial"}


def test_diagnostic_redaction_omits_every_operation_free_text(tmp_path):
    from provelume.operations import OperationLedger

    store = InstanceStore.initialise(tmp_path / "instance")
    ledger = OperationLedger(store)
    marker = "PRIVATE_SENTINEL_CREDENTIAL_PATH_TITLE"
    operation = ledger.start(kind=marker, title=marker, related={"secret": marker})
    ledger.append(operation.id, marker, marker, details={"secret": marker})
    ledger.close(operation.id, status="failed", summary=marker, error_code=marker, error=marker)
    plan = DiagnosticExportService(store).preview(["operations_summary"])
    target = LocalTargetRegistry(store).register_output(tmp_path / "diagnostics.zip")
    result = DiagnosticExportService(store).export(
        plan["plan_ref"],
        plan["revision"],
        target["target_ref"],
        target["target_revision"],
        confirm=True,
        request_key="export",
    )
    with zipfile.ZipFile(tmp_path / "diagnostics.zip") as archive:
        assert all(marker.encode() not in archive.read(name) for name in archive.namelist())
    assert marker not in json.dumps([plan, result])


def test_existing_export_and_wrong_confirmation_do_not_write(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    service = DiagnosticExportService(store)
    plan = service.preview(["build"])
    path = tmp_path / "export.zip"
    target = LocalTargetRegistry(store).register_output(path)
    with pytest.raises(MaintenanceTargetError, match="invalid_input"):
        service.export(
            plan["plan_ref"],
            plan["revision"],
            target["target_ref"],
            target["target_revision"],
            confirm=1,
            request_key="bad",
        )
    assert not path.exists()
    path.write_bytes(b"unrelated")
    with pytest.raises(MaintenanceTargetError, match="output_exists"):
        service.export(
            plan["plan_ref"],
            plan["revision"],
            target["target_ref"],
            target["target_revision"],
            confirm=True,
            request_key="ok",
        )
    assert path.read_bytes() == b"unrelated"


def test_registry_state_outside_backup_and_explicit_metadata_forgetting(selected):
    store, _, _ = selected
    registry = LocalTargetRegistry(store)
    assert not registry.root.is_relative_to(store.paths.root)
    service = DiagnosticExportService(store)
    plan = service.preview(["build"])
    result = service.forget(plan["plan_ref"], plan["revision"], confirm=True)
    assert not result["exported_files_deleted"]
    with pytest.raises(MaintenanceTargetError, match="target_missing"):
        service.forget(plan["plan_ref"], plan["revision"], confirm=True)


def test_real_process_registry_contention_preserves_selected_archive(selected):
    store, archive, target = selected
    raw = archive.read_bytes()
    script = (
        "import sys; from provelume.storage import InstanceStore; "
        "from provelume.maintenance_targets import LocalTargetRegistry; "
        "r=LocalTargetRegistry(InstanceStore(sys.argv[1])); "
        "guard=r.hold(); guard.__enter__(); print('held',flush=True); "
        "sys.stdin.readline(); guard.__exit__(None,None,None)"
    )
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", script, str(store.paths.root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert child.stdout.readline().strip() == "held"
        with pytest.raises(MaintenanceTargetError, match="busy"):
            LocalTargetRegistry(store).revoke(target["target_ref"], target["target_revision"])
    finally:
        _, errors = child.communicate("release\n", timeout=10)
    assert child.returncode == 0, errors
    assert archive.read_bytes() == raw
    assert (
        BackupVerificationService(store).plan(parameters(target))["archive_sha256"]
        == target["archive_sha256"]
    )


def test_open_archive_handle_rejects_or_detects_mutation(selected, monkeypatch):
    import provelume.maintenance_backups as module

    store, archive, target = selected
    service = BackupVerificationService(store)
    plan = service.plan(parameters(target))
    original = module.inspect_backup_stream
    observed = []

    def competing_write(handle, **kwargs):
        result = original(handle, **kwargs)
        try:
            with archive.open("r+b") as writer:
                writer.seek(0)
                writer.write(b"XX")
                writer.flush()
                os.fsync(writer.fileno())
        except PermissionError:
            observed.append("denied")
        else:
            observed.append("changed")
        return result

    monkeypatch.setattr(module, "inspect_backup_stream", competing_write)
    if os.name == "nt":
        assert service.verify(plan)["status"] == "verified"
        assert observed == ["denied"]
    else:
        with pytest.raises(MaintenanceTargetError, match="target_stale"):
            service.verify(plan)
        assert observed == ["changed"]


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse boundary")
def test_windows_junction_and_device_selections_are_rejected(selected, tmp_path):
    import _winapi

    store, archive, _ = selected
    link = tmp_path / "junction"
    _winapi.CreateJunction(str(tmp_path), str(link))
    with pytest.raises(MaintenanceTargetError, match="target_unsafe"):
        LocalTargetRegistry(store).register_archive(link / archive.name)
    for name in ("NUL", "COM1.txt", "trailing.", "trailing "):
        with pytest.raises(MaintenanceTargetError, match="target_unsafe"):
            absolute_local_path(tmp_path / name)


def test_output_parent_replacement_cannot_publish_to_new_directory(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    parent = tmp_path / "selected"
    parent.mkdir()
    target = LocalTargetRegistry(store).register_output(parent / "diagnostics.zip")
    parent.rename(tmp_path / "old")
    parent.mkdir()
    service = DiagnosticExportService(store)
    plan = service.preview(["build"])
    with pytest.raises(MaintenanceTargetError, match="target_stale"):
        service.export(
            plan["plan_ref"],
            plan["revision"],
            target["target_ref"],
            target["target_revision"],
            confirm=True,
            request_key="stale",
        )
    assert not list(parent.iterdir())


def test_tampered_private_diagnostic_projection_cannot_export_content(tmp_path):
    from provelume.maintenance_targets import canonical_bytes, revision

    store = InstanceStore.initialise(tmp_path / "instance")
    service = DiagnosticExportService(store)
    plan = service.preview(["build"])
    path = service._path(plan["plan_ref"])
    value = json.loads(path.read_bytes())
    value["snapshot"]["categories"]["build"]["secret"] = "PRIVATE_SENTINEL"
    value["revision"] = revision(value["snapshot"])
    path.write_bytes(canonical_bytes(value))
    target = LocalTargetRegistry(store).register_output(tmp_path / "diagnostics.zip")
    with pytest.raises(MaintenanceTargetError, match="invalid_private_state"):
        service.export(
            plan["plan_ref"],
            value["revision"],
            target["target_ref"],
            target["target_revision"],
            confirm=True,
            request_key="tampered",
        )
    assert not (tmp_path / "diagnostics.zip").exists()


def test_export_receipt_interruption_remains_explicit_and_never_overwrites(tmp_path, monkeypatch):
    import provelume.maintenance_diagnostics as module

    store = InstanceStore.initialise(tmp_path / "instance")
    service = DiagnosticExportService(store)
    plan = service.preview(["build"])
    target = LocalTargetRegistry(store).register_output(tmp_path / "diagnostics.zip")
    original = module.write_local_bytes
    count = 0

    def fail_final_receipt(path, raw, **kwargs):
        nonlocal count
        if path == service._path(plan["plan_ref"]):
            count += 1
            if count == 2:
                raise OSError("synthetic receipt interruption")
        return original(path, raw, **kwargs)

    monkeypatch.setattr(module, "write_local_bytes", fail_final_receipt)
    args = (plan["plan_ref"], plan["revision"], target["target_ref"], target["target_revision"])
    with pytest.raises(MaintenanceTargetError, match="export_outcome_uncertain"):
        service.export(*args, confirm=True, request_key="interrupted")
    raw = (tmp_path / "diagnostics.zip").read_bytes()
    with pytest.raises(MaintenanceTargetError, match="export_outcome_uncertain"):
        DiagnosticExportService(store).export(*args, confirm=True, request_key="interrupted")
    assert (tmp_path / "diagnostics.zip").read_bytes() == raw


def test_partial_record_bound_and_explicit_plan_capacity_recovery(tmp_path):
    from provelume.maintenance_diagnostics import MAX_PLANS, MAX_RECORDS

    store = InstanceStore.initialise(tmp_path / "instance")
    folder = store.paths.state / "operations/records"
    folder.mkdir(parents=True)
    for n in range(MAX_RECORDS + 1):
        (folder / f"invalid{n}.json").write_text("{}", encoding="utf-8")
    service = DiagnosticExportService(store)
    plans = [service.preview(["operations_summary"]) for _ in range(MAX_PLANS)]
    assert all(p["coverage"] == {"operations_summary": "partial"} for p in plans)
    with pytest.raises(MaintenanceTargetError, match="diagnostic_capacity"):
        service.preview(["operations_summary"])
    service.forget(plans[0]["plan_ref"], plans[0]["revision"], confirm=True)
    assert service.preview(["build"])["coverage"] == {"build": "complete"}


def test_recovery_status_is_pure_and_survives_restart(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    registry = LocalTargetRegistry(store)
    assert registry.status()["targets"] == []
    assert DiagnosticExportService(store).status()["plans"] == []
    assert not registry.root.exists()
    target = registry.register_output(tmp_path / "diagnostics.zip")
    service = DiagnosticExportService(store)
    plan = service.preview(["build"])
    service.export(
        plan["plan_ref"],
        plan["revision"],
        target["target_ref"],
        target["target_revision"],
        confirm=True,
        request_key="status",
    )
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in registry.root.rglob("*") if p.is_file()
    }
    assert LocalTargetRegistry(store).status()["targets"] == [target]
    status = DiagnosticExportService(store).status()
    assert status["complete"] and status["invalid_count"] == 0
    assert status["plans"][0]["plan_ref"] == plan["plan_ref"]
    assert status["plans"][0]["receipts"][0]["state"] == "exported"
    assert str(tmp_path) not in json.dumps(status)
    assert {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in registry.root.rglob("*") if p.is_file()
    } == before


def test_default_diagnostics_use_actual_resource_producer_and_closed_build_projection(
    tmp_path, monkeypatch
):
    import provelume.about as about
    from provelume.resource_statistics import ResourceStatisticsManager
    from provelume.storage import utc_now

    store = InstanceStore.initialise(tmp_path / "instance")
    snapshot = ResourceStatisticsManager(store).capture(
        {
            "id": "job_" + "a" * 32,
            "job_kind": "maintenance.resource_snapshot",
            "scope": {"kind": "instance", "id": store.read_config()["instance"]["id"]},
            "attempts": [{"started_at": utc_now()}],
        }
    )
    marker = "PRIVATE_ABOUT_CREDENTIAL"
    monkeypatch.setattr(
        about,
        "current_about",
        lambda: {
            "version": "0.10.0",
            "commit": marker,
            "runtime": {"path": marker},
            "unknown": marker,
        },
    )
    service = DiagnosticExportService(store)
    plan = service.preview()
    assert plan["coverage"]["resources"] == "complete"
    target = LocalTargetRegistry(store).register_output(tmp_path / "diagnostics.zip")
    service.export(
        plan["plan_ref"],
        plan["revision"],
        target["target_ref"],
        target["target_revision"],
        confirm=True,
        request_key="all",
    )
    with zipfile.ZipFile(tmp_path / "diagnostics.zip") as archive:
        resources = json.loads(archive.read("resources.json"))
        assert resources["categories"] == snapshot["categories"]
        assert resources["snapshot_count"] == 1
        assert resources["source_observed_at"] == snapshot["observed_at"]
        from provelume.maintenance_targets import revision

        assert resources["source_revision"] == revision(snapshot)
        assert json.loads(archive.read("build.json")) == {
            "coverage": "complete",
            "version": "0.10.0",
            "commit": None,
        }
        assert all(marker.encode() not in archive.read(name) for name in archive.namelist())
    assert marker.encode() not in service._path(plan["plan_ref"]).read_bytes()


@pytest.mark.parametrize(
    "kind,code", [("remote", "target_remote"), ("unknown", "target_locality_unknown")]
)
def test_unaccepted_locality_stops_before_target_open(tmp_path, monkeypatch, kind, code):
    import provelume.maintenance_local_files as module

    if os.name == "nt":

        class Classifier:
            def __call__(self, anchor):
                return 4 if kind == "remote" else 0

        class Kernel:
            GetDriveTypeW = Classifier()

        monkeypatch.setattr(module.ctypes, "WinDLL", lambda *args, **kwargs: Kernel())
    else:
        from pathlib import Path

        read = Path.read_text

        def mounts(path, **kwargs):
            if str(path) == "/proc/self/mountinfo":
                filesystem = "nfs" if kind == "remote" else "unrecognised"
                return f"1 0 0:1 / / rw - {filesystem} source rw\n"
            return read(path, **kwargs)

        monkeypatch.setattr(Path, "read_text", mounts)
    with (
        pytest.raises(MaintenanceTargetError, match=code),
        module.open_local_file(tmp_path / "absent.zip"),
    ):
        pytest.fail("unaccepted filesystem was opened")


@pytest.mark.skipif(os.name != "nt", reason="Windows directory share-access boundary")
def test_windows_pinned_parent_denies_actual_rename_until_handle_closes(tmp_path):
    from provelume.maintenance_local_files import pinned_parent

    parent = tmp_path / "guarded"
    parent.mkdir()
    moved = tmp_path / "moved"
    with pinned_parent(parent / "output.zip"), pytest.raises(PermissionError) as failure:
        parent.rename(moved)
    assert failure.value.winerror == 32
    assert parent.is_dir() and not moved.exists()
    parent.rename(moved)
    assert moved.is_dir() and not parent.exists()
