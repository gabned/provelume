# 0051 — Source reporting and physical CPU selection

Status: selected before fresh scoring, 2026-10-10, authorized 0.12/S08 revision
under sole PR #333 / issue #332. No acceptance or Recommended promotion.

## Retained observations

The complete Italian instruction translation in ADR 0050 is not accepted.
Both native jobs reached the unchanged twenty-minute ceiling. Linux completed
32 valid selections, 30 gold and eight required abstentions; both mixed Italian
content/injection cases incorrectly abstained. Windows retained 21 cases, 20 gold,
and failed inherited warm/S06/S07 and S08 cold timing criteria. Final integrity
and network observations remain incomplete. Original reports and all observations
are retained in the [candidate24 ledger](https://github.com/gabned/provelume/pull/333#issuecomment-6095609356).

Both runners used Intel CPUs, whereas candidate23 used AMD CPUs. Unchanged base
warm inference also slowed. Existing containment selects the first two logical
CPUs without recording physical topology. The reports do not establish whether
those two CPUs shared a core; neither that cause nor semantic success is assumed.

## Selected bounded revision

Profile `extractive-source-reporting-v11` returns to the common canonical English
instructions and selection request of ADR 0049, with the same four English and
Italian demonstration pairs. It clarifies the existing contradiction rule:
selection records what a source reports, without deciding which account is true.
Paired contradictory accounts remain both selected or both omitted. All other
selection rules, grammar, discarded assessment, mapping and one-inference contract
remain unchanged. Source content never supplies instructions or an output grammar.
Host and native worker share the revised canonical task; exact framing identities
invalidate old consent and technical evidence in both languages.

The worker selects one logical CPU from each of two distinct OS-reported physical cores
within its already permitted affinity. Linux reads the kernel package/core
topology for allowed CPUs. Windows reads bounded current-group processor-core
records through GetLogicalProcessorInformation and intersects them with the
process affinity mask. Incomplete, overlapping, unknown or insufficient topology
fails closed. No wider processor mask, third CPU, thread, priority increase or
parent-affinity change is introduced. The worker reports selected logical CPUs,
observed allowed core counts and whether the previous first-two-logical choice
would share a core. The configuration binds this selection policy.

Microsoft's [API contract](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getlogicalprocessorinformation)
and [core relationship structure](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-system_logical_processor_information)
were reviewed before implementation. Current-group scope is retained; this is not
a new multi-group runtime profile. Fresh native reports must establish actual
topology, containment and timing. Virtualized topology does not reveal unobserved
hypervisor placement. A synthetic topology test is not a speed claim.

## Unchanged qualification

Keep the pinned Qwen3.5-2B Q5_K_M model, llama.cpp b11379 libraries and licenses,
ADR 0033 and both frozen corpora/gold. All 26 gates, two threads/CPUs, input/output,
context, memory, latency, cancellation, self-test lifetime and twenty-minute job
ceiling remain unchanged. No rescoring, unchanged failed-profile rerun, retry,
semantic post-filter or output repair. Record unsupported topology explicitly.

Full unchanged-source checks, exact-head CI/reviews, normal expected-head merge
and actual-main qualification precede S09. Human exact-artifact and live-provider
evidence remain separate. No version, tag, publication or v0.11.0 change.
