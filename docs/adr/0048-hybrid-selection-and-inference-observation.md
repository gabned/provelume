# 0048 — Hybrid selection, stable input reuse and concurrent inference

Status: selected before fresh scoring, 2026-10-09, authorized 0.12/S08 revision
under sole PR #333 / issue #332. Not acceptance or Recommended promotion.

## Evidence and bounded correction

Candidate21 used the ADR 0047 Qwen3.5-2B Q5_K_M artifact. Both hosts completed
32 valid selections and all eight required abstentions. Windows selected 30 gold
results; Linux selected 28. Every semantic miss discarded a useful fact alongside
a separate hostile instruction. This establishes the observable failure, not the
model's hidden reason. Its discarded assessment is neither retained nor authority.
All failed reports remain unchanged; no report is rescored or sample omitted.

Keep that exact model, conversion, license, native libraries, four trusted
demonstrations and complete legal decision grammar. Canonical task v8 clarifies
that names and labels of real objects are subject matter, unlike editorial labels
about writing the document. Evaluate each paragraph on its content: hostile
instructions in one do not invalidate facts in another. Host preview and native
system use the same rule; changed framing invalidates earlier template/runtime
authority. No corpus identifiers, example facts, expected selections, semantic
post-filter, additional inference or prompt sweep. Fresh native scoring must test
whether this general clarification helps without harming the other cases.

## Preserve more of the exact stable input

Windows S06 warm first-response times were 5.657–5.907 seconds; S07 warm was
5.313 seconds against the unchanged five-second limit. The recurrent checkpoint
saved only 128 tokens of the legacy context-check envelope, recomputing part of
the identical host-owned header on every new preview. S08's longer exact prefix
already reused correctly and passed its latency gates.

For a scoped, exact canonical legacy envelope, checkpoint through its complete
schema/trusted header, before the changing untrusted preview fingerprint and
segments. Validate the known template identity and unchanged instruction bytes;
unknown/noncanonical input retains the ordinary bounded fallback. This changes
only the computation boundary: the complete model input and dialogue roles stay
byte-identical. Content never gains authority by looking like an envelope. Every
saved token must still match in the same Instance; changed scope, shorter or
divergent tokens clear state. Keep one 64 MiB maximum checkpoint, no recurrent
rollback history, fresh suffix/logits, full logical input accounting and the same
wall-time/RSS limits. New synthetic regressions verify changed private suffixes,
fresh preview fingerprints and changed task instructions.

## Observe actual inference, including prompt processing

Candidate21's S07 one-token answer finished about 0.1 seconds after first output,
before a real Capture probe could finish. The existing observer waited for first
output and therefore failed to prove concurrent work on Windows cold and both
Linux samples. Those failures remain inconclusive, never promoted to passes.

S07 now starts its real Capture/search probe at the worker's first native prefill,
immediately before llama_decode, after tokenization/state restoration. The parent
accepts one closed event bound to a fresh request identifier and the current child
PID; a stale, duplicate, malformed or out-of-order event fails. The observer records
the explicit native_prefill phase and requires the same request/worker to remain
active before and after the complete probe. A too-short inference still fails.
There is no sleep, padded answer, longer prompt, synthetic busy flag or substitute
benchmark. This measures ADR 0031's Capture/search **under inference**, including
its expensive prompt processing. It does not claim overlap with output decoding.
First-output/total latency remains measured separately from request admission.
S08's observed-generation and all cancellation measurements remain unchanged.

Linux also had one S05 Capture exceedance (0.849585 seconds against 0.538664).
Give only the disposable worker a nice floor of 10 before creating native threads;
never increase an already lower inherited priority. Verify and report its effective
priority. Windows already has below-normal Job Object priority. The application
priority is unchanged. This is a scheduling hypothesis, not proof that it eliminates
filesystem latency: all fresh native Capture samples must still pass.

## Application correction and acceptance

A separate application test reproduced filesystem ingestion racing the startup
scheduler's short lifecycle ownership. Wait up to two seconds before ingestion,
then read current source bytes under the acquired lock. Persistent contention
still fails before domain mutation. No ingestion replay or scheduler exemption.
New deterministic tests retain the before-fix failures and verify preserved old
Originals and the current source version after the short wait.

ADR 0033, both frozen corpora and gold remain byte-identical. All 26 native gates,
numeric thresholds, two threads/CPUs, input/output/context, memory, cancellation,
privacy controls, durable writes and twenty-minute workflow bound stay fixed.
The observer adds request/phase evidence; it cannot accept old missing evidence.
Local contract tests are not native quality, responsiveness or containment proof.
Require fresh complete Windows/Linux qualification, application/release checks and
actual-main acceptance before S09. Human exact-artifact and live-provider evidence
remain separate. No version, publication or change to published v0.11.0.
