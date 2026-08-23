# Provelume Instance

`instance/` contains public packaging examples for self-hosted Provelume. Runtime data and real operator configuration do not belong in this repository.

## Docker Compose demo

From this directory:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8042/`. The container creates a fresh Instance in the named `provelume-instance` volume. The public synthetic source under `../examples/demo-source` is mounted read-only at `/sources/local`.

Ingest it with:

```bash
docker compose exec provelume provelume ingest /instance /sources/local
```

To mount a different local source directory, set `PROVELUME_SOURCE_DIR` before `docker compose up`. No Git repository, GitHub credential or AI key is required.

## Runtime state

A real Instance owns its own `provelume.yml`, originals, canonical knowledge, derived state and indexes. Do not commit populated Instance directories or secrets to this repository.
