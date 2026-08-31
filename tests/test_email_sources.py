from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

import provelume.email_containers as email_containers
import provelume.email_contract as email_contract
from provelume.email_contract import EmailLimits
from provelume.email_sources import (
    EmailSourceError,
    EmailSourceManager,
    EmailSourceNotFound,
)
from provelume.storage import InstanceStore


def _store_and_manager(tmp_path: Path) -> tuple[InstanceStore, EmailSourceManager]:
    store = InstanceStore.initialise(tmp_path / "instance")
    return store, EmailSourceManager(store)


def _eml(path: Path) -> bytes:
    data = b"From: sender@example.invalid\r\nSubject: synthetic\r\n\r\nbody\r\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _qualify_linux_cpython312(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        email_contract,
        "qualified_runtime_target",
        lambda: "ubuntu-24.04-x86_64-cpython312",
    )


def test_create_is_disabled_manual_path_redacted_and_has_no_hidden_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manager = _store_and_manager(tmp_path)
    message = tmp_path / "mail" / "message.eml"
    original = _eml(message)

    original_scandir = os.scandir

    def guarded_enumeration(path: object) -> object:
        if Path(path) in {message, message.parent}:
            raise AssertionError("Source configuration must not enumerate the container")
        return original_scandir(path)

    def forbidden_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Source configuration must not use the network")

    monkeypatch.setattr(os, "scandir", guarded_enumeration)
    monkeypatch.setattr(socket, "socket", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    created = manager.create(
        name="  Synthetic   EML  ",
        path=message,
        profile="eml-file-v1",
    )

    source_id = created["id"]
    assert created["name"] == "Synthetic EML"
    assert created["state"] == "disabled"
    assert created["lifecycle_state"] == "active"
    assert created["schedule"]["mode"] == "manual"
    assert created["path"] == str(message)
    assert created["autodiscovery"] is False
    assert created["automatic_activity"] is False
    assert message.read_bytes() == original

    public = manager.public_view(source_id)
    assert "path" not in public
    assert str(tmp_path) not in json.dumps(public, sort_keys=True)
    assert manager.list_public() == [public]
    assert manager.list_local() == [created]
    assert store.list_canonical("sources") == [
        {
            "created_at": created["created_at"],
            "id": source_id,
            "kind": "email",
            "name": "Synthetic EML",
        }
    ]
    assert store.read_config()["email_sources"][source_id]["state"] == "disabled"
    assert not list((store.paths.state / "scheduler/jobs").glob("*.json"))
    assert not list((store.paths.state / "email-intake").glob("**/*"))
    with pytest.raises(EmailSourceError) as caught:
        manager.source_config(source_id, require_enabled=True)
    assert caught.value.code == "email_source_disabled"


def test_state_schedule_and_tombstone_lifecycle_are_explicit(tmp_path: Path) -> None:
    store, manager = _store_and_manager(tmp_path)
    message = tmp_path / "mail" / "message.eml"
    _eml(message)
    created = manager.create(name="Mail", path=message, profile="eml-file-v1")
    source_id = created["id"]
    created_at = created["created_at"]

    enabled = manager.enable(source_id)
    assert enabled["state"] == "enabled"
    assert "path" not in enabled
    assert manager.source_config(source_id, require_enabled=True).path == message

    scheduled = manager.configure_schedule(
        source_id,
        mode="interval",
        interval_seconds=300,
    )
    assert scheduled["schedule"]["mode"] == "interval"
    assert scheduled["schedule"]["interval_seconds"] == 300
    assert scheduled["schedule"]["timezone"] == "UTC"
    paused = manager.pause(source_id)
    assert paused["state"] == "paused"
    with pytest.raises(EmailSourceError) as caught:
        manager.source_config(source_id, require_enabled=True)
    assert caught.value.code == "email_source_paused"
    assert manager.disable(source_id)["state"] == "disabled"
    manual = manager.configure_schedule(source_id, mode="manual")
    assert manual["schedule"]["mode"] == "manual"
    assert manual["schedule"]["interval_seconds"] is None

    removed = manager.remove(source_id)
    assert removed["lifecycle_state"] == "removed"
    assert removed["state"] == "disabled"
    assert removed["removed_at"] is not None
    assert removed["created_at"] == created_at
    assert "path" not in removed
    assert manager.remove(source_id) == removed
    assert manager.list_public(include_removed=False) == []
    assert manager.list_local()[0]["path"] == str(message)
    assert store.read_canonical("sources", source_id) is not None
    assert store.read_config()["email_sources"][source_id]["lifecycle_state"] == (
        "removed"
    )
    removed_capability = manager.capability(source_id)
    assert removed_capability["available"] is False
    assert removed_capability["state"] == "source-removed"
    assert removed_capability["reason"] == "email_source_removed"
    assert removed_capability["probe"] is None

    for action in (
        lambda: manager.enable(source_id),
        lambda: manager.configure_schedule(source_id, mode="manual"),
        lambda: manager.source_config(source_id),
    ):
        with pytest.raises(EmailSourceError) as caught:
            action()
        assert caught.value.code == "email_source_removed"


@pytest.mark.parametrize(
    ("mode", "interval_seconds"),
    [("interval", 59), ("calendar", None), ("manual", 300)],
)
def test_schedule_rejects_unbounded_or_implicit_modes(
    tmp_path: Path,
    mode: str,
    interval_seconds: int | None,
) -> None:
    _store, manager = _store_and_manager(tmp_path)
    message = tmp_path / "message.eml"
    _eml(message)
    source_id = manager.create(
        name="Mail", path=message, profile="eml-file-v1"
    )["id"]

    with pytest.raises(EmailSourceError):
        manager.configure_schedule(
            source_id,
            mode=mode,
            interval_seconds=interval_seconds,
        )


def test_mbox_is_reported_and_rejected_as_unsupported(tmp_path: Path) -> None:
    store, manager = _store_and_manager(tmp_path)
    report = manager.capability()
    by_profile = {item["profile"]: item for item in report["profiles"]}

    assert set(by_profile) == {"eml-file-v1", "maildir-cur-new-v1", "mbox"}
    assert by_profile["mbox"]["available"] is False
    assert by_profile["mbox"]["state"] == "format-unsupported"
    assert by_profile["mbox"]["reason"] == "email_format_unsupported"
    assert report["network_access"] == "none"
    assert report["runtime_downloads"] is False
    assert report["remote_fallback"] is False

    with pytest.raises(EmailSourceError) as caught:
        manager.create(name="mbox", path=tmp_path / "mailbox", profile="mbox")
    assert caught.value.code == "email_profile_unsupported"
    assert store.list_canonical("sources") == []
    assert "email_sources" not in store.read_config()


def test_disabled_and_paused_capability_do_not_probe_the_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, manager = _store_and_manager(tmp_path)
    missing = tmp_path / "missing.eml"
    source_id = manager.create(
        name="Missing", path=missing, profile="eml-file-v1"
    )["id"]

    def forbidden_adapter(_config: object) -> object:
        raise AssertionError("disabled or paused Sources must not be probed")

    monkeypatch.setattr(email_containers, "adapter_for_profile", forbidden_adapter)
    disabled = manager.capability(source_id)
    assert disabled["available"] is False
    assert disabled["state"] == "source-disabled"
    assert disabled["reason"] == "email_source_disabled"
    assert disabled["probe"] is None
    manager.enable(source_id)
    manager.pause(source_id)
    paused = manager.capability(source_id)
    assert paused["state"] == "source-paused"
    assert paused["reason"] == "email_source_paused"
    assert paused["probe"] is None


def test_enabled_capability_probe_is_bounded_path_free_and_effective(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _qualify_linux_cpython312(monkeypatch)

    def forbidden_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("email capability probes must remain offline")

    monkeypatch.setattr(socket, "socket", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)
    _store, manager = _store_and_manager(tmp_path)
    missing = tmp_path / "missing.eml"
    missing_id = manager.create(
        name="Missing", path=missing, profile="eml-file-v1"
    )["id"]
    manager.enable(missing_id)

    unavailable = manager.capability(missing_id, limits=EmailLimits())
    assert unavailable["available"] is False
    assert unavailable["state"] == "source-unavailable"
    assert unavailable["reason"] == "email_source_missing"
    assert unavailable["probe"]["network_attempted"] is False
    assert "path" not in unavailable["source"]
    assert str(tmp_path) not in json.dumps(unavailable, sort_keys=True)

    message = tmp_path / "mail" / "message.eml"
    _eml(message)
    ready_id = manager.create(
        name="Ready", path=message, profile="eml-file-v1"
    )["id"]
    manager.enable(ready_id)
    ready = manager.capability(ready_id)
    assert ready["available"] is True
    assert ready["state"] == "ready"
    assert ready["reason"] is None
    assert ready["adapter"]["limits"] == EmailLimits().as_record()
    assert ready["probe"]["available"] is True
    assert ready["probe"]["network_attempted"] is False
    assert manager.capability(ready_id, local=True)["source"]["path"] == str(
        message
    )


def test_maildir_capability_requires_explicit_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _qualify_linux_cpython312(monkeypatch)
    _store, manager = _store_and_manager(tmp_path)
    maildir = tmp_path / "maildir"
    for name in ("cur", "new", "tmp"):
        (maildir / name).mkdir(parents=True, exist_ok=True)
    source_id = manager.create(
        name="Maildir",
        path=maildir,
        profile="maildir-cur-new-v1",
    )["id"]

    assert manager.capability(source_id)["state"] == "source-disabled"
    manager.enable(source_id)
    ready = manager.capability(source_id)
    assert ready["available"] is True
    assert ready["adapter"]["mailbox_format"] == "maildir"
    assert ready["adapter"]["profile"] == "maildir-cur-new-v1"
    assert ready["probe"]["available"] is True


def test_source_paths_reject_instance_overlap_and_links(
    tmp_path: Path,
) -> None:
    store, manager = _store_and_manager(tmp_path)

    for unsafe in (store.paths.root, store.paths.root / "mail", tmp_path):
        with pytest.raises(EmailSourceError) as caught:
            manager.create(name="Unsafe", path=unsafe, profile="eml-file-v1")
        assert caught.value.code == "email_source_unsafe"

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(EmailSourceError) as caught:
        manager.create(
            name="Linked",
            path=linked / "message.eml",
            profile="eml-file-v1",
        )
    assert caught.value.code == "email_source_unsafe"
    assert store.list_canonical("sources") == []


def test_path_replaced_by_symlink_after_registration_fails_probe_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _qualify_linux_cpython312(monkeypatch)
    _store, manager = _store_and_manager(tmp_path)
    message = tmp_path / "message.eml"
    replacement = tmp_path / "replacement.eml"
    _eml(message)
    _eml(replacement)
    source_id = manager.create(
        name="Mutable", path=message, profile="eml-file-v1"
    )["id"]
    message.unlink()
    try:
        message.symlink_to(replacement)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    manager.enable(source_id)

    report = manager.capability(source_id)
    assert report["available"] is False
    assert report["state"] == "source-unavailable"
    assert report["reason"] == "email_source_unsafe"
    assert report["probe"] is None
    assert manager.local_view(source_id)["path"] == str(message)


def test_hardlink_and_non_regular_eml_are_not_advertised_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _qualify_linux_cpython312(monkeypatch)
    _store, manager = _store_and_manager(tmp_path)
    original = tmp_path / "original.eml"
    linked = tmp_path / "linked.eml"
    _eml(original)
    try:
        os.link(original, linked)
    except OSError:
        pytest.skip("hard links are unavailable on this platform")
    linked_id = manager.create(
        name="Hard link", path=linked, profile="eml-file-v1"
    )["id"]
    manager.enable(linked_id)
    hardlink = manager.capability(linked_id)
    assert hardlink["available"] is False
    assert hardlink["reason"] == "email_source_unsafe"

    directory = tmp_path / "directory.eml"
    directory.mkdir()
    directory_id = manager.create(
        name="Directory", path=directory, profile="eml-file-v1"
    )["id"]
    manager.enable(directory_id)
    non_regular = manager.capability(directory_id)
    assert non_regular["available"] is False
    assert non_regular["reason"] == "email_input_non_regular"


@pytest.mark.parametrize("write_then_fail", [False, True])
def test_create_compensates_config_write_failure_without_partial_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_then_fail: bool,
) -> None:
    store, manager = _store_and_manager(tmp_path)
    message = tmp_path / "message.eml"
    _eml(message)
    before = store.paths.config.read_bytes()
    original_write = store.write_config

    def failing_write(config: dict[str, object]) -> None:
        if write_then_fail:
            original_write(config)
        raise OSError("synthetic config failure")

    monkeypatch.setattr(store, "write_config", failing_write)
    with pytest.raises(OSError, match="synthetic config failure"):
        manager.create(name="Mail", path=message, profile="eml-file-v1")

    assert store.paths.config.read_bytes() == before
    assert store.list_canonical("sources") == []
    assert "email_sources" not in store.read_config()


def test_create_compensates_source_write_failure_after_exact_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manager = _store_and_manager(tmp_path)
    message = tmp_path / "message.eml"
    _eml(message)
    before = store.paths.config.read_bytes()
    original_write = store.write_source

    def failing_write(source: object) -> None:
        original_write(source)  # type: ignore[arg-type]
        raise OSError("synthetic Source failure")

    monkeypatch.setattr(store, "write_source", failing_write)
    with pytest.raises(OSError, match="synthetic Source failure"):
        manager.create(name="Mail", path=message, profile="eml-file-v1")

    assert store.paths.config.read_bytes() == before
    assert store.list_canonical("sources") == []
    assert "email_sources" not in store.read_config()


def test_missing_and_corrupt_source_identity_fail_closed(tmp_path: Path) -> None:
    store, manager = _store_and_manager(tmp_path)
    with pytest.raises(EmailSourceNotFound) as caught:
        manager.public_view("src_0123456789abcdef0123456789abcdef")
    assert caught.value.code == "email_source_missing"

    message = tmp_path / "message.eml"
    _eml(message)
    source_id = manager.create(
        name="Mail", path=message, profile="eml-file-v1"
    )["id"]
    config = store.read_config()
    config["email_sources"][source_id]["profile"] = "mbox"
    store.write_config(config)
    with pytest.raises(EmailSourceError) as caught:
        manager.public_view(source_id)
    assert caught.value.code == "email_profile_unsupported"


def test_invalid_source_id_is_rejected_before_canonical_path_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manager = _store_and_manager(tmp_path)

    def forbidden_read(_kind: str, _record_id: str) -> object:
        raise AssertionError("invalid Source ID reached canonical storage")

    monkeypatch.setattr(store, "read_canonical", forbidden_read)
    with pytest.raises(EmailSourceNotFound) as caught:
        manager.public_view("../../outside")
    assert caught.value.code == "email_source_missing"
    assert str(caught.value) == "email Source not found"
