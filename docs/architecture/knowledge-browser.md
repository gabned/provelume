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
- Browse: Sources, logical areas, media-type filters and breadcrumb navigation.
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

## Planned navigation modes

- Classic library: area, Source, tag and media-type trees with breadcrumbs.
- Direct retrieval: recent and pinned items, saved views and bounded full-text search.
- Connected context: outgoing links, backlinks, related items and an optional secondary graph.
- Evidence navigation: version and provenance timelines plus explainable knowledge-health states.

Deterministic navigation remains complete without AI, embeddings or a vector store. Later semantic
retrieval may add suggestions, but cannot replace stable links, filters, provenance or full-text
fallbacks.

## Guardrails

The browser does not require GitHub, an external AI provider or Provelume Cloud. Provenance is a first-class view rather than hidden behind chat. Build identity is kept separate from cryptographic verification. When rendered Markdown is introduced, raw HTML, active content and unsafe local or remote resource loading remain disabled by default. Write-back, destructive actions and advanced editing are outside this slice.
