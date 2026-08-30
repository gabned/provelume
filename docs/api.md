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
- `GET /api/v1/sources` — registered Sources with document counts and current availability state;
  connector declarations report `configuration_only` until their guarded transport exists.
- `GET /api/v1/sources/{id}` — one Source.

Physical source paths remain operator configuration and are not returned by these endpoints.

## Connector lifecycle and read surfaces

- `GET /api/v1/connectors` — definitions, isolated connector instances, selected Sources,
  lifecycle counts, local health, empty cursor envelopes and the canonical/Original authority
  boundary;
- `GET /api/v1/connectors/definitions/{id}` — one versioned connector definition manifest;
- `GET /api/v1/connectors/{connector_instance_id}` — one instance with provider/account identity,
  safe endpoint origin, scopes, policy, external credential reference, cursor/health state and
  selected Source views;
- `GET /api/v1/connectors/{connector_instance_id}/sources/{source_id}` — one selected Source with
  configured/effective lifecycle state plus retained Document and Acquisition counts.
- `GET /api/v1/connectors/{connector_instance_id}/sources/{source_id}/acquisitions` — newest
  retained manual web Acquisition summaries for that exact connector/Source binding;
- `GET /api/v1/connectors/{connector_instance_id}/sources/{source_id}/acquisitions/{id}` — one
  completed result with retrieval evidence, canonical Document/Version/Original records, provenance
  and explicit replay/duplicate/derived-text status.

The API models come directly from the same application service used by the CLI and EN/IT
`/connectors` Browser pages. They are configuration-derived and perform no DNS resolution,
provider request, OAuth flow, cursor update or Instance mutation. Connector credential values
cannot be stored; the local detail view may show only the validated external reference kind/name.
The privacy/network inventory remains stricter and omits that reference entirely.

Create, update, enable, disable and tombstone removal are explicit local service/CLI actions.
Removal retains canonical instance/Source identity, requires child Sources to be removed
independently before their parent, and never deletes or overwrites acquired Original bytes.
Configuration operations are path-redacted and secret-free. There are deliberately no connector
`POST`, `PATCH` or `DELETE` routes.

Manual acquisition is likewise not initiated over HTTP. It requires the application service or the
explicit local command below, whose URL must exactly match the enabled web Source after guarded
canonicalization:

```bash
provelume connector-web-acquire INSTANCE CONNECTOR_INSTANCE_ID SOURCE_ID URL --confirm-network
```

The command performs one guarded request and returns its completed result. Browser and API reads do
not retry, refresh, contact the Source or create missing derived state. See
[`architecture/manual-web-acquisition.md`](architecture/manual-web-acquisition.md).

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

## Durable scheduler and job journal

- `GET /api/v1/scheduler` — bounded policy/job counts, next due instant, executable/deferred job
  kinds and explicit network/deletion flags;
- `GET /api/v1/scheduler/policies` — all strict, versioned policies;
- `GET /api/v1/scheduler/policies/{policy_id}` — one policy;
- `GET /api/v1/scheduler/jobs?status=...&policy_id=...&limit=100` — newest privacy-minimizing
  durable jobs, bounded to 500;
- `GET /api/v1/scheduler/jobs/{job_id}` — one job with lease/checkpoint/attempt evidence and its
  terminal receipt reference;
- `GET /api/v1/scheduler/receipts?limit=100` — newest immutable terminal receipts, bounded to 500.

The endpoints are read-only and perform no evaluation, execution, recovery, network request,
repair or deletion. Scheduler mutations require the application service or an explicit local CLI
action through `scheduler-policy-create`, `scheduler-policy-state`, `scheduler-run-now` and
`scheduler-run`. The EN/IT `/scheduler` Browser view uses the same service reads; its active local
runtime evaluates at most one safe job per cycle while the Browser is running.

Deep Instance validation and the initial derived FTS reindex are the `0.8/S01` executors. `0.8/S02`
also executes `source.refresh` for an exact managed folder Source after its durable observer reaches
a stable snapshot. `0.8/S03` adds incremental reindex, Markdown-library rebuild, Original assurance
and duplicate scan plus resumable per-item FTS generation evidence. `0.8/S04` adds exact
Source-scoped reconciliation with monotonic cursors and closed lifecycle evidence. Records contain
only IDs, clocks, closed status/error values, fingerprints and counts; caller idempotency text,
paths, URLs, credentials and document content are not persisted.
See
[`architecture/durable-scheduler-and-job-journal.md`](architecture/durable-scheduler-and-job-journal.md).
The random lease token is execution authority and is never returned by service, CLI, API or
Browser read surfaces; those views retain only worker/timing evidence plus `token_present`.

## Local OCR capability, jobs and bundles

- `GET /api/v1/ocr/capability` — disabled/availability state, closed localized error, configured
  and installed languages, exact engine/renderer/decoder identities and effective limits;
- `GET /api/v1/ocr/jobs?limit=100` — bounded durable OCR jobs joined to content-free execution
  run state, warnings or closed error;
- `GET /api/v1/ocr/jobs/{job_id}` — one OCR scheduler job and its run record;
- `GET /api/v1/ocr/bundles?version_id=...` — checksum-verified derived bundle manifests, optionally
  restricted to one exact DocumentVersion.

These reads never enable OCR, probe when the configured mode is disabled, queue work, invoke a
component or repair/remove state. Lease tokens are sanitized. There are deliberately no versioned
API mutation routes; `POST /api/v1/ocr/...` is not defined.

Local mutations require explicit CLI commands or the loopback `/ocr` Browser surface, whose forms
carry a per-process CSRF token:

```bash
provelume ocr-configure INSTANCE --mode automatic --language eng \
  --engine-executable /usr/bin/tesseract
provelume ocr-capability INSTANCE
provelume ocr-queue INSTANCE VERSION_ID --mode forced --language eng
provelume ocr-run INSTANCE JOB_ID
provelume ocr-cancel INSTANCE JOB_ID
provelume ocr-remove INSTANCE VERSION_ID
provelume ocr-rebuild INSTANCE VERSION_ID
```

Capability is disabled by default and reports `ready` only after compatible local Tesseract,
pypdfium2/PDFium, Pillow and every selected local language pack are observed. Execution has no
runtime download, cloud provider or remote fallback. OCR results remain unverified derived state;
the API does not promote them into canonical Document content. See
[`architecture/local-ocr-contract.md`](architecture/local-ocr-contract.md).

## Managed folder Sources

- `GET /api/v1/sources` and `GET /api/v1/sources/{source_id}` include a path-redacted `folder`
  view for managed filesystem Sources;
- `GET /api/v1/folder-sources` lists only managed folder Sources with lifecycle, policy,
  availability, quiescence, fingerprint/count and last-run evidence.

These routes never enumerate a mount and expose no configured path. Registration, observation,
enable/pause and refresh remain local service/CLI authority; the loopback `/sources` Browser adds
the same explicit controls behind a per-process CSRF token. See
[`architecture/durable-folder-sources.md`](architecture/durable-folder-sources.md).

## Maintenance catalogue and reindex generations

- `GET /api/v1/maintenance` — the complete closed catalogue, exact availability boundaries and
  linked scheduler policies;
- `GET /api/v1/maintenance/actions/{action_id}` — one catalogue action;
- `GET /api/v1/maintenance/plans/{action_id}` — a read-only full/incremental reindex estimate and
  temporary-space preflight;
- `GET /api/v1/maintenance/runs?limit=100` — newest durable reindex generation records;
- `GET /api/v1/maintenance/runs/{run_id}` — one content-free plan, cursor, generation and recovery
  record.
- `GET /api/v1/maintenance/source-cursors` — path-redacted reconciliation lifecycle for every
  managed filesystem Source;
- `GET /api/v1/maintenance/source-cursors/{source_id}` — one exact Source cursor;
- `GET /api/v1/maintenance/source-runs?limit=100` — newest content-free reconciliation runs;
- `GET /api/v1/maintenance/source-runs/{run_id}` — one Source-bound plan, classification counts,
  checkpoint and terminal state.
- `GET /api/v1/maintenance/resource-statistics?history_limit=30` — current threshold settings,
  newest content-free observation and bounded trend history;
- `GET /api/v1/maintenance/resource-statistics/snapshots?limit=100` — newest immutable Instance
  resource snapshots;
- `GET /api/v1/maintenance/resource-statistics/snapshots/{snapshot_id}` — one exact file/byte/
  category/capacity observation and its previous-snapshot delta.

All maintenance API routes are read-only. They never queue work, activate a generation, read a
Source path or accept a backup destination. Local mutations use `maintenance-policy-create` and
`maintenance-run`; the loopback `/maintenance` Browser protects Run now with a per-process CSRF
token. Full and incremental plans expose only canonical IDs, counts, byte estimates, fingerprints
and observed free space. See
[`architecture/maintenance-catalogue-and-reindex-recovery.md`](architecture/maintenance-catalogue-and-reindex-recovery.md).
Source reconciliation endpoints never enumerate a Source or expose locators. Local policy and Run
now mutations require an exact managed `source_id`; see
[`architecture/source-reconciliation-cursors-and-lifecycle.md`](architecture/source-reconciliation-cursors-and-lifecycle.md).
Resource endpoints return aggregate regular-file and logical-byte counts, closed categories,
filesystem capacity and applied threshold codes; they expose no path, filename or content. Threshold
configuration remains local service/CLI authority. See
[`architecture/resource-statistics-capacity-and-thresholds.md`](architecture/resource-statistics-capacity-and-thresholds.md).

## Documents

- `GET /api/v1/documents`
- `GET /api/v1/documents/{id}`
- `GET /api/v1/documents/{id}/versions`
- `GET /api/v1/documents/{id}/provenance`
- `GET /api/v1/documents/{id}/original`
- `GET /api/v1/documents/{id}/classification`
- `GET /api/v1/documents/{id}/disposition`
- `GET /api/v1/documents/{id}/content?mode=raw|original`

`/documents` supports `source_id`, `media_type`, `area`, `hierarchy_id`,
`include_descendants`, `date_from`, `date_to` and
`disposition=active|archived|trashed|all`. The default is `active`; trashed Documents are absent
from default browse/search/library views but remain directly addressable until permanent purge.
Date-only values are inclusive for their entire UTC day. An `area` is the first logical path
component below a Source; it is not a physical absolute path or a canonical Area identity.
`hierarchy_id` selects Documents whose primary or secondary classification is the selected node or,
by default, one of its descendants.

The original endpoint returns the preserved bytes of the current DocumentVersion as an attachment.
It resolves only the content-addressed Instance reference recorded in canonical state and verifies
the current Version/Original hash and size bindings before returning bytes. A mismatch returns
`409`. The content endpoint is `text/plain`, verifies the same binding and exposes either the raw
Markdown representation or decoded Original text. Binary/non-UTF-8 Originals return `415` for
`mode=original`; they are never inlined as active content.

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

## Markdown library and Viewer

- `GET /api/v1/library` — read-only manifest/inventory validation for the generated `library/`;
- `GET /api/v1/documents/{id}/content?mode=raw|original` — verified plain-text Viewer input;
- `/documents/{id}?mode=rendered|raw|original` — EN/IT loopback Viewer modes;
- `GET /api/v1/documents/{id}/original` — exact preserved bytes as a download attachment.

Library status is `missing`, `invalid`, `modified`, `stale` or `ready`. A read never creates or
repairs the projection. Rebuild remains a local service/CLI mutation through `library-rebuild` or
the coordinated `rebuild-derived` command; HTTP `POST /api/v1/library` is not defined.

Rendered mode uses a bounded structural Markdown subset. Raw HTML is escaped, while Markdown links
and images become inert labels with no document-controlled `href` or `src`. Raw and Original text
are HTML-escaped by the template. The Viewer does not build missing bundles, load local/remote
document resources, contact a provider or treat projection edits as canonical input. See
[`architecture/markdown-library-viewer.md`](architecture/markdown-library-viewer.md).

## Retention status

- `GET /api/v1/documents?disposition=active|archived|trashed|all` — filter by effective canonical
  disposition;
- `GET /api/v1/documents/{id}/disposition` — status, library inclusion, restoration coordinates and
  revision for one Document.

Archive, library exclusion, recoverable trash, restoration and permanent purge remain local
application-service/CLI mutations. There is deliberately no generic HTTP `DELETE`, retention
`POST` or purge route on the unauthenticated loopback API. See
[`architecture/retention-boundaries.md`](architecture/retention-boundaries.md).

## Search

`GET /api/v1/search?q=...` supports `source_id`, `media_type`, `date_from`, `date_to` and `limit`.

User input is converted to literal FTS terms rather than accepted as raw SQLite FTS syntax. The SQLite database is a disposable acceleration structure and does not provide durable object IDs.

## Knowledge health

`GET /api/v1/knowledge-health` reports issues detectable by the first slice, including extraction failures, missing Sources, duplicate current content and missing/out-of-date derived search state.

## Privacy and network activity

`GET /api/v1/security/network` derives an effective network policy and component inventory from the
local Instance configuration and canonical connector declarations. The same contract is available
through `provelume network-status <instance>` and the EN/IT `/security/network` browser page.
Connector entries disclose only safe origin/data-category declarations and authorization mode;
external credential references are omitted from this network-status surface. Connector inventory
and detail responses may include an external reference kind/name and schema-3 authorization status,
time, loopback-binding and consent metadata, but never state, authorization URI, code, PKCE
verifier, token, client secret or credential value.

The result is observationally honest:

- `network_used` is `false` because reading the result performs no network request;
- `observed_activity.status` is `not_instrumented`, which is not a claim that zero traffic occurred;
- filesystem Sources are classified as `local_only`, but their physical paths are never returned;
- configured HTTP(S) endpoints are reduced to their origin, excluding paths, query strings, fragments and credentials;
- unknown Source, connector or provider types are `undeclared` with `network_capability: unknown` rather than silently treated as local;
- conflicts include enabled external components under `external_access: false`, enabled update checks without an endpoint and malformed declarations.

The endpoint is read-only and does not mutate canonical, derived or configuration state.

## Read-only boundary

The v1 routes in this slice do not expose mutation endpoints. Connector lifecycle, ingestion,
retry, index rebuild,
Markdown-library rebuild and every retention action are operator actions through the application
service/CLI. Instance validation, migration, backup and restore are also local service/CLI
operations. Portable export and replacement import likewise remain explicit local service/CLI
authority; physical bundle/backup paths, import/restore authority and purge confirmation tokens are
not exposed through HTTP. Future write APIs require separate scope and permission design rather
than being added implicitly to this read-only surface. See
[`architecture/portable-export-import.md`](architecture/portable-export-import.md).

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
