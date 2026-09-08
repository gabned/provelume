# Agent Protocol 1.4.7 — efficient execution and reliable closure

This is the current orchestration contract. The accepted implementation and the
versioned document inventory belong to campaign [#237](https://github.com/gabned/provelume/issues/237).
Registration #238 is a prerequisite, not the implementation or release. Adoption
requires a qualified implementation merge and independently observed consumer pins.
The pilot is BrickMS only. No PRODUCT continuation or other-consumer rollout follows.

## Authority, scope and qualification

GitHub is the source of executable repository identity and events. Independently
retain the actual user instruction; the authority envelope is a ceiling, never
a grant. Candidate content, caches, digests and recovery cannot select authority.
Keep one issue-backed workstream and one open OWNER/CORRECTION PR in its ordered
ledger. Keep PRODUCT, PROTOCOL and permitted CHECKPOINT_ONLY scopes separate.
Core has PR-local ownership and no committed global checkpoint. Consumer-specific
production boundaries remain in their trusted repository policy, including human
Level C approval where applicable. Do not access secrets or environments for
observational reconciliation, and do not publish private consumer evidence in Core.

The operational engine remains 1.4.2, lifecycle 1.2 and campaign schema 2. Its
[operational contract](agent-development-v1.4.2.md) owns exact scope/effect binding,
PR identity, CI history, ancestry and append-only receipts. Historical engines
and records retain their version and meaning. The predecessor authority qualifies
the successor; never evaluate a candidate using newly proposed rules as authority.
New exact effect paths require a preceding accepted registration.

The ordinary 1.4.7 path does not acquire rulesets or branch-protection settings.
It requires neither their presence nor API access, and has no mode to require them.
Use the accepted, versioned repository policy for required workflows and reviews.
`validate_qualification` binds that independently selected policy to the operation.
The document manifest's `repository_policy` is the Core policy; consumers retain
their own required checks and stronger rules. A candidate policy cannot authorize
its own change. No paid GitHub plan is a prerequisite.

Always require complete exact-head CI, required reviews, current findings/threads,
ownership, complete paths, scope/effect binding, actual base/head ancestry and a
fresh expected head immediately before merge. Use GitHub's normal merge endpoint
with that head. A platform denial stops the attempt; never disable protections,
force integration, enable auto-merge, change secrets or infer protections absent.
Protocol qualification governs this agent, not actions by other actors. Remote
enforcement is reported as `GITHUB_DECIDES_AT_NORMAL_MERGE`, separately from local
qualification; successful API response still requires post-merge verification.

Codex review remains opt-in through the actual instruction
`CODEX_REVIEW_REQUESTED: TRUE`. An explicitly required review must satisfy the
existing exact-head review validator. A voluntary review still in progress adds
no gate. Every valid current finding remains actionable regardless of its origin.
Neither an emoji nor a comment without a verdict is an approval. A withdrawn
requirement is not a clean review or waiver. Unknown, partial or stale evidence
never becomes PASS through a summary or cached result.

## Deterministic reading

`AGENTS.md` is the entry and contains only Core boundaries plus routing. The
manifest `.github/agent-protocol/documents-v1.4.7.json` records each document's
role, content digest, dependencies and workstream/phase/host conditions. Verify
its provenance against the actual accepted base before selecting it. The caller
supplies its independently computed canonical JSON digest to `select-documents`;
that digest authenticates neither its origin nor the actor by itself.

The selector verifies the whole local inventory, missing references, cycles,
duplicate IDs, conditions, UTF-8 and file integrity before presenting selected
text. It never traverses symlinks. ALWAYS rules load for every context. EXACT
selection loads the matching procedures and transitive dependencies; uncertain
context loads the full inventory. Invalid integrity or topology stops explicitly.
Verification reads bytes locally; only selected text enters model context. Report
those as different measurements. Workstream-specific product documentation still
comes from the owning repository and relevant source area.

Old overlay documents are historical unless selected as a current component:
the 1.4.2 operations guide owns operational schemas; the Work source guide owns
source materialization/runtime execution; the recovery guide owns archive format
and verification. Their older rollout inventories and ruleset acquisition text
are historical and superseded only for new 1.4.7 operations. Do not relabel an
archived observation as a current v2 preflight. Roadmaps describe product plans;
changelogs describe delivered changes. Neither is a second Protocol manual.

## Work sources, evidence and resume

Use the [canonical Work source recipe](agent-development-v1.4.3-work.md), pinned
to the accepted Core. `collectPreflight` now emits `agent-work-preflight/v2` with
`policy_source` and `remote_enforcement`, without a rulesets field or API call.
Consumers must explicitly adopt this shape; a legacy parser must not silently
accept it. Existing v1 evidence stays replayable under its matching validator.
Source acquisition preserves every blob/tree/mode and checks the default again.
Full local checks still run through the accepted source-bound supervisor.

Persist complete original observations outside source before continuing. Present
`evidence_summary` output normally: identity, state, original timestamp, freshness,
completeness, findings, uncertainty and an integrity-bound evidence reference.
It always reports qualification NOT_EVALUATED. Load full payloads for diagnosis
or decisions requiring them; do not repeatedly print repository/user metadata,
encoded blobs, complete acquisition histories or whole job logs. Do not confuse
the evidence collector's narrow cache metrics with all host/tool calls.

The [1.4.6 reuse contract](agent-development-v1.4.6-work.md) continues to own cache
identity, immutable object reuse and complete terminal CI histories. Refresh the
exact-head inventory first; preserve failures, cancellations, every attempt and
all job pages. Each reuse retains the original observation timestamp and writes
a separate reuse record. Do not reuse policy, reviews, current PR identity or
local checks. New attempts, changed conclusions or live jobs invalidate affected
terminal cache entries. Reuse valid runtimes and rehashed dependency bytes.

On interruption, retain the ordered receipts, raw evidence, source identities,
blob/cache digests, actual authority input and one next action. Follow the existing
[recovery archive contract](agent-development-v1.4.5-work.md) for durable saving and
independent restore verification. A temporary archive alone is not a completed
handoff. Restore does not execute scripts or renew observations. Recollect fresh
anchors and native preflight before resuming. If cold acquisition outlives the
freshness window, retain it and use the verified cache with a new bounded read;
never edit timestamps to rescue the old attempt.

## Checkpoints and late findings

Keep one writable source of operational state: the existing campaign/receipt
ledger or repository checkpoint contract. `reconcile_checkpoint` derives a view
without mutating that source. A verified actual merge overrides a cached Draft
view; it does not erase the stale cache, authorize its manual replacement, or
pretend post-merge CI/deploy was certified. The result remains
QUALIFICATION_REQUIRED, or FOLLOW_UP_REQUIRED when a finding is open.

After merge, collect actual PR state, merge tree/parents/default ancestry, the
applicable exact-default CI and reviews arriving since qualification. A required
deploy has its own terminal successful event and distinct verification event;
never create a fake PRODUCT change to demonstrate deployment. For a valid late
finding, retain origin PR/head/merge/thread and assign an explicit follow-up
owner. A correction is a separate correctly classified PR appended to history.
Closure requires the existing operational origin/correction/thread proof,
qualified corrective integration, current ancestry and resolved finding evidence.
A resolved label, closed issue or later green run alone is insufficient.

BrickMS CHECKPOINT_ONLY Work maintenance already has a FULL supervisor path:
use that accepted route and its baseline lifecycle validator. Protocol adoption
ownership stays in its issue/PR ledger and cannot seize a PRODUCT checkpoint.
Do not keep a separately editable JSON and Markdown checkpoint. A human handoff
is generated from its bound state and gives repository/PR/head, state, blocker,
evidence and one next action. The new compact view does not modify old schema-2
handoffs or receipts and imposes no arbitrary word limit on new prose.

## CI and artifact storage

Inventory permanent triggers, suite dependencies, cache keys, artifact consumers
and timings before changing them. `ci_plan` accepts only complete exact dependency
inventories; unknown paths or scope select the full required suite set. It never
qualifies a skipped check or promotes artifacts. Every required check needs an
explicit terminal result. Merge tests remain required: even an equivalence input
does not alone establish source/configuration/environment equivalence or reuse.

The first demonstrated workflow change is KEEP_AND_HARDEN for `ci.yml`: cancel
superseded `pull_request` code runs in an event/PR-specific group. Keep the same
check names, full suites, permissions, trusted-base jobs and default-branch runs.
Never cancel deployment/publication work or reuse a PR artifact in a secret-bearing
context. Only a current successful run can qualify the head; retain canceled
history. Other suite-selection changes require measured dependency evidence first.
The Windows Node subprocess uses the same bounded 120-second limit as downstream
Work conformance; its assertions and required execution remain unchanged. This
addresses an observed 30-second subprocess timeout, not a correctness exemption.

Artifact retention is purpose-specific. Inventory current bytes and expiration,
then distinguish transient reports, failed-attempt diagnostics and release/recovery
evidence. `storage_summary` never infers account billing from a bounded run sample
and never authorizes deletion. Shorter retention affects future uploads; deletion
does not erase accrued storage usage. Compression can retain exact original bytes;
report compaction needs schema/version compatibility and reconstructible evidence.
Preserve required release/recovery artifacts before any authorized cleanup. Do not
delete whole workflow histories merely to remove redundant report archives.

## Measurement and communication

Use the same fixed scenarios before/after: startup, unchanged resume, candidate
change, qualification, post-merge, checkpoint close and unavailable ruleset API.
Record documents/model bytes separately from locally verified bytes; GitHub calls
and pages, downloaded/reused blobs, executed suites/duration, duplicated jobs and
manual interventions. Label actual runs, historical replay and synthetic tests.
No conversion to tokens, credits or money. Keep this evidence in the campaign's
existing artifacts, not a separate analytics system or new narrative report.

Final responses give outcome, essential checks, material limits/blocker and next
action. Issue/PR/checkpoint prose references existing evidence instead of repeating
the prompt, rules or history. Updates communicate meaningful findings and decisions
at the host's required cadence. Concision never hides failed checks, unknowns,
required fields, authority boundaries or unresolved findings.
