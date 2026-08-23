# ADR 0005 — embedded runtime build identity is descriptive evidence

- Status: Accepted
- Date: 2026-08-23

## Context

Provelume releases publish checksums, an SBOM, a provider-independent manifest, deterministic-build evidence and external provenance attestations. An installed runtime nevertheless needs an offline way to state which public source identity was embedded in its package.

A displayed version or commit can easily become misleading if the interface presents it as proof that the current installation is intact or officially signed. The runtime does not yet have a trusted local manifest-verification engine, platform code-signature verification or offline attestation validation.

## Decision

Every Python package contains a schema-versioned `build_info.json` resource.

The tracked public source declares a development placeholder. During deterministic distribution assembly, the builder writes validated metadata into each clean build copy before the artifact is created. Official metadata includes:

- package version;
- canonical source repository `gabned/provelume`;
- matching semantic release tag;
- full public source commit;
- `preview` or `stable` channel;
- source commit timestamp;
- `official: true`.

Development builds may include a source commit and timestamp but have no release tag, use the `development` channel and declare `official: false`.

The installed package exposes one shared application-layer result through CLI, API and web UI. It has three identity states:

- `official_metadata_present`;
- `development_build`;
- `identity_unavailable`.

The result always includes a separate verification boundary. Until actual checks are implemented it reports:

- installation integrity: not verified;
- artifact provenance: not verified locally;
- platform signature: not verified;
- network request: not performed.

The loader validates exact fields, canonical repository, semantic version/tag rules, commit shape, source timestamp consistency and agreement with the installed package version. Missing or inconsistent metadata fails closed to `identity_unavailable`.

## Consequences

- users and operators can inspect version/tag/commit/source identity offline;
- metadata is included in deterministic artifact hashes, not appended after build;
- GitHub and Provelume Cloud are not runtime dependencies;
- official metadata is informational and must not use a false verified/green integrity state;
- the same contract is available through `provelume build-info`, `/api/v1/build-info` and `/security`;
- a future verifier can extend the separate verification object without changing the meaning of embedded identity;
- local file manifests, platform signing and offline attestation verification remain separate milestones.
