# Verifying a Provelume release

Official release assets are designed to be independently checkable against public source and build provenance.

## Check the published checksums

Download the release assets and `SHA256SUMS`, then compare each asset's SHA-256 value with the published entry. The provider-independent `release-manifest.json` repeats artifact hashes together with the release version, public tag, commit SHA, source repository and SBOM identity.

## Verify GitHub build provenance

For artifacts published from the public GitHub repository, GitHub CLI can verify the signed artifact attestation against the canonical repository:

```bash
gh attestation verify provelume-<version>-py3-none-any.whl -R gabned/provelume
```

The release workflow also creates a CycloneDX SBOM attestation for the wheel. Artifact attestation proves the relationship between artifact and build source/workflow; it does not prove that the artifact is vulnerability-free or that every build component is reproducible.

## Offline and provider-independent direction

`release-manifest.json`, `SHA256SUMS` and the SBOM are normal downloadable files and remain interpretable without Provelume Cloud. Future signing and launcher work will add an offline-friendly verification path for the manifest and platform runtime. GitHub is the initial attestation/distribution provider, not the logical identity of Provelume knowledge or Instance data.

## Current assurance

The current release foundation targets **traceable builds**. Byte-for-byte reproducible releases are not yet claimed because dependency and build inputs are not fully pinned and independently rebuilt in CI.
