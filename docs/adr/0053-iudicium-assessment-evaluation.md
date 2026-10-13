# ADR 0053 — Iudicium assessment contracts and confidence evidence

Status: implemented candidate for 0.13/S01 (#350), parent #349; not model qualification.

## Decision and boundary

Extend Custodia's `TaskTemplate`, `TemplateIdentity`, context/preview validation and
base gateway receipts. `classification-en-v1` and `classification-it-v1` require
complete selected text and 1–64 host-supplied candidate identities from the existing
Area/Project/Collection/document-type vocabulary. This is one-target assessment,
not a new ontology or a durable proposal. Canonical existence, hierarchical
consistency and current scope must be resolved in S02 before proposal/application.

Target identities and indexes occupy the trusted allowlist; display labels and
source segments remain untrusted payload data. Template revision binds labels,
order, identities, language, instructions and result schema. Existing context-check
and synthesis revisions retain their exact accepted-main bytes. No new provider,
scheduler, UI, transport, model profile, install/update or version change.

The closed output is `schema_version`, `preview_fingerprint`, `status`, `target`,
`references`. `selected` requires an in-range integer target and unique sorted
supporting segment indexes; `abstained` requires null target and no references.
Booleans are not indexes. Extra keys, including model confidence, tools and policy,
are rejected. Shape/anchor validation does not prove semantic relevance or model
resistance to malicious wording: that needs real task/profile evaluation later.

`assessment_receipt` revalidates context and the same gateway plan before checking
supplied bytes. It preserves the base receipt's PLANNED/DENIED outcome and absence
of transmission, and adds source/Original identity, request/template/policy/profile,
canonical assessed output and evaluation fingerprints. It records indexes and
status without raw text or target labels. `supplied_for_validation` does not claim
inference, consent to execute, a durable proposal or permission to apply anything.
A stale or denied plan cannot produce a successful assessment. The existing
scheduler/budget/consent path remains mandatory for future real execution.

## Evaluation protocol fixed before profile scoring

The pure evaluator takes a host-established corpus and complete observations.
Gold labels are independently curated: a digest proves identity, not gold-label
correctness or authority. Each observation binds case/input, corpus, exact template
and profile, output fingerprint and selected/abstained/invalid outcome. A corpus has
1–4096 unique case IDs and unique input fingerprints; 1–64 targets. Missing,
duplicate, foreign or mixed identities fail. Invalid output is neither a selection
nor a successful abstention; it remains in total accuracy and abstention failures.
No implicit case deletion or substitution of another profile's results.

Report measured accuracy (including required abstentions), classification coverage
and precision, required-abstention failures, false positives, and per-target
support/precision with a 95% Wilson lower confidence bound (z=1.959963984540054).
The point estimate is precision in this corpus for this predicted target, **not an
individual document probability** or a calibrated real-world certainty. Zero
support is null, not zero certainty or perfect accuracy. Fewer than 20 distinct
input fingerprints per predicted target is `insufficient_support`; 20 or more is only
`evaluated_unqualified`. Twenty is an evidence-display minimum, not a quality or
autonomy threshold. Distinct fingerprints do not prove statistical independence.
A real release must freeze representative calibration/held-out
corpora and quality thresholds before scoring a model, without using this sample
minimum to promote it. Reports always retain `qualification: NOT_EVALUATED` and
`automation_authorized: false` in S01. Absence of evaluation leaves confidence null.

The checked-in EN/IT fixtures exercise clear, absent, ambiguous and hostile input.
A gold-output fake tests arithmetic/attribution; a careless fake exposes false
positives under the same corpus. Neither is a real classifier or proof of model
quality. Fixture outputs cannot promote the existing Custodia synthesis profile to
classification. S02–S05 must obtain the missing task/profile evidence, maintain
unknown human/hardware results and keep #348's original qualification failure separate.

## Compatibility and verification

No canonical schema/migration or persistent storage is added. Drop an in-memory
assessment to discard it. Six existing template revisions are frozen regression
assertions from main cd7dc64. Tests cover adversarial schema/input boundaries, stale
identity/policy, no ambient I/O, duplicate evidence, abstention failures, small/zero
support and adapter-independent scoring. Full native tests/Ruff/diff and all
applicable exact-head remote checks remain necessary for the actual candidate.
New user-visible surfaces, calibrated support and autonomous application are not
claimed by this slice. No 0.13.0 publication is authorized.
