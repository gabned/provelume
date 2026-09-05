from __future__ import annotations

import errno
import json
import os
import re
from pathlib import Path
from threading import BoundedSemaphore, Event

import pytest
from fastapi.testclient import TestClient

import provelume.folder_source_enrollment as enrollment
from provelume.cli import main
from provelume.folder_source_enrollment import (
    DIAGNOSTICS,
    FolderSourceEnrollmentError,
    classify_path,
    diagnose_os_error,
)
from provelume.folder_source_i18n import FOLDER_SOURCE_TRANSLATIONS
from provelume.service import ProvelumeInstance
from provelume.web import create_app


@pytest.fixture
def instance(tmp_path):
    return ProvelumeInstance.initialise(tmp_path / "instance", name="Enrollment fixture")


@pytest.mark.parametrize(
    "path",
    [
        "",
        "smb://server/share",
        "file:///folder",
        "C:relative",
        "\\\\server",
        "\\\\server\\",
        "\\\\?\\C:\\folder",
        "\\\\.\\NUL",
        "\\\\user@server\\share",
        "C:\\folder\\file:stream",
        "C:\\folder\\CON.txt",
        "NUL",
        "folder\\aux.txt",
        "C:\\folder\\trailing.",
        "\\folder",
        "folder\x00name",
        "folder\nname",
    ],
)
def test_unsupported_windows_selectors_fail_before_io(path):
    with pytest.raises(FolderSourceEnrollmentError) as exc:
        classify_path(path, platform="nt")
    assert exc.value.code == "unsupported_path"


@pytest.mark.parametrize(
    "path,kind",
    [
        ("C:\\Documents\\Résumé", "windows_drive"),
        ("\\\\server\\share\\folder", "unc"),
        ("//server/share/folder", "unc"),
        ("\\\\localhost\\C$\\folder", "unc"),
        ("relative-folder", "native"),
    ],
)
def test_explicit_windows_path_shapes(path, kind):
    assert classify_path(path, platform="nt") == kind


@pytest.mark.parametrize("path", ["C:\\folder", "\\\\server\\share", "//server/share"])
def test_windows_paths_are_not_silently_enrolled_as_posix_relative_paths(path):
    with pytest.raises(FolderSourceEnrollmentError) as exc:
        classify_path(path, platform="posix")
    assert exc.value.code == "unsupported_platform"


@pytest.mark.parametrize(
    "winerror,expected",
    [
        (5, "permission_denied"),
        (65, "permission_denied"),
        (53, "network_unreachable"),
        (67, "network_unreachable"),
        (1219, "windows_session_required"),
        (1312, "windows_session_required"),
        (1326, "windows_session_required"),
        (1909, "windows_session_required"),
        (123, "unsupported_path"),
    ],
)
def test_windows_error_diagnostics_are_actionable_and_redacted(winerror, expected):
    error = OSError(errno.EIO, "private-host private-user private-path")
    error.winerror = winerror
    code = diagnose_os_error(error, source_class="network", path_kind="unc")
    assert code == expected
    assert "private-" not in enrollment.diagnostic_message(code)
    assert enrollment.diagnostic_message(code, "it") != enrollment.diagnostic_message(code, "en")


def test_mapped_drive_visibility_is_distinct_from_a_missing_child():
    error = FileNotFoundError(errno.ENOENT, "redacted")
    assert (
        diagnose_os_error(
            error, source_class="network", path_kind="windows_drive", drive_visible=False
        )
        == "mapped_drive_unavailable"
    )
    assert (
        diagnose_os_error(
            error, source_class="network", path_kind="windows_drive", drive_visible=True
        )
        == "network_unreachable"
    )


@pytest.mark.parametrize(
    "source_class,code",
    [
        ("local", "path_unavailable"),
        ("removable", "mount_unavailable"),
        ("network", "network_unreachable"),
    ],
)
def test_unavailable_path_never_enrolls_or_creates_policy(instance, tmp_path, source_class, code):
    before = instance.store.read_config()
    policies = instance.scheduler.journal.list_policies()
    result = instance.validate_folder_source_path(tmp_path / "missing", source_class=source_class)
    assert result["can_enroll"] is False and result["diagnostic_code"] == code
    with pytest.raises(FolderSourceEnrollmentError) as exc:
        instance.register_folder_source(
            tmp_path / "missing", name="Missing", source_class=source_class
        )
    assert exc.value.code == code
    assert instance.store.read_config() == before
    assert instance.scheduler.journal.list_policies() == policies
    assert instance.store.list_canonical("sources") == []


def test_preview_is_read_only_and_registration_revalidates(instance, tmp_path):
    folder = tmp_path / "mounted"
    folder.mkdir()
    before = instance.store.read_config()
    assert instance.validate_folder_source_path(folder, source_class="removable")["can_enroll"]
    assert instance.store.read_config() == before
    assert instance.store.list_canonical("sources") == []
    folder.rmdir()
    with pytest.raises(FolderSourceEnrollmentError, match="Reconnect"):
        instance.register_folder_source(folder, name="Volume", source_class="removable")
    assert instance.store.list_canonical("sources") == []


def test_read_permission_is_checked_before_any_enrollment(instance, tmp_path, monkeypatch):
    folder = tmp_path / "unreadable"
    folder.mkdir()

    def denied(path):
        raise PermissionError(errno.EACCES, "private path must not be diagnosed")

    monkeypatch.setattr(enrollment.os, "scandir", denied)
    result = instance.validate_folder_source_path(folder, source_class="network")
    assert result["diagnostic_code"] == "permission_denied"
    assert "private path" not in json.dumps(result)
    assert instance.store.list_canonical("sources") == []


def test_timed_out_workers_are_bounded_read_only_and_cannot_enroll_late(
    instance,
    tmp_path,
    monkeypatch,
):
    folder = tmp_path / "slow"
    folder.mkdir()
    release = Event()
    entered = Event()
    monkeypatch.setattr(enrollment, "_VALIDATION_SLOTS", BoundedSemaphore(1))
    monkeypatch.setattr(enrollment, "VALIDATION_TIMEOUT_SECONDS", 0.03)
    original = instance.folder_sources._selected_path

    def blocked(path):
        entered.set()
        assert release.wait(3)
        return original(path)

    monkeypatch.setattr(instance.folder_sources, "_selected_path", blocked)
    try:
        assert (
            instance.validate_folder_source_path(folder)["diagnostic_code"] == "validation_timeout"
        )
        assert entered.is_set()
        assert instance.validate_folder_source_path(folder)["diagnostic_code"] == "validation_busy"
        assert instance.store.list_canonical("sources") == []
    finally:
        release.set()
    # Wait for the same read-only worker to release its slot, not a retry loop.
    assert enrollment._VALIDATION_SLOTS.acquire(timeout=3)
    enrollment._VALIDATION_SLOTS.release()
    assert instance.store.list_canonical("sources") == []
    assert instance.scheduler.journal.list_policies() == []


def test_source_identity_survives_reconnect_restart_and_reconciliation(instance, tmp_path):
    folder, detached = tmp_path / "volume", tmp_path / "detached"
    folder.mkdir()
    (folder / "note.txt").write_text("stable source identity", encoding="utf-8")
    options = dict(
        name="Volume", source_class="removable", quiescence_seconds=0, stable_observations=1
    )
    source = instance.register_folder_source(folder, **options)
    source_id = source["id"]
    assert (
        instance.refresh_folder_source(source_id, request_key="seed")["job"]["status"]
        == "succeeded"
    )
    original = instance.folder_sources.public_view(source_id)
    canonical = {
        kind: instance.store.list_canonical(kind)
        for kind in ("sources", "acquisitions", "originals", "documents", "versions")
    }
    assert len(canonical["acquisitions"]) == len(canonical["documents"]) == 1
    folder.rename(detached)
    observed = instance.observe_folder_source(source_id)
    assert observed["last_error_code"] == "mount_unavailable"
    folder_view = instance.folder_sources.local_view(source_id)
    assert folder_view["identity_fingerprint"] == original["identity_fingerprint"]
    detached.rename(folder)
    reopened = ProvelumeInstance(instance.root)
    repeated = reopened.register_folder_source(folder / ".", **options)
    assert repeated["id"] == source_id
    assert repeated["identity_fingerprint"] == original["identity_fingerprint"]
    observed = reopened.observe_folder_source(source_id)
    assert observed["pending_fingerprint"] == original["observer"]["pending_fingerprint"]
    reopened.source_reconciliation.build_plan(source_id)
    assert {kind: instance.store.list_canonical(kind) for kind in canonical} == canonical
    assert len(reopened.scheduler.journal.list_policies()) == 1


def test_invalid_schedule_and_reserved_paths_cannot_partially_enroll(instance, tmp_path):
    folder = tmp_path / "valid"
    folder.mkdir()
    with pytest.raises(ValueError):
        instance.register_folder_source(folder, name="Invalid schedule", schedule={})
    for path in (instance.root, instance.store.paths.originals, tmp_path):
        result = instance.validate_folder_source_path(path)
        assert result["diagnostic_code"] == "unsafe_path"
    assert instance.store.list_canonical("sources") == []


def test_identity_and_unavailable_diagnostics_survive_backup_and_portable_transfer(
    instance,
    tmp_path,
    monkeypatch,
):
    folder = tmp_path / "transfer-volume"
    folder.mkdir()
    source = instance.register_folder_source(folder, name="Transfer", source_class="removable")
    folder.rmdir()
    assert instance.observe_folder_source(source["id"])["last_error_code"] == "mount_unavailable"
    backup = tmp_path / "enrollment-backup.zip"
    instance.backup(destination=backup, reason="enrollment-identity")
    instance.set_folder_source_state(source["id"], "paused")
    instance.restore(backup)
    restored = ProvelumeInstance(instance.root)
    portable = tmp_path / "enrollment-portable.zip"
    restored.export_portable(portable)
    target = ProvelumeInstance.initialise(tmp_path / "imported")
    target.import_portable(portable)
    imported = ProvelumeInstance(target.root)
    for current in (restored, imported):
        view = current.folder_sources.local_view(source["id"])
        assert view["id"] == source["id"]
        assert view["identity_fingerprint"] == source["identity_fingerprint"]
        assert view["policy_id"] == source["policy_id"]
        assert view["diagnostic_code"] == "mount_unavailable"
        assert current.validate_instance()["status"] == "valid"

    def forbidden_resolution(path, *args, **kwargs):
        raise AssertionError("An inventory read must not resolve disconnected mounts")

    # Instance construction above is allowed to resolve its own root. Inventory
    # rendering after construction must use stored Source paths without probing.
    monkeypatch.setattr(Path, "resolve", forbidden_resolution)
    assert (
        imported.folder_sources.local_view(source["id"])["diagnostic_code"] == "mount_unavailable"
    )


def test_unexpected_probe_failure_never_leaks_paths_or_enrolls(instance, monkeypatch):
    def failed(path):
        raise LookupError("private-server/private-share must not escape the worker")

    monkeypatch.setattr(instance.folder_sources, "_selected_path", failed)
    checked = instance.validate_folder_source_path("valid-shape")
    assert checked["diagnostic_code"] == "validation_failed"
    assert "private-server" not in json.dumps(checked)
    assert instance.store.list_canonical("sources") == []


def test_browser_and_local_api_validate_without_writes_and_preserve_form(instance, tmp_path):
    folder = tmp_path / "browser-folder"
    folder.mkdir()
    with TestClient(create_app(instance.root)) as client:
        page = client.get("/sources?lang=it")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        fields = {
            "csrf_token": token,
            "action": "validate",
            "name": "Nome conservato",
            "path": str(folder),
            "source_class": "removable",
            "state": "paused",
            "quiescence_seconds": "17",
            "stable_observations": "3",
            "watch_interval_seconds": "",
            "timezone": "Europe/Rome",
        }
        checked = client.post("/sources?lang=it", data=fields)
        assert checked.status_code == 200
        assert "Il percorso è leggibile" in checked.text
        assert 'value="Nome conservato"' in checked.text and 'value="17"' in checked.text
        assert instance.store.list_canonical("sources") == []
        api = client.post(
            "/api/v1/folder-sources/validate?lang=it",
            data={
                "csrf_token": token,
                "path": str(folder),
                "source_class": "removable",
            },
        )
        assert api.status_code == 200 and api.json()["can_enroll"]
        assert str(tmp_path) not in api.text
        assert "Il percorso è leggibile" in api.json()["message"]
        assert (
            client.post("/api/v1/folder-sources/validate", data={"path": str(folder)}).status_code
            == 403
        )
        assert client.get("/api/v1/folder-sources/validate").status_code == 405
    with TestClient(create_app(instance.root), client=("192.0.2.1", 1234)) as remote:
        assert (
            remote.post("/api/v1/folder-sources/validate", data={"path": str(folder)}).status_code
            == 403
        )


def test_cli_validation_reports_localized_closed_diagnostics(instance, tmp_path, capsys):
    assert (
        main(
            [
                "folder-source-validate",
                str(instance.root),
                str(tmp_path / "missing"),
                "--class",
                "removable",
                "--lang",
                "it",
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["diagnostic_code"] == "mount_unavailable"
    assert "Ricollega" in result["message"] and str(tmp_path) not in json.dumps(result)
    assert instance.store.list_canonical("sources") == []


def test_enrollment_translation_and_diagnostic_parity():
    assert FOLDER_SOURCE_TRANSLATIONS["en"].keys() == FOLDER_SOURCE_TRANSLATIONS["it"].keys()
    for code, translations in DIAGNOSTICS.items():
        assert len(translations) == 2 and all(translations)
        assert enrollment.diagnostic_message(code, "en") != enrollment.diagnostic_message(
            code, "it"
        )


@pytest.mark.skipif(os.name != "nt", reason="Requires the permanent Windows filesystem matrix")
def test_real_windows_unc_enrollment_reconnect_and_instance_alias_safety(instance, tmp_path):
    folder = tmp_path / "UNC résumé"
    folder.mkdir()
    (folder / "note.txt").write_text("real Windows filesystem qualification", encoding="utf-8")
    # Use the runner's existing local administrative share and current session.
    # No share creation, credentials, firewall or LAN configuration changes.
    drive = folder.drive.rstrip(":")
    relative = str(folder.relative_to(folder.anchor))
    unc = Path(f"\\\\localhost\\{drive}$\\{relative}")
    assert unc.is_dir(), "Permanent Windows runner cannot qualify its existing local UNC share"
    options = dict(
        name="UNC fixture", source_class="network", quiescence_seconds=0, stable_observations=1
    )
    before = instance.validate_folder_source_path(unc, source_class="network")
    assert before["can_enroll"] and before["path_kind"] == "unc"
    source = instance.register_folder_source(unc, **options)
    refreshed = instance.refresh_folder_source(source["id"], request_key="unc-seed")
    assert refreshed["job"]["status"] == "succeeded"
    acquisitions = instance.store.list_canonical("acquisitions")
    assert len(acquisitions) == len(instance.store.list_canonical("documents")) == 1
    detached = tmp_path / "UNC detached"
    folder.rename(detached)
    try:
        assert instance.observe_folder_source(source["id"])["availability"] == "missing"
    finally:
        detached.rename(folder)
    assert instance.register_folder_source(unc, **options)["id"] == source["id"]
    assert instance.store.list_canonical("acquisitions") == acquisitions
    assert (
        instance.folder_sources.public_view(source["id"])["identity_fingerprint"]
        == source["identity_fingerprint"]
    )
    instance_relative = str(instance.root.relative_to(instance.root.anchor))
    alias = Path(f"\\\\localhost\\{instance.root.drive.rstrip(':')}$\\{instance_relative}")
    assert (
        instance.validate_folder_source_path(alias, source_class="network")["diagnostic_code"]
        == "unsafe_path"
    )
