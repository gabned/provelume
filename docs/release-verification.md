# Verifying a Provelume release

Official release assets are designed to be independently checkable against public source and build provenance.

## Check the published checksums

Download the release assets and `SHA256SUMS`, then compare each asset's SHA-256 value with the published entry. The provider-independent `release-manifest.json` repeats artifact hashes together with the release version, public tag, commit SHA, source repository and SBOM identity.

## Inspect deterministic-build evidence

Each release includes `build-determinism.json`. It records the public source identity, source fingerprint, `SOURCE_DATE_EPOCH`, certified Python/platform and exact build frontend/backend versions, plus both independently produced hashes for the wheel and source distribution.

For a successful official build:

- `assurance` is `same-source-same-environment-byte-identical`;
- both artifact records have `byte_identical: true`;
- each first/second SHA-256 pair is equal;
- `source_commit` matches the release manifest commit;
- `full_release_reproducibility_claimed` remains `false`.

The machine-readable contract is `docs/build-determinism.schema.json`.

This evidence demonstrates repeated byte-identical Python distributions within the certified build environment. It is not proof that an independently provisioned third-party environment or every future platform artifact will produce the same bytes.

## Verify GitHub build provenance

For artifacts published from the public GitHub repository, GitHub CLI can verify the signed artifact attestation against the canonical repository:

```bash
gh attestation verify provelume-<version>-py3-none-any.whl -R gabned/provelume
```

The release workflow also creates provenance for the source distribution, release manifest and deterministic-build evidence, plus a CycloneDX SBOM attestation for the wheel. Artifact attestation proves the relationship between artifact and build source/workflow; it does not prove that the artifact is vulnerability-free or that the complete release is reproducible.

## Offline and provider-independent direction

`release-manifest.json`, `SHA256SUMS`, `build-determinism.json` and the SBOM are normal downloadable files and remain interpretable without Provelume Cloud. Future signing and launcher work will add an offline-friendly verification path for the manifest and platform runtime. GitHub is the initial attestation/distribution provider, not the logical identity of Provelume knowledge or Instance data.

## Current assurance

The current release foundation provides:

- **traceable builds** for official release artifacts;
- **measured deterministic components** for the Python wheel and source distribution on the certified Linux build path.

A full byte-for-byte **reproducible release** is not yet claimed because the build is not yet compared across independently provisioned environments and not every future platform artifact is covered.
