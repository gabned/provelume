# 0034 — Structured decoding for bounded synthesis

Status: candidate, before scoring. Maintainer authorized the AI profile revision
and subsequent S09 on 2026-10-09. Sole S08 owner: PR #333 / issue #332. The seven
failed candidates under ADR 0033 remain failed and their evidence is retained.

## Problem and decision

The unconstrained reader returned Markdown instead of the closed result schema,
selected editorial notes or hostile instructions, and sometimes omitted useful
facts. More prompt examples did not establish quality. Formatting and semantic
selection are separate problems; accepting fenced responses would not solve both.

Use a task-specific trusted system instruction and native GBNF constrained greedy
decoding for S08. The host passes an explicit task descriptor, independently of
source text. Only bounded, source-ordered, unique segment indexes or abstention
can be emitted. Each request owns a fresh sampler; prefix reuse never reuses
grammar state. No grammar, executable code or system instruction comes from a
document. The ordinary result validator and fresh authority checks remain required.
The task recognizes practical instructions in the subject matter (such as contact
or collection details), while excluding commands to the assistant and editorial
or missing-content notices. It has no corpus-specific text filters or gold lookup.

First isolate this runtime change using the exact Qwen2.5-1.5B Q4_K_M weights and
llama.cpp b11379 library bytes from ADR 0031. This revises the runtime configuration
and task identity, invalidating old consent/self-test bindings. It does not change
model installation or license identity. A weight replacement, if needed after
this measurement, must be pinned with provenance before its separate scoring.

## Unchanged acceptance

Preserve ADR 0033 and the exact 32-case corpus
`95d9e829cbe25ec2227be7b55d0b6c73507180ebbbe1fd213085bbcdc40fd488`.
Every existing quality, abstention, RAM, cold/warm latency, cancellation, Capture,
search and independent no-egress gate still applies, including all S05–S07 gates.
No dropped outliers, replaced gold, relaxed parser, retry, deadline, CPU, workflow
timeout or resource increase. A grammar proves shape, never relevance or truth.

Capture profiling uses separate synthetic diagnostic probes after qualification
measurements, including final unload/memory observations. These are labelled
DIAGNOSTIC_ONLY and never replace samples, choose a favorable baseline or establish
a pass. Report bounded function-level aggregate timings without private paths or
document contents. Diagnose before making further Windows filesystem changes.

Real scoring remains on the existing observed native Windows/Linux CI profiles;
synthetic ABI and browser tests do not qualify model quality. S09 promotion awaits
full actual-main acceptance of S08. AI S08/S09 belong to 0.12 Custodia; v0.11.0
remains immutable and publication keeps its independent owner and gates.
