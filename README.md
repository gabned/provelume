# Provelume

**Knowledge you can trace.**

Provelume is a provenance-first personal knowledge intelligence system for building durable, portable and traceable knowledge from files and, over time, other sources.

This repository is the public clean-room home of the reusable **Provelume Core** and the self-hosted **Provelume Instance** distribution. It does not contain the private Nexus reference instance, personal data, private product documentation or private Git history.

> The AI is not the memory. Your knowledge outlives your AI.

## Current status: 0.8.0 Vigilia published preview

[`v0.8.0`](https://github.com/gabned/provelume/releases/tag/v0.8.0) Vigilia is the latest published
prerelease. It was built from commit
[`d20e63079adf85829723cab86766266a8bc6cdcd`](https://github.com/gabned/provelume/commit/d20e63079adf85829723cab86766266a8bc6cdcd)
by the permanent trusted [Official release workflow](https://github.com/gabned/provelume/actions/runs/33315580878).
Vigilia adds an explicitly configured durable scheduler, folder Sources, recoverable local
maintenance, Source reconciliation and content-free resource observations while keeping startup
and upgrade default-disabled.

Issues [#122](https://github.com/gabned/provelume/issues/122),
[#124](https://github.com/gabned/provelume/issues/124),
[#126](https://github.com/gabned/provelume/issues/126),
[#128](https://github.com/gabned/provelume/issues/128) and
[#130](https://github.com/gabned/provelume/issues/130), together with the
[0.8.0 release plan](docs/releases/0.8.0.md), define this release. The
[0.7.0 release plan](docs/releases/0.7.0.md) remains the published connector and safe-web-intake
baseline.
See the [public roadmap](docs/roadmap.md), the
[configurable-folder contract](docs/architecture/configurable-folder-settings.md) and the
[Windows preview guide](docs/windows-preview.md) for portability and trust boundaries.

The roadmap records `0.8.0 Vigilia` as a published preview and `0.9.0 Lectio` only as the next
forecast while retaining the later sequence through `1.0.0`. Package and embedded build identity
are aligned to `0.8.0`, `v0.8.0` and the exact published commit. Forecast entries are sequencing
coordinates, not publication claims or release authorization.

The active source tree can:

- initialize a portable Instance in an ordinary directory;
- ingest local TXT, Markdown, PDF and other bounded supported formats;
- preserve exact originals with SHA-256 content identity;
- record Sources, Acquisitions, Documents, DocumentVersions and provenance;
- retain stable parent-linked Area/Subarea, Project and Collection identities plus one primary and
  multiple secondary Document classifications;
- rebuild a deterministic `library/` with one primary Markdown path per Document, README indexes
  and relative secondary/Source/date/type links without copying acquired Originals;
- archive, exclude from the library, recoverably trash and restore a Document as distinct local
  actions without deleting its Original or changing its stable identity;
- permanently purge a trashed Document only after a fresh impact preview, short-lived confirmation
  token and explicit acknowledgement of Source/backup/replica limits;
- export a deterministic hash-manifested portable bundle with explicit derived-state policy;
- replace an existing target from a fully validated portable bundle with an automatic verified
  backup, atomic staging, rollback and interrupted-import recovery;
- keep durable ingestion runs and retry only failed or interrupted items;
- process an Instance-local or external Drop Inbox with move-after-verified-commit semantics;
- configure the Inbox display name, Drop folder and managed-copy folder locally;
- build deterministic Markdown, page-map and bounded-asset document bundles;
- detect exact and conservative probable duplicates without automatic merge or deletion;
- verify retained Original bytes and canonical references without automatic repair;
- coordinate incremental and full derived-state rebuilds under an exclusive Instance lock;
- browse ordered, bounded and path-redacted operation evidence;
- extract text locally and build a disposable SQLite FTS5 search index;
- expose a read-only versioned Knowledge API with FastAPI;
- provide an EN/IT Knowledge Browser for browse, search, safe rendered/raw/Original document
  viewing, versions, provenance, Inbox, bundles, duplicates, assurance, rebuild reports,
  operations, settings and health;
- report its embedded version/tag/commit/source identity offline through CLI, API and browser;
- define provider-independent connector types and keep ConnectorDefinition, ConnectorInstance and
  Source as separate stable multi-instance identities;
- create, inspect, update, disable and tombstone-remove connector instances and Sources while
  retaining acquired knowledge and immutable Original provenance;
- expose aligned connector inventory and health through service, CLI, read-only API and EN/IT
  Browser views;
- perform installed-app OAuth 2.0 authorization with mandatory PKCE S256, exact callback binding,
  explicit consent and revocation/reauthorization without deleting acquired knowledge;
- acquire one explicitly requested HTTP(S) URL through current Instance, connector and Source
  authority with SSRF, DNS-rebinding, redirect and bounded-response protections;
- preserve exact guarded-response bytes as an immutable Original and create separately identified,
  deterministic readable text only for supported web representations;
- configure disabled, paused or enabled durable policies for manual, interval or local calendar
  execution with explicit timezone, DST, quiet-window, jitter and missed-run behavior;
- journal bounded validation and derived FTS-reindex jobs with leases, heartbeat, checkpoints,
  retry/backoff, crash recovery and content-free terminal receipts;
- register independently enabled or paused local, removable and mounted-network folder Sources,
  with explicit timezone-aware manual/interval/calendar refresh policies;
- observe path-redacted durable availability, quiescence and mount-loss state, then refresh stable
  snapshots through deterministic crash-resumable ingestion without duplicate Acquisitions;
- inspect and control the candidate scheduler and folder Sources through service, CLI, read-only
  API and local EN/IT Browser surfaces without hidden provider access or automatic deletion;
- inspect a closed maintenance catalogue, dry-run full or incremental FTS work with exact
  item/byte/free-space evidence, and schedule available actions through the same durable journal;
- build full or incremental FTS candidates outside the active index, checkpoint each committed
  item, resume after stale leases, and atomically activate only a complete validated generation;
- schedule Markdown-library rebuild, deep Instance validation, Original assurance and duplicate
  scanning while target-bound backup catalogue entries remain visibly unavailable;
- reconcile one exact managed filesystem Source against current canonical provenance, classifying
  current, changed, renamed, untracked and missing evidence without ingesting or deleting anything;
- retain path-redacted Source cursors and per-job runs with lifecycle, resync, bounded retry,
  checkpoint and replay evidence across crash, stale lease, backup/restore and portable transfer;
- record append-only, content-free Instance resource snapshots with exact regular-file and logical-
  byte totals, closed authority-aware categories, filesystem capacity and user-selected warning or
  critical thresholds;
- inspect exact per-snapshot count, byte, free-capacity and category deltas across clock change and
  interrupted scheduler receipt commits without quota enforcement, automatic retention, cleanup or
  canonical mutation;
- restart without losing canonical state;
- run without Git, GitHub, Provelume Cloud or an external AI provider.

The `v0.2.0` preview added local installation verification against wheel `RECORD` and declared
Privacy & Network Activity transparency. The `v0.3.0` preview optionally links installation checks
to an operator-supplied local release bundle. The `v0.4.0` and `v0.4.1` previews introduced and
hardened the per-user Windows product shell.

These checks are read-only and perform no network request. They do not prove official origin,
operating-system egress enforcement or zero runtime traffic. All extracted/searchable
representations remain derived state and can be recreated from preserved originals after deletion
of those derived copies.

The published `0.8.0` Vigilia preview creates no scheduler policy or job on install, upgrade or
startup.
Folder refresh and maintenance require explicit local configuration and run only while the current
runtime is active. Native filesystem-event watchers, always-on desktop agents, OCR, email/Google
Drive intake, semantic/vector search and AI classification remain later work.

## Quick start

Requires Python 3.12 or newer.

```bash
python scripts/bootstrap.py
```

The bootstrap command creates `.venv` and installs Provelume plus developer checks. Then:

```bash
.venv/bin/provelume init .local/demo --name "My Provelume"
.venv/bin/provelume ingest .local/demo examples/demo-source
.venv/bin/provelume serve .local/demo
```

On Windows, use `.venv\\Scripts\\provelume.exe` for the same commands. Open `http://127.0.0.1:8000/` after starting the server.

Configure a custom Inbox name and local folders. Relative paths resolve from the Instance root;
absolute paths may live elsewhere on the local filesystem:

```bash
.venv/bin/provelume configure-inbox .local/demo \
  --name "Incoming knowledge" \
  --drop "Drop" \
  --managed "/path/to/provelume-managed-copies"
.venv/bin/provelume folder-settings .local/demo
.venv/bin/provelume inbox-process .local/demo
```

A missing external folder fails visibly and is not silently recreated. Once Inbox Documents or
Acquisitions exist, changing the managed-copy location requires a future verified relocation
workflow; the display name and Drop folder can still change.

Register an unreleased managed folder Source with portable interval watching, inspect its durable
state, or request one exact journaled refresh:

```bash
.venv/bin/provelume folder-source-register .local/demo /path/to/research \
  --name "Research" --class removable --mode interval \
  --timezone Europe/Rome --interval-seconds 300
.venv/bin/provelume folder-sources .local/demo
.venv/bin/provelume folder-source-refresh .local/demo <source-id>
```

The observer waits for two stable metadata snapshots and five quiescent seconds by default. Mount
loss is visible and never deletes acquired knowledge. See the
[durable folder Source contract](docs/architecture/durable-folder-sources.md).

Inspect the unreleased maintenance catalogue, dry-run an exact reindex plan, or execute one
journaled incremental generation:

```bash
.venv/bin/provelume maintenance-catalog .local/demo
.venv/bin/provelume maintenance-plan .local/demo search.reindex.incremental
.venv/bin/provelume maintenance-run .local/demo search.reindex.incremental \
  --idempotency-key operator-incremental-1
```

Timed actions use `maintenance-policy-create` with the same timezone, DST, quiet-window, jitter and
missed-run controls as every other scheduler policy. Candidate indexes are derived and disposable;
durable run evidence is included in backup and portable transfer. See the
[maintenance catalogue and reindex recovery contract](docs/architecture/maintenance-catalogue-and-reindex-recovery.md).

Reconcile one exact managed Source without changing canonical knowledge:

```bash
.venv/bin/provelume maintenance-policy-create .local/demo maintenance.source_reconcile \
  --source-id <source-id> --state paused --mode interval --timezone Europe/Rome \
  --interval-seconds 3600
.venv/bin/provelume maintenance-run .local/demo maintenance.source_reconcile \
  --source-id <source-id> --idempotency-key operator-reconcile-1
.venv/bin/provelume maintenance-source-cursors .local/demo
.venv/bin/provelume maintenance-source-runs .local/demo
```

Only Source-bound hashes, digests, counts and clocks are journaled; locators and configured paths
are not. A mounted-network Source is reported truthfully in its terminal receipt, but the action
opens no provider or HTTP transport. See the
[Source reconciliation contract](docs/architecture/source-reconciliation-cursors-and-lifecycle.md).

Inspect the navigable operation log or run a consistency rebuild:

```bash
.venv/bin/provelume operations .local/demo
.venv/bin/provelume rebuild-derived .local/demo --mode agreement
```

Rebuild or validate only the portable Markdown filesystem projection:

```bash
.venv/bin/provelume library-rebuild .local/demo
.venv/bin/provelume library-status .local/demo
```

The projection contains `areas/`, `projects/`, `archive/`, `unclassified/` and generated
Collection/tag/person/Source/date/type indexes. Generated links are relative, secondary
classifications never duplicate a Document file, and projection edits never mutate canonical
knowledge. See the
[Markdown library and Viewer contract](docs/architecture/markdown-library-viewer.md).

Apply retention actions locally. Archive and projection removal retain canonical lineage;
recoverable trash hides the Document from default browse/search/library views but can restore it:

```bash
.venv/bin/provelume archive-document .local/demo <document-id>
.venv/bin/provelume remove-from-library .local/demo <document-id>
.venv/bin/provelume trash-document .local/demo <document-id>
.venv/bin/provelume restore-from-trash .local/demo <document-id>
```

Permanent purge is a separate two-step action. The preview reports the exact current live-Instance
impact and issues a short-lived token; the commit requires both that token and acknowledgement that
configured Source files, backups and replicas are outside the erasure claim:

```bash
.venv/bin/provelume purge-preview .local/demo <document-id>
.venv/bin/provelume purge-document .local/demo <document-id> \
  --confirm <confirmation-token> --acknowledge-boundaries
```

See the [retention and purge boundary](docs/architecture/retention-boundaries.md).

Validate the Instance without changing it, or create a hash-verified backup outside the Instance:

```bash
.venv/bin/provelume validate .local/demo
.venv/bin/provelume backup .local/demo --output /path/to/demo-backup.zip
```

Opening a supported schema-1 Instance runs the forward-only schema-2 migration only after deep
preflight and a verified automatic backup. `validate` never migrates. An operator can make the
transition explicit, or restore a same-Instance backup through staged validation and automatic
rollback:

```bash
.venv/bin/provelume migrate .local/demo
.venv/bin/provelume restore .local/demo /path/to/demo-backup.zip
```

Backup ZIPs include canonical JSON, acquired Originals and retained Instance state. Rebuildable
`indexes/`, the generated `library/` projection and transient locks are excluded by the manifest
policy. External Inbox/Source working folders are not part of the Instance backup. See the
[Portable Instance contract](docs/architecture/portable-instance.md).

For cross-Instance or cross-platform transfer, export a separate deterministic portable bundle.
The default policy rebuilds indexes and the Markdown library after import; `include` carries their
current manifested bytes. Import replaces an existing valid target, so initialize an empty target
first when moving to a new directory:

```bash
.venv/bin/provelume export .local/demo --output /path/to/demo-portable.zip
.venv/bin/provelume init .local/imported --name "Import target"
.venv/bin/provelume import .local/imported /path/to/demo-portable.zip
```

Every bundle path and payload hash is validated before target mutation. Reserved Windows names,
case/file-directory collisions, traversal, absolute paths, symlinks, undeclared members and partial
bundles fail closed. See the
[portable export/import contract](docs/architecture/portable-export-import.md).

Create and navigate canonical hierarchy locally, then classify a Document without copying or
rewriting its knowledge:

```bash
.venv/bin/provelume hierarchy-create .local/demo area "Work"
.venv/bin/provelume hierarchy-create .local/demo project "Atlas" --parent-id <area-id>
.venv/bin/provelume classify .local/demo <document-id> --primary <project-id> \
  --secondary <collection-id>
.venv/bin/provelume hierarchy-list .local/demo
```

Rename keeps the same node identity; `hierarchy-move` changes only its stable parent link. See the
[hierarchical classification contract](docs/architecture/hierarchical-classification.md).

Inspect the package's embedded source identity without creating an Instance or making a network request:

```bash
.venv/bin/provelume build-info
```

Inspect the installed product, packaging and update policy, also without a network request:

```bash
.venv/bin/provelume about
```

An update check is a separate explicit network action. It contacts GitHub Releases, sends no
Instance content and is never enabled in the background by the Core:

```bash
.venv/bin/provelume check-updates --channel preview
```

The published Windows `0.8.0` preview packages the same behavior behind a per-user installer and
EN/IT launcher. Download it only from the official
[`v0.8.0` prerelease](https://github.com/gabned/provelume/releases/tag/v0.8.0); it remains an
unsigned preview. See the [Windows preview guide](docs/windows-preview.md).

Inspect one Instance's declared network policy and components, also without making a network request:

```bash
.venv/bin/provelume network-status .local/demo
```

Verify the installed package against local metadata, or optionally against a local release
bundle and separately obtained manifest hash:

```bash
.venv/bin/provelume verify-installation
.venv/bin/provelume verify-installation \
  --release-bundle /path/to/provelume-release-bundle \
  --expected-manifest-sha256 <64-hex-digest>
```

To expose the same release-linked result through the read-only API and EN/IT browser, a local
operator configures it when starting the server:

```bash
.venv/bin/provelume serve .local/demo \
  --release-bundle /path/to/provelume-release-bundle \
  --expected-manifest-sha256 <64-hex-digest>
```

The server verifies once at startup and serves the cached result. HTTP clients cannot supply
or change server-local evidence paths.

Run all tests with:

```bash
.venv/bin/python -m pytest -q
```

## Docker Compose

A generic self-hosted example is available in `instance/docker-compose.yml`:

```bash
cd instance
docker compose up --build
```

It starts a local Instance on `http://127.0.0.1:8042/` and mounts the synthetic demo source read-only. Set `PROVELUME_SOURCE_DIR` to another local directory before starting if desired.

## Portable Instance layout

Schema 2 uses an ordinary filesystem directory with a closed manifest:

```text
<instance>/
  provelume.yml
  instance-manifest.json
  originals/
  knowledge/
  state/
  indexes/
  library/
```

`instance-manifest.json` binds stable Instance identity, current schema and the explicit derived-
state policy. `originals/` and `knowledge/` are durable canonical state. Retained artifacts under
`state/` are included in local backups; `indexes/` and `library/` are rebuildable. SQLite is used
only for search acceleration; neither it nor the Markdown projection is the authoritative
knowledge format.

Drop and managed-copy folders may optionally be elsewhere on the local filesystem. They remain
working locations rather than alternate canonical stores. A Provelume backup preserves acquired
knowledge but not unacquired files waiting in an external Drop folder.

See `docs/architecture/portable-instance.md`,
`docs/architecture/portable-export-import.md`,
`docs/architecture/canonical-derived-state.md` and
`docs/architecture/configurable-folder-settings.md`, plus the unreleased
`docs/architecture/durable-folder-sources.md` contract.

## Knowledge API

The browser and external clients use the same application layer. The read-only API is under `/api/v1`, including:

- `GET /health`
- `GET /api/v1/build-info`
- `GET /api/v1/about`
- `GET /api/v1/instance`
- `GET /api/v1/sources`
- `GET /api/v1/sources/{id}`
- `GET /api/v1/folder-sources`
- `GET /api/v1/ingestion/runs`
- `GET /api/v1/ingestion/runs/{id}`
- `GET /api/v1/hierarchy`
- `GET /api/v1/hierarchy/{id}`
- `GET /api/v1/library`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{id}`
- `GET /api/v1/documents/{id}/content`
- `GET /api/v1/documents/{id}/classification`
- `GET /api/v1/documents/{id}/versions`
- `GET /api/v1/documents/{id}/provenance`
- `GET /api/v1/documents/{id}/original`
- `GET /api/v1/search`
- `GET /api/v1/inbox`
- `GET /api/v1/inbox/submissions`
- `GET /api/v1/operations`
- `GET /api/v1/operations/{id}`
- `GET /api/v1/bundles`
- `GET /api/v1/duplicates`
- `GET /api/v1/assurance`
- `GET /api/v1/rebuild`
- `GET /api/v1/settings/folders`
- `GET /api/v1/knowledge-health`
- `GET /api/v1/security/network`
- `GET /api/v1/security/installation`

The settings API redacts external absolute paths. Folder mutation is available only through local
CLI or the loopback/CSRF-protected browser form. See `docs/api.md` for the complete contract and
filtering behavior.

## Multi-instance connector lifecycle

Connector definitions, isolated account/endpoint policies and independently selected Sources are
canonical local JSON. The service and CLI can create, inspect, update, enable, disable and retain a
removal tombstone for each instance or Source. Removal never implies Document purge or Original
deletion, and a parent instance can be removed only after its Sources are handled independently.

```bash
.venv/bin/provelume connector-inventory .local/demo
.venv/bin/provelume connector-instance-show .local/demo CONNECTOR_INSTANCE_ID
.venv/bin/provelume connector-source-show .local/demo CONNECTOR_INSTANCE_ID SOURCE_ID
```

`GET /api/v1/connectors` and the EN/IT `/connectors` Browser pages expose the same read models.
Mutation stays local to the service/CLI. Every configuration operation is path-redacted and
secret-free; the per-instance cursor envelope remains empty and health remains configuration-only
until later OAuth, guarded transport and refresh slices are implemented.

## Privacy and network baseline

The baseline Instance config disables external access and update checks. The runtime contains no analytics, telemetry, CDN assets or external AI calls. Its core ingestion, provenance, full-text search, API and browser remain useful offline.

`provelume network-status`, `GET /api/v1/security/network` and `/security/network` expose the effective policy and configured capability inventory. Physical Source paths are redacted, configured HTTP(S) endpoints are reduced to origins, unknown component types fail visibly, and observed traffic remains explicitly `not_instrumented`. Connector configuration and future AI providers must declare network capability explicitly and remain optional; the current connector lifecycle performs no provider request. See `docs/privacy-network.md` and `docs/architecture/provider-boundaries.md`.

## Verifiable and deterministic release foundation

Official Core/self-hosted release artifacts are traceable to the public `gabned/provelume` repository. The release workflow is separate from normal CI and activates only for semantic version tags that point to commits already present on `main`.

A release publishes Python wheel/source artifacts together with SHA-256 checksums, a CycloneDX SBOM and a provider-independent `release-manifest.json`, then creates GitHub build-provenance attestations. Pre-1.0 tags are published as preview releases.

The Python wheel and source distribution also pass a measured deterministic-component gate. The build backend is pinned exactly, `SOURCE_DATE_EPOCH` comes from the public commit, and two independent clean source copies must produce byte-identical wheel and source-distribution hashes before release assembly continues. The evidence is published as `build-determinism.json`.

The deterministic builder also embeds validated package identity before each copy is built. Official packages carry their matching version, tag, full public commit, release channel and source timestamp. Development builds carry a development state and may identify the source commit without claiming to be a release.

The same offline result is available from:

- `provelume build-info`;
- `GET /api/v1/build-info`;
- the Knowledge Browser's **Security** page at `/security`.

These surfaces distinguish official metadata, development builds and unavailable identity. They intentionally report local integrity, platform signature and external provenance as **not verified**: embedded metadata describes the package but is not yet a complete installation-verification engine.

To run the deterministic comparison locally after installing `requirements-release.txt`:

```bash
SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" \
python scripts/deterministic_build.py \
  --source . \
  --output-dir dist \
  --evidence build-determinism.json \
  --commit "$(git rev-parse HEAD)"
```

This supports a **traceable build** guarantee and a **same-source/same-environment byte-identical** guarantee for the Python distributions. It is not yet a claim that the complete release is independently reproducible on every platform or that the current installation has been cryptographically verified.

See `docs/architecture/verifiable-builds.md`, `docs/release-verification.md`, ADR 0004 and ADR 0005.

The official publication path is additionally gated by the reviewed Ubuntu/CPython build-input lock and an offline rebuild on a separately provisioned runner. Candidate construction, rebuild and final bundle assembly remain read-only; release and attestation permissions exist only in the final tag-only job after `release-assurance.json` reports a passed publication gate.

Official release bundles also include a standard-library-only offline verifier. It recomputes checksums, manifest, lock and rebuild evidence without network access, while explicitly distinguishing internal bundle consistency from official-origin authentication. An independently trusted manifest SHA-256 can be supplied as a cryptographic anchor. See `docs/release/offline-verification.md`.

The local Security surface also provides **Verify installation** through the CLI, read-only
API and browser. Its backward-compatible default checks installed package bytes against wheel
`RECORD`. An explicit local release bundle adds bounded bundle/wheel validation and direct
installed-to-released byte comparison without network access. Self-consistency remains
separate from publisher authentication. See `docs/security/verify-installation.md`.

## Product boundaries

| Area | Repository | Purpose |
| --- | --- | --- |
| Provelume Core + self-hosted Instance | `gabned/provelume` | Public source-available product code and public operator documentation |
| Nexus | `gabned/nexus` | Private personal archive and private reference instance |
| Official website + managed cloud/SaaS | `gabned/provelume.com` | Private website, control plane and cloud-specific code |

`provelume.com` must consume released/versioned Provelume Core artifacts; it must not vendor or copy the Core source tree.

## Principles

- provenance first;
- canonical knowledge remains durable and provider-independent;
- derived indexes are reconstructable;
- self-hosted and privacy-first;
- GitHub and external AI are optional;
- clients and providers are replaceable;
- no hidden dependency on the private Nexus instance.

## Clean-room rule

Do not copy private Nexus data, secrets, generated knowledge, private documentation, deployment state or Git history into this repository. Public implementation work is written from public requirements and sanitized interfaces. See `docs/clean-room.md`.

## License

Provelume is **source-available**, not OSI open source. Non-commercial use is licensed under PolyForm Noncommercial 1.0.0. Commercial use requires a separate commercial license.

See `LICENSE`, `COMMERCIAL-LICENSE.md` and `THIRD_PARTY_NOTICES.md`.

## Website

The canonical product website is https://provelume.com.
