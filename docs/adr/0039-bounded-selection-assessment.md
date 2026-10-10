# 0039 — Bounded assessment before paragraph selection

Status: selected before native scoring, 2026-10-09. Maintainer-authorized profile
revision within S08 PR #333 / issue #332, for 0.12 Custodia. No Recommended or
publication authority.

## Evidence and hypothesis

Twelve candidates remain failed in the owner ledger. The 4B Q2_K candidate's
Windows run stopped with an idle-cleanup/admission race after 31 inherited warm
samples; its observed first-output maximum was 8.828 seconds. Linux completed
60 such samples, with an 8.893-second maximum, then failed governed-job timing
and setup. Both exceed the fixed five-second warm gate; S08 was not reached.
Correcting the race cannot make that measured configuration acceptable.

Re-evaluate the exact official Qwen3-1.7B Q4_K_M bytes pinned in ADR 0035. Its
previous profile passed all nineteen inherited gates and S08 performance, but
binary decisions selected irrelevant neighboring paragraphs. Evaluate one change
to that semantic method: a short English assessment before the decision array,
within a single native response. The hypothesis is that naming the distinction
between subject matter and editorial/assistant instructions before choosing helps
this small model. No acceptance claim follows from this hypothesis.

## Closed response and authority

Use the official non-thinking template and greedy decoding. This does not enable
an unbounded thinking mode. The worker grammar admits exactly an object containing
`assessment` followed by `decisions`. Assessment is 1–160 printable ASCII characters,
excluding double quote and backslash; decisions contain exactly one KEEP or DROP
per source paragraph, with the same two/three-KEEP ceiling. Two fixed bilingual
editorial examples illustrate this format without using qualification fixtures.
After revalidating the host's indexed envelope, native input is the corresponding
ordered JSON array of paragraph strings, matching those examples. No text is
filtered, reordered or rewritten; checked positions still bind every citation.
Dropping redundant native index wrappers also saves input bytes. Provider payloads
and the original host consent envelope retain their existing contracts.

The worker validates the entire object, discards assessment and losslessly maps
KEEP positions to source indexes. Assessment is untrusted, is not scored as truth,
does not affect validation or selection, and never enters results, receipts or logs.
It can neither grant authority nor override a decision. Every generated token,
including assessment and syntax, counts against the unchanged 128-token output
budget and actual usage. Truncated/invalid responses fail closed. No retry, second
inference, semantic post-filter, source-dependent grammar or corpus oracle.

The new format and exact instructions bind template/runtime identities and
invalidate earlier self-test/consent evidence. The 1.7B registry entry becomes a
candidate again, without restoring prior activation authority; it needs a fresh
explicit technical test and consent. Both failed 4B and Qwen2.5 entries remain
readable/removable and refused for installation, activation and use. No automatic
download, deletion, model switch or fallback. Historical retirement and failed
qualification evidence remain retained.

## Lifecycle correction and unchanged acceptance

An idle timer closing the previous worker must not be mistaken for another active
inference. A separate nonblocking request reservation admits one caller only; it
waits cancellably at most two seconds for existing lifecycle cleanup. Other
callers fail busy immediately. Cleanup retains the global process slot until exit
is confirmed. The wait counts inside the original sixty-second request deadline.
Regression tests first reproduce the race, then cover completion, cancellation,
timeout, concurrent refusal and cancellation of an already loaded worker.
Stopping also revokes model reuse before attempting termination. If exit cannot
be confirmed, process ownership and the global slot remain held, but a new request
cannot send a payload or accept a late response from that worker. A regression
first reproduced this stale-response bug and now verifies refusal and recovery
only after confirmed exit.

The native report declares S06, S07 and S08 requirements before any measurement,
so early failures retain all 26 gates as NOT_RUN where appropriate. This repairs
an omitted S07 field in the failed Windows report, not its outcome.

Keep ADR 0033 and both quality corpora byte-identical. Every case, gold selection,
abstention, task/language score, CPU/context/memory/output ceiling, latency,
cancellation, Capture/search bound, OS observer and twenty-minute workflow limit
remains unchanged. All exact-head and actual-main checks must pass before S08
acceptance. S09 and final release qualification remain subsequent work.
