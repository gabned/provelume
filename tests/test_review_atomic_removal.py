"""Reviewed undo retains real preimages and never removes unrelated knowledge."""

import hashlib
import json
import os

import pytest

from provelume import atomic_commit
from provelume.atomic_commit import (
    MANUAL_WEB_TRANSACTION_PROFILE,
    REVIEW_TRANSACTION_PROFILE,
    AtomicCommitError,
    AtomicCommitIntegrityError,
    AtomicCommitRecoveryError,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    recover_atomic_transactions,
)
from provelume.storage import InstanceStore

RELATIVE = "knowledge/classifications/classification_" + "1" * 32 + ".json"
BEFORE = b'{"synthetic":"retained classification"}'


class Interrupted(BaseException):
    pass


def prepared(tmp_path, replace=os.replace):
    store = InstanceStore.initialise(tmp_path / "instance")
    target = store.paths.root / RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(BEFORE)
    control = tmp_path / ".review-control"
    transaction = AtomicInstanceCommit(
        store, control / "transactions", profile=REVIEW_TRANSACTION_PROFILE,
        owner_id="review_" + "2" * 32, replace=replace,
    )
    transaction.remove_classification(RELATIVE, expected_sha256=hashlib.sha256(BEFORE).hexdigest())
    transaction.add("state/review/retained.json", b'{"undo":"receipt"}', immutable=True)
    return store, target, control, transaction


def recover(store, control):
    return recover_atomic_transactions(
        store, control, handlers=(AtomicRecoveryHandler(profile=REVIEW_TRANSACTION_PROFILE),),
    )


def test_review_removal_and_receipt_commit_together_and_cleanup_is_recoverable(
    tmp_path, monkeypatch,
):
    store, target, control, transaction = prepared(tmp_path)
    real_cleanup = atomic_commit.shutil.rmtree
    monkeypatch.setattr(atomic_commit.shutil, "rmtree", lambda *a, **kw: None)
    transaction.commit()
    assert not target.exists()
    assert (store.paths.root / "state/review/retained.json").read_bytes() == b'{"undo":"receipt"}'
    stage = next((control / "transactions").iterdir())
    manifest = json.loads((stage / "manifest.json").read_text())
    assert manifest["schema_version"] == 2 and manifest["status"] == "committed"
    monkeypatch.setattr(atomic_commit.shutil, "rmtree", real_cleanup)
    assert recover(store, control)["committed_cleanups"] == 1
    assert not target.exists() and not list((control / "transactions").iterdir())


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("crash", [False, True])
def test_partial_removal_rolls_back_with_receipt_and_preserves_originals(tmp_path, after, crash):
    def replace(source, target):
        if str(source).endswith(RELATIVE.replace("/", os.sep)):
            if after:
                os.replace(source, target)
            raise Interrupted() if crash else OSError("synthetic publication failure")
        os.replace(source, target)

    store, target, control, transaction = prepared(tmp_path, replace)
    original = store.paths.originals / "public.bin"
    original.write_bytes(b"unchanged Original")
    with pytest.raises(Interrupted if crash else AtomicCommitError):
        transaction.commit()
    if crash:
        assert target.exists() is (not after)
        assert recover(store, control)["rolled_back"] == 1
    assert target.read_bytes() == BEFORE
    assert original.read_bytes() == b"unchanged Original"
    assert not (store.paths.root / "state/review/retained.json").exists()
    assert not list((control / "transactions").iterdir())
    assert recover(store, control) is None


def test_prepared_removal_never_overwrites_a_foreign_post_removal_write(tmp_path):
    def replace(source, target):
        os.replace(source, target)
        raise Interrupted()

    store, target, control, transaction = prepared(tmp_path, replace)
    with pytest.raises(Interrupted):
        transaction.commit()
    target.write_bytes(b"independent new classification")
    with pytest.raises(AtomicCommitRecoveryError):
        recover(store, control)
    assert target.read_bytes() == b"independent new classification"
    assert list((control / "transactions").iterdir())


def test_stale_removal_preimage_refuses_before_publication(tmp_path):
    store, target, control, transaction = prepared(tmp_path)
    target.write_bytes(b"changed before preparation")
    with pytest.raises(AtomicCommitIntegrityError):
        transaction.commit()
    assert target.read_bytes() == b"changed before preparation"
    assert not list((control / "transactions").iterdir())


def test_unapplied_prepared_removal_preserves_a_foreign_write(tmp_path):
    def replace(source, target):
        source.write_bytes(b"foreign classification before rename")
        raise OSError("synthetic failure before moving the live preimage")

    _store, target, control, transaction = prepared(tmp_path, replace)
    with pytest.raises(AtomicCommitError):
        transaction.commit()
    assert target.read_bytes() == b"foreign classification before rename"
    assert not list((control / "transactions").iterdir())


@pytest.mark.parametrize("path", ["originals/public.bin", "knowledge/documents/doc.json",
                                  "knowledge/classifications/../other.json"])
def test_removal_is_restricted_to_exact_classification_metadata(tmp_path, path):
    _store, _target, _control, transaction = prepared(tmp_path)
    with pytest.raises(AtomicCommitIntegrityError):
        transaction.remove_classification(path, expected_sha256="0" * 64)


def test_non_review_profile_cannot_enable_removal(tmp_path):
    store = InstanceStore.initialise(tmp_path / "instance")
    transaction = AtomicInstanceCommit(
        store, tmp_path / "transactions", profile=MANUAL_WEB_TRANSACTION_PROFILE,
        owner_id="op_" + "3" * 32,
    )
    with pytest.raises(AtomicCommitIntegrityError):
        transaction.remove_classification(RELATIVE, expected_sha256="0" * 64)
