# 0050 — Language-matched canonical synthesis instructions

Status: selected before fresh scoring, 2026-10-10, authorized 0.12/S08 revision
under sole PR #333 / issue #332. No acceptance or Recommended promotion.

## Observed limitation

The ADR 0049 candidate passed all 26 native gates and all 32 gold selections on
Linux. Windows passed 25 gates and 31 gold selections; it retained one of two
contradictory Italian accounts in a summary. Italian key points, English tasks,
all required abstentions and every runtime/performance gate passed on both hosts.
The complete first-attempt reports and CI inventory remain in the
[failure ledger](https://github.com/gabned/provelume/pull/333#issuecomment-6095149218).
The differing selections do not establish an internal reasoning cause or a
bitwise generation guarantee across platforms.

## Complete Italian task framing

Keep Qwen3.5-2B Q5_K_M, the same four demonstrations in each language, grammar,
assessment bounds, lossless selection mapping and English native prompt bytes.
For Italian tasks, translate the complete canonical selection instructions and
the final selection request into Italian. The host and worker share that same
trusted translation; do not abbreviate the native task or add a corpus-specific
rule. The translation preserves subject matter, redaction, negations, conditions,
practical directions, paired contradictory accounts, editorial exclusions,
assistant-command exclusions, independent paragraph judgement and the maximum.
Closed JSON field names and the brief discarded English assessment stay unchanged.

Profile `extractive-language-instructions-v10` selects instructions and examples
only from the host-owned task language. The native descriptor/envelope must agree.
Template/runtime fingerprints bind the exact framing and invalidate old consent
and self-test authority. Neither source content nor an untrusted result selects
the language or changes the rules. One inference, no post-filter, repair, added
example topic, hidden retry or automatic resend.

This tests complete instruction-language alignment after the narrower example
translation improved measured results. It is a hypothesis, not a qualification
claim. English frames and the protected grammar/mapping/demonstration ASTs are
frozen against ADR 0049 before scoring.

## Validation and unchanged acceptance

Contract tests cover host/native agreement in both languages, language-specific
authority invalidation, stale instruction rejection and source isolation.
Native input checks still reject a complete frame exceeding the existing bounds
before consent. Synthetic tests do not establish semantic quality or speed.

ADR 0033, both frozen corpora/gold and all 26 gates on Windows and Linux remain
unchanged: two threads/CPUs, existing context/input/output/memory limits,
cancellation, sixty-second self-test lifetime and twenty-minute job ceiling.
Retain every fresh observation and all earlier failures. Complete exact-head
CI/reviews, normal merge and actual-main qualification precede S09. Human
exact-artifact and live-provider evidence remain separate. No version, tag,
publication or immutable v0.11.0 change.
