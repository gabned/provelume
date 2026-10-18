# Explicit manual Knowledge Object services

S03 [#387](https://github.com/gabned/provelume/issues/387) builds on accepted S01
contracts and S02 schema-3 storage. `ProvelumeInstance.object_services()` returns
the local Python service seam. Construction performs no Instance I/O, recovery,
inference, scheduling or canonical write. This is not a stabilized external API;
the local HTTP/interface boundary belongs to S04 and reviewed proposals to S05.

## Manual authority and concurrency

Writes default to denial. The trusted local caller must supply the literal
per-operation confirmation `consent=True`; a record field, model output, alias,
stored origin or truth-looking text cannot supply that confirmation. It is not a
persistent consent or permission grant. A later browser/CLI host must establish
current local-user authority before calling this seam. Existing runtime policy,
filesystem permissions, AI consent and interface preferences are not changed.

`create` assigns a new Instance-bound identity and immutable first revision.
`update` admits only title, aliases, state, typed body and evidence IDs, requiring
the independently read current record SHA-256. Identity, kind, Instance, revision,
timestamps and proposal origin cannot be supplied as edits. A stale preimage fails
before any new evidence, head or revision is committed. Existing lifecycle
serialization, registered recovery and the bounded atomic writer remain the single
persistence boundary. Service reads do not repair state; writers settle prior
registered transactions under that existing boundary.

Project/Collection creation, identity, name and parent remain owned by the existing
hierarchy service. Object metadata edits retain the exact hierarchy ID. Renames
use `rename_hierarchy_node`, preserving metadata and writing the next object
revision atomically with the hierarchy record. Alias matching never merges IDs.

Relations require exact current source and target references: object ID, revision
and SHA-256 in the same Instance. Current/type/graph validation rejects dangling
or stale endpoints, invalid typed links and dependency/containment cycles.
An existing relation retains historical endpoints after an object changes; reads
report `current: false` rather than retargeting it. Explicit retraction can retain
those exact historical references. New or active links still require current
preimages, and complete immutable history/type closure remains mandatory.

Manual object edits produce `origin: manual`, never a fabricated reviewed-proposal
origin. These services introduce no provider, network, inference, automatic
classification, canonical deletion or identity merge.

## Evidence availability is not truth

`evidence_for_version` prepares an inert reference without persisting it. At
application, referenced sources are freshly resolved against canonical
Document/Version/Original identity and actual retained Original bytes. A newer
Version never replaces an older reference. Availability means the exact attributed
bytes and bindings are present; views retain `truth: NOT_VERIFIED`. Claims remain
operator assertions, not certified facts.

Whole-Original evidence works independently of file format. The closed text
profile is **text/plain page v1**, matching the existing context profile:

1. Resolve the exact retained representation, output and anchor. Recompute anchor
   identity from representation, ordinal, kind and target; a syntactically valid
   fabricated anchor ID is insufficient.
2. Require an active, available, uncorrected representation bound to that Version
   and Original, with the selected output inside its owned output directory.
3. Re-read/hash the bounded output bytes. Strict UTF-8 uses form-feed as the page
   delimiter; the selected page must exist and be nonempty.
4. `quote_sha256` binds the **entire selected page**, including exact whitespace
   and line endings, excluding the form-feed delimiter. No Unicode/newline
   normalization or guessed excerpt/offset is applied.

Time, region, sheet/cell/member and reserved anchors do not acquire text semantics
through inference. Unsupported, removed, corrected, missing or changed references
report `UNAVAILABLE` with a content-free reason. No representation is derived and
no current Version substituted to make evidence available. Whole-Original evidence
remains the supported alternative for other formats.

New assertions and substantive edits require available evidence. A pure explicit
withdrawal (Claim `retracted`, Entity `retired`, Task `cancelled`, for example) may
retain existing unavailable attribution without presenting it as verified. This
exception cannot be combined with new text, endpoints or evidence. Independent
object history remains after explicit document purge; source availability then
reflects the missing retained document.

## Calendar instants and bounded reads

CalendarEvent retains S01's explicit-offset and increasing-UTC interval rules.
The service additionally loads the named zone from shipped `tzdata.zoneinfo`
resources, with no host-time-zone fallback. Both selected offsets must agree with
that IANA zone. DST folds retain their explicit selected offsets; nonexistent
wall times, wrong seasonal offsets and unknown zones fail. No all-day, recurrence
or provider synchronization is introduced.

| Boundary | Current service limit |
| --- | --- |
| Closed record and references | Existing S01 256 KiB / 128 references |
| Evidence source-byte budget per resolution pass | 512 MiB |
| Retained representation descriptor | 2 MiB, depth 16, 32,768 values |
| Selected text output | 8 MiB |
| One verified object/relation history | 1,024 revisions / 8 MiB canonical bytes |
| List page | 100 summaries; existing 100,000-entry container cap |

An append exceeding the history reader's budget is refused before writing, so
the last supported head remains readable. `get` and `history` verify the selected
immutable chain; `list` returns bounded head summaries explicitly marked
`history: NOT_CHECKED`, not complete history/evidence verification. Reads reject
linked/junction components, including replacement links in an already-open
Instance's ancestors. Errors use fixed codes, not private text/paths. Source growth
or byte mismatch fails within the budget.

## Local operator example

```python
services = instance.object_services()
evidence = services.evidence_for_version(exact_retained_version_id)
created = services.create(
    "claim", "Operator assertion", {"statement": "An explicitly attributed assertion"},
    evidence=[evidence], consent=True,
)
edited = services.update(
    created["record"]["id"], {"state": "disputed"},
    expected_sha256=created["sha256"], consent=True,
)
```

After an uncertain write outcome, read current heads/history rather than blindly
replaying stale edits. Reads and reference preparation perform no derivation or
network request. Manual object writes do not silently rebuild disposable indexes
or library. An `include` portable export retains its existing explicit ready-state
contract:

```python
instance.rebuild_index()
instance.rebuild_library()
instance.export_portable(destination, derived_state="include")
```

The `rebuild` transfer choice remains available. Canonical objects, evidence,
revisions and relation references survive either portable choice and verified
backup/restore. Instance identity, exact Originals, Knowledge, preferences,
consents, permissions and Cura-primary/explicit reversible Current selection
retain their authority. Synthetic machine qualification implies no human
UX/accessibility/catalog review, real classifier quality or release readiness.
