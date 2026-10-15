# ADR 0056 — Governed Iudicium assessment records and review

Status: S02 backend/review candidate, #352, parent #349. Not accepted; full S02
task activation and real classifier quality remain pending. Same distinct owner
`iudicium-s02-governed-proposals`, started after prerequisite #353 acceptance on
`fd0dde8628f36d6ffacaa9caf7af6519ca841261`, tree
`5b63de25842f401d6b897d4309e177f371eff39d`.

## Recorded output is not execution or application authority

ADR 0054 resolves current host-allowlisted Area/Project/Collection/recorded-MIME
identities. ADR 0053 validates supplied assessments and evaluates synthetic
observations. Neither establishes real model execution, quality or write authority.

The new producer runs inside the existing `AiJobs` result projection, after known
call settlement and fresh gateway validation, before terminal job/receipt
publication. It accepts the closed classification schema against the exact
current context/template. It does not dispatch, enqueue or create another worker
or queue. Only an actually running journal job with its current lease can enter
this projector. A supplied assessment or a completed job cannot be projected
retroactively.

The host computes `classification_request_ref` from the prepared preview and
complete current target-observation revision before enqueue. It must revalidate
that observation in its live current callback on admission and every authority
poll. The producer independently resolves it again and verifies the exact
request reference, source/Original/representation bytes, current targets/template,
source scope, request/plan binding and actual attempted profile route. Changes to
the observed hierarchy, placement or provenance cannot be rebound after execution.

Source text, target labels and model output remain untrusted data. Unknown,
ambiguous, denied, stale, out-of-allowlist or malformed output fails closed.
A known completed call still settles its recorded usage when projection fails;
it is not resent or refunded. No model-supplied confidence, tools, commands,
policy, provider selection, URLs or mutation instruction enters a proposal.

## Private storage, restart and disposal

The private body is a bounded disposable derived artifact. The new closed
`classification_ref` result anchors its complete SHA256 in the existing immutable
terminal AI result/receipt. It binds source, recipe/selections/redaction, current
target revision, policy fingerprint, template, actual profile/model/route and
validated assessment. Bodies are at most 32 KiB and at most 128 retained bodies
per Instance; exhaustion fails closed, without silent deletion or new inference.

A private read reuses the existing verified representation/Original producer,
source-association policies and lifecycle/journal transaction. It rechecks the
whole target observation, current source/policy/configuration association and body
hash. A restart or offline model does not itself require renewed inference or
consent to read an otherwise current record. Changed or unavailable source/policy
shows an unavailable assessment while preserving safe removal.

Explicit removal unlinks only this derived body in a pinned parent. It preserves
the job, recipe, receipt, actual usage and all canonical/Original bytes; existing
backups may retain copies. Repetition is idempotent. A terminal job cannot reenter
the projector and resurrect a removed result. There is no regeneration/apply route.

An interruption between body publication and terminal result publication can leave
an orphan. It is not projected as a successful assessment. The existing explicit
orphan-disposal contract is reused with the classification producer's path: the
original job must be terminal and every attempt demonstrably quiescent; uncertain
transmission requires its original reconciliation first. The requested revision
binds Instance, job, control/session and exact body bytes. Cleanup neither changes
accounting nor authorizes replay.

## Existing Action Center and application

The existing classification queue projects only receipt-bound recorded metadata,
without copying private excerpts into its queue evidence. Opening the record
performs the fresh bounded source/policy/target checks above. The review page
shows the target or abstention, exact retained excerpts, coverage, model/route and
receipt identity, with an explicit unevaluated-quality warning. Stale, corrupt or
missing bodies do not become current evidence.

The AI producer has no Action Center decision or canonical placement/application
action; its domain-review projection is explicitly absent. Ordinary manual domain
review remains independent. The existing local-only form controls, CSRF, mutation
nonce, Instance binding, return context, settings/services and scheduler are reused
for removal and explicit orphan cleanup. Cura and the explicit backup both render
the same recorded result. No new provider, ontology, authority, queue, application
or copy of canonical knowledge is introduced.

The seven shipped catalogs include the new result/unavailability copy. Automated
rendering/escaping and form tests are conformance evidence. New sensitive copy is
linguistically UNVERIFIED. Exact-candidate keyboard, Narrator/screen-reader,
zoom/reflow, themes/contrast and native Windows/catalog journeys remain NOT_RUN;
historical Cura/other-context checks do not automatically qualify these views.

## Real task/profile activation remains unavailable

This candidate adds the governed projection and recorded-result review/disposal,
not a production-classifier request builder or a newly qualified native/remote
task profile. Ordinary AI settings acquire no classification execution route.
Records retain `classification_quality: NOT_EVALUATED`, null confidence and
false application/automation flags. Existing Custodia runtime/synthesis passes
and synthetic job adapters cannot promote this task or grant application authority.

Before real task/profile scoring, freeze a representative licensed EN/IT corpus,
exact input/context/target manifests, independently reviewed labels with recorded
disagreements, calibration/held-out separation without duplicate/version/family
leakage, exact template/profile/redaction/configuration and numerical acceptance
thresholds. Retain absent/ambiguous targets, required abstentions, incomplete
context and hostile text/labels. Do not tune thresholds or discard cases from
held-out results. These inputs are currently MISSING/NOT_FROZEN/NOT_REVIEWED.
S01's twenty-input display floor is not a quality or autonomy threshold.

The remaining S02 request/consent composition and real task/profile activation
must use that independent qualification; this backend candidate does not claim
full S02 delivery. Reviewed scoped/expiring rules and guarded reversible application
remain S03, separate derived-processing autonomy S04 and integrated qualification
S05. Missing mandatory human/data evidence blocks their applicable acceptance.

## Qualification and campaign boundary

Retain full unchanged-candidate native tests, every workflow attempt/job and
failure, effect/policy binding, reviews/findings/threads, fresh preflight, normal
expected-head merge, actual parents/tree and post-merge gates. Do not transfer the
first design candidate's native/CI results to this implementation. S02 and #349
remain open; no successor slice starts around a pending dependency. One final
integrated qualification includes S01 and Cura before the single authorized
0.13.0 publication. Version identity stays 0.12.1 until that final workstream.
Independent #348 and published 0.12.1/0.12.0 assets/receipts/kits/readiness are
untouched; no runtime correction or old-host qualification is inferred.
