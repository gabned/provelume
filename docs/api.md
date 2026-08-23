# Knowledge API v1

The first Provelume Knowledge API is read-only and served by the same application layer used by the Knowledge Browser. The stable prefix for this pre-1.0 contract is `/api/v1`.

## Health

`GET /health` reports runtime version, embedded build-identity status, Instance identity and derived search-index status. The build status is descriptive metadata, not a local signature or integrity verification result.

## Build identity

`GET /api/v1/build-info` returns the source identity embedded in the installed package. It reads packaged local metadata and performs no network request.

The response distinguishes:

- `official_metadata_present` — structurally valid official-release metadata is embedded;
- `development_build` — structurally valid non-release metadata is embedded;
- `identity_unavailable` — metadata is missing, malformed or inconsistent with the installed package version.

Fields include package version, canonical source repository, release tag, source commit, release channel, source timestamp and the `official` declaration. The nested `verification` object deliberately reports `not_performed` for local file integrity, platform signature and artifact provenance. Embedded identity describes the package; it does not independently prove the installed files or external attestations.

The same application-layer contract is exposed by `provelume build-info` and the local `/security` browser page.

## Instance and sources

- `GET /api/v1/instance` — Instance identity, canonical object counts, knowledge/index status and explicit network baseline.
- `GET /api/v1/sources` — registered Sources with document counts and current local availability.
- `GET /api/v1/sources/{id}` — one Source.

Physical source paths remain operator configuration and are not returned by these endpoints.

## Documents

- `GET /api/v1/documents`
- `GET /api/v1/documents/{id}`
- `GET /api/v1/documents/{id}/versions`
- `GET /api/v1/documents/{id}/provenance`
- `GET /api/v1/documents/{id}/original`

`/documents` supports `source_id`, `media_type`, `area`, `date_from` and `date_to`. Date-only values are inclusive for their entire UTC day. An area is the first logical path component below a Source; it is not a physical absolute path.

The original endpoint returns the preserved bytes of the current DocumentVersion. It resolves only the content-addressed Instance reference recorded in canonical state.

## Search

`GET /api/v1/search?q=...` supports `source_id`, `media_type`, `date_from`, `date_to` and `limit`.

User input is converted to literal FTS terms rather than accepted as raw SQLite FTS syntax. The SQLite database is a disposable acceleration structure and does not provide durable object IDs.

## Knowledge health

`GET /api/v1/knowledge-health` reports issues detectable by the first slice, including extraction failures, missing Sources, duplicate current content and missing/out-of-date derived search state.

## Read-only boundary

The v1 routes in this slice do not expose mutation endpoints. Ingestion and index rebuild are operator actions through the application service/CLI. Future write APIs require separate scope and permission design rather than being added implicitly to this read-only surface.
