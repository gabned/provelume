# Provelume Instance

`instance/` contains public packaging examples for self-hosted Provelume. Runtime data and real operator configuration do not belong in this repository.

## Docker Compose demo

First prepare the closed native build inputs from the repository root, using the
development environment installed by `python scripts/bootstrap.py`:

```bash
.venv/bin/python scripts/ai_runtime_acquire.py --directory build-native/acquired --platform all --accept-licenses
for platform in windows linux; do
  .venv/bin/python scripts/build_ai_runtime_input.py --directory "build-native/acquired/$platform" --platform "$platform" --output "build-native/$platform.zip"
done
```

These explicit developer commands acquire the pinned, licensed runtime libraries
from GitHub. They acquire no model weights. The image verifies both closed input
inventories and contains their notices. Missing or altered inputs stop the build.
On a host requiring an outbound proxy, use a separately verified input pair from
the release-build workflow; the direct acquisition tool does not use ambient proxies.

Then, from this directory:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8042/`. The container creates a fresh Instance in the named `provelume-instance` volume. The public synthetic source under `../examples/demo-source` is mounted read-only at `/sources/local`.

The image runs as UID 10001. Model files use the separate `provelume-models`
volume at `/.instance.provelume`, outside portable Instance data. AI starts Off;
the image includes no weights or enabled session. Local AI also needs the
documented hardware and effective container memory/CPU limits. The browser's
connection through Docker port forwarding is not container loopback: privileged
AI administration retains its loopback restriction. Integrated qualification
uses an ordinary HTTP client inside the container, with external networking off;
it does not establish remote-administration support.

Ingest it with:

```bash
docker compose exec provelume provelume ingest /instance /sources/local
```

To mount a different local source directory, set `PROVELUME_SOURCE_DIR` before `docker compose up`. No Git repository, GitHub credential or AI key is required.

## Runtime state

A real Instance owns its own `provelume.yml`, originals, canonical knowledge, derived state and indexes. Do not commit populated Instance directories or secrets to this repository.
