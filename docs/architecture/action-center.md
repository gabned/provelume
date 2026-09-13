# Instance Action Center

The `0.11/S03` Action Center composes eight typed local queues: intake, classification,
exact duplicate, probable duplicate, version conflict, extraction error, Source change and
retention. `ActionCenter` receives an already opened Instance store. Its snapshot, item and
authority reads do not open an Instance, run recovery, create directories or acquire mutation
locks. Adapters inspect recorded local evidence; reading attention never scans external Sources,
runs an extractor, refreshes a Source or schedules a job.

## One read contract

`snapshot(queue=None, state="awaiting_review", limit=100, offset=0)` and `get_item(id)` provide
the same item identity, input revision, review state, proposal, evidence and supported actions
to Browser, API, Overview and notification consumers. Pagination is bounded to 500 returned
items. Counts and snapshot revision describe the selected set before pagination, not the
returned page. Per-queue completeness, reason and bounds remain visible. An incomplete queue
has no exact total; `observed_count` is only the number of observed matches. Invalid/unreadable
evidence cannot turn into a successful empty queue. A legitimate never-created producer directory
is distinct from an expected missing/corrupt record.

Item identity binds Instance, queue and native producer identity. Its SHA-256 input revision
binds the producer's exact decision-relevant evidence; UI language, timestamps of polling,
unchanged rescan times and heartbeats are not proposal revisions. Domain links use local paths.
Canonical IDs and Original hashes remain references to the owning records, not new canonical
knowledge or claims that a GET freshly rehashed Original bytes. Unknown confidence remains null.

Delivery, ingestion, execution, representation availability, document disposition and review are
separate dimensions. Completed ingestion does not mean accepted review. Missing derived output
does not mean missing Original. A later retry or proposal may supersede prior evidence; prior
receipts stay readable, including when the originating record is no longer available.

## Explicit decisions and scope

The closed review vocabulary is `awaiting_review`, `accepted`, `rejected`, `superseded`.
S03 supports only explicit evidence actions that it can actually perform:

- `acknowledge_evidence` records that the local operator inspected the exact input. Its accepted
  receipt says `records_inspection_only`: it does not fix an error, retry a job, accept an
  Acquisition, change an Original or mutate canonical knowledge.
- `reject_proposal` rejects an exact duplicate/probable duplicate/manual version proposal within
  the review store. Documents, Versions, Originals, Acquisitions and detection evidence remain.
- Classification placement, linking/merging occurrences and resolving competing Versions are
  S05 domain actions. They are unavailable in S03. Intake rejection requires S06 quarantine
  integration. A receipt cannot simulate these effects.

Manual classification review proposes `needs_manual_placement` only for valid visible
unclassified Documents, without inventing a destination or confidence. Recorded recoverable
trash proposes `review_recoverable_trash`, never a purge deadline or permission. Archive,
library exclusion, trash and permanent purge retain their distinct retention contracts.
`purge_preview` itself changes control state and must never run from an adapter GET.

Authority has independent revision and explicit queue plus Instance/Source scope. Modes use
the shared vocabulary `disabled`, `proposal-only`, `confirm-each`, `controlled-automatic`.
S03 exposes the final mode as unsupported and rejects its activation. Default supported
evidence actions require individual confirmation. Source rules can restrict the Instance rule;
they do not bypass a disabled broader scope. Notifications never grant authority or make a
review decision.

## Atomic receipts, replay and stale inputs

`state/action-center/state.json` is the Instance-local owner of proposal registrations,
authority rules and review receipts. A command atomically replaces this single versioned
document; GET never writes it. It is bounded to 8 MiB and 10,000 receipts/proposals; exhaustion
fails visibly rather than pruning history. Inputs are JSON data with bounded depth/size.
No credentials, notification delivery data, document text or titles are required in a receipt.

Every decision requires the exact input revision, authority revision and request identity.
Same request plus same payload returns the original receipt without repeating its effect;
reusing the request identity for another payload conflicts. A different request cannot decide
an already decided exact proposal. A changed input requires a new decision and retains the
old revision's receipt as superseded history. Failed atomic persistence cannot yield acceptance.

Commands acquire the existing Instance lifecycle mutation lock before rereading canonical and
producer evidence. Duplicate decisions additionally hold the duplicate-case writer lock while
recollecting and committing their receipt. Order is lifecycle then duplicate case; duplicate
scan takes only the case lock and may already run under the scheduler's outer lifecycle lock.
This avoids nested lifecycle acquisition and excludes both acquisition changes and case rewrites
from the decision CAS window. No read acquires either lock: both may create control files.
Future S05 domain writers must supply their own shared mutation/CAS boundary; a queue-only lock
does not protect an uncooperative producer.

## Explicit version-conflict producer

`propose_version_conflict` registers a proposal, not a Version mutation. The local caller supplies
one target Document, its expected current Version, two to sixteen explicit alternative
`{version_id, original_id, sha256}` records and one reason: `competing_versions`,
`conflicting_sources` or `manual_comparison`. Alternatives must identify distinct existing
Versions and at least two content hashes. Their exact Original metadata and target-current
binding are checked under the lifecycle lock with the expected authority revision.

The producer persists the supplied alternatives and reason with deterministic Instance-scoped
identity and input digest. Restart preserves it. If the target's current Version changes, the
old proposal is superseded and cannot authorize a decision against the new input. Missing or
inconsistent alternative evidence is unavailable, not a successful empty queue. A normal
updated Acquisition, different sequence numbers or a stale form does not invent a conflict.

The existing ingestion, duplicate, hierarchy, representation, Source reconciliation and
retention contracts continue to own their domain evidence and effects. S03 adds a review
contract and shared projection; it does not replace those stores or broaden their authority.
