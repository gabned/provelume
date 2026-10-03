"""Pure internal planning only. There is deliberately no dispatch/adapter registry."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .ai_contract import (
    MAX_ASSOCIATIONS,
    MAX_DESCRIPTOR_BYTES,
    MAX_PROFILES,
    AiContractError,
    Assurance,
    BaseReceipt,
    Capability,
    EffectivePolicy,
    GovernanceSnapshot,
    Limits,
    Locality,
    LocalityEvidence,
    Mode,
    Outcome,
    Plan,
    PolicyRule,
    Profile,
    Reason,
    RequestDescriptor,
    RouteDecision,
    Scope,
    digest,
    require,
    sequence,
)


def resolve_policy(snapshot: GovernanceSnapshot, rules: tuple[PolicyRule, ...]) -> EffectivePolicy:
    """Intersect every applicable ceiling; only route preferences can be inherited."""
    require(type(snapshot) is GovernanceSnapshot)
    sequence(rules, MAX_ASSOCIATIONS * 2, empty=False)
    require(all(type(rule) is PolicyRule for rule in rules))
    by_scope = {}
    expected = {(scope.kind, scope.id) for scope in snapshot.scopes}
    for rule in rules:
        key = (rule.scope.kind, rule.scope.id)
        require(key in expected, Reason.CONFLICT)
        require(key not in by_scope or by_scope[key] == rule, Reason.CONFLICT)
        by_scope[key] = rule  # Identical repeated acquisitions cannot change the decision.
    require(set(by_scope) == expected, Reason.MISSING)
    ordered = tuple(by_scope[key] for key in sorted(by_scope))
    require(not any(rule.deny for rule in ordered), Reason.DENY)
    require(not any(rule.mode == Mode.OFF for rule in ordered), Reason.OFF)
    instance = by_scope[(Scope.INSTANCE, snapshot.context.instance_id)]
    require(instance.mode is not None, Reason.OFF)
    require(
        instance.allowed_profiles is not None
        and instance.allowed_capabilities is not None
        and instance.limits is not None,
        Reason.MISSING,
    )
    profiles = set(instance.allowed_profiles)
    capabilities = set(instance.allowed_capabilities)
    limits = instance.limits.values()
    for rule in ordered:
        if rule.allowed_profiles is not None:
            profiles.intersection_update(rule.allowed_profiles)
        if rule.allowed_capabilities is not None:
            capabilities.intersection_update(rule.allowed_capabilities)
        if rule.limits is not None:
            limits = tuple(min(a, b) for a, b in zip(limits, rule.limits.values(), strict=True))
    preferences = [rule for rule in ordered if rule.mode is not None]
    precedence = {scope: index for index, scope in enumerate(Scope)}
    priority = max(precedence[rule.scope.kind] for rule in preferences)
    nearest = [rule for rule in preferences if precedence[rule.scope.kind] == priority]
    selections = {(rule.mode, rule.route) for rule in nearest}
    require(len(selections) == 1, Reason.CONFLICT)
    mode, route = selections.pop()
    policy_fingerprint = digest([rule.as_record() for rule in ordered])
    return EffectivePolicy(
        mode,
        any(rule.local_only or rule.mode == Mode.LOCAL_ONLY for rule in ordered),
        tuple(sorted(profiles)),
        tuple(sorted(capabilities)),
        Limits(*limits),
        route,
        policy_fingerprint,
    )


def _locality(profile: Profile, evidence: tuple[LocalityEvidence, ...]) -> Locality:
    matching = {item for item in evidence if item.profile_fingerprint == profile.fingerprint}
    require(len(matching) == 1, Reason.LOCALITY)
    item = matching.pop()
    if (item.locality, item.assurance) == (Locality.LOCAL, Assurance.MANAGED_OFFLINE):
        return Locality.LOCAL
    if (item.locality, item.assurance) == (Locality.REMOTE, Assurance.REMOTE):
        return Locality.REMOTE
    raise AiContractError(Reason.LOCALITY)


def _route_reasons(
    request: RequestDescriptor,
    snapshot: GovernanceSnapshot,
    policy: EffectivePolicy,
    profile: Profile,
    evidence: tuple[LocalityEvidence, ...],
    position: int,
) -> tuple[Reason, ...]:
    reasons = set()
    if profile.id not in policy.allowed_profiles:
        reasons.add(Reason.PROFILE)
    if request.capability not in profile.capabilities:
        reasons.add(Reason.CAPABILITY)
    try:
        locality = _locality(profile, evidence)
        if policy.local_only and locality != Locality.LOCAL:
            reasons.add(Reason.LOCAL_ONLY)
        if not snapshot.external_access and locality == Locality.REMOTE:
            reasons.add(Reason.NETWORK)
        if policy.mode == Mode.REMOTE and locality != Locality.REMOTE:
            reasons.add(Reason.LOCALITY)
    except AiContractError as error:
        reasons.add(error.code)
    if position >= min(policy.limits.max_attempts, request.limits.max_attempts):
        reasons.add(Reason.LIMIT)
    if any(a > b for a, b in zip(request.limits.values(), profile.limits.values(), strict=True)):
        reasons.add(Reason.LIMIT)
    return tuple(sorted(reasons))


def explain(
    request: RequestDescriptor | dict[str, Any],
    *,
    snapshot: GovernanceSnapshot,
    rules: tuple[PolicyRule, ...],
    profiles: tuple[Profile, ...],
    evidence: tuple[LocalityEvidence, ...],
) -> Plan:
    """A plan is not an execution token. Inputs are snapshots, never I/O handles.

    The host supplies governance and qualification independently of the request.
    No S01 user route can dispatch this plan, including a forged planned record.
    """
    try:
        if type(request) is not RequestDescriptor:
            request = RequestDescriptor.from_mapping(request)
        require(type(snapshot) is GovernanceSnapshot)
        sequence(profiles, MAX_PROFILES)
        sequence(evidence, MAX_PROFILES * 2)
        require(all(type(item) is Profile for item in profiles))
        require(all(type(item) is LocalityEvidence for item in evidence))
        require(len({item.id for item in profiles}) == len(profiles), Reason.CONFLICT)
        policy = resolve_policy(snapshot, rules)
        require(request.context == snapshot.context, Reason.CONTEXT)
        require(snapshot.consent_granted, Reason.CONSENT)
        require(
            request.capability == Capability.STRUCTURED_OUTPUT
            and request.capability in policy.allowed_capabilities,
            Reason.CAPABILITY,
        )
        require(request.input_bytes <= request.limits.max_input_bytes, Reason.LIMIT)
        require(
            all(
                a <= b for a, b in zip(request.limits.values(), policy.limits.values(), strict=True)
            ),
            Reason.LIMIT,
        )
        require(bool(policy.route), Reason.ROUTE)
        profile_map = {item.id: item for item in profiles}
        require(all(identity in profile_map for identity in policy.route), Reason.ROUTE)
        routes = tuple(profile_map[identity] for identity in policy.route)
        # Order-independent security inputs; ordered routes deliberately remain ordered.
        bound = {
            "schema_version": 1,
            "request": request.as_record(),
            "snapshot": replace(
                snapshot,
                scopes=tuple(sorted(snapshot.scopes, key=lambda item: (item.kind, item.id))),
            ).as_record(),
            "policy": policy.as_record(),
            "profiles": [profile.as_record() for profile in routes],
            "evidence": sorted(
                {item.fingerprint: item.as_record() for item in evidence}.values(), key=digest
            ),
        }
        from .representations import canonical_json_bytes

        require(len(canonical_json_bytes(bound)) <= MAX_DESCRIPTOR_BYTES, Reason.LIMIT)
        decisions = tuple(
            RouteDecision(index, profile.fingerprint, not reasons, reasons)
            for index, profile in enumerate(routes)
            for reasons in [_route_reasons(request, snapshot, policy, profile, evidence, index)]
        )
        # A denied primary route never silently promotes a fallback to primary.
        allowed = decisions[0].eligible
        return Plan(
            Outcome.PLANNED if allowed else Outcome.DENIED,
            () if allowed else decisions[0].reasons,
            digest(bound),
            policy.policy_fingerprint,
            request.limits,
            decisions,
        )
    except AiContractError as error:
        return Plan(Outcome.DENIED, (error.code,), None, None, None, ())


def revalidate(plan: Plan, request: RequestDescriptor | dict[str, Any], **current: Any) -> Plan:
    """Recompute rather than trusting a previous binding, outcome or candidate receipt."""
    fresh = explain(request, **current)
    if type(plan) is not Plan or plan != fresh:
        return Plan(Outcome.DENIED, (Reason.STALE,), None, None, None, ())
    return fresh


def receipt(plan: Plan) -> BaseReceipt:
    require(type(plan) is Plan and plan.outcome in (Outcome.PLANNED, Outcome.DENIED))
    return BaseReceipt(plan.outcome, plan.binding, plan.reasons)
