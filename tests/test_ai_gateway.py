from __future__ import annotations

import builtins
import itertools
import json
import os
import socket
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from ai_gateway_fakes import (
    DeterministicFakeAdapter,
    assert_not_transmitted,
    simulate_synthetic,
    synthetic_case,
)

from provelume import google_oauth
from provelume.ai_contract import (
    AiContractError,
    Assurance,
    BaseReceipt,
    Capability,
    Limits,
    Locality,
    Mode,
    Outcome,
    PolicyRule,
    Reason,
    RequestDescriptor,
    Scope,
    ScopeRef,
    digest,
)
from provelume.ai_gateway import explain, receipt, resolve_policy, revalidate
from provelume.google_credentials import GoogleCredentialVault
from provelume.service import ProvelumeInstance
from provelume.storage import CANONICAL_KINDS, InstanceStore


def add_rule(current, scope, **restriction):
    ref = ScopeRef(*scope)
    return {
        **current,
        "snapshot": replace(current["snapshot"], scopes=(*current["snapshot"].scopes, ref)),
        "rules": (*current["rules"], PolicyRule(ref, digest(str(scope)), **restriction)),
    }


def denied(plan, reason):
    assert plan.outcome == Outcome.DENIED
    assert reason in plan.reasons
    assert plan.execution_authorized is False


def test_executable_s01_demonstration(monkeypatch):
    request, current = synthetic_case()
    fake = DeterministicFakeAdapter()
    # 1. Only a synthetic simulation; a permitted plan is never execution authority.
    plan = ProvelumeInstance.ai_explain(request, **current)
    assert plan.outcome == Outcome.PLANNED and not plan.execution_authorized
    result = simulate_synthetic(plan, request, adapter=fake, **current)
    assert result.receipt.outcome == Outcome.SIMULATED
    assert_not_transmitted(result)
    repeated = simulate_synthetic(plan, request, adapter=fake, **current)
    assert repeated.to_bytes() == result.to_bytes()
    # 2. Source local-only excludes the expressly configured remote fallback.
    rules = (
        *current["rules"][:1],
        replace(current["rules"][1], local_only=True),
        current["rules"][2],
    )
    local = {**current, "rules": rules}
    plan = explain(request, **local)
    assert plan.routes[0].eligible and not plan.routes[1].eligible
    assert plan.routes[1].reasons == (Reason.LOCAL_ONLY,)
    # 3. A changed exact Version refuses the earlier plan before any fake call.
    changed = replace(request, context=replace(request.context, version_id="synthetic_version_2"))

    def unexpected_call(*args, **kwargs):
        pytest.fail("stale decision reached the adapter")

    monkeypatch.setattr(fake, "simulate", unexpected_call)
    stale = simulate_synthetic(plan, changed, adapter=fake, **local)
    assert stale.outcome == Outcome.DENIED and stale.reasons == (Reason.STALE,)
    assert fake.simulations == 2
    assert_not_transmitted(stale)


@pytest.mark.parametrize("scope", list(Scope))
@pytest.mark.parametrize(
    "restriction,reason", [({"mode": Mode.OFF}, Reason.OFF), ({"deny": True}, Reason.DENY)]
)
def test_off_and_explicit_deny_at_every_scope_never_call_fake(
    scope, restriction, reason, monkeypatch
):
    request, current = synthetic_case()
    if scope in (Scope.INSTANCE, Scope.SOURCE, Scope.CATEGORY):
        changes = {**restriction, **({"route": ()} if "mode" in restriction else {})}
        rules = tuple(
            replace(rule, **changes) if rule.scope.kind == scope else rule
            for rule in current["rules"]
        )
        current = {**current, "rules": rules}
    else:
        current = add_rule(current, (scope, "association"), **restriction)
    plan = explain(request, **current)
    denied(plan, reason)
    fake = DeterministicFakeAdapter()

    def unexpected_call(*args, **kwargs):
        pytest.fail("denied request reached the adapter")

    monkeypatch.setattr(fake, "simulate", unexpected_call)
    assert_not_transmitted(simulate_synthetic(plan, request, adapter=fake, **current))
    assert fake.simulations == 0


def test_source_local_only_cannot_be_overridden_by_project_remote_preference():
    request, current = synthetic_case()
    current["rules"] = tuple(
        replace(rule, local_only=True) if rule.scope.kind == Scope.SOURCE else rule
        for rule in current["rules"]
    )
    current = add_rule(
        current, (Scope.PROJECT, "project_a"), mode=Mode.REMOTE, route=("synthetic_remote",)
    )
    denied(explain(request, **current), Reason.LOCAL_ONLY)


@pytest.mark.parametrize("scope", [Scope.SOURCE, Scope.CATEGORY, Scope.AREA, Scope.PROJECT])
def test_secondary_association_applies_even_with_a_permissive_primary(scope):
    request, current = synthetic_case()
    current = add_rule(current, (scope, "primary"))
    current = add_rule(current, (scope, "secondary"), allowed_profiles=())
    denied(explain(request, **current), Reason.PROFILE)


def test_duplicate_acquisition_rules_do_not_select_a_more_permissive_policy():
    request, current = synthetic_case()
    original = explain(request, **current)
    current["rules"] = (*current["rules"], current["rules"][1])
    assert explain(request, **current) == original
    current["rules"] = (*current["rules"], replace(current["rules"][1], local_only=True))
    denied(explain(request, **current), Reason.CONFLICT)


def test_all_restriction_permutations_and_scope_inventory_order_are_equivalent():
    request, current = synthetic_case()
    current = add_rule(
        current,
        (Scope.PROJECT, "project_a"),
        local_only=True,
        allowed_profiles=("synthetic_local",),
    )
    expected = explain(request, **current)
    for rules in itertools.permutations(current["rules"]):
        assert explain(request, **{**current, "rules": rules}) == expected
    snapshot = replace(current["snapshot"], scopes=tuple(reversed(current["snapshot"].scopes)))
    assert explain(request, **{**current, "snapshot": snapshot}) == expected


def test_exhaustive_restriction_monotonicity_for_profiles_and_limits():
    request, current = synthetic_case()
    candidates = ("synthetic_local", "synthetic_remote")
    for count in range(3):
        for allowlist in itertools.combinations(candidates, count):
            for byte_limit in (128, 256, 4096):
                for local_only in (False, True):
                    restricted = add_rule(
                        current,
                        (Scope.AREA, "area_a"),
                        allowed_profiles=allowlist,
                        local_only=local_only,
                        limits=Limits(byte_limit, 128, 2, 10),
                    )
                    before = resolve_policy(current["snapshot"], current["rules"])
                    after = resolve_policy(restricted["snapshot"], restricted["rules"])
                    assert set(after.allowed_profiles) <= set(before.allowed_profiles)
                    assert all(
                        a <= b
                        for a, b in zip(after.limits.values(), before.limits.values(), strict=True)
                    )
                    initial = explain(request, **current)
                    actual = explain(request, **restricted)
                    assert {r.profile_fingerprint for r in actual.routes if r.eligible} <= {
                        r.profile_fingerprint for r in initial.routes if r.eligible
                    }


def test_missing_conflicting_and_unexpected_scope_inputs_fail_closed():
    request, current = synthetic_case()
    denied(explain(request, **{**current, "rules": current["rules"][:1]}), Reason.MISSING)
    unknown = PolicyRule(ScopeRef(Scope.PROJECT, "unexpected"), digest("rule"))
    denied(explain(request, **{**current, "rules": (*current["rules"], unknown)}), Reason.CONFLICT)
    current = add_rule(
        current, (Scope.PROJECT, "one"), mode=Mode.LOCAL_ONLY, route=("synthetic_local",)
    )
    current = add_rule(
        current, (Scope.PROJECT, "two"), mode=Mode.REMOTE, route=("synthetic_remote",)
    )
    for rules in (current["rules"], tuple(reversed(current["rules"]))):
        denied(explain(request, **{**current, "rules": rules}), Reason.CONFLICT)


@pytest.mark.parametrize("capability", list(Capability)[1:])
def test_reserved_capabilities_remain_unavailable(capability):
    request, current = synthetic_case()
    denied(explain(replace(request, capability=capability), **current), Reason.CAPABILITY)


@pytest.mark.parametrize(
    "field,value",
    [
        ("capability", "invented"),
        ("capability", None),
        ("schema_version", 2),
        ("schema_version", True),
        ("input_bytes", True),
        ("input_bytes", 0),
        ("input_bytes", 1024 * 1024 + 1),
        ("input_bytes", "1"),
        ("input_bytes", float("inf")),
    ],
)
def test_malformed_request_returns_only_closed_error(field, value):
    request, current = synthetic_case()
    row = request.as_record()
    row[field] = value
    assert explain(row, **current).outcome == Outcome.DENIED


@pytest.mark.parametrize("path", ["context", "template", "limits", None])
def test_unknown_fields_missing_fields_and_private_payloads_are_not_echoed(path, caplog):
    request, current = synthetic_case()
    for value in (
        "PRIVATE SYNTHETIC TEXT",
        "C:\\synthetic-private\\note.txt",
        "Bearer fake-secret",
        "x" * 200_000,
    ):
        row = request.as_record()
        target = row[path] if path else row
        target["unexpected"] = value
        plan = explain(row, **current)
        denied(plan, Reason.INVALID)
        assert value not in receipt(plan).to_bytes().decode()
        assert value not in repr(plan)
        with pytest.raises(AiContractError) as caught:
            RequestDescriptor.from_mapping(row)
        assert value not in str(caught.value)
        assert caplog.text == ""
    row = request.as_record()
    del (row[path] if path else row)["schema_version"]
    denied(explain(row, **current), Reason.INVALID)


@pytest.mark.parametrize(
    "field", ["max_input_bytes", "max_output_tokens", "max_attempts", "max_seconds"]
)
@pytest.mark.parametrize("value", [0, -1, True, None, "12", 2**63, 1.5])
def test_invalid_limits_are_rejected(field, value):
    request, current = synthetic_case()
    row = request.as_record()
    row["limits"][field] = value
    denied(explain(row, **current), Reason.INVALID)


@pytest.mark.parametrize("change", ["absent", "unknown", "unqualified", "conflicting", "stale"])
def test_independent_locality_evidence_is_required(change):
    request, current = synthetic_case()
    local, remote = current["evidence"]
    if change == "absent":
        current["evidence"] = (remote,)
    elif change == "unknown":
        current["evidence"] = (replace(local, locality=Locality.UNKNOWN), remote)
    elif change == "unqualified":
        current["evidence"] = (replace(local, assurance=Assurance.UNQUALIFIED), remote)
    elif change == "conflicting":
        current["evidence"] = (local, replace(local, assurance=Assurance.UNQUALIFIED), remote)
    else:
        current["profiles"] = (
            replace(current["profiles"][0], route_revision=digest("new endpoint")),
            current["profiles"][1],
        )
    denied(explain(request, **current), Reason.LOCALITY)


def test_provider_brand_and_loopback_cannot_manufacture_locality():
    request, current = synthetic_case()
    for provider in ("localhost", "ollama", "openai-compatible"):
        profiles = (replace(current["profiles"][0], provider=provider), current["profiles"][1])
        denied(
            explain(request, **{**current, "profiles": profiles, "evidence": ()}), Reason.LOCALITY
        )
    row = request.as_record()
    row["endpoint"] = "http://localhost:11434"
    denied(explain(row, **current), Reason.INVALID)


def test_no_implicit_fallback_or_primary_promotion():
    request, current = synthetic_case()
    instance, *other = current["rules"]
    current["rules"] = (replace(instance, mode=Mode.LOCAL_ONLY, route=("synthetic_local",)), *other)
    assert len(explain(request, **current).routes) == 1
    current["evidence"] = current["evidence"][1:]
    denied(explain(request, **current), Reason.LOCALITY)
    current["rules"] = (instance, *other)
    plan = explain(request, **current)
    denied(plan, Reason.LOCALITY)
    assert plan.routes[1].eligible  # Evaluated, never selected or executed.


@pytest.mark.parametrize(
    "restriction,reason",
    [
        ({"local_only": True}, Reason.LOCAL_ONLY),
        ({"allowed_profiles": ("synthetic_local",)}, Reason.PROFILE),
    ],
)
def test_explicit_fallback_eligibility_is_restricted(restriction, reason):
    request, current = synthetic_case()
    current = add_rule(current, (Scope.AREA, "area_a"), **restriction)
    plan = explain(request, **current)
    assert plan.outcome == Outcome.PLANNED
    assert plan.routes[1].reasons == (reason,)


def test_attempt_budget_and_external_network_gate_apply_to_fallback():
    request, current = synthetic_case()
    request = replace(request, limits=replace(request.limits, max_attempts=1))
    current["snapshot"] = replace(current["snapshot"], external_access=False)
    plan = explain(request, **current)
    assert plan.outcome == Outcome.PLANNED
    assert set(plan.routes[1].reasons) == {Reason.LIMIT, Reason.NETWORK}


@pytest.mark.parametrize(
    "dimension",
    [
        "version",
        "context",
        "consent",
        "governance",
        "policy",
        "template",
        "route",
        "limits",
        "profile",
        "evidence",
        "order",
    ],
)
def test_revalidation_binds_all_relevant_inputs(dimension):
    request, current = synthetic_case()
    plan = explain(request, **current)
    if dimension in ("version", "context", "consent"):
        field = {
            "version": "version_id",
            "context": "context_fingerprint",
            "consent": "consent_revision",
        }[dimension]
        value = "synthetic_version_2" if dimension == "version" else digest("changed")
        request = replace(request, context=replace(request.context, **{field: value}))
        current["snapshot"] = replace(current["snapshot"], context=request.context)
    elif dimension == "governance":
        current["snapshot"] = replace(
            current["snapshot"], revision=digest("new association revision")
        )
    elif dimension == "policy":
        current["rules"] = (
            replace(current["rules"][0], revision=digest("new policy")),
            *current["rules"][1:],
        )
    elif dimension == "template":
        request = replace(
            request, template=replace(request.template, revision=digest("new template"))
        )
    elif dimension in ("route", "profile"):
        field = "route_revision" if dimension == "route" else "revision"
        current["profiles"] = (
            replace(current["profiles"][0], **{field: digest("new profile")}),
            current["profiles"][1],
        )
        current["evidence"] = (
            replace(current["evidence"][0], profile_fingerprint=current["profiles"][0].fingerprint),
            current["evidence"][1],
        )
    elif dimension == "limits":
        request = replace(request, limits=replace(request.limits, max_output_tokens=64))
    elif dimension == "evidence":
        current["evidence"] = (
            replace(current["evidence"][0], qualification_revision=digest("new")),
            current["evidence"][1],
        )
    else:
        current["rules"] = (
            replace(current["rules"][0], route=("synthetic_remote", "synthetic_local")),
            *current["rules"][1:],
        )
    assert explain(request, **current).outcome == Outcome.PLANNED
    denied(revalidate(plan, request, **current), Reason.STALE)


def test_deterministic_serialization_and_forged_plan_is_not_a_token():
    request, current = synthetic_case()
    reconstructed = RequestDescriptor.from_mapping(json.loads(request.to_bytes()))
    assert reconstructed == request
    assert reconstructed.to_bytes() == request.to_bytes()
    plan = explain(request, **current)
    assert explain(reconstructed, **current).to_bytes() == plan.to_bytes()
    denied(revalidate(replace(plan, binding=digest("forged")), request, **current), Reason.STALE)
    with pytest.raises(AiContractError):
        replace(plan, execution_authorized=True)
    with pytest.raises(AiContractError):
        BaseReceipt(Outcome.EXECUTED, plan.binding, ())


def test_no_io_secrets_model_discovery_or_canonical_mutation(tmp_path, monkeypatch, caplog):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text(
        "Synthetic deterministic capture remains useful.", encoding="utf-8"
    )
    instance.ingest(source)
    before = {kind: instance.store.list_canonical(kind) for kind in CANONICAL_KINDS}
    original_bytes = {r["id"]: instance.store.original_bytes(r["id"]) for r in before["originals"]}
    request, current = synthetic_case()

    def forbidden(*args, **kwargs):
        pytest.fail("S01 preflight attempted a forbidden side effect")

    with monkeypatch.context() as patch:
        for owner, names in (
            (socket, ("socket", "getaddrinfo", "gethostbyname", "create_connection")),
            (subprocess, ("Popen", "run")),
            (os, ("getenv",)),
            (google_oauth, ("resolve_google_credential",)),
            (GoogleCredentialVault, ("_access",)),
            (builtins, ("open",)),
            (
                Path,
                (
                    "open",
                    "read_bytes",
                    "read_text",
                    "write_bytes",
                    "write_text",
                    "glob",
                    "rglob",
                    "iterdir",
                ),
            ),
            (InstanceStore, ("open", "original_bytes", "read_config", "list_canonical")),
        ):
            for name in names:
                patch.setattr(owner, name, forbidden)
        plan = instance.ai_explain(request, **current)
        assert plan.outcome == Outcome.PLANNED
        assert_not_transmitted(
            simulate_synthetic(plan, request, adapter=DeterministicFakeAdapter(), **current)
        )
    assert caplog.text == ""
    assert before == {kind: instance.store.list_canonical(kind) for kind in CANONICAL_KINDS}
    assert original_bytes == {
        r["id"]: instance.store.original_bytes(r["id"]) for r in before["originals"]
    }


def test_default_off_missing_consent_and_unmatched_context():
    request, current = synthetic_case()
    rules = (replace(current["rules"][0], mode=None, route=()), *current["rules"][1:])
    denied(explain(request, **{**current, "rules": rules}), Reason.OFF)
    snapshot = replace(current["snapshot"], consent_granted=False)
    denied(explain(request, **{**current, "snapshot": snapshot}), Reason.CONSENT)
    denied(
        explain(
            replace(request, context=replace(request.context, document_id="another")), **current
        ),
        Reason.CONTEXT,
    )


def test_limits_capability_and_category_ceilings_cannot_be_enlarged():
    request, current = synthetic_case()
    restricted = add_rule(current, (Scope.CATEGORY, "restricted_category"), allowed_capabilities=())
    denied(explain(request, **restricted), Reason.CAPABILITY)
    restricted = add_rule(current, (Scope.PROJECT, "project_a"), limits=Limits(100, 64, 1, 5))
    denied(explain(request, **restricted), Reason.LIMIT)
    denied(explain(replace(request, input_bytes=4097), **current), Reason.LIMIT)
    profile = replace(current["profiles"][0], capabilities=(Capability.VISION,))
    current["profiles"] = (profile, current["profiles"][1])
    assert Reason.CAPABILITY in explain(request, **current).routes[0].reasons


def test_equivalent_allowlist_order_and_duplicate_evidence_do_not_change_binding():
    request, current = synthetic_case()
    expected = explain(request, **current)
    current["rules"] = (
        replace(current["rules"][0], allowed_profiles=("synthetic_remote", "synthetic_local")),
        *current["rules"][1:],
    )
    current["evidence"] = (*reversed(current["evidence"]), current["evidence"][0])
    assert explain(request, **current) == expected


def test_oversized_and_malformed_security_inventories_fail_closed():
    request, current = synthetic_case()
    for key, value in (
        ("rules", current["rules"] * 100),
        ("profiles", current["profiles"] * 9),
        ("evidence", current["evidence"] * 17),
        ("snapshot", {}),
        ("rules", ({},)),
        ("profiles", ({},)),
        ("evidence", ({},)),
    ):
        denied(explain(request, **{**current, key: value}), Reason.INVALID)
    denied(explain(request, **{**current, "profiles": ()}), Reason.ROUTE)
    for item in (
        request,
        request.context,
        request.template,
        request.limits,
        current["snapshot"],
        *current["rules"],
        *current["profiles"],
        *current["evidence"],
    ):
        with pytest.raises(AiContractError, match=Reason.SCHEMA):
            replace(item, schema_version=2)
    with pytest.raises(AiContractError):
        replace(current["snapshot"], scopes=current["snapshot"].scopes * 2)
    with pytest.raises(AiContractError):
        replace(current["snapshot"], scopes=current["snapshot"].scopes[:1])
    with pytest.raises(AiContractError):
        replace(current["evidence"][0], locality="invented")


def test_planned_receipts_do_not_echo_valid_but_sensitive_labels():
    request, current = synthetic_case()
    label = "synthetic_private_label"
    request = replace(request, template=replace(request.template, id=label))
    plan = explain(request, **current)
    assert plan.outcome == Outcome.PLANNED
    for record in (plan, receipt(plan)):
        assert label not in record.to_bytes().decode()
        assert "synthetic_document" not in record.to_bytes().decode()
        assert "synthetic_local" not in record.to_bytes().decode()
