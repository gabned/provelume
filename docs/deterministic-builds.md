# Deterministic Python distribution builds

Provelume's official release chain distinguishes three assurance levels:

1. **Traceable build** — artifacts point back to a public tag, commit and
   workflow and carry hashes, SBOM and attestations.
2. **Deterministic component** — a defined component produces byte-identical
   output when its recorded inputs and environment are held constant.
3. **Reproducible release** — an independent rebuilder can reproduce the claimed
   release artifacts from published inputs.

The current implementation reaches level 2 for the Python wheel and source
distribution only. It does not claim level 3.

## What the comparison does

`scripts/deterministic_build.py`:

- resolves one full public commit;
- creates one clean source tar archive with `git archive`;
- extracts that identical snapshot into two independent workspaces;
- creates a distinct virtual environment for each run;
- installs both build environments from the same pre-resolved wheelhouse;
- disables package-index access during the builds;
- sets `SOURCE_DATE_EPOCH` to the source commit timestamp;
- controls timezone, locale and Python hash seed;
- builds one wheel and one source distribution in each workspace;
- fails if filenames, sizes or SHA-256 digests differ;
- copies only the first verified output into the candidate distribution folder;
- writes `build-comparison.json` even when the byte comparison fails.

The report records the source snapshot identity, full commit, environment,
wheelhouse file hashes, resolved build package set and both runs' artifact hashes.
Its public schema is `build-comparison.schema.json`.

## CI verification

The `Deterministic Python distributions` workflow performs the real two-build
comparison for pull requests and `main`. It preserves the distributions and
comparison report as a short-lived Actions artifact for inspection.

The official release workflow repeats the same comparison. A mismatch prevents
attestation and publication. `build-comparison.json` and its schema are included
in the release bundle, checksummed by `SHA256SUMS` and the report itself receives
a provenance attestation.

## Local verification

Requires Python 3.12, Git and network access only while resolving the wheelhouse:

```bash
rm -rf .build-wheelhouse dist-deterministic build-comparison.json
python -m pip download \
  --only-binary=:all: \
  --dest .build-wheelhouse \
  --requirement requirements-build.txt
SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
python scripts/deterministic_build.py \
  --repository . \
  --commit HEAD \
  --source-date-epoch "$SOURCE_DATE_EPOCH" \
  --wheelhouse .build-wheelhouse \
  --requirements requirements-build.txt \
  --output-dir dist-deterministic \
  --report build-comparison.json
```

A successful run prints the two verified distribution filenames and records
`"result": "match"`.

## Remaining limits

- transitive build packages are hashed and recorded for each run, but are not yet
  frozen by a cross-run lockfile with required hashes;
- the official comparison currently certifies Linux with CPython 3.12.14;
- no independent external rebuilder is part of the release gate yet;
- Docker images and future Windows installer/runtime artifacts are outside this
  comparison;
- signatures and attestations prove provenance, not byte reproducibility by
  themselves.

These limits are intentional and must remain visible in product language and the
future **Verify installation** UX.
