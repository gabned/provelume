# Canonical and derived state

Provelume treats durable knowledge and provenance as distinct from acceleration structures.

## Canonical state

The first public Instance format stores canonical records as readable JSON under `knowledge/` and exact acquired bytes under `originals/`. Canonical records include Sources, Acquisitions, Originals, Documents, DocumentVersions and provenance edges. These records are sufficient to retain identity, version history and where each version came from.

Canonical state is not an SQLite database and does not depend on Git, GitHub or an AI provider.

## Derived state

Extracted text, derived-artifact manifests and search indexes live under `state/derived/` and `indexes/`. They may be deleted and rebuilt from canonical records plus preserved originals. A rebuild must not mutate canonical documents, versions or provenance.

The first search implementation uses local SQLite FTS5 only as a rebuildable index. SQLite is not the authoritative knowledge format.

## Human-facing Markdown

Markdown is the first-class portable reading and classic-navigation format, but it is not a
replacement for canonical records. When Markdown is acquired, its exact bytes remain an Original
and its identity, version and provenance remain canonical JSON. Deterministic Markdown libraries,
front matter, link indexes and exports generated from canonical knowledge are derived projections:
they may be deleted and rebuilt, and changes to them never silently mutate an Original or
canonical record. A changed projection becomes knowledge only if it is deliberately submitted
through the normal acquisition and review path as a new Original.

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

User-directed erasure uses separate archive, remove-projection, recoverable-trash and permanent-
purge operations. Permanent purge requires explicit authorization, an impact summary and honest
backup/replica boundaries. Rejecting an Inbox item, finding a duplicate, removing a connector or
changing classification never implies purge.

## Identity and versioning

- Sources and Documents receive stable opaque IDs when first registered.
- Original identity is content-addressed by SHA-256 and identical bytes are stored once.
- DocumentVersion identity is deterministic from Document identity plus content hash.
- A new Acquisition is recorded on each observation; a new DocumentVersion is created only when content changes.
- Physical source paths are operator configuration. Canonical document locators are normalized relative locators inside a Source.

## Provenance

The canonical chain is explicit:

`Source -> Acquisition -> Original -> DocumentVersion -> Document`

Derived provenance extends it with:

`DocumentVersion -> DerivedArtifact`

Derived edges disappear safely with derived state and can be regenerated.
