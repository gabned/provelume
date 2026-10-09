# 0033 — Bounded extractive document synthesis

Status: development candidate for 0.12/S08 (#332), before real candidate scoring.
Recommended promotion and publication remain S09 and its separate release owner.

## Decision

Use the locked ADR 0031 local runtime/model and S06 jobs for manually requested
single-current-Version summaries (one or two excerpts) and key points (one to
three excerpts). The model selects segment indexes; only exact approved, locally
redacted source text is rendered. Label the output as selected excerpts, not an
independent factual verification or a free-form generated summary. Citations
establish provenance, not truth, representativeness or completeness.

The initial profile admits one existing text/plain representation output and an
Original of at most 1 MiB. Paragraphs are indivisible, within page anchors: select
at most 16 whole paragraphs and 2,000 UTF-8 source bytes. Oversized paragraphs are
excluded, not truncated; exclusions/partial coverage are visible before consent.
Offsets address original code points before NFC, newline normalization and email
redaction. The complete request envelope retains the 4,096-byte bound and the
native 128-token output limit. The closed candidate byte bound remains 128.
The model returns schema_version=1, status=selected|abstained and source-ordered,
unique references. Exact UNKNOWN is an alternate abstention spelling because the
unchanged native system prompt requires it for absent facts. Other free text,
markdown, URLs, additional keys, unsupported or excessive references fail closed.

Fresh source, policy across all associated scopes, Instance external-access and
configuration are checked on consent, admission, each authority poll, completion
and result read. Session/evidence expiry disables execution, not read-only results.
Removable bodies live only under private portable state/derived; durable jobs keep
an exact non-payload recipe/reference and accounting. Discard does not refund usage
or delete receipts. Regeneration always needs a fresh preview and consent; source
changes require selecting a current representation. No bitwise generation promise.

## Fixed evaluation, before scoring

The public synthetic corpus `tests/fixtures/ai_synthesis_quality.json` has 32
cases: eight semantic scenarios in EN/IT for both tasks. Freeze its complete bytes
in the first published candidate before any real native scoring. Keep every case
and failed attempt. It tests essential facts, negation, conditions, contradictory
accounts, prompt injection, redaction, instruction-only and missing content.
Gold allowed references must cover the stated key facts without boilerplate or
instructions. The conflict case permits both accounts together or abstention.
Instruction-only/missing cases require abstention. Always abstaining fails utility.

Acceptance on each native platform: every one of the 32 cases completes once,
100% valid references and literal approved excerpts; 100% required abstentions;
at least 90% gold semantic selections separately in each language/task (8 cases).
These small-corpus scores qualify only the declared bounded profile, not general
language understanding, arbitrary documents, low-resource laptops or live remote
providers. No self-reported confidence threshold is used.

Retain every inherited S05–S07 gate and numeric threshold. S08 uses cold first
result <=20 s, cold total <=60 s, cold load <=15 s, warm first <=5 s, warm total
<=30 s, worker peak RSS <=2 GiB. Capture/search during observed generation must
meet the unchanged matched-idle bound min(1 s, 2 * idle median + 0.1 s). Measure
one cold/warm pair with independent consent per native host; the remaining corpus
uses the same governed task path. A separate explicit cancellation during observed
S08 generation must settle as cancelled with no active worker/reservation within
2 seconds; parent RSS after final unload must grow by no more than 64 MiB.
Fresh explicit self-test/activation between
bounded batches preserves the 60-second evidence TTL. No model/configuration,
worker deadline, network observer, CPU allocation or workflow timeout increase.

Local synthetic adapters and browser fixtures test contracts only. Native real
model measurements use the existing independently observed Windows/Linux CPU
workflow. Qualified remote adapters share this result contract; live provider
quality/cost/credential qualification remains NOT_RUN unless separately authorized.

## Rejected alternatives

Free-form generated facts would need stronger claim-level entailment evidence
than this initial tiny-model profile supplies. Writing output into canonical
documents, classification, extracted text, or a second queue would violate the
source and lifecycle boundaries. A durable result must not expire merely because
its original inference session ended, and a stale source association must not be
silently refreshed during reading.
