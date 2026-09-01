# ADR 0019: cross-source qualification findings and human corrections

- Status: accepted for unreleased `0.9/S06`
- Date: 2026-09-01
- Owner issue: [#153](https://github.com/gabned/provelume/issues/153)
- Owner PR: pending candidate creation
- Parent tracker: [#137](https://github.com/gabned/provelume/issues/137)
- Public identity: `0.8.0`

## Context

Lectio now has separate filesystem/document, OCR bundle, local email, synthetic Gmail/Drive and
SRT/WebVTT Source contracts. Similar bytes, metadata, participants, times or representations can
be useful review signals, but none proves a shared identity, event, document or person. Reusing a
provider cursor globally, rewriting an Original, or silently promoting a heuristic would violate
the canonical/derived and Source-isolation boundaries established by ADRs 0014–0018.

Human review also needs durability. Replacing an observed value in place would hide provenance;
editing a prior decision would destroy accountability; and accepting a stale finding after a
Version or Source mutation could apply a conclusion to different evidence.

## Decision

S06 adds a replaceable `provelume.cross-source-qualification` 1.0.0 finding provider. A job is
queued only for two or more explicit Source IDs. The job captures Source/configuration and current
object fingerprints, applies closed limits, checkpoints bounded batches, owns a time-limited
lease, rechecks every input before atomic publication and records a complete result only after the
whole comparison succeeds. Cancellation, crash, stale lease, retry, resync and replay are visible;
partial findings are never complete.

Findings are derived observations with stable `finding_<sha256>` identity. They contain internal
Source/object references, fingerprints, sanitized evidence codes/hashes/counts, rule and algorithm
versions, an epistemic state, bounded confidence, provenance, operational time and effective
limits. The closed type registry covers exact-byte candidates, possible revision/content/event
relations, metadata/checksum/time/format inconsistencies, ambiguous participants, representation
state and unqualified inputs. Exact bytes prove only an exact-byte observation. No rule merges,
deduplicates, renames or verifies anything.

Human actions are separate additive canonical `qualification-decisions`. Each decision is
attributed to an opaque local actor, has a sanitized rationale, binds the exact finding identity,
uses optimistic expected revision and is appended atomically. Actions acknowledge, accept, reject,
defer, declare distinct objects, add a relation, correct a derived observation, supersede,
withdraw or revert. Result states are `acknowledged`, `accepted`, `rejected`, `deferred`,
`superseded`, `withdrawn` or `reverted`. Reversal appends history; no earlier decision or source
observation is erased.

Before a decision, all participating Source/configuration and object fingerprints are rechecked.
A changed or missing reference fails as `qualification_reference_stale`. Concurrent or replayed
submissions with the same expected revision fail as `qualification_conflict`. Corrections never
change Original bytes, provider objects, Source observations or other Sources, and speaker labels
remain unverified labels.

The conformance matrix is closed and versioned as `2026-09-01.1`. It distinguishes deterministic
local conformance, platform preview and authenticated real-provider qualification. Public
synthetic Gmail and Drive fixtures are `synthetic-qualified` only; authenticated Gmail and Drive
remain `unqualified` until an authorized permanent positive exact-head matrix exists.

Service, CLI and protected loopback Browser may mutate jobs and decisions explicitly. The
`/api/v1/qualification/*` contract is read-only. Operational views expose only internal IDs,
checksums, counts, types and sanitized codes/rationales. No qualification path opens a socket,
resolves credentials, downloads a runtime, calls AI, follows links or writes to a provider.

Backup/restore and portable export/import include job, result, Source checkpoint and decision
history as durable state. The portable `rebuild` policy rebuilds indexes/library; it does not drop
qualification evidence. Replay never adds a Version, finding or decision implicitly.

## Consequences

- A user can inspect and correct cross-source observations without creating a global identity
  authority.
- Findings can be regenerated or superseded while append-only human history remains durable.
- Source enumeration, cursors, retry, lease and resync remain independent; the qualification
  checkpoint is an additional Source-scoped consumer cursor, not a provider cursor.
- Private source text, names, subjects, titles and speaker labels are read only transiently where
  needed and reduced to hashes before any finding, job, log or diagnostic output.
- The permanent smoke uses public synthetic fixtures on Ubuntu 24.04 and Windows Server 2025
  x86-64 with CPython 3.12. It does not create a real-provider claim.

## Rejected alternatives

- Automatic Document, Version, Original, person or Source merge: rejected because similarity is
  not identity authority.
- Semantic deduplication, entity resolution, embeddings, RAG or AI classification: rejected as
  both epistemically unsafe and outside S06.
- Editing source observations or prior decisions: rejected because provenance and reversibility
  require append-only overlays.
- Provider write-back or a mutative HTTP API: rejected because S06 is local review only.
- A global provider cursor or implicit scan: rejected because every Source retains its own
  enumeration, retry, lease and resync state.

See the [English architecture contract](../architecture/cross-source-qualification.md) and its
[Italian counterpart](../architecture/cross-source-qualification.it.md).
