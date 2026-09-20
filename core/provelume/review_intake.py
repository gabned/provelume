"""Route already committed acquisitions without changing the intake outcome."""

from __future__ import annotations

from .action_center_model import digest
from .atomic_commit import AtomicCommitError
from .instance_lifecycle import InstanceLifecycleError
from .review_effects import ReviewError

_ROUTING_ERRORS = (ReviewError, InstanceLifecycleError, AtomicCommitError, OSError, ValueError)


def route_committed_acquisitions(store, acquisitions, *, routing, decisions):
    return _route_committed_acquisitions(
        store, acquisitions, routing=routing, decisions=decisions, lifecycle_held=False,
    )


def route_committed_acquisitions_locked(store, acquisitions):
    """Internal folder refresh caller owns lifecycle for the complete operation."""
    return _route_committed_acquisitions(
        store, acquisitions, routing=None, decisions=None, lifecycle_held=True,
    )


def _route_committed_acquisitions(store, acquisitions, *, routing, decisions, lifecycle_held):
    documents = sorted({row["document_id"] for row in acquisitions if row.get("document_id")})
    if not documents:
        return []
    if len(documents) > 1000:
        return [{"status": "review_required", "reason": "routing_batch_bound"}]
    try:
        if routing is None:
            from .review_routing import RoutingProvider

            routing = RoutingProvider(store)
        if decisions is None:
            from .review_authority import ReviewAuthority
            from .review_decisions import ReviewDecisions
            from .review_integrity import CAPABILITIES
            from .review_runtime import (
                recover_review_transactions_locked,
                review_transaction_factory,
            )

            authority = ReviewAuthority(store, CAPABILITIES)
            decisions = ReviewDecisions(
                store, [routing], authority_resolver=authority.resolve,
                transaction_factory=review_transaction_factory(store),
                mutation_guard=recover_review_transactions_locked,
            )
    except _ROUTING_ERRORS as exc:
        return [
            {"document_id": key, "status": "review_required", "reason": str(exc)}
            for key in documents
        ]
    outcomes = []
    confirm = decisions._confirm_locked if lifecycle_held else decisions.confirm
    for document_id in documents:
        try:
            candidates = routing.candidates(document_id)
            rule_id = candidates.get("automatic_rule_id")
            if not rule_id:
                if candidates.get("rule_ids"):
                    outcomes.append({
                        "document_id": document_id, "status": "proposal", **candidates,
                    })
                continue
            plan = decisions.preview("routing", document_id, "apply_rule", {"rule_id": rule_id})
            if not plan["authority"]["automatic_allowed"]:
                outcomes.append({
                    "document_id": document_id, "status": "proposal", **candidates,
                })
                continue
            committed = confirm(
                "routing", document_id, "apply_rule", {"rule_id": rule_id},
                expected_plan_revision=plan["plan_revision"],
                expected_authority_revision=plan["authority_revision"],
                request_id="routing_" + digest([rule_id, document_id, plan["plan_revision"]]),
                principal="rule:" + rule_id,
            )
            outcomes.append({
                "document_id": document_id, "status": "committed",
                "receipt": committed["receipt"]["id"],
            })
        except _ROUTING_ERRORS as exc:
            outcomes.append({
                "document_id": document_id, "status": "review_required", "reason": str(exc),
            })
    return outcomes
