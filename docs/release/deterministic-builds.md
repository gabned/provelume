# Deterministic Python package builds

Provelume separates three different supply-chain guarantees:

1. **Traceable build** — an artifact is linked to a public source commit and public workflow through hashes, manifest metadata and attestations.
2. **Deterministic package component** — rebuilding the same Python package source twice in one declared controlled environment yields byte-identical wheel and source-distribution files.
3. **Reproducible release** — an independent party can reconstruct the complete release from fully controlled inputs and obtain equivalent artifacts where the platform permits it.

The repository currently implements the first guarantee and a continuously tested form of the second. It does not yet claim the third.

## Gate behavior

`scripts/deterministic_build.py` performs the package comparison used by CI and the official release workflow.

It verifies the exact direct versions of the selected build frontend and backend, obtains `SOURCE_DATE_EPOCH` from the source commit, sets a fixed Python hash seed and performs two `--no-isolation` wheel/sdist builds in separate temporary directories. It then requires:

- exactly one wheel from each build;
- exactly one source distribution from each build;
- identical filenames;
- identical sizes;
- identical SHA-256 digests.

A mismatch returns a non-zero exit status and stops the release before publication.

The compared artifacts from the first build become the candidate release artifacts. The temporary comparison copy is discarded.

## Machine-readable evidence

A successful gate emits `build-determinism.json` with:

- assurance schema and level;
- canonical public source repository;
- full source commit;
- `SOURCE_DATE_EPOCH`;
- Python implementation/version and operating-system family;
- exact direct build tool versions;
- artifact filenames, sizes and SHA-256 digests;
- an explicit `byte_identical: true` result;
- current limitations.

For an official tag build, this report is:

- included in `release-manifest.json`;
- included in `SHA256SUMS`;
- attached to the GitHub Release bundle;
- covered by its own GitHub build-provenance attestation.

## Run locally

Use Python 3.12 and install the controlled build inputs:

```bash
python -m pip install -e ".[dev]" \
  -r requirements-build.txt \
  -r requirements-release.txt
```

Set the source epoch and run the comparison:

```bash
export SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
python scripts/deterministic_build.py \
  --commit "$(git rev-parse HEAD)" \
  --output-dir dist \
  --evidence release/build-determinism.json
```

On PowerShell:

```powershell
$env:SOURCE_DATE_EPOCH = git show -s --format=%ct HEAD
python scripts/deterministic_build.py `
  --commit (git rev-parse HEAD) `
  --output-dir dist `
  --evidence release/build-determinism.json
```

The script is intentionally fail-closed. A different tool version, invalid source identity, missing artifact or byte mismatch is an error rather than an inconclusive green result.

## Remaining work before a reproducible-release claim

The direct package tools are pinned, but the transitive build dependency closure is not yet locked with hashes. Both comparison builds currently share one provisioned CI host. Future installers, containers and platform launchers are outside this package-level evidence.

The next hardening step is therefore:

1. generate and review a hash-locked build dependency closure;
2. build from an offline wheelhouse or equivalent immutable input set;
3. run an independent rebuild in separately provisioned infrastructure;
4. compare its outputs with the release candidate;
5. retain the independent evidence with the release.

Until those steps are implemented, documentation and UI must say **traceable build** and **deterministic Python package artifacts**, not simply **reproducible build**.
