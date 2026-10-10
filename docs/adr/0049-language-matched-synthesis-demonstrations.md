# 0049 — Language-matched synthesis demonstrations

Status: selected before fresh scoring, 2026-10-10, authorized 0.12/S08 revision
under sole PR #333 / issue #332. No acceptance or Recommended promotion.

## Observed limitation

The ADR 0048 profile completed all 32 valid selections and all eight required
abstentions on Windows and Linux. Both passed 24 of 26 gates, including every
inherited runtime/job/setup gate, English semantic quality and S08 performance.
Windows selected 29 gold results and Linux 30. Both kept only one of two
contradictory Italian accounts; Windows also abstained on a useful Italian fact
alongside a separate hostile command. The original reports and complete CI
inventory remain in the [failure ledger](https://github.com/gabned/provelume/pull/333#issuecomment-6094797668).
Discarded assessments do not establish the internal cause of these selections.

## Bounded language revision

Keep the same Qwen3.5-2B Q5_K_M artifact, complete canonical v8 semantic task,
grammar, assessment/output bounds and lossless KEEP/DROP mapping. Keep English
native prompt bytes unchanged. For Italian tasks, translate the same four
trusted demonstrations into Italian, retaining their facts, decisions and brief
English assessment strings. There is no added demonstration topic or evaluation
case, corpus identifier, source classifier, semantic post-filter or extra inference.
This tests whether matching the task language improves transfer of the existing
editorial rules; it does not assert that the hypothesis will pass qualification.

The selected Italian examples use the existing pump/safety, conflicting tank
quantities, redacted practical direction plus assistant command, and unsupported
fabrication command. They remain trusted example turns, never selectable source
paragraphs or evidence. Actual source text and quoted outputs are unchanged.

Profile `extractive-language-demonstrations-v9` has a closed native descriptor
with an explicit `en` or `it` language. One helper derives the descriptor from
the four allowed host template identities. The worker requires exact agreement
between that language and the host envelope's template ID. Missing, unsupported
or mismatched language fails; untrusted content never chooses a demonstration set.
The runtime configuration binds all four task/language frames, and each template
identity binds its corresponding frame. Old configuration, self-test and consent
cannot authorize the changed profile. The existing checkpoint still requires
identical prefix tokens and Instance scope, so a changed language frame clears it.

## Validation and unchanged acceptance

Contract tests cover descriptor/envelope agreement, source isolation, unsupported
languages, and authority invalidation when either language's examples change.
Source fingerprints verify unchanged English frames, canonical semantic functions,
grammar/mapping, model/runtime/license pins and frozen evaluation corpora.
Synthetic tests cannot establish semantic quality or native latency.

Keep every ADR 0033 criterion and all 26 native gates, numerical thresholds,
two-thread/CPU allocation, context/input/output bounds, memory, cancellation,
sixty-second self-test evidence lifetime and twenty-minute workflow ceiling.
Fresh complete Windows/Linux scoring must retain every result. No old report is
rescored, sample omitted, failed profile retried unchanged or threshold waived.
Complete application/release checks and accepted actual-main integration remain
required before S09. Exact-artifact human and live-provider evidence remain
separate. No package version, tag, publication or published v0.11.0 change.

The separate Windows unit-test correction permits equal monotonic-clock ticks
while retaining distinct request identifiers, exact PID and event-phase checks.
It changes no production clock or numeric acceptance criterion.
