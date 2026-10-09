# 0042 — Trusted demonstration turns for bounded selection

Status: selected before native scoring, 2026-10-09. Authorized S08 profile revision
under PR #333 / issue #332 for 0.12 Custodia. Not qualification or promotion.

## Observed problem

The quotation profile in ADR 0041 regressed to 17/32 gold selections and 4/8
required abstentions on Linux, despite 32 valid outputs and all 19 inherited gates
passing. It preserved conflicting accounts and redacted directions but also kept
editorial notices and instructions to invent information. Windows reached the
unchanged 20-minute workflow timeout; its partial NOT_RUN artifact has 60 base
samples but no final gates or later-phase checkpoints. It does not identify the
phase executing when cancellation occurred. Both outcomes remain failed evidence.

More prose and inline examples did not establish robust selection. Treating the
examples as explicit canonical dialogue turns is a narrower instruction-following
hypothesis, not a claim about the model's internal reasoning or general quality.

## Decision before scoring

Keep the exact Granite Q5_K_M model, llama.cpp libraries and native ABI. Use
`extractive-demonstrated-decisions-v6`: concise system classification instructions
followed by four repository-owned user/assistant demonstration pairs. The final
user turn alone contains the exact ordered approved source strings. Demonstrations
are neither source segments nor selectable evidence. Their complete framed bytes,
including roles and outputs, bind the template/runtime identity before consent.

Fix public examples for a pump specification/safety direction with an editorial
notice, two conflicting tank measurements, a redacted practical direction paired
with an assistant command, and an assistant-only request that must be dropped.
Their strings are separate from the evaluation corpus. All examples obey the
same schema and the smallest task maximum. No source-dependent instruction,
classification, grammar alternative, keyword filter or gold-reference lookup is
introduced. The classifier still makes every selection in one native inference.

The fixed system text is 557 UTF-8 bytes and the complete trusted dialogue prefix
is 1,720 bytes. Canonical role delimiters remain forbidden in source, including
after decoding JSON. The complete frame must fit the unchanged 4,096-byte and
1,536-token input bounds; the 2,000-source-byte fixture remains covered. The
128-token output budget includes assessment and syntax. The 1–160-character
assessment, fresh request-owned grammar/greedy sampler and lossless KEEP/DROP
mapping remain unchanged. Every legal subset remains possible, including empty.
There is no second inference, semantic repair, automatic retry or hidden analysis.

Record intermediate qualification phases and completed S08 public cases before
proceeding. Partial reports remain NOT_RUN until the existing evaluation and
independent observer finish; recording progress cannot create a passed gate.
No case, measurement, timing boundary, threshold, CPU allocation or workflow
timeout is changed. These observations help diagnose interruption, not waive it.

## Acceptance

Retain ADR 0033, both frozen corpora and all fifteen failed candidates/attempts.
Fresh complete Windows/Linux scoring must pass all 26 gates independently with
unchanged language/task, abstention and resource requirements. Synthetic contract
tests do not qualify model quality; browser evidence reuse is limited to unchanged
surfaces. S08 actual-main acceptance still precedes S09 activation, Recommended
promotion and separate release preparation. Immutable v0.11.0 is unchanged.
