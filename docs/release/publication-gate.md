# Official release publication gate

The official Provelume release workflow is a small caller around `.github/workflows/release-pipeline.yml`. The reusable pipeline is also invoked by a read-only pull-request dry run, so the package/rebuild/assembly path is exercised before a tag exists.

## Job and permission boundaries

| Stage | Purpose | Repository permissions |
| --- | --- | --- |
| Tag request (web only) | validate a semantic tag/full-main-SHA pair and create that exact lightweight tag | contents write |
| Candidate | test source, verify reviewed lock, build deterministic wheel/sdist offline | contents read |
| Offline rebuild | separately provisioned rebuild and byte comparison | contents read, actions read |
| Assembly | verify full evidence chain, smoke-test wheel, generate SBOM/manifest/checksums | contents read, actions read |
| Publication | reverify bundle, attest and create GitHub Release | contents write, actions read, OIDC and attestations write |

The final publication job is omitted entirely when the pipeline is called with `publish: false`. Pull-request code therefore receives no release or attestation privilege.

## Official tag behavior

For a `vX.Y.Z` tag, the candidate stage rejects the run unless:

- the repository is exactly `gabned/provelume`;
- the tag is semantic and equals the `pyproject.toml` version;
- the tag commit is already reachable from public `main`;
- the source gates pass;
- the committed build lock resolves and verifies;
- wheel/sdist double builds are byte-identical.

The second stage must then reproduce those package hashes from the transferred verified wheelhouse. The assembly stage validates all reports with `scripts/release_assurance.py` before creating the final bundle.

The publication stage refuses to overwrite an existing release for the tag.

## Creating a tag from GitHub.com

Maintainers can start an official release without creating a blank GitHub Release:

1. open **Actions → Official release → Run workflow**;
2. select `main`;
3. enter an exact semantic tag such as `v0.1.0`;
4. enter the full 40-character commit already present on `main`;
5. run the workflow.

The tag-request job is fail-closed. It requires the workflow revision to be current `main`, verifies that the selected commit is reachable from public `main`, reads the package version from that commit, rejects an existing Release or a tag on another commit, and creates only the exact lightweight tag requested. The same run then passes that tagged source commit through the reusable candidate, offline-rebuild, assembly and publication jobs. Before privilege use, both the assurance and publication stages fetch the tag and require it to resolve to the selected commit.

Direct `vX.Y.Z` tag pushes remain supported and enter the read-only assurance pipeline without running the tag-request job. A tightly validated `release-request/vX.Y.Z/<full-sha>` branch carrying one empty commit above current `main` is an automation transport for clients that can create branches but cannot invoke `workflow_dispatch`; it is removed after the request is accepted and does not become release source.

## Release assets

In addition to wheel, source distribution, license files and SBOM, the verified bundle contains:

- `release-manifest.json`;
- `SHA256SUMS`;
- `release-assurance.json`;
- `candidate-identity.json`;
- `deterministic-build-report.json`;
- `rebuild-deterministic-build-report.json`;
- `independent-rebuild-report.json`;
- `offline-rebuild-evidence.json`;
- `build-input-manifest.json`;
- `ubuntu-py312-x86_64.lock.json`;
- `ubuntu-py312-x86_64.requirements.txt`;
- human-readable license and third-party notices.

The manifest and checksum file cover the evidence assets. GitHub artifact attestations cover wheel, sdist, manifest and build-assurance files; the wheel also receives the CycloneDX SBOM attestation.

## Dry-run behavior

`Verified release pipeline dry run` is path-filtered to release/build inputs and scripts. It invokes the same candidate, offline rebuild and assembly jobs with:

- synthetic tag identity `v<package-version>`;
- channel `development`;
- deterministic build timestamp for manifest validation;
- no publication or attestation job.

This is the required review path for changes to release workflows, build locks, package metadata or evidence scripts.

## Local evidence verification

A downloaded release bundle can be checked with:

```bash
python -m scripts.verify_release_bundle \
  --root path/to/release \
  --version 0.1.0 \
  --tag v0.1.0 \
  --commit <full-public-commit-sha>
```

This verifies manifest artifact identities, SBOM identity, assurance source/version/tag/commit, SHA256SUMS, path safety and presence of all required evidence files.

GitHub attestation verification remains an additional provider-specific check. The release manifest/evidence format is intentionally independent of the hosting provider so a future offline verifier or release mirror can preserve the trust chain.

## Current limitations

The publication gate covers the Python wheel and source distribution using the reviewed Ubuntu x86_64 / CPython 3.12.14 build lock. Runtime dependency resolution used to smoke-test the installed wheel and generate the SBOM is recorded but not yet governed by the package build lock. Future Windows installers, containers and cloud deployment packages require separate build, signing and rollback evidence.
