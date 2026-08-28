# Knowledge Browser/Viewer architecture

The first Knowledge Browser/Viewer is a read-mostly interface over the public Provelume application service and Knowledge API concepts. It does not define a second knowledge model in the frontend.

## Stack

- FastAPI for runtime/API routing;
- Jinja2 for server-rendered HTML;
- local custom CSS and system fonts;
- no required CDN or remote asset;
- no client-side JavaScript in the first read-only slice.

HTMX is deliberately deferred until a real partial-update interaction needs it. Avoiding unused client dependencies keeps the no-network baseline small without preventing HTMX adoption later.

## Initial views

- Home: Instance status, counts, latest documents, ingestion errors and network baseline.
- Browse: canonical Area/Project/Collection hierarchy, Sources, logical Source areas, media-type
  filters and breadcrumb navigation.
- Search: local text search with Source/type/date filters.
- Document detail: metadata, current raw extracted-text preview, preserved original and version history.
- Provenance: explicit Source/Acquisition/Original/Version/Derived relationships.
- Knowledge health: explainable issues and rebuildable-index status.
- Security: embedded package version/tag/commit/source identity, explicit official/development/unavailable states and an honest boundary showing which integrity, signature and provenance checks have not yet been performed.

The Security view uses the same build-information service as the CLI and read-only API. It reads packaged metadata only, performs no network request and deliberately avoids a green “verified” state until a future verification engine checks actual installed files and trusted evidence.

The UI is EN/IT ready through local JSON catalogs. Code, technical contracts and API fields remain English.

## Representation boundary

Markdown is the first-class portable human-facing reading and classic-navigation format, not the
canonical metadata store. Acquired Markdown bytes are preserved as an exact Original; canonical
identity, version and provenance records remain JSON. A generated Markdown library or export is a
rebuildable projection unless it is deliberately acquired later as a new Original through the
normal ingestion and review path.

The initial Viewer shows bounded extracted text without interpreting Markdown. The roadmap adds a
sanitized rendered mode beside raw text and explicit original download. Rendering remains a view
over application-service data and cannot mutate an Original or become an alternate source of
truth.

## Navigation modes

- Classic library: area, Source, tag and media-type trees with breadcrumbs.
- Direct retrieval: recent and pinned items, saved views and bounded full-text search.
- Connected context: outgoing links, backlinks, related items and an optional secondary graph.
- Evidence navigation: version and provenance timelines plus explainable knowledge-health states.

The canonical `0.6/S02` hierarchy now drives Browser breadcrumbs, subtree counts and Document
filtering. One primary classification and multiple secondary associations are shown from the same
application-service result returned to the read-only API; the template maintains no private tree.
Source-locator areas remain a distinct compatibility filter. Filesystem projection and safe
rendered Markdown are now implemented by `0.6/S03` from the same application-service state.

Deterministic navigation remains complete without AI, embeddings or a vector store. Later semantic
retrieval may add suggestions, but cannot replace stable links, filters, provenance or full-text
fallbacks.

## Filesystem library

The `library/` projection is a supported offline navigation surface. Its canonical input
is the stable hierarchy and classification model described in
[`hierarchical-classification.md`](hierarchical-classification.md). It contains a root
README, hierarchical Area/Subarea and Project paths, per-folder README indexes, Archive and
generated Collection/tag/person/Source/date/type views. Each document has one primary projected
path; secondary associations are links and indexes rather than duplicate knowledge. Stable
parent-linked identifiers survive user-visible folder rename and movement, and Windows/Linux path
rules produce deterministic portable slugs.

The Browser mirrors this hierarchy instead of maintaining a private tree. Deleting and rebuilding
the complete library from canonical JSON and Originals yields equivalent navigation. External
edits to a generated Markdown projection are not silently accepted as canonical changes; they
enter the normal acquisition/review path.

The Document detail page now offers explicit rendered, raw Markdown, Original-text and download
modes. Rendered mode escapes raw HTML and turns authored links/images into inert labels, so the
document cannot emit navigable resources or active elements. Binary Originals remain download-only.
The complete contract is in
[`markdown-library-viewer.md`](markdown-library-viewer.md).

## Inbox and Action Center

The local Drop Inbox first exposes stabilizing, acquired, duplicate, error and processed states.
The later unified `Needs attention` Action Center adds typed intake, hierarchical classification,
exact/probable duplicate, version-conflict, extraction-error, Source-change, retention and AI-
proposal queues for local, connector and mobile capture.

Every decision card shows preview, provenance/hash, proposed action, reason/confidence, impact and
reversibility. Confirmed rules automate bounded non-destructive routing only. Destructive or
identity-changing actions always require a human decision; rejecting, ignoring or timing out a
queue item never deletes an acquired Original.

## Guardrails

The browser does not require GitHub, an external AI provider or Provelume Cloud. Provenance is a first-class view rather than hidden behind chat. Build identity is kept separate from cryptographic verification. Rendered Markdown disables raw HTML, active content and unsafe local or remote resource loading. Generic `Delete` is not a valid knowledge action: archive, projection removal, recoverable trash and permanent purge remain visibly distinct. Write-back, destructive actions and advanced editing are outside the initial slice.
