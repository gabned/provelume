# Knowledge API v1

The first Provelume Knowledge API is read-only and served by the same application layer used by the Knowledge Browser. The stable prefix for this pre-1.0 contract is `/api/v1`.

## Local serving boundary

`provelume serve` is intentionally loopback-only in the `0.5.x` line. The CLI accepts only
`localhost`, IPv4 loopback addresses or IPv6 loopback addresses; wildcard, LAN and arbitrary
hostnames fail before Uvicorn starts. HTTP requests must also carry a loopback or local-test Host
value, which prevents a local browser session from accepting an unrelated Host header.

The application adds a restrictive Content Security Policy, clickjacking/content-type/referrer
protections, a limited browser permissions policy and `Cache-Control: no-store` to local responses.
The interactive `/api/docs` page is disabled because it is not part of the packaged offline
browser contract; the versioned JSON API remains available directly and performs no implicit
network request. A future non-loopback mode requires separate authentication, authorization, TLS
and deployment design rather than weakening this local boundary.

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

## About and installed product

`GET /api/v1/about` reports the installed product version, packaging mode, platform and declared
update lifecycle. It reads only local runtime identity. It never performs an update check;
network access remains a separate explicit Windows-launcher or `provelume check-updates` action.

The same contract is exposed by `provelume about` and the local `/about` browser page.

## Instance and sources

- `GET /api/v1/instance` — Instance identity, schema/manifest versions, derived-state policy,
  migration/recovery counts, canonical object counts, knowledge/index status and explicit network
  baseline.
- `GET /api/v1/sources` — registered Sources with document counts and current local availability.
- `GET /api/v1/sources/{id}` — one Source.

Physical source paths remain operator configuration and are not returned by these endpoints.

## Durable ingestion runs

- `GET /api/v1/ingestion/runs?limit=50` — newest durable run summaries, bounded to 200.
- `GET /api/v1/ingestion/runs/{run_id}` — one run and its ordered per-item results.

Run and item records are schema-versioned operational state under `state/ingestion/`. Responses
contain Source identity and normalized Source-relative locators, never configured absolute paths.
They expose closed status, counts, safety limits, attempt/retry lineage, Acquisition linkage and
bounded error codes/messages.

The same service contract is available locally through:

```bash
provelume ingest INSTANCE SOURCE
provelume ingestion-runs INSTANCE
provelume ingestion-run INSTANCE RUN_ID
provelume retry-ingestion INSTANCE RUN_ID
```

`ingest` prints the complete run result. It exits non-zero when one or more items fail while still
committing and indexing valid work. Retry selects only failed or interrupted items and is a local
operator mutation; no HTTP ingestion or retry route is introduced. See
[`architecture/durable-ingestion-runs.md`](architecture/durable-ingestion-runs.md).

## Documents

- `GET /api/v1/documents`
- `GET /api/v1/documents/{id}`
- `GET /api/v1/documents/{id}/versions`
- `GET /api/v1/documents/{id}/provenance`
- `GET /api/v1/documents/{id}/original`
- `GET /api/v1/documents/{id}/classification`

`/documents` supports `source_id`, `media_type`, `area`, `hierarchy_id`,
`include_descendants`, `date_from` and `date_to`. Date-only values are inclusive for their entire
UTC day. An `area` is the first logical path component below a Source; it is not a physical
absolute path or a canonical Area identity. `hierarchy_id` selects Documents whose primary or
secondary classification is the selected node or, by default, one of its descendants.

The original endpoint returns the preserved bytes of the current DocumentVersion. It resolves only the content-addressed Instance reference recorded in canonical state.

## Hierarchy and classification

- `GET /api/v1/hierarchy` — deterministic flat nodes plus the equivalent nested tree;
- `GET /api/v1/hierarchy/{id}` — one node with stable ID, portable path, breadcrumbs and direct/
  subtree Document counts;
- `GET /api/v1/documents/{id}/classification` — the current primary node and ordered secondary
  associations, or `null` for an unclassified Document.

Hierarchy nodes and classification records are canonical JSON. Rename and movement preserve node
IDs; no API response is generated from a browser-private model. Mutation remains local service/CLI
authority and is not exposed through HTTP. See
[`architecture/hierarchical-classification.md`](architecture/hierarchical-classification.md).

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

The v1 routes in this slice do not expose mutation endpoints. Ingestion, retry and index rebuild
are operator actions through the application service/CLI. Instance validation, migration, backup
and restore are also local service/CLI operations; physical backup paths and restore authority are
not exposed through HTTP. Future write APIs require separate scope and permission design rather
than being added implicitly to this read-only surface.

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
