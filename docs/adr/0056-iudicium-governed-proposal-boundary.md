# ADR 0056 — Governed Iudicium assessment records and review

Status: S02 request/execution/review candidate, #352, parent #349. Not accepted;
unchanged-source machine qualification remains mandatory. Same distinct owner
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

## Explicit request and existing native/provider routes

The document page opens a classification request using an existing text
representation, EN/IT task language and one current destination group. The host
resolves at most 64 Area, Project or Collection identities of that group, or the
document's recorded MIME identity. The preview displays every label, complete
selected text, redaction, route/model/destination and existing budget. It does
not enqueue, activate AI, renew consent or execute a model. Complete pages must
fit the existing 2000-byte/16-segment selection bound; omitted context is refused.

Explicit consent uses the existing expiring previews, form/session/Instance
controls, source restrictions, current profile/locality evidence and scheduler.
The random preview-context nonce is frozen first; the request reference then binds
the exact prepared preview and current complete target observation. Revalidation
on every authority poll rejects changed targets, source, policy or session.
Synthesis and classification execute routes refuse each other's preview kinds.

The native task adds a closed output format to the existing worker and model,
not a provider, model profile, worker loop or model configuration. Trusted task
framing is bound into the classification template revision. Labels and text stay
in the user data role; decoded role delimiters and caller grammars are refused.
Records made against a preceding template revision become unavailable on fresh
read and remain explicitly removable; they are not silently upgraded or replayed.
The grammar restricts output to the known fingerprint, target indexes and source
references; structural validation still rejects duplicates, wrong fingerprints,
extra fields and unsupported choices. Source/current-policy validation and receipt
publication remain inside the original governed job boundary.

The model's 128-token limit and request limits are unchanged. The candidate byte
proxy accounts separately for the closed schema's exact host fingerprint field;
the variable selection fields retain the original 128-byte bound and the total
wire input remains bounded. This adds no capacity for text, tools or authority.
Actual usage still settles from the original adapter observation. No runtime
failure or historical host correction is claimed.

The configured provider uses its existing structured-output transport and current
qualification/price/network policy. Live external support is not inferred from
synthetic adapters. The permanent CPU qualification adds exactly one governed
native execution in each task language, then reads/removes its receipt-bound body
and verifies source/accounting preservation and session-off/worker termination.
Either a valid selection or abstention is accepted: this measures execution and
schema conformance, not target accuracy, confidence, calibration or robustness.

## Maintainer change to the human and label-review scope

On 2026-10-15 the maintainer explicitly instructed: “saltiamo sia le prove umane,
sia le label revisionate, procedi con la prossima slice”. Recorded authority:
https://github.com/gabned/provelume/issues/349#issuecomment-6186153379 . Human
Windows/accessibility/catalog observations and independent gold-label review are
therefore non-blocking for this campaign. Factual states remain NOT_RUN,
NOT_REVIEWED and UNVERIFIED; none is a PASS or a Protocol waiver. This supersedes
the earlier wait-for-human wording above, without certifying those observations.

Real classifier quality remains NOT_EVALUATED, confidence null and application/
automation flags false. No accuracy benchmark or held-out scoring is performed.
Any future semantic quality claim still needs a representative licensed corpus,
frozen inputs/configuration/thresholds and an honest account of label provenance
and review; synthetic execution passes do not provide it. S01's twenty-input
display floor is not a quality or autonomy threshold.

Reviewed scoped/expiring rules and guarded reversible application remain S03,
separate derived-processing autonomy S04 and integrated qualification S05. Native,
CI, ownership, reviews, source/policy binding and integration gates remain intact.

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
