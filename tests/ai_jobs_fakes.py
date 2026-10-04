"""S06 public synthetic host authority; never installed as a product provider."""

from dataclasses import replace

from ai_context_fakes import context_plan
from ai_provider_fakes import SyntheticAdapter, provider_case

from provelume.ai_context import preview_context
from provelume.ai_contract import Scope, digest
from provelume.ai_job_contract import Budget
from provelume.ai_job_runtime import ProviderJobAdapter
from provelume.ai_jobs import AiJobs
from provelume.scheduler import SchedulerCoordinator
from provelume.storage import InstanceStore

REF = digest("public-s06-request")
UNITS = 16384 + 2048
BUDGET = Budget(UNITS * 4, UNITS * 8, concurrency=2)


def inputs_for(instance_id):
    inputs = provider_case()
    version = replace(inputs.source.version, instance_id=instance_id)
    source = replace(inputs.source, version=version)
    selections = tuple(replace(s, version=version) for s in inputs.selections)
    current = dict(inputs.current)
    limits = replace(current["request_limits"], max_seconds=300)
    current["request_limits"] = limits
    profiles = tuple(replace(p, limits=limits) for p in inputs.profiles)
    evidence = tuple(
        replace(e, profile_fingerprint=p.fingerprint)
        for e, p in zip(inputs.evidence, profiles, strict=True)
    )
    snapshot = current["snapshot"]
    scopes = tuple(
        replace(s, id=instance_id) if s.kind == Scope.INSTANCE else s for s in snapshot.scopes
    )
    current["snapshot"] = replace(
        snapshot, scopes=scopes, context=replace(snapshot.context, instance_id=instance_id)
    )
    current["rules"] = tuple(
        replace(r, scope=replace(r.scope, id=instance_id)) if r.scope.kind == Scope.INSTANCE else r
        for r in current["rules"]
    )
    current["rules"] = tuple(
        replace(r, route=r.route[:1], limits=limits if r.limits else None) for r in current["rules"]
    )
    preview = preview_context(source, selections, **current)
    gateway = {"profiles": profiles, "evidence": evidence}
    plan = context_plan(preview, source, selections, current, gateway)
    return replace(
        inputs,
        source=source,
        selections=selections,
        current=current,
        preview=preview,
        plan=plan,
        profiles=profiles,
        evidence=evidence,
    )


def manager(root, *, adapter=None, fault=None):
    coordinator = SchedulerCoordinator(InstanceStore.open(root))
    inputs = inputs_for(coordinator.journal.instance_id)
    holder = [inputs]
    jobs = AiJobs(
        coordinator,
        current=lambda ref, route: replace(holder[0], route_index=route),
        adapters={
            inputs.profiles[0].fingerprint: adapter or ProviderJobAdapter(SyntheticAdapter())
        },
        fault=fault,
    )
    coordinator.ai_jobs = jobs
    # The synthetic child-process host explicitly authorizes its own session.
    if jobs.status()["mode"] == "enabled":
        jobs.enable_current_session(requested=True)
    return jobs, holder
