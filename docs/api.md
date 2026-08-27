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

## Privacy and network activity

`GET /api/v1/security/network` derives an effective network policy and component inventory from the local Instance configuration. The same contract is available through `provelume network-status <instance>` and the EN/IT `/security/network` browser page.

The result is observationally honest:

- `network_used` is `false` because reading the result performs no network request;
- `observed_activity.status` is `not_instrumented`, which is not a claim that zero traffic occurred;
- filesystem Sources are classified as `local_only`, but their physical paths are never returned;
- configured HTTP(S) endpoints are reduced to their origin, excluding paths, query strings, fragments and credentials;
- unknown Source, connector or provider types are `undeclared` with `network_capability: unknown` rather than silently treated as local;
- conflicts include enabled external components under `external_access: false`, enabled update checks without an endpoint and malformed declarations.

The endpoint is read-only and does not mutate canonical, derived or configuration state.

## Read-only boundary

The v1 routes in this slice do not expose mutation endpoints. Ingestion and index rebuild are operator actions through the application service/CLI. Future write APIs require separate scope and permission design rather than being added implicitly to this read-only surface.

## Installation security

`GET /api/v1/security/installation` verifies the locally installed Provelume package against
wheel `RECORD` SHA-256 identities. It performs no network I/O and does not read Instance
knowledge or configuration. The response is a verification snapshot computed once when the
server process starts.

An operator can add release evidence only through trusted process-start configuration:

```bash
provelume serve INSTANCE \
  --release-bundle /path/to/provelume-release-bundle \
  --expected-manifest-sha256 <64-hex-digest>
```

Core verifies the bounded bundle contract, candidate wheel identity and
internal wheel `RECORD`, then compares installed package bytes directly with wheel members.
The result adds `release_linkage` while preserving the original top-level installation states
(`package_integrity_verified`, `modified_installation`, or `verification_unavailable`). A
self-consistent bundle leaves publisher authentication `not_established`. A matching supplied
hash reports `trusted_manifest_sha256_matched`, meaning only that the checked bundle matches
the independently obtained hash.

HTTP clients cannot select or change a server-local release directory or expected hash. The
endpoint rejects `release_bundle` and `expected_manifest_sha256` query parameters with `400`
and only returns the cached startup result. This keeps the unauthenticated read-only surface
from becoming a path-probing or repeated bundle-processing interface.
