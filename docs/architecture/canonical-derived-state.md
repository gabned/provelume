# Canonical and derived state

Provelume treats durable knowledge and provenance as distinct from acceleration structures.

## Canonical state

The public Instance format stores canonical records as readable JSON under `knowledge/` and exact
acquired bytes under `originals/`. Canonical records include Sources, Acquisitions, Originals,
Documents, DocumentVersions, stable Area/Project/Collection nodes, Document classifications,
Document dispositions, connector definitions and instances, and provenance edges. These records are
sufficient to retain identity, version history, current primary/secondary placement, connector and
Source configuration, retention state and where each version or association came from. Connector
credential values remain external; canonical state contains only a validated reference. See
[`connector-framework.md`](connector-framework.md).

Canonical state is not an SQLite database and does not depend on Git, GitHub or an AI provider.

## Derived state

Extracted text, derived-artifact manifests and search indexes live under `state/derived/` and `indexes/`. They may be deleted and rebuilt from canonical records plus preserved originals. A rebuild must not mutate canonical documents, versions or provenance.

The first search implementation uses local SQLite FTS5 only as a rebuildable index. SQLite is not the authoritative knowledge format.

Instance schema 2 makes backup treatment explicit without promoting derived data to canonical
authority: retained `state/` artifacts are included for operational continuity, while `indexes/`
and the filesystem `library/` projection are excluded and rebuilt. Inclusion in a backup is a
retention/continuity choice, not a claim that the artifact becomes authoritative.

## Human-facing Markdown

Markdown is the first-class portable reading and classic-navigation format, but it is not a
replacement for canonical records. When Markdown is acquired, its exact bytes remain an Original
and its identity, version and provenance remain canonical JSON. Deterministic Markdown libraries,
front matter, link indexes and exports generated from canonical knowledge are derived projections:
they may be deleted and rebuilt, and changes to them never silently mutate an Original or
canonical record. A changed projection becomes knowledge only if it is deliberately submitted
through the normal acquisition and review path as a new Original.

`0.6/S03` implements this boundary through a hash-manifested staged `library/` and a safe local
Viewer. The projection binds the deep canonical/Original fingerprint, produces one primary file
per Document and uses README links for secondary/generated views. See
[`markdown-library-viewer.md`](markdown-library-viewer.md).

`0.6/S05` preserves the same authority split during cross-platform transfer. Portable export
always includes canonical JSON, acquired Originals and retained state artifacts; default import
rebuilds `indexes/` and `library/`, while explicit `include` carries only views that validate as
ready. See [`portable-export-import.md`](portable-export-import.md).

For PDF input, the human/agent-facing derivative is a versioned document bundle rather than an
unqualified text dump. It may contain normalized `content.md`, a page map, referenced images and
tables, extraction confidence and an optional separately hashed viewing/mobile-optimized PDF. The
bundle records the generator and recipe and remains rebuildable. Optimization never replaces an
acquired PDF, especially when signatures, encryption or embedded content make byte preservation
material.

## Original assurance and retention

The hash-verified acquisition commit is the assurance boundary. After it succeeds, routine
classification, deduplication, refresh, source disappearance, indexing and library rebuilds do not
overwrite or delete an Original. Exact duplicates reuse the same content-addressed bytes while
retaining each Acquisition, Source and routing observation. A missing or deleted provider item is
a Source state change, not an instruction to erase imported knowledge.

Staging files, generated Markdown libraries, optimized PDFs, previews, indexes and other derived
artifacts have explicit retention policies independent from Originals. A staging input may move
only after exact bytes and canonical provenance commit successfully.

`0.6/S04` implements user-directed retention as separate archive, remove-from-library,
recoverable-trash and permanent-purge operations. Archive and projection removal change only the
canonical disposition and synchronized derived views. Trash retains the complete canonical
lineage and restoration coordinates; restore preserves the same Document, Version, Original,
Acquisition, classification and provenance identities.

Permanent purge is available only for a trashed Document after deep validation, a fresh exact
impact preview, a short-lived target-bound token and explicit acknowledgement of the erasure
boundary. It removes the selected lineage from the live Instance while retaining a shared Original
still referenced by another Document. It does not modify configured Source files or managed backup
archives and cannot observe external backups or replicas. A content-minimizing receipt records
hashed Document/token identity, counts and these limits rather than the raw Document ID or title.
See [`retention-boundaries.md`](retention-boundaries.md).

Rejecting an Inbox item, finding a duplicate, removing a connector or changing classification never
implies purge.

## Identity and versioning

- Sources and Documents receive stable opaque IDs when first registered.
- ConnectorDefinition and ConnectorInstance identities remain separate from each connector Source;
  every connector Source retains its own stable `src_` identity.
- Original identity is content-addressed by SHA-256 and identical bytes are stored once.
- DocumentVersion identity is deterministic from Document identity plus content hash.
- Area, Project and Collection identities are stable opaque IDs independent from display names,
  portable slugs and parent paths.
- Each classified Document has one deterministic classification-record ID, one primary hierarchy
  node and a unique ordered set of secondary associations.
- Each Document has an effective disposition; an explicit transition creates one deterministic
  canonical disposition-record ID and monotonically advances its revision.
- A new Acquisition is recorded on each observation; a new DocumentVersion is created only when content changes.
- Physical source paths are operator configuration. Canonical document locators are normalized relative locators inside a Source.

## Provenance

The canonical chain is explicit:

`Source -> Acquisition -> Original -> DocumentVersion -> Document`

Derived provenance extends it with:

`DocumentVersion -> DerivedArtifact`

Derived edges disappear safely with derived state and can be regenerated.

Canonical classification provenance extends the retained graph with:

`Document -> Area/Project/Collection`

These association edges use stable node IDs, remain valid after rename or movement and are not
part of the disposable derived-provenance directory.
