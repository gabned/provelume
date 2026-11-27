"""Lone I/O keeps the full durability/recovery boundary without a worker hop."""
from __future__ import annotations

import json
import threading

import pytest

from provelume import atomic_commit
from provelume.atomic_commit import (
    EMAIL_INTAKE_TRANSACTION_PROFILE,
    AtomicCommitError,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    recover_atomic_transactions,
)
from provelume.storage import InstanceStore


def transaction(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    control = tmp_path / ".instance.provelume"
    commit = AtomicInstanceCommit(
        store, control / "transactions", profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
        owner_id="job_0123456789abcdef0123456789abcdef",
    )
    commit.add("state/lone/record.bin", b"synthetic", immutable=True)
    return store, control, commit


def test_single_payload_and_directory_keep_barriers_without_starting_pool(tmp_path, monkeypatch):
    store, control, commit = transaction(tmp_path)
    owner = threading.get_ident()
    operations = []
    original_write = atomic_commit._write_journal_payload
    original_flush = atomic_commit._fsync_directory
    original_bytes = store._atomic_bytes

    def pool(*args, **kwargs):
        pytest.fail("one payload/directory has no parallel I/O to schedule")

    def write(path, data):
        assert threading.get_ident() == owner
        result = original_write(path, data)
        operations.append("payload_durable")
        return result

    def flush(path):
        assert threading.get_ident() == owner
        result = original_flush(path)
        if path == store.paths.root / "state/lone":
            assert (path / "record.bin").read_bytes() == b"synthetic"
            operations.append("target_directory_durable")
        return result

    def marker(path, data):
        if path.name == "manifest.json":
            operations.append(json.loads(data)["status"])
        return original_bytes(path, data)

    monkeypatch.setattr(atomic_commit, "ThreadPoolExecutor", pool)
    monkeypatch.setattr(atomic_commit, "_write_journal_payload", write)
    monkeypatch.setattr(atomic_commit, "_fsync_directory", flush)
    monkeypatch.setattr(store, "_atomic_bytes", marker)
    commit.commit()
    assert operations == ["payload_durable", "prepared", "target_directory_durable", "committed"]
    assert not list((control / "transactions").iterdir())


@pytest.mark.parametrize("phase", ["prepare", "publish"])
@pytest.mark.parametrize("interrupt", [False, True], ids=["OSError", "KeyboardInterrupt"])
def test_single_io_failure_never_acknowledges_and_preserves_recovery(
    tmp_path, monkeypatch, phase, interrupt,
):
    store, control, commit = transaction(tmp_path)
    failure = KeyboardInterrupt("synthetic interruption") if interrupt else OSError("synthetic I/O")
    original_write = atomic_commit._write_journal_payload
    original_flush = atomic_commit._fsync_directory
    original_bytes = store._atomic_bytes
    markers = []
    injected = False

    def marker(path, data):
        if path.name == "manifest.json":
            markers.append(json.loads(data)["status"])
        return original_bytes(path, data)

    def write(path, data):
        original_write(path, data)
        if phase == "prepare":
            raise failure

    def flush(path):
        nonlocal injected
        original_flush(path)
        if not injected and phase == "publish" and path == store.paths.root / "state/lone":
            injected = True
            raise failure

    monkeypatch.setattr(atomic_commit, "_write_journal_payload", write)
    monkeypatch.setattr(atomic_commit, "_fsync_directory", flush)
    monkeypatch.setattr(store, "_atomic_bytes", marker)
    with pytest.raises(KeyboardInterrupt if interrupt else AtomicCommitError) as caught:
        commit.commit()
    if interrupt:
        assert caught.value is failure
    assert markers == ([] if phase == "prepare" else ["prepared"])
    stages = list((control / "transactions").iterdir())
    target = store.paths.root / "state/lone/record.bin"
    assert bool(stages) == interrupt
    assert target.exists() == (interrupt and phase == "publish")
    monkeypatch.setattr(atomic_commit, "_write_journal_payload", original_write)
    monkeypatch.setattr(atomic_commit, "_fsync_directory", original_flush)
    recover_atomic_transactions(
        store, control, handlers=(AtomicRecoveryHandler(EMAIL_INTAKE_TRANSACTION_PROFILE),),
    )
    assert not target.exists() and not list((control / "transactions").iterdir())


def test_single_directory_rollback_failure_keeps_prepared_journal(tmp_path, monkeypatch):
    store, control, commit = transaction(tmp_path)
    original = atomic_commit._fsync_directory

    def unavailable(path):
        if path == store.paths.root / "state/lone":
            raise OSError("synthetic persistent directory failure")
        return original(path)

    monkeypatch.setattr(atomic_commit, "_fsync_directory", unavailable)
    with pytest.raises(AtomicCommitError):
        commit.commit()
    manifest = next((control / "transactions").glob("*/manifest.json"))
    assert json.loads(manifest.read_bytes())["status"] == "prepared"
    monkeypatch.setattr(atomic_commit, "_fsync_directory", original)
    recover_atomic_transactions(
        store, control, handlers=(AtomicRecoveryHandler(EMAIL_INTAKE_TRANSACTION_PROFILE),),
    )
    assert not (store.paths.root / "state/lone/record.bin").exists()
    assert not list((control / "transactions").iterdir())
