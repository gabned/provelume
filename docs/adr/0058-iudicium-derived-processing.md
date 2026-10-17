# ADR 0058 — Independent, bounded local processing autonomy

Status: S04 implementation candidate, owner #369, campaign #349. Acceptance is
recorded only after unchanged-source and actual-main qualification. Accepted S03
base is `295db5536e7accd0d8151e88ec1dd838c759e2ab`.

Use a distinct `processing` domain in the existing local review coordinator,
retained capabilities, atomic transaction and receipts. One reviewed policy per
Source selects an exact locator prefix, supported local operations, mode, UTC
expiry within ninety days, maximum reserved jobs and maximum input/text bytes.
Every initial or changed policy requires explicit local review. The policy binds
current canonical Source bytes and the complete host configuration revision,
including privacy, Source and resource settings. A classification rule, label,
confidence value, document instruction or model response supplies no processing
permission. Processing supplies no canonical classification or AI permission.

Automatic dispatch requires both the reviewed rule and a separately confirmed
controlled-automatic host capability limited to the `run` action. A confirm-each
host grant cannot be upgraded by rule mode. To edit/disable a rule, first restore
the appropriate confirm-each host actions through their existing explicit review.

The automatic allowlist is deliberately bounded to existing deterministic local
text extraction, universal text-representation materialization and scoped FTS
refresh. OCR, ASR/transcription, photo/video/file-family transformations and AI
summarization keep their existing explicit controls, supported-component checks,
limits and consent; this policy cannot activate or reconfigure them. No new
provider or business ontology is introduced. AI session/consent/model admission,
accounting, guarded network access and classification quality gates are preserved.

An opted-in Source always acquires its exact Original and canonical Version using
the existing ingestion ledger. It defers inline extraction/indexing, including
when its processing policy is disabled, expired, malformed or unreadable. Sources
without a policy retain their existing ingestion behavior. A background refresh
cannot fall back to an Instance-wide index rebuild when reviewed processing scopes
exist. A separately explicit full rebuild retains its own existing authorization.

`confirm-each` needs an exact retained local `run` confirmation. The browser queues
its receipt-bound request after the atomic confirmation; interrupted enqueue can
reuse that permit without another review mutation. `controlled-automatic` permits
only current in-scope Versions under that explicitly reviewed local rule and
independent host capability. Disabled/proposal-only modes perform no derived work.
Unknown, stale, outside-prefix, expired, over-budget, archived/trashed/hidden,
conflicting or unsupported requests fail before derived writes. Content is passive
input, never interpreted as configuration, a tool request, provider choice or a
write destination. Originals and extracted text are bounded and checksum-verified.

Use schema-2 `processing.execute` requests in the existing scheduler journal,
leases, cooperative controls and terminal receipts. Producer policies are disabled
manual carriers, never an unattended schedule without an exact execution plan.
There is no second queue, cursor, processing ledger or authority file. Automatic
reconciliation derives current requests from canonical identities and returns the
existing deterministic reservation after restart. A dependent stage waits for its
existing prerequisite, including pause/failure; it cannot create an implicit retry.
Failed/cancelled reservations and linked restarts consume the same reviewed budget.

Index refresh binds every current active/included Version and text artifact within
the reviewed Source/prefix, with an aggregate resource bound. It updates only that
set. Missing/corrupt global cache or changes outside that set require the existing
separately authorized full rebuild; narrow work cannot broaden its own effect.

The scheduler owns lifecycle throughout bounded deterministic work. Pause/cancel
wins at existing cooperative boundaries before the first write; commit then fences
late control. The request is recollected after reads/extraction. Exact identities,
closed history, current capability, input hashes and limits are rechecked at
execution and resume. Output materialization uses existing rebuildable stores and
universal removal/rebuild controls; no Original, classification, retention or
external-provider write is permitted. Terminal receipts report no canonical
mutation and no network use. No timeout, snapshot, threshold, native binary or
security permission is changed.

Cura and the reversible Current interface share the review flow, localized closed
choices, fresh server preview, one-use local browser confirmation, history and
existing maintenance job controls. All seven shipped catalogs retain linguistic
review `UNVERIFIED`. Human observations remain `NOT_RUN` and independent classifier
labels `NOT_REVIEWED`, nonblocking by #349 comment6186153379. Classifier real quality
remains `NOT_EVALUATED`, confidence absent and automatic classification denied.
No real scoring precedes a frozen representative corpus, splits, configuration and
thresholds. Synthetic mechanics are not real task qualification.
