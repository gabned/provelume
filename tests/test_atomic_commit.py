from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from provelume import atomic_commit
from provelume.atomic_commit import (
    ATOMIC_COMMIT_SCHEMA_VERSION,
    EMAIL_INTAKE_TRANSACTION_PROFILE,
    MANUAL_WEB_TRANSACTION_PROFILE,
    AtomicCommitError,
    AtomicCommitIntegrityError,
    AtomicCommitLimitError,
    AtomicCommitLimits,
    AtomicCommitProfile,
    AtomicCommitRecoveryError,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    recover_atomic_transactions,
)
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.storage import InstanceStore

JOB_ID = "job_0123456789abcdef0123456789abcdef"
OPERATION_ID = "op_0123456789abcdef0123456789abcdef"


def _store(tmp_path: Path) -> tuple[InstanceStore, Path]:
    store = InstanceStore.initialise(tmp_path / "instance")
    control_root = tmp_path / ".instance.provelume"
    return store, control_root


def _profile(
    *,
    max_entries: int = 4,
    max_entry_bytes: int = 16,
    max_candidate_bytes: int = 32,
    max_preimage_bytes: int = 16,
    max_journal_payload_bytes: int = 48,
) -> AtomicCommitProfile:
    return AtomicCommitProfile(
        key="email-intake",
        kind="email.intake",
        owner_id_pattern=r"job_[0-9a-f]{32}\Z",
        limits=AtomicCommitLimits(
            max_entries=max_entries,
            max_entry_bytes=max_entry_bytes,
            max_candidate_bytes=max_candidate_bytes,
            max_preimage_bytes=max_preimage_bytes,
            max_journal_payload_bytes=max_journal_payload_bytes,
        ),
    )


def _transaction(
    store: InstanceStore,
    control_root: Path,
    *,
    profile: AtomicCommitProfile,
    owner_id: str = JOB_ID,
    replace_file=os.replace,
) -> AtomicInstanceCommit:
    return AtomicInstanceCommit(
        store,
        control_root / "transactions",
        profile=profile,
        owner_id=owner_id,
        replace=replace_file,
    )


def test_builtin_profiles_publish_closed_limits() -> None:
    assert MANUAL_WEB_TRANSACTION_PROFILE.as_dict() == {
        "schema_version": ATOMIC_COMMIT_SCHEMA_VERSION,
        "key": "manual-web",
        "kind": "connector.web.acquire",
        "owner_id_pattern": r"op_[0-9a-f]{32}\Z",
        "limits": {
            "max_entries": 2048,
            "max_entry_bytes": 64 * 1024 * 1024,
            "max_candidate_bytes": 128 * 1024 * 1024,
            "max_preimage_bytes": 64 * 1024 * 1024,
            "max_journal_payload_bytes": 192 * 1024 * 1024,
        },
    }
    assert EMAIL_INTAKE_TRANSACTION_PROFILE.as_dict()["limits"] == {
        "max_entries": 4096,
        "max_entry_bytes": 64 * 1024 * 1024,
        "max_candidate_bytes": 256 * 1024 * 1024,
        "max_preimage_bytes": 128 * 1024 * 1024,
        "max_journal_payload_bytes": 384 * 1024 * 1024,
    }
    assert EMAIL_INTAKE_TRANSACTION_PROFILE.accepts_owner_id(JOB_ID)
    assert not EMAIL_INTAKE_TRANSACTION_PROFILE.accepts_owner_id(OPERATION_ID)


def test_entry_limit_rejects_before_staging_and_keeps_accepted_write(
    tmp_path: Path,
) -> None:
    store, control_root = _store(tmp_path)
    transaction = _transaction(
        store,
        control_root,
        profile=_profile(max_entries=1),
    )
    transaction.add("state/email/first.bin", b"one", immutable=True)

    with pytest.raises(AtomicCommitLimitError):
        transaction.add("state/email/second.bin", b"two", immutable=True)

    assert not (control_root / "transactions").exists()
    transaction.commit()
    assert (store.paths.root / "state/email/first.bin").read_bytes() == b"one"
    assert not (store.paths.root / "state/email/second.bin").exists()


def test_candidate_limits_apply_at_exact_boundary_and_plus_one(tmp_path: Path) -> None:
    store, control_root = _store(tmp_path)
    profile = _profile(
        max_entry_bytes=5,
        max_candidate_bytes=4,
        max_preimage_bytes=4,
        max_journal_payload_bytes=8,
    )
    exact = _transaction(store, control_root, profile=profile)
    exact.add("state/email/exact.bin", b"1234", immutable=True)
    exact.commit()

    excessive = _transaction(store, control_root, profile=profile)
    with pytest.raises(AtomicCommitLimitError):
        excessive.add("state/email/excessive.bin", b"12345", immutable=True)

    assert (store.paths.root / "state/email/exact.bin").read_bytes() == b"1234"
    assert not list((control_root / "transactions").glob("email-intake-*"))


@pytest.mark.parametrize(
    ("profile", "expected_error"),
    [
        (
            _profile(
                max_entry_bytes=5,
                max_candidate_bytes=5,
                max_preimage_bytes=3,
                max_journal_payload_bytes=8,
            ),
            AtomicCommitLimitError,
        ),
        (
            _profile(
                max_entry_bytes=4,
                max_candidate_bytes=4,
                max_preimage_bytes=4,
                max_journal_payload_bytes=7,
            ),
            AtomicCommitLimitError,
        ),
    ],
)
def test_preimage_and_total_journal_limits_preserve_live_state(
    tmp_path: Path,
    profile: AtomicCommitProfile,
    expected_error: type[Exception],
) -> None:
    store, control_root = _store(tmp_path)
    target = store.paths.root / "state/email/current.bin"
    store._atomic_bytes(target, b"old!")
    transaction = _transaction(store, control_root, profile=profile)
    transaction.add("state/email/current.bin", b"new!", immutable=False)

    with pytest.raises(expected_error):
        transaction.commit()

    assert target.read_bytes() == b"old!"
    assert not list((control_root / "transactions").glob("email-intake-*"))


def test_duplicate_add_is_idempotent_but_conflicts_fail_closed(tmp_path: Path) -> None:
    store, control_root = _store(tmp_path)
    transaction = _transaction(store, control_root, profile=_profile())
    transaction.add("state/email/item.bin", b"same", immutable=True)
    transaction.add("state/email/item.bin", b"same", immutable=True)

    with pytest.raises(AtomicCommitIntegrityError):
        transaction.add("state/email/item.bin", b"different", immutable=True)
    with pytest.raises(AtomicCommitIntegrityError):
        transaction.add("state/email/item.bin", b"same", immutable=False)

    transaction.commit()
    assert (store.paths.root / "state/email/item.bin").read_bytes() == b"same"

    immutable_conflict = _transaction(store, control_root, profile=_profile())
    immutable_conflict.add("state/email/item.bin", b"replacement", immutable=True)
    with pytest.raises(AtomicCommitIntegrityError):
        immutable_conflict.commit()
    assert (store.paths.root / "state/email/item.bin").read_bytes() == b"same"


@pytest.mark.parametrize("second_has_preimage", [False, True])
def test_failed_commit_preserves_concurrent_unapplied_target_change(
    tmp_path: Path,
    second_has_preimage: bool,
) -> None:
    store, control_root = _store(tmp_path)
    first = store.paths.root / "state/email/a.bin"
    second = store.paths.root / "state/email/b.bin"
    store._atomic_bytes(first, b"first-old")
    if second_has_preimage:
        store._atomic_bytes(second, b"second-old")

    def replace_then_mutate_next(source: Path, target: Path) -> None:
        os.replace(source, target)
        if target == first:
            store._atomic_bytes(second, b"external-change")

    transaction = _transaction(
        store,
        control_root,
        profile=_profile(
            max_entry_bytes=32,
            max_candidate_bytes=32,
            max_preimage_bytes=32,
            max_journal_payload_bytes=64,
        ),
        replace_file=replace_then_mutate_next,
    )
    transaction.add("state/email/a.bin", b"first-new", immutable=False)
    transaction.add("state/email/b.bin", b"second-new", immutable=False)

    with pytest.raises(AtomicCommitError):
        transaction.commit()

    assert first.read_bytes() == b"first-old"
    assert second.read_bytes() == b"external-change"
    assert not list((control_root / "transactions").glob("email-intake-*"))


def test_dispatcher_recovers_both_profiles_deterministically(tmp_path: Path) -> None:
    store, control_root = _store(tmp_path)

    def crash_after_replace(source: Path, target: Path) -> None:
        os.replace(source, target)
        raise KeyboardInterrupt

    manual = _transaction(
        store,
        control_root,
        profile=MANUAL_WEB_TRANSACTION_PROFILE,
        owner_id=OPERATION_ID,
        replace_file=crash_after_replace,
    )
    manual.add("state/email/manual.bin", b"manual", immutable=True)
    with pytest.raises(KeyboardInterrupt):
        manual.commit()

    email = _transaction(
        store,
        control_root,
        profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
        replace_file=crash_after_replace,
    )
    email.add("state/email/message.bin", b"message", immutable=True)
    with pytest.raises(KeyboardInterrupt):
        email.commit()

    callbacks: list[tuple[str, str]] = []
    report = recover_atomic_transactions(
        store,
        control_root,
        handlers=(
            AtomicRecoveryHandler(
                profile=MANUAL_WEB_TRANSACTION_PROFILE,
                on_prepared_rollback=lambda _store, owner: callbacks.append(
                    ("manual-web", owner)
                ),
            ),
            AtomicRecoveryHandler(
                profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
                on_prepared_rollback=lambda _store, owner: callbacks.append(
                    ("email-intake", owner)
                ),
            ),
        ),
    )

    assert report == {
        "schema_version": ATOMIC_COMMIT_SCHEMA_VERSION,
        "status": "recovered",
        "rolled_back": 2,
        "committed_cleanups": 0,
        "profiles": {
            "email-intake": {"rolled_back": 1, "committed_cleanups": 0},
            "manual-web": {"rolled_back": 1, "committed_cleanups": 0},
        },
    }
    assert callbacks == [
        ("email-intake", JOB_ID),
        ("manual-web", OPERATION_ID),
    ]
    assert not (store.paths.root / "state/email/manual.bin").exists()
    assert not (store.paths.root / "state/email/message.bin").exists()


def test_committed_marker_cleanup_preserves_committed_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, control_root = _store(tmp_path)
    transaction = _transaction(
        store,
        control_root,
        profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
    )
    transaction.add("state/email/committed.bin", b"committed", immutable=True)
    real_rmtree = atomic_commit.shutil.rmtree

    def interrupt_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path).name.startswith("email-intake-"):
            raise KeyboardInterrupt
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(atomic_commit.shutil, "rmtree", interrupt_cleanup)
    with pytest.raises(KeyboardInterrupt):
        transaction.commit()
    monkeypatch.setattr(atomic_commit.shutil, "rmtree", real_rmtree)

    report = recover_atomic_transactions(
        store,
        control_root,
        handlers=(AtomicRecoveryHandler(EMAIL_INTAKE_TRANSACTION_PROFILE),),
    )

    assert report is not None
    assert report["rolled_back"] == 0
    assert report["committed_cleanups"] == 1
    assert (store.paths.root / "state/email/committed.bin").read_bytes() == b"committed"
    assert not list((control_root / "transactions").glob("email-intake-*"))


def test_callback_failure_leaves_recoverable_journal(tmp_path: Path) -> None:
    store, control_root = _store(tmp_path)

    def crash_after_replace(source: Path, target: Path) -> None:
        os.replace(source, target)
        raise KeyboardInterrupt

    transaction = _transaction(
        store,
        control_root,
        profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
        replace_file=crash_after_replace,
    )
    transaction.add("state/email/retry.bin", b"retry", immutable=True)
    with pytest.raises(KeyboardInterrupt):
        transaction.commit()

    def fail_callback(_store: InstanceStore, _owner: str) -> None:
        raise RuntimeError("synthetic callback failure")

    with pytest.raises(AtomicCommitRecoveryError):
        recover_atomic_transactions(
            store,
            control_root,
            handlers=(
                AtomicRecoveryHandler(
                    EMAIL_INTAKE_TRANSACTION_PROFILE,
                    on_prepared_rollback=fail_callback,
                ),
            ),
        )
    assert list((control_root / "transactions").glob("email-intake-*"))

    report = recover_atomic_transactions(
        store,
        control_root,
        handlers=(AtomicRecoveryHandler(EMAIL_INTAKE_TRANSACTION_PROFILE),),
    )
    assert report is not None
    assert report["rolled_back"] == 1
    assert not (store.paths.root / "state/email/retry.bin").exists()


def test_lifecycle_dispatches_email_recovery_before_validation(tmp_path: Path) -> None:
    store, control_root = _store(tmp_path)

    def crash_after_replace(source: Path, target: Path) -> None:
        os.replace(source, target)
        raise KeyboardInterrupt

    transaction = _transaction(
        store,
        control_root,
        profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
        replace_file=crash_after_replace,
    )
    transaction.add("state/email/interrupted.bin", b"interrupted", immutable=True)
    with pytest.raises(KeyboardInterrupt):
        transaction.commit()

    result = InstanceLifecycleManager(store).prepare()

    assert result["email_intake_recovery"] == {
        "schema_version": ATOMIC_COMMIT_SCHEMA_VERSION,
        "status": "recovered",
        "rolled_back": 1,
        "committed_cleanups": 0,
    }
    assert result["manual_web_recovery"] is None
    assert result["transaction_recovery"]["profiles"] == {
        "email-intake": {"rolled_back": 1, "committed_cleanups": 0}
    }
    assert not (store.paths.root / "state/email/interrupted.bin").exists()


def test_recovery_rejects_tampered_candidate(tmp_path: Path) -> None:
    store, control_root = _store(tmp_path)

    def crash_before_replace(_source: Path, _target: Path) -> None:
        raise KeyboardInterrupt

    transaction = _transaction(
        store,
        control_root,
        profile=EMAIL_INTAKE_TRANSACTION_PROFILE,
        replace_file=crash_before_replace,
    )
    transaction.add("state/email/tampered.bin", b"expected", immutable=True)
    with pytest.raises(KeyboardInterrupt):
        transaction.commit()
    stage = next((control_root / "transactions").glob("email-intake-*"))
    candidate = next((stage / "candidates").iterdir())
    candidate.write_bytes(b"tampered")

    with pytest.raises(AtomicCommitRecoveryError):
        recover_atomic_transactions(
            store,
            control_root,
            handlers=(AtomicRecoveryHandler(EMAIL_INTAKE_TRANSACTION_PROFILE),),
        )

    assert stage.exists()
    assert not (store.paths.root / "state/email/tampered.bin").exists()


def test_recovery_bounds_manifest_before_json_parsing(tmp_path: Path) -> None:
    store, control_root = _store(tmp_path)
    profile = _profile(max_entries=1)
    stage = (
        control_root
        / "transactions"
        / "email-intake-0123456789abcdef0123456789abcdef"
    )
    stage.mkdir(parents=True)
    (stage / "manifest.json").write_bytes(b"{" + b" " * (80 * 1024) + b"}")

    with pytest.raises(AtomicCommitRecoveryError):
        recover_atomic_transactions(
            store,
            control_root,
            handlers=(AtomicRecoveryHandler(profile),),
        )


def test_profile_copy_can_tighten_limits_without_changing_identity() -> None:
    tightened = replace(
        EMAIL_INTAKE_TRANSACTION_PROFILE,
        limits=AtomicCommitLimits(
            max_entries=1,
            max_entry_bytes=1,
            max_candidate_bytes=1,
            max_preimage_bytes=1,
            max_journal_payload_bytes=2,
        ),
    )
    assert tightened.key == EMAIL_INTAKE_TRANSACTION_PROFILE.key
    assert tightened.kind == EMAIL_INTAKE_TRANSACTION_PROFILE.kind
    assert tightened.limits.max_entries == 1


def test_profile_rejects_more_entries_than_schema_one_can_name() -> None:
    with pytest.raises(ValueError, match="journal entry namespace"):
        AtomicCommitProfile(
            key="too-many",
            kind="test.too-many",
            owner_id_pattern=r"job_[0-9a-f]{32}\Z",
            limits=AtomicCommitLimits(
                max_entries=10_001,
                max_entry_bytes=1,
                max_candidate_bytes=1,
                max_preimage_bytes=1,
                max_journal_payload_bytes=2,
            ),
        )


def test_instance_root_is_not_an_atomic_write_target(tmp_path: Path) -> None:
    store, control_root = _store(tmp_path)
    transaction = _transaction(store, control_root, profile=_profile())

    with pytest.raises(AtomicCommitIntegrityError):
        transaction.add("", b"invalid", immutable=True)


def test_manual_web_wrapper_maps_invalid_transaction_root(tmp_path: Path) -> None:
    from provelume.web_acquisition import (
        ManualWebAtomicityError,
        recover_manual_web_transactions,
    )

    store, control_root = _store(tmp_path)
    transaction_root = control_root / "transactions"
    transaction_root.parent.mkdir(parents=True)
    transaction_root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ManualWebAtomicityError):
        recover_manual_web_transactions(store, control_root)
