# 0036 — Explicit paragraph decisions for extractive synthesis

Status: candidate selected before scoring, 2026-10-09. Same maintainer-authorized
S08 profile revision and sole PR #333 owner; not Recommended or release authority.

## Evidence and decision

The first Qwen3 profile preserves schema validity, but its Windows and Linux
measurements still include editorial boilerplate and injected instructions in
selected excerpts. Both score 17/32 correct selections and 6/8 required abstentions,
including failure on Italian missing-content abstention. The retained native reports
and exact-head application failure remain failures; no sample or gate is removed.
Format constraints cannot establish semantic correctness.

Replace the native index-list decision with **one explicit KEEP/DROP decision per
paragraph**, in a single inference. Use the same pinned Qwen3 weights, b11379
libraries, official non-thinking template and fresh grammar/greedy sampler. The
generic editorial instruction distinguishes subject matter and practical directions
from editorial metadata, missing-content notices and instructions to the assistant.
It states that the excerpt maximum is a ceiling, not a target count. It contains no
evaluation fixture, expected index or corpus-specific phrase filter.

The grammar depends only on the validated segment count and task maximum. It
admits exactly one decision for each of at most 16 paragraphs, with at most two
KEEP decisions for summaries or three for key points. Every legal subset, including
the empty subset, remains representable. At most 697 alternatives are possible.
The worker validates the complete array and translates each KEEP **without any
semantic filtering** into its original index. All DROP means abstention. Invalid,
incomplete or excessive decisions fail; none are repaired or trimmed.

The public candidate remains the original bounded schema_version/status/references
JSON and passes the existing independent candidate/source validator. Providers
retain that public schema. Native model usage and timing count the actual decision
array, and only its validated representation is translated. There is no second
inference, hidden retry, post-hoc quality oracle or new content access. This is a
format adaptation of the same authorized selection task, not generated prose.

`extractive-decisions-v2` binds both template and runtime configuration identities.
The original approved envelope is rechecked before the native task's output format
is adapted. Source remains exclusively in the untrusted user message. Old consent
and runtime evidence do not authorize the revised profile.

## Acceptance stays fixed

Retain ADR 0033's 32 original cases and gold, all 26 native gates, EN/IT task
matrix, input/output budgets, 2-CPU/3-GiB hard limits, 2-GiB RSS threshold,
cancellation, worker deadline and workflow timeout. The ordinary S05 quality
corpus also remains unchanged. Local format/translation tests prove boundaries,
never model quality. Every previous native and local failure stays in the ledger.

Separately, the Windows application suite exposed transient lifecycle contention
during consent. Consent/configuration and enqueue wait at most two seconds **before**
their transaction, then revalidate current authority. Persistent contention yields
the existing localized HTTP conflict, consumes the old form and performs no replay.
Cancellation polling/control and settlement do not gain a new wait. Deterministic
tests hold the real Instance lock, exercise release/timeout/revocation, and verify
zero job/adaptor work on refusal. This does not relax any native quality gate.
The bounded wait runs in an owned thread task, outside the ASGI event loop, so
search/navigation remains responsive while the Instance is busy. The existing
two-task cap remains. Disconnecting a request does not abandon its accepted
mutation; shutdown retains ownership and drains it. A concurrent-navigation
regression fails against the initial synchronous candidate and passes only after
moving these waits off the event loop. The interrupted initial full run remains
unqualified; all final checks must run again on unchanged source.
