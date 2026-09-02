# Cross-source qualification and correction findings

`0.9/S06` is published with Lectio. It compares explicitly selected existing Sources and produces
review findings; it does not merge, verify or rewrite them. Package, runtime and embedded identity
are `0.9.0`. No automatic merge is available.

## Authority and identity boundary

Every ConnectorInstance and Source remains authoritative only for its own selection. Provider and
filesystem cursors, page fingerprints, enumeration, deduplication, retry, lease and resync never
move between Sources. A qualification job has a separate checkpoint per Source and reads only
retained internal records and checksum-bound local representations. It performs no intake and
opens no network connection.

`Original` bytes and existing `DocumentVersion` records remain immutable. Equal bytes in two
Sources may share the content-addressed Original already used by Core, but their Documents,
Versions, Acquisitions and Source provenance remain separate. Metadata equality, a speaker label,
address component, timestamp or provider revision is never global identity.

## Closed qualification matrix

The schema-1 matrix is version `2026-09-01.1`.

| Profile | Deterministic local claim | Platform preview | Authenticated real claim |
|---|---|---|---|
| `filesystem-document-v1` | qualified for canonical/Original binding checks | Ubuntu 24.04, Windows Server 2025 x86-64 | not applicable |
| `ocr-document-bundle-v1` | qualified for retained checksum-bound bundle evidence | Ubuntu 24.04 x86-64 | not applicable; real OCR remains under S02 evidence |
| `local-email-v1` | qualified for closed EML/Maildir records | EML Ubuntu/Windows; Maildir Ubuntu | not applicable |
| `gmail-synthetic-v1` | synthetic-qualified | Ubuntu/Windows | **unqualified** |
| `drive-synthetic-v1` | synthetic-qualified | Ubuntu/Windows | **unqualified** |
| `transcript-srt-v1` | qualified for the S05 closed profile | Ubuntu/Windows | not applicable |
| `transcript-webvtt-v1` | qualified for the S05 closed profile | Ubuntu/Windows | not applicable |

Synthetic fixtures do not prove authenticated provider behavior. Unlisted Source kinds, mixed
algorithm versions, missing representations and every combination outside these stated
conditions are unqualified and produce visible review evidence instead of a stronger claim.

## Finding schema and epistemic states

`qualification_finding.schema.json` defines an immutable derived finding. Its stable ID hashes the
type/version, participating internal Source and object references, sanitized evidence, rule and
algorithm identity. The record includes:

- one closed finding type and version;
- participating Source IDs and exact internal object ID/fingerprint references;
- evidence limited to codes, SHA-256 values, counts, sizes and sanitized enum values;
- deterministic rule ID/version and algorithm ID/version;
- `deterministic-observation`, `possible`, `incompatible`, `requires-human-review` or
  `unqualified` epistemic state;
- bounded confidence whose label always states its limit;
- workflow state, job/source-snapshot provenance, operational timestamp and all effective limits.

Closed finding types are `possible-exact-byte-duplicate`, `possible-revision-relation`,
`observed-metadata-inconsistent`, `checksum-provenance-incompatible`, `timestamp-inconsistent`,
`language-format-discordant`, `possible-same-event-document-content`,
`possible-participant-homonym`, `representation-missing`, `representation-obsolete`,
`representation-not-reconstructible`, `representation-recipe-inconsistent` and
`qualification-required`.

The exact-byte rule is deterministic about bytes only. Revision/content/event and participant
rules are candidates, never verified relations or people. Address components and transcript labels
are normalized transiently and only a SHA-256 observation can reach a finding. Source text,
subject, title, name, path, speaker label and provider identifier are absent from operational
state.

## Decision and correction schema

`qualification_decision.schema.json` defines the append-only human overlay. A decision binds one
finding identity, monotonically increasing revision, action, resulting workflow state, opaque
actor, sanitized rationale, action-specific payload, source/job provenance and an operational
timestamp. It declares that Originals, provider objects and Source observations were not changed
and that no automatic propagation occurred.

| Action | Result | Payload and meaning |
|---|---|---|
| `acknowledge` | `acknowledged` | reviewed without conclusion |
| `accept` / `reject` | `accepted` / `rejected` | confirm or reject only this finding |
| `defer` | `deferred` | bounded review-until observation |
| `declare-distinct` | `accepted` | explicitly keeps two or more referenced objects distinct |
| `add-relation` | `accepted` | adds `related`, `revision-of` or `distinct-from`; no merge |
| `correct-observation` | `accepted` | overlays one closed derived observation field |
| `supersede` | `superseded` | replaces a cited earlier decision |
| `withdraw` / `revert` | `withdrawn` / `reverted` | neutralizes a cited decision without deleting it |

Rationales reject control characters, script/data/file/HTTP-like values and spreadsheet-leading
formula characters. Corrected values use an even smaller inert-text grammar. A stale expected
revision fails concurrent/double submission. A changed Source, Version, representation or object
fingerprint fails as `qualification_reference_stale` before append. Rebuild changes derived views
only and retains complete history.

## Durable jobs, limits and errors

Queue identity binds the sorted Source set, exact snapshot, algorithm and complete effective
limits. A result is staged in a private directory and atomically renamed only after every input is
rechecked. Cancellation, exception or changed input leaves no complete result. Expired leases
return to the bounded retry queue; attempt exhaustion fails visibly. Resync increments only that
Source's qualification cursor. Identical queue/replay returns the same job; a new complete result
supersedes missing old finding IDs without deleting their decision history.

Defaults are 16 Sources, 10,000 objects, 10,000 findings, 50,000 candidate relations, batch 500,
600 seconds, 512 MiB temporary state, 4 KiB per evidence object, 32 MiB result output, 1,000
rationale characters, 120-second leases and three attempts. Every value has a closed ceiling;
unknown or incomplete limit records fail. Pair count, serialized evidence and serialized result
size prevent output amplification.

Closed errors include cancellation, conflict, input change, invalid decision/Source, expired
lease, bound/output overflow, missing object, stale reference and retry exhaustion. Job records
expose status, attempt, checkpoint, counts, sanitized error code and lease presence/expiry; the
random lease token stays internal.

## Surfaces, security and recovery

The service and CLI expose matrix/limits, Source checkpoint/resync, queue/run/cancel/retry/rebuild,
job/finding filters, evidence/provenance inspection and decision/history controls. The protected
loopback EN/IT Browser uses CSRF, strict form encoding/body/field limits, keyboard-native controls,
table headings, fieldsets, labels, status/alert roles and visually separate observation, evidence,
decision and canonical-boundary panels.

The `/api/v1/qualification` Knowledge API family is inspection-only: matrix, limits, Source
checkpoint, jobs, findings, sanitized evidence/provenance and decision history. It has no `POST`,
`PATCH`, `DELETE`, upload or remote intake route.

Markup, formulas, links, escape-like strings and script payloads remain inert data. There is no
provider SDK call, credential resolution, runtime download, remote fallback, AI or shell/process
path. Source-controlled paths are never dereferenced outside the Instance; unsafe, missing or
checksum-mismatched representation references become findings or fail validation.

Instance backup/restore and portable export/import preserve qualification jobs, complete results,
checkpoints and canonical decisions. Portable `rebuild` applies to indexes/library and does not
discard this durable evidence. Finding recalculation remains an explicit job. Crash recovery never
presents staged output or a partial decision as complete.
