# Knowledge Browser architecture

The first Knowledge Browser is a read-mostly interface over the public Provelume application service and Knowledge API concepts. It does not define a second knowledge model in the frontend.

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
- Document detail: metadata, current extracted-text preview, preserved original and version history.
- Provenance: explicit Source/Acquisition/Original/Version/Derived relationships.
- Knowledge health: explainable issues and rebuildable-index status.
- Security: embedded package version/tag/commit/source identity, explicit official/development/unavailable states and an honest boundary showing which integrity, signature and provenance checks have not yet been performed.

The Security view uses the same build-information service as the CLI and read-only API. It reads packaged metadata only, performs no network request and deliberately avoids a green “verified” state until a future verification engine checks actual installed files and trusted evidence.

The UI is EN/IT ready through local JSON catalogs. Code, technical contracts and API fields remain English.

## Guardrails

The browser does not require GitHub, an external AI provider or Provelume Cloud. Provenance is a first-class view rather than hidden behind chat. Build identity is kept separate from cryptographic verification. Write-back, destructive actions and advanced editing are outside this slice.
