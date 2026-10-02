"""Synthetic contract fixture only: excluded from the installed product package."""

from dataclasses import replace

from provelume.ai_contract import (
    Assurance,
    BaseReceipt,
    Capability,
    ContextBinding,
    GovernanceSnapshot,
    Limits,
    Locality,
    LocalityEvidence,
    Mode,
    Outcome,
    PolicyRule,
    Profile,
    RequestDescriptor,
    Scope,
    ScopeRef,
    SimulatedResult,
    TemplateIdentity,
    digest,
)
from provelume.ai_gateway import receipt, revalidate


def synthetic_case():
    limits = Limits(4096, 128, 2, 10)
    context = ContextBinding(
        "synthetic_instance",
        "synthetic_document",
        "synthetic_version",
        digest("public synthetic context"),
        digest("synthetic consent"),
    )
    request = RequestDescriptor(
        Capability.STRUCTURED_OUTPUT,
        context,
        TemplateIdentity("synthetic_template", digest("template v1")),
        128,
        limits,
    )
    profiles = (
        Profile(
            "synthetic_local",
            "test_fake",
            "not_a_model",
            digest("profile v1"),
            digest("local route v1"),
            (Capability.STRUCTURED_OUTPUT,),
            limits,
        ),
        Profile(
            "synthetic_remote",
            "test_fake",
            "not_a_model",
            digest("profile v1"),
            digest("remote route v1"),
            (Capability.STRUCTURED_OUTPUT,),
            limits,
        ),
    )
    evidence = (
        LocalityEvidence(
            profiles[0].fingerprint,
            Locality.LOCAL,
            Assurance.MANAGED_OFFLINE,
            digest("synthetic offline qualification"),
        ),
        LocalityEvidence(
            profiles[1].fingerprint,
            Locality.REMOTE,
            Assurance.REMOTE,
            digest("synthetic remote qualification"),
        ),
    )
    scopes = (
        ScopeRef(Scope.INSTANCE, context.instance_id),
        ScopeRef(Scope.SOURCE, "source_a"),
        ScopeRef(Scope.CATEGORY, "document_text"),
    )
    snapshot = GovernanceSnapshot(context, scopes, digest("governance v1"), True, True)
    rules = (
        PolicyRule(
            scopes[0],
            digest("instance policy v1"),
            allowed_profiles=tuple(item.id for item in profiles),
            allowed_capabilities=(Capability.STRUCTURED_OUTPUT,),
            limits=limits,
            mode=Mode.FALLBACK,
            route=tuple(item.id for item in profiles),
        ),
        PolicyRule(scopes[1], digest("source policy v1")),
        PolicyRule(scopes[2], digest("category policy v1")),
    )
    return request, dict(snapshot=snapshot, rules=rules, profiles=profiles, evidence=evidence)


class DeterministicFakeAdapter:
    """No model, no transport, no user registration. Calls count simulations only."""

    def __init__(self):
        self.simulations = 0

    def simulate(self, plan, request, **current):
        fresh = revalidate(plan, request, **current)
        if fresh.outcome != Outcome.PLANNED:
            return receipt(fresh)
        if request.context.document_id != "synthetic_document":
            raise ValueError("synthetic fixture required")
        self.simulations += 1
        return SimulatedResult(
            "synthetic_contract_v1",
            digest(["synthetic", fresh.binding]),
            replace(receipt(fresh), outcome=Outcome.SIMULATED),
        )


def assert_not_transmitted(value):
    record = value if isinstance(value, BaseReceipt) else value.receipt
    assert record.transmitted is False
    assert record.attempted_routes == ()
    assert record.usage is None
    assert record.canonical_mutation is False
