"""Transaction work must settle before journal cleanup or acknowledgement."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor as RealExecutor
from pathlib import Path
from types import SimpleNamespace

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


def _fixture(tmp_path, monkeypatch, phase, submit_error, shutdown_error=None):
    store = InstanceStore.initialise(tmp_path / "instance")
    control = tmp_path / ".instance.provelume"
    parent = control / "transactions"
    targets = [store.paths.root / "state/left/value.bin",
               store.paths.root / "state/right/value.bin"]
    before, after = [b"old-a", b"old-b"], [b"new-a", b"new-b"]
    for path, data in zip(targets, before, strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        store._atomic_bytes(path, data)
    transaction = AtomicInstanceCommit(
        store, parent, profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
        owner_id="job_0123456789abcdef0123456789abcdef")
    for path, data in zip(targets, after, strict=True):
        transaction.add(path.relative_to(store.paths.root).as_posix(), data, immutable=False)
    state = SimpleNamespace(entered=threading.Event(), release=threading.Event(),
        finished=threading.Event(), submit_failed=threading.Event(), draining=threading.Event(),
        pools=[], futures=[], outcomes=[], destructive=[], markers=[], selected_submissions=0)
    if phase == "prepare":
        original_write = atomic_commit._write_journal_payload
        def work(path, data):
            if path.parent.name == "candidates" and path.name == "0000.bin":
                state.entered.set()
                try:
                    assert state.release.wait(10)
                    return original_write(path, data)
                finally:
                    state.finished.set()
            return original_write(path, data)
        monkeypatch.setattr(atomic_commit, "_write_journal_payload", work)
    else:
        original_flush = atomic_commit._fsync_directory
        def work(path):
            if path == targets[0].parent:
                state.entered.set()
                try:
                    assert state.release.wait(10)
                    return original_flush(path)
                finally:
                    state.finished.set()
            return original_flush(path)
        monkeypatch.setattr(atomic_commit, "_fsync_directory", work)

    class FaultPool:
        def __init__(self, *args, **kwargs):
            self.actual = RealExecutor(*args, **kwargs)
            state.pools.append(self)

        def submit(self, function, *args, **kwargs):
            future = self.actual.submit(function, *args, **kwargs)
            state.futures.append(future)
            if function is work:
                state.selected_submissions += 1
                if state.selected_submissions == 2:
                    assert state.entered.wait(5)
                    state.submit_failed.set()
                    # Work was accepted, but its Future never reaches the caller.
                    raise submit_error
            return future

        def shutdown(self, wait=True, *, cancel_futures=False):
            if state.submit_failed.is_set():
                state.draining.set()
                if shutdown_error is not None:
                    raise shutdown_error
            return self.actual.shutdown(wait=wait, cancel_futures=cancel_futures)

        def __enter__(self):
            return self

        def __exit__(self, *_exception):
            self.shutdown(wait=True)

    monkeypatch.setattr(atomic_commit, "ThreadPoolExecutor", FaultPool)
    original_bytes = store._atomic_bytes
    def marker(path, data):
        if path.name == "manifest.json":
            state.markers.append((json.loads(data)["status"], all(f.done() for f in state.futures)))
        return original_bytes(path, data)
    monkeypatch.setattr(store, "_atomic_bytes", marker)
    original_remove = atomic_commit.shutil.rmtree
    def remove(path, *args, **kwargs):
        if Path(path).parent == parent:
            state.destructive.append(("remove", state.finished.is_set()))
        return original_remove(path, *args, **kwargs)
    monkeypatch.setattr(atomic_commit.shutil, "rmtree", remove)
    original_rollback = atomic_commit._rollback_prepared_transaction
    def rollback(*args, **kwargs):
        state.destructive.append(("rollback", state.finished.is_set()))
        return original_rollback(*args, **kwargs)
    monkeypatch.setattr(atomic_commit, "_rollback_prepared_transaction", rollback)

    def commit():
        try:
            transaction.commit()
        except BaseException as error:
            state.outcomes.append(error)
        else:
            state.outcomes.append("acknowledged")
    state.worker = threading.Thread(target=commit)
    state.worker.start()
    return SimpleNamespace(store=store, control=control, parent=parent, targets=targets,
                           before=before, after=after, state=state, phase=phase)


def _stages(value):
    return list(value.parent.iterdir()) if value.parent.exists() else []


def _live(value):
    return [p.read_bytes() for p in value.targets]


def _release_and_join(value):
    value.state.release.set()
    value.state.worker.join(10)
    # Faulted shutdown deliberately left quiescence unproven. Test teardown must
    # really join those tasks before inspecting recovery or disposing fixtures.
    for pool in value.state.pools:
        pool.actual.shutdown(wait=True)
    assert not value.state.worker.is_alive()
    assert value.state.finished.is_set() and all(f.done() for f in value.state.futures)


def _assert_recoverable(value):
    recover_atomic_transactions(value.store, value.control,
        handlers=(AtomicRecoveryHandler(EMAIL_INTAKE_TRANSACTION_PROFILE),))
    assert _live(value) == value.before and _stages(value) == []


@pytest.mark.parametrize(
    "error", [OSError("accepted prepare task"), KeyboardInterrupt("accepted prepare task")],
    ids=["Exception", "KeyboardInterrupt"],
)
def test_partial_prepare_submit_waits_for_accepted_work_before_stage_cleanup(
    tmp_path, monkeypatch, error,
):
    value = _fixture(tmp_path, monkeypatch, "prepare", error)
    try:
        assert value.state.entered.wait(5) and value.state.submit_failed.wait(5)
        assert value.state.draining.wait(5)
        assert value.state.worker.is_alive() and value.state.outcomes == []
        assert _stages(value) and not list(value.parent.glob("*/manifest.json"))
        assert _live(value) == value.before and value.state.destructive == []
        assert value.state.markers == []
    finally:
        _release_and_join(value)
    assert len(value.state.outcomes) == 1 and _live(value) == value.before
    assert all(finished for _kind, finished in value.state.destructive)
    if isinstance(error, Exception):
        assert isinstance(value.state.outcomes[0], AtomicCommitError) and _stages(value) == []
    else:
        assert value.state.outcomes[0] is error and _stages(value)
        _assert_recoverable(value)


@pytest.mark.parametrize(
    "error", [OSError("accepted directory task"), KeyboardInterrupt("accepted directory task")],
    ids=["Exception", "KeyboardInterrupt"],
)
def test_partial_publish_submit_waits_before_rollback_or_interruption(tmp_path, monkeypatch, error):
    value = _fixture(tmp_path, monkeypatch, "publish", error)
    try:
        assert value.state.entered.wait(5) and value.state.submit_failed.wait(5)
        assert value.state.draining.wait(5)
        assert value.state.worker.is_alive() and value.state.outcomes == []
        assert _live(value) == value.after and value.state.destructive == []
        assert value.state.markers == [("prepared", True)]
        manifest = next(value.parent.glob("*/manifest.json"))
        assert value.store._read_json(manifest)["status"] == "prepared"
    finally:
        _release_and_join(value)
    assert len(value.state.outcomes) == 1
    assert all(finished for _kind, finished in value.state.destructive)
    assert all(status != "committed" for status, _settled in value.state.markers)
    if isinstance(error, Exception):
        assert isinstance(value.state.outcomes[0], AtomicCommitError)
        assert _live(value) == value.before and _stages(value) == []
    else:
        assert value.state.outcomes[0] is error and _live(value) == value.after and _stages(value)
        _assert_recoverable(value)


@pytest.mark.parametrize("phase", ["prepare", "publish"])
def test_failed_shutdown_preserves_unquiesced_journal_and_public_safe_error(
    tmp_path, monkeypatch, phase,
):
    value = _fixture(tmp_path, monkeypatch, phase, OSError("accepted but unreturned"),
                     OSError("private shutdown failure"))
    try:
        assert value.state.entered.wait(5) and value.state.submit_failed.wait(5)
        assert value.state.draining.wait(5)
        value.state.worker.join(5)
        assert not value.state.worker.is_alive() and len(value.state.outcomes) == 1
        error = value.state.outcomes[0]
        assert isinstance(error, AtomicCommitError) and str(error) == AtomicCommitError.safe_message
        assert error.__cause__ is None and error.__suppress_context__ is True
        assert not value.state.finished.is_set() and _stages(value)
        assert value.state.destructive == [] and all(
            s != "committed" for s, _ in value.state.markers
        )
        assert _live(value) == (value.before if phase == "prepare" else value.after)
    finally:
        _release_and_join(value)
    _assert_recoverable(value)


@pytest.mark.parametrize("phase", ["prepare", "publish"])
def test_shutdown_interrupt_preserves_same_exception_and_journal_without_ack(
    tmp_path, monkeypatch, phase,
):
    interruption = KeyboardInterrupt("unproven drain")
    value = _fixture(tmp_path, monkeypatch, phase, OSError("accepted but unreturned"), interruption)
    try:
        assert value.state.entered.wait(5) and value.state.submit_failed.wait(5)
        assert value.state.draining.wait(5)
        value.state.worker.join(5)
        assert not value.state.worker.is_alive() and value.state.outcomes == [interruption]
        assert value.state.outcomes[0] is interruption
        assert not value.state.finished.is_set() and _stages(value)
        assert value.state.destructive == [] and all(
            s != "committed" for s, _ in value.state.markers
        )
        assert _live(value) == (value.before if phase == "prepare" else value.after)
    finally:
        _release_and_join(value)
    _assert_recoverable(value)
