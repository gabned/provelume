"""Registered bounded commit and recovery hooks for retained reviewed decisions."""

from __future__ import annotations

from .atomic_commit import (
    REVIEW_TRANSACTION_PROFILE,
    AtomicCommitRecoveryError,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    recover_atomic_transactions,
)
from .instance_lifecycle import InstanceLifecycleManager


def review_transaction_factory(store):
    root = InstanceLifecycleManager(store).control_root / "transactions"

    def create(owner_id: str) -> AtomicInstanceCommit:
        return AtomicInstanceCommit(
            store,
            root,
            profile=REVIEW_TRANSACTION_PROFILE,
            owner_id=owner_id,
        )

    return create


def recover_review_transactions_locked(store):
    """Caller owns lifecycle; recover before using a potentially partial receipt.

    This does not acquire another lock, scan domain inputs, or create absent state.
    A malformed journal raises the same recovery barrier used at Instance open.
    """
    control = InstanceLifecycleManager(store).control_root
    root = control / "transactions"
    if any(path.is_symlink() or path.is_junction() for path in (control, root)):
        raise AtomicCommitRecoveryError()
    if (
        not root.exists() or (root.is_dir() and not any(root.glob("review-*")))
    ):
        return None
    return recover_atomic_transactions(
        store,
        control,
        handlers=(AtomicRecoveryHandler(profile=REVIEW_TRANSACTION_PROFILE),),
    )
