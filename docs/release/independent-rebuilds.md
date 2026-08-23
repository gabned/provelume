# Independent Python package rebuild evidence

The `Independent Python package rebuild` workflow adds a second package-level supply-chain check beyond the same-run deterministic gate.

## What the workflow proves

For the checked-out public commit, the workflow:

1. provisions a candidate job;
2. builds wheel and source distribution twice and requires byte identity;
3. uploads the compared candidate artifacts and deterministic report;
4. provisions a separate rebuild job;
5. independently installs the declared direct build toolchain;
6. rebuilds the same commit twice using the same commit-derived `SOURCE_DATE_EPOCH`;
7. downloads the candidate from the same workflow run;
8. recomputes all artifact hashes from bytes on disk;
9. compares the candidate and rebuild artifact sets;
10. emits `independent-rebuild-report.json` only when every identity matches.

The evidence covers exactly one Python wheel and one Python source distribution.

## Report validation

`scripts/independent_rebuild.py` verifies:

- both artifact directories contain exactly one wheel and one sdist;
- both deterministic reports use schema 1 and have a green result;
- both reports name `gabned/provelume` as the source repository;
- both reports identify the expected full source commit;
- both reports use the same positive `SOURCE_DATE_EPOCH`;
- both reports declare the same exact direct build tool versions;
- report filenames, sizes and SHA-256 values match recomputed file identities;
- candidate and rebuild files are byte-identical.

A report mismatch is treated the same as a byte mismatch: the workflow fails closed.

## Permissions

The workflow does not create tags, releases or repository commits. Repository contents are read-only. The rebuild job receives `actions: read` solely to download the candidate from the current workflow run. No signing, deployment or private-reference credentials are made available.

## Run the comparison manually

After producing two deterministic build directories and reports:

```bash
python scripts/independent_rebuild.py \
  --candidate-dir candidate/dist \
  --rebuild-dir rebuild/dist \
  --candidate-report candidate/deterministic-build-report.json \
  --rebuild-report rebuild/deterministic-build-report.json \
  --output-report rebuild/independent-rebuild-report.json \
  --commit "$(git rev-parse HEAD)"
```

## Assurance boundary

This workflow demonstrates a separately provisioned rebuild on the same CI provider. It does not make transitive dependencies immutable: only the direct package build tools are exact today. It also does not cover installers, containers or managed-cloud packaging.

Therefore the correct statement is:

> A separately provisioned CI runner reproduced the candidate Python package artifact hashes for this commit.

The repository must not simplify that statement to “the complete release is reproducible” until the transitive build closure is hash-locked, the official release is gated on this evidence and a genuinely independent reconstruction path has been demonstrated.
