# Reviewed document decisions in Cura

S05 keeps a reviewed decision distinct from the S03 acknowledgement of evidence.
The shared coordinator verifies the actual input and scoped capability again
under the Instance lifecycle lock. Duplicate choices additionally take the
duplicate-case lock, in that order. Providers prepare immutable values without
performing IO; the coordinator checks each exact path and preimage and commits
the effect, attributed domain history and idempotency receipt together.

## Explicit local authority

Review capabilities begin disabled. A local user can preview and confirm a
capability configuration, including its subjects, actions and optional Source
scope. Configuration uses the same retained decision coordinator. Revocation
changes the authority revision and invalidates outstanding confirmations.
The modes are disabled, proposal-only, confirm-each and controlled-automatic.
Only routing application can receive controlled automatic authority. A routing
rule also requires its own explicit automatic enablement; both conditions must
remain true when an unclassified Document is processed. A Source-filtered grant
requires a retained Document Source, never an unverified Source in client JSON.

Acquisition completes before its separate routing effect. Ambiguous rules,
changed evidence, a busy lifecycle or a failed atomic routing commit preserve
the acquisition and return a proposal or a review-required outcome. The caller
does not report the already committed intake as failed or automatically retry it.

## Duplicate relations and Version choices

An exact link, a related-document decision and a keep-separate decision have
different retained histories. None deletes or coalesces Documents, Versions,
Acquisitions, Sources or Originals. A probable match cannot authorize an exact
link. Each preview binds the complete producer observation and prior decisions;
another decision or changed input makes the old confirmation stale.

Selecting an existing current Version is allowed only when that Version already
belongs to the target Document. Creating a new target Version instead creates a
new immutable identity referencing the selected retained Original. It preserves
the source Version, target's previous Versions and every Acquisition. The original
acquisition timestamp remains factual; the separate review timestamp records the
new decision. No synthetic Acquisition is invented for this local operation.

The additive canonical record `knowledge/review-origins/<version-id>.json` binds
the new Version to its source Version/Document, target Document, previous current
Version, Original hash, actor and exact domain history digest. Deep validation and
Original assurance verify this chain and its committed receipt. Missing or changed
origin evidence is invalid; an origin does not excuse arbitrary acquisition gaps.

## Retention, recovery and limits

Review history, annotations, capability configuration and receipts live under
`state/review/`, outside removable derived output. Backup/restore and portable
transfer preserve this state. Portable rebuild also preserves review-origin
canonical records. Removing generated output cannot silently remove human edits.

The registered review atomic profile permits at most 257 writes, 8 MiB per entry,
40 MiB of candidate bytes, 32 MiB of preimages and 72 MiB total journal payload.
The coordinator additionally limits a provider effect to 256 writes and 32 MiB.
These are new review bounds; existing acquisition and test limits are unchanged.
Reviewed Original verification streams at most 256 MiB and Version inventory
permits at most 10,000 records/32 MiB. Exceeding a bound reports unavailable
evidence rather than treating a partial observation as complete.

Effective capability configuration is validated against the complete confirmed
authority history and its receipts before use, including automatic routing.
The chain permits at most 10,000 configurations and 32 MiB; a confirmation that
would exceed the byte limit is rejected before writing. A syntactically valid
configuration that differs from its confirmed chain does not grant permission.
Receipt identities must also match their retained filenames.

An interrupted prepared journal rolls back before another lifecycle writer or
receipt replay proceeds. A committed journal is verified before cleanup. Read-only
review surfaces never recover or create state and do not present partial journal
effects as completed decisions. Corrupt and unsupported retained formats fail
closed; ordinary reads do not reset them.
Recovery rejects linked control, transaction and stage directories, including
Windows junctions, before following them or removing any abandoned stage.

Automated tests, browser observations and language review remain distinct forms
of evidence. Generated interface text is not a human linguistic approval.
