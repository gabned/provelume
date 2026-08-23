# Verified build-input wheelhouse and offline rebuild

The `Offline verified build-input rebuild` workflow ensures that candidate and rebuild jobs consume the same transitive Python package-build input bytes.

## Candidate bundle

The candidate job resolves `requirements-build.txt` once with binary wheels only. It creates a wheelhouse and `build-input-manifest.json` containing:

- canonical public source repository and full commit;
- Python implementation/version, cache tag, operating-system family and machine family;
- direct requirements filename and SHA-256;
- every wheel filename, size and SHA-256;
- explicit assurance limitations.

The manifest generator requires the exact direct `build` and `hatchling` wheels declared by repository policy. It rejects empty bundles, symlinks and non-wheel files.

The candidate then creates a fresh virtual environment and installs the build toolchain with:

```text
pip --no-index --find-links <wheelhouse> -r requirements-build.txt
```

The package build uses `--no-isolation`, so it cannot silently create another online backend environment.

## Second-runner verification

The rebuild job downloads the candidate bundle from the current workflow run and recomputes:

- the direct requirements hash;
- the complete wheel filename set;
- every wheel size;
- every wheel SHA-256;
- source repository and commit identity.

Only after those checks succeed does it create a new environment from the wheelhouse with `PIP_NO_INDEX=1`. It performs its own deterministic double build and compares candidate/rebuild wheel and sdist bytes.

## Evidence files

The workflow retains:

- `build-input-manifest.json` in the candidate workflow artifact;
- candidate and rebuild deterministic reports;
- `independent-rebuild-report.json`;
- `offline-rebuild-evidence.json`.

The final offline report links the verified wheelhouse manifest hash and identities to the matching package artifact hashes.

## Manual manifest commands

Create a manifest:

```bash
python -m scripts.build_input_bundle create \
  --wheelhouse wheelhouse \
  --requirements requirements-build.txt \
  --output build-input-manifest.json \
  --commit "$(git rev-parse HEAD)"
```

Verify it before installation:

```bash
python -m scripts.build_input_bundle verify \
  --wheelhouse wheelhouse \
  --requirements requirements-build.txt \
  --manifest build-input-manifest.json \
  --commit "$(git rev-parse HEAD)"
```

## What remains unresolved

This bundle is immutable for one workflow run, but it is not yet a durable dependency policy committed to the repository. The package index is contacted once to resolve the candidate wheelhouse, and workflow artifacts expire. Both builders also remain on the same CI provider.

The correct public claim is therefore **verified offline rebuild from an immutable per-run build-input bundle**, not complete long-term reproducibility.

The next step is a reviewed lock/update mechanism with retained hashes, followed by integration of this evidence as a required predecessor to official release publication.
