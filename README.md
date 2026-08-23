# Provelume

**Knowledge you can trace.**

Provelume is a provenance-first personal knowledge intelligence system for building durable, portable and traceable knowledge from files and, over time, other sources.

This repository is the public clean-room home of the reusable **Provelume Core** and the self-hosted **Provelume Instance** distribution. It does not contain the private Nexus reference instance, personal data, private product documentation or private Git history.

> The AI is not the memory. Your knowledge outlives your AI.

## Current status: first local vertical slice

Version `0.1.0` implements a small local Instance that can:

- initialize in an ordinary directory;
- ingest local TXT, Markdown and PDF files;
- preserve exact originals with SHA-256 content identity;
- record Sources, Acquisitions, Documents, DocumentVersions and provenance;
- create a new version only when file content changes;
- extract text locally and build a disposable SQLite FTS5 search index;
- expose a read-only versioned Knowledge API with FastAPI;
- provide a minimal EN/IT Knowledge Browser for browse, search, document detail, versions, provenance and knowledge health;
- restart without losing canonical state;
- run without Git, GitHub, Provelume Cloud or an external AI provider.

OCR, semantic/vector search, cloud connectors and AI enrichment are deliberately outside this first slice.

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

See `docs/api.md` for the contract and filtering behavior.

## Privacy and network baseline

The baseline Instance config disables external access and update checks. The runtime contains no analytics, telemetry, CDN assets or external AI calls. Its core ingestion, provenance, full-text search, API and browser remain useful offline.

Future connectors and AI providers must declare network capability explicitly and remain optional. See `docs/architecture/provider-boundaries.md`.

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
