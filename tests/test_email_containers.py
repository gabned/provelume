from __future__ import annotations

import hashlib
import os
import socket
from dataclasses import replace
from pathlib import Path

import pytest

import provelume.email_containers as email_containers
from provelume.email_containers import EmlFileAdapter, MaildirAdapter, adapter_for_profile
from provelume.email_contract import (
    EmailContractError,
    EmailLimits,
    EmailSourceConfig,
    FilesystemIdentity,
)

SOURCE_ID = "src_" + "2" * 32
WINDOWS_MAILDIR_UNQUALIFIED = pytest.mark.skipif(
    os.name == "nt", reason="Maildir is not qualified on Windows"
)


@pytest.fixture(autouse=True)
def qualified_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name != "nt":
        monkeypatch.setattr(
            "provelume.email_contract.qualified_runtime_target",
            lambda: "ubuntu-24.04-x86_64-cpython312",
        )


def eml_config(path: Path, *, state: str = "enabled") -> EmailSourceConfig:
    return EmailSourceConfig(
        source_id=SOURCE_ID,
        mailbox_format="eml",
        profile="eml-file-v1",
        path=path.absolute(),
        state=state,  # type: ignore[arg-type]
    )


def maildir_config(path: Path, *, state: str = "enabled") -> EmailSourceConfig:
    return EmailSourceConfig(
        source_id=SOURCE_ID,
        mailbox_format="maildir",
        profile="maildir-cur-new-v1",
        path=path.absolute(),
        state=state,  # type: ignore[arg-type]
    )


def make_maildir(path: Path) -> Path:
    for name in ("cur", "new", "tmp"):
        (path / name).mkdir(parents=True, exist_ok=True)
    return path


def test_eml_snapshot_and_read_preserve_exact_source_bytes(tmp_path: Path) -> None:
    data = b"Subject: line endings\r\nX-Folded: one\r\n\ttwo\r\n\r\nbody\nlast"
    path = tmp_path / "message.eml"
    path.write_bytes(data)
    adapter = EmlFileAdapter(eml_config(path))

    probe = adapter.probe()
    assert probe.available and probe.network_attempted is False
    snapshot = adapter.snapshot()
    assert snapshot.message_count == 1
    assert snapshot.total_bytes == len(data)
    assert snapshot.network_used is False
    observed = adapter.read_exact(snapshot.candidates[0])
    assert observed.data == data
    assert observed.size_bytes == len(data)
    assert observed.sha256 == hashlib.sha256(data).hexdigest()
    assert adapter.recheck(snapshot).snapshot_sha256 == snapshot.snapshot_sha256


def test_windows_open_identity_uses_stable_handle_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = FilesystemIdentity(
        device=3,
        inode=5,
        size_bytes=7,
        mtime_ns=11,
        ctime_ns=13,
        link_count=1,
        file_attributes=32,
    )
    monkeypatch.setattr(email_containers, "_WINDOWS_PLATFORM", True)
    opened = replace(expected, ctime_ns=17, file_attributes=0)
    assert email_containers._same_open_identity(opened, expected)
    assert not email_containers._same_open_identity(
        replace(opened, inode=opened.inode + 1), expected
    )
    assert not email_containers._same_open_identity(
        replace(opened, size_bytes=opened.size_bytes + 1), expected
    )


@pytest.mark.parametrize(
    ("state", "code"),
    (("disabled", "email_source_disabled"), ("paused", "email_source_paused")),
)
def test_source_state_prevents_enumeration_and_read(
    tmp_path: Path, state: str, code: str
) -> None:
    path = tmp_path / "message.eml"
    path.write_bytes(b"Subject: inert\r\n\r\nbody")
    adapter = EmlFileAdapter(eml_config(path, state=state))
    with pytest.raises(EmailContractError) as caught:
        adapter.snapshot()
    assert caught.value.code == code


def test_probe_is_read_only_and_reports_missing_or_unsafe(tmp_path: Path) -> None:
    missing = EmlFileAdapter(eml_config(tmp_path / "missing.eml")).probe()
    assert not missing.available
    assert missing.state == "source-missing"
    assert missing.reason == "email_source_missing"
    assert list(tmp_path.iterdir()) == []

    directory = tmp_path / "not-a-message"
    directory.mkdir()
    unsafe = EmlFileAdapter(eml_config(directory)).probe()
    assert not unsafe.available
    assert unsafe.state == "source-unsafe"
    assert unsafe.reason == "email_input_non_regular"


def test_eml_message_and_run_limits_are_checked_before_read(tmp_path: Path) -> None:
    path = tmp_path / "message.eml"
    path.write_bytes(b"123456789")
    adapter = EmlFileAdapter(eml_config(path))
    limits = replace(
        EmailLimits(),
        max_message_bytes=8,
        max_maildir_container_bytes=8,
        max_total_read_bytes=8,
    )
    with pytest.raises(EmailContractError) as caught:
        adapter.snapshot(limits=limits)
    assert caught.value.code == "email_message_limit_exceeded"


def test_eml_rejects_change_replace_and_disappearance(tmp_path: Path) -> None:
    path = tmp_path / "message.eml"
    path.write_bytes(b"Subject: first\r\n\r\nbody")
    adapter = EmlFileAdapter(eml_config(path))
    snapshot = adapter.snapshot()
    path.write_bytes(b"Subject: changed\r\n\r\nbody")
    with pytest.raises(EmailContractError) as caught:
        adapter.read_exact(snapshot.candidates[0])
    assert caught.value.code == "email_input_changed"

    path.unlink()
    with pytest.raises(EmailContractError) as caught:
        adapter.read_exact(snapshot.candidates[0])
    assert caught.value.code in {"email_input_changed", "email_source_missing"}


def test_eml_recheck_rejects_stale_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "message.eml"
    path.write_bytes(b"Subject: first\r\n\r\nbody")
    adapter = EmlFileAdapter(eml_config(path))
    snapshot = adapter.snapshot()
    path.write_bytes(b"Subject: second\r\n\r\nbody")
    with pytest.raises(EmailContractError) as caught:
        adapter.recheck(snapshot)
    assert caught.value.code == "email_input_changed"


def test_symlink_hardlink_and_non_regular_inputs_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "target.eml"
    target.write_bytes(b"Subject: target\r\n\r\nbody")
    symlink = tmp_path / "link.eml"
    try:
        symlink.symlink_to(target)
    except (NotImplementedError, OSError):
        pass
    else:
        probe = EmlFileAdapter(eml_config(symlink)).probe()
        assert not probe.available
        assert probe.reason == "email_source_unsafe"

    hardlink = tmp_path / "hard.eml"
    try:
        os.link(target, hardlink)
    except OSError:
        pass
    else:
        probe = EmlFileAdapter(eml_config(hardlink)).probe()
        assert not probe.available
        assert probe.reason == "email_source_unsafe"

    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "message.fifo"
        os.mkfifo(fifo)
        probe = EmlFileAdapter(eml_config(fifo)).probe()
        assert not probe.available
        assert probe.reason == "email_input_non_regular"


def test_reparse_point_branch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "reparse.eml"
    path.write_bytes(b"Subject: synthetic\r\n\r\nbody")
    monkeypatch.setattr("provelume.email_containers._is_reparse", lambda _value: True)
    probe = EmlFileAdapter(eml_config(path)).probe()
    assert probe.available is False
    assert probe.reason == "email_source_unsafe"


@WINDOWS_MAILDIR_UNQUALIFIED
def test_maildir_enumerates_only_cur_and_new_and_preserves_bytes(tmp_path: Path) -> None:
    root = make_maildir(tmp_path / "maildir")
    first = b"Subject: cur\n\ncur-body\n"
    second = b"Subject: new\r\n\r\nnew-body\r\n"
    (root / "cur" / "z:2,S").write_bytes(first)
    (root / "new" / "a").write_bytes(second)
    (root / "tmp" / "incomplete").write_bytes(b"must never be enumerated")
    adapter = MaildirAdapter(maildir_config(root))

    assert adapter.probe().available
    snapshot = adapter.snapshot()
    assert snapshot.message_count == 2
    assert snapshot.total_bytes == len(first) + len(second)
    observed = {adapter.read_exact(item).data for item in snapshot.candidates}
    assert observed == {first, second}
    assert all(b"incomplete" not in value for value in observed)


@WINDOWS_MAILDIR_UNQUALIFIED
def test_maildir_requires_exact_layout_and_rejects_bad_entries(tmp_path: Path) -> None:
    root = tmp_path / "maildir"
    root.mkdir()
    assert MaildirAdapter(maildir_config(root)).probe().reason == "email_source_missing"

    make_maildir(root)
    (root / "cur" / "nested").mkdir()
    probe = MaildirAdapter(maildir_config(root)).probe()
    assert not probe.available
    assert probe.reason == "email_input_non_regular"


@WINDOWS_MAILDIR_UNQUALIFIED
def test_maildir_rejects_symlink_and_hardlink_entries(tmp_path: Path) -> None:
    root = make_maildir(tmp_path / "maildir")
    target = root / "new" / "message"
    target.write_bytes(b"Subject: x\r\n\r\ny")
    symlink = root / "cur" / "linked"
    try:
        symlink.symlink_to(target)
    except (NotImplementedError, OSError):
        pass
    else:
        assert MaildirAdapter(maildir_config(root)).probe().reason == "email_source_unsafe"
        symlink.unlink()

    alias = root / "cur" / "hard"
    try:
        os.link(target, alias)
    except OSError:
        pass
    else:
        assert MaildirAdapter(maildir_config(root)).probe().reason == "email_source_unsafe"


@WINDOWS_MAILDIR_UNQUALIFIED
def test_maildir_rename_or_mutation_invalidates_snapshot(tmp_path: Path) -> None:
    root = make_maildir(tmp_path / "maildir")
    message = root / "new" / "one"
    message.write_bytes(b"Subject: one\r\n\r\nbody")
    adapter = MaildirAdapter(maildir_config(root))
    snapshot = adapter.snapshot()
    message.rename(root / "cur" / "one:2,S")
    with pytest.raises(EmailContractError) as caught:
        adapter.read_exact(snapshot.candidates[0])
    assert caught.value.code == "email_input_changed"
    with pytest.raises(EmailContractError) as caught:
        adapter.recheck(snapshot)
    assert caught.value.code == "email_input_changed"


@WINDOWS_MAILDIR_UNQUALIFIED
def test_maildir_cumulative_limits_fail_before_any_message_read(tmp_path: Path) -> None:
    root = make_maildir(tmp_path / "maildir")
    (root / "new" / "one").write_bytes(b"12345")
    (root / "new" / "two").write_bytes(b"67890")
    adapter = MaildirAdapter(maildir_config(root))
    limits = replace(EmailLimits(), max_messages_per_run=1)
    with pytest.raises(EmailContractError) as caught:
        adapter.snapshot(limits=limits)
    assert caught.value.code == "email_container_limit_exceeded"

    limits = replace(
        EmailLimits(),
        max_message_bytes=8,
        max_maildir_container_bytes=9,
        max_total_read_bytes=9,
    )
    with pytest.raises(EmailContractError) as caught:
        adapter.snapshot(limits=limits)
    assert caught.value.code == "email_container_limit_exceeded"


def test_container_operations_do_not_use_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "message.eml"
    data = b"Subject: https://tracker.invalid/pixel\r\n\r\nbody"
    path.write_bytes(data)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("email container attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    adapter = adapter_for_profile(eml_config(path))
    snapshot = adapter.snapshot()
    assert adapter.read_exact(snapshot.candidates[0]).data == data
    assert adapter.recheck(snapshot).network_used is False


def test_adapter_factory_rejects_mismatched_profiles(tmp_path: Path) -> None:
    config = eml_config(tmp_path / "message.eml")
    assert isinstance(adapter_for_profile(config), EmlFileAdapter)
    with pytest.raises(EmailContractError) as caught:
        adapter_for_profile(replace(config, profile="maildir-cur-new-v1"))  # type: ignore[arg-type]
    assert caught.value.code == "email_profile_unsupported"
