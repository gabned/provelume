# Provelume

**Knowledge you can trace.**

Provelume is a provenance-first personal knowledge intelligence system for building durable, portable and traceable knowledge from files and, over time, other sources.

This repository is the public clean-room home of the reusable **Provelume Core** and the self-hosted **Provelume Instance** distribution. It does not contain the private Nexus reference instance, personal data, private product documentation or private Git history.

> The AI is not the memory. Your knowledge outlives your AI.

## Current status: 0.2.0 preview

The latest published preview is `v0.2.0`.

The published `v0.1.0` baseline implements a small local Instance that can:

- initialize in an ordinary directory;
- ingest local TXT, Markdown and PDF files;
- preserve exact originals with SHA-256 content identity;
- record Sources, Acquisitions, Documents, DocumentVersions and provenance;
- create a new version only when file content changes;
- extract text locally and build a disposable SQLite FTS5 search index;
- expose a read-only versioned Knowledge API with FastAPI;
- provide a minimal EN/IT Knowledge Browser for browse, search, document detail, versions, provenance, knowledge health and build transparency;
- report its embedded version/tag/commit/source identity offline through CLI, API and browser;
- restart without losing canonical state;
- run without Git, GitHub, Provelume Cloud or an external AI provider.

The `v0.2.0` preview adds:

- local installation verification against wheel `RECORD`, with package integrity kept
  separate from official-origin authentication;
- declared Privacy & Network Activity transparency, including safe endpoint origins,
  policy-conflict reporting and an explicit `not_instrumented` traffic-observation state.

These checks are read-only and perform no network request. They do not prove official origin,
operating-system egress enforcement or zero runtime traffic. All extracted/searchable
representations remain derived state and can be recreated from preserved originals after
deletion.

OCR, semantic/vector search, cloud connectors and AI enrichment remain later milestones.

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

Inspect the package's embedded source identity without creating an Instance or making a network request:

```bash
.venv/bin/provelume build-info
```

Inspect one Instance's declared network policy and components, also without making a network request:

```bash
.venv/bin/provelume network-status .local/demo
```

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

Schema 1 uses an ordinary filesystem directory:

```text
<instance>/
  provelume.yml
  originals/
  knowledge/
  state/
  indexes/
```

`originals/` and `knowledge/` are durable canonical state. `state/derived/` and `indexes/` are rebuildable derived state. SQLite is used only for search acceleration; it is not the authoritative knowledge format.

See `docs/architecture/portable-instance.md` and `docs/architecture/canonical-derived-state.md`.

## Knowledge API

The browser and external clients use the same application layer. The first read-only API is under `/api/v1`, including:

- `GET /health`
- `GET /api/v1/build-info`
- `GET /api/v1/instance`
- `GET /api/v1/sources`
- `GET /api/v1/sources/{id}`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{id}`
- `GET /api/v1/documents/{id}/versions`
- `GET /api/v1/documents/{id}/provenance`
- `GET /api/v1/documents/{id}/original`
- `GET /api/v1/search`
- `GET /api/v1/knowledge-health`
- `GET /api/v1/security/network`

See `docs/api.md` for the contract and filtering behavior.

## Privacy and network baseline

The baseline Instance config disables external access and update checks. The runtime contains no analytics, telemetry, CDN assets or external AI calls. Its core ingestion, provenance, full-text search, API and browser remain useful offline.

`provelume network-status`, `GET /api/v1/security/network` and `/security/network` expose the effective policy and configured capability inventory. Physical Source paths are redacted, configured HTTP(S) endpoints are reduced to origins, unknown component types fail visibly, and observed traffic remains explicitly `not_instrumented`. Future connectors and AI providers must declare network capability explicitly and remain optional. See `docs/privacy-network.md` and `docs/architecture/provider-boundaries.md`.

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

The local Security surface also provides **Verify installation** through the CLI, read-only API and browser. It checks installed package bytes against wheel `RECORD` without network access, while keeping package integrity distinct from official-origin authentication. See `docs/security/verify-installation.md`.

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
