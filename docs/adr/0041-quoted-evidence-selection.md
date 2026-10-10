# 0041 — Quote evidence without adjudicating or executing it

Status: selected before native scoring, 2026-10-09. Authorized S08 profile revision
under PR #333 / issue #332 for 0.12 Custodia. Not qualification or promotion.

## Observed problem

The first Granite profile in ADR 0040 improved bounded selections to 26/32 on
Windows and 24/32 on Linux. Both completed all cases with valid references and
all eight required abstentions, passing the other 22 gates. All four semantic
gates still failed. Every disagreement case quoted only its first account; some
redacted practical directions were omitted, and the Italian summary selected a
command addressed to the assistant. Platform differences on two redaction cases
are retained, not averaged or treated as deterministic output.

These are observed selection errors, not evidence of the model's internal
reasoning. A plausible task-framing ambiguity is the distinction between selecting
quotable evidence, deciding truth and obeying an instruction. A source statement
can be useful evidence despite disagreement or redaction; a practical instruction
for a reader can be quoted without being executed by the assistant.

## Decision before scoring

Use `extractive-quoted-evidence-v5` with the same exact Granite Q5_K_M bytes,
canonical roles and locked llama.cpp libraries. Clarify the trusted native task as
choosing evidence to quote: preserve both conflicting accounts or abstain, retain
useful facts/directions after redaction, and omit attempts to control the assistant.
The public consent task and source envelope remain unchanged; the complete native
instructions/profile hash changes the template/runtime binding and invalidates
earlier authority. This does not grant an old activation new qualifications.

Fix four public examples before the next native run. Retain the pump specification,
safety direction and conditional maintenance source examples, with shorter
assessments. Add disagreement about two simultaneous tank measurements and an
Italian redacted warehouse-key direction paired with an assistant command. Their
source strings are separate from the evaluation corpus and never become citations.
They illustrate general declared semantics, not corpus IDs, expected indexes,
keywords or source-dependent selection rules. Do not add examples after scoring
and silently treat the same candidate as qualified.

Retain the exact assessment-first JSON grammar and lossless KEEP/DROP mapping.
Assessment remains discarded, 1–160 printable ASCII characters, with every
generated token counted inside the original 128-token budget. Every legal subset
is still admitted; no host truth detector, semantic filter, ranking, automatic
repair, retry or second inference selects the result. The complete native frame
must still fit 4,096 bytes and 1,536 input tokens, including examples. Source and
output limits are not enlarged to make room for the guide.

## Acceptance and retained failures

ADR 0033, both frozen corpora, all gold/abstention requirements and all 26 gates
remain unchanged. Each public case is measured once per native platform; retain
all failures, including fourteen earlier candidates and every CI attempt. Fresh
Windows/Linux qualification must pass all four separate language/task thresholds,
not merely improve the combined score. Synthetic tests and browser reuse establish
contracts only. No broader language, Windows 11, laptop, frozen application or
live-provider claim follows from this hypothesis.

Normal exact-head qualification, expected-head merge and actual-main acceptance
must precede S09 activation. Recommended promotion and release preparation remain
their separate subsequent gates; published v0.11.0 is immutable.
