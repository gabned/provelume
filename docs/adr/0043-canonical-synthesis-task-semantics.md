# 0043 — One semantic instruction for host and native synthesis

Status: selected before native scoring, 2026-10-09. Authorized S08 profile revision
under PR #333 / issue #332 for 0.12 Custodia. Not qualification or promotion.

## Observed problem

ADR 0042's demonstrated profile completed all 32 cases with valid references and
all eight required abstentions on both native hosts. Windows selected 23/32 gold
results; Linux selected 22/32. Both passed 22/26 gates, failing all four semantic
gates. Most failures include editorial/testing notices; one Windows conflict case
omits an account, and two Linux cases include assistant commands. All failures
and platform differences remain retained, without averaging or rerun.

The native system instruction had separately abbreviated the task. The canonical
host instruction explicitly excludes text about the document itself, commands to
invent facts or transfer data, and filling a quota with irrelevant text. Separate
wording can drift even when both versions intend the same task. This observable
code difference is not proof of the model's internal reasoning or sole error cause.

## Decision before scoring

Use `extractive-canonical-decisions-v7`. Native instructions reuse the existing
`_selection_instructions` function already used by the host task, then append only
the native response syntax. Do not change that function, its words, the approved
host envelope or the source selectors. This consolidates task semantics rather
than adding corpus phrases or source-dependent rules.

Keep the same four trusted dialogue demonstrations from ADR 0042 byte-for-byte,
the exact Granite Q5_K_M model and llama.cpp libraries, canonical roles, bounded
assessment, grammar and lossless KEEP/DROP mapping. All legal subsets, including
abstention, remain possible in one inference. No host semantic filter, repair,
retry, second inference, hidden analysis or gold-reference lookup is added.

The resulting native system text is 730 UTF-8 bytes and its complete trusted
prefix is 1,893 bytes. The entire native frame still must fit 4,096 bytes and 1,536
input tokens, including examples. The existing 2,000-source-byte/16-paragraph
fixture remains covered. Every generated assessment/syntax/decision token remains
inside 128 tokens; assessment is still discarded. New framing/profile hashes
invalidate prior template/runtime authority, without authorizing old consent.

The regression changes a synthetic public host rule and inspects the actual
native system frame through the adapter. That rule must reach the model and
invalidate the previous template identity; a separately copied native task fails
this contract. This tests framing/authority, not semantic model quality.

## Acceptance

Retain all sixteen failed candidates, both frozen corpora and ADR 0033. Every
language/task threshold, abstention requirement, inherited gate, resource limit,
timing boundary and the 20-minute workflow cap is unchanged. Fresh complete
Windows/Linux qualification must pass all 26 gates independently. Intermediate
diagnostics remain observations, not qualification. S08 actual-main acceptance
still precedes S09 activation, Recommended promotion and separate release work.
Published v0.11.0 remains immutable.
