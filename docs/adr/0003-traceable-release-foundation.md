# ADR 0003: Traceable release foundation before reproducibility claims

- Status: Accepted
- Date: 2026-08-23

## Context

Provelume needs official Core and self-hosted artifacts that users can connect to public source and a public build pipeline. The current Python packaging inputs are not yet fully pinned, so byte-for-byte reproducibility has not been demonstrated.

## Decision

The first release assurance level is **traceable build**. Official releases will be produced only from public tags on reviewed `main`, using a separate public release workflow. The workflow will build Python distribution artifacts, publish SHA-256 checksums, a machine-readable SBOM and a provider-independent release manifest, and generate GitHub artifact attestations for distributable artifacts.

The project will not describe these releases as reproducible until independent rebuild comparison demonstrates that claim.

## Consequences

- build provenance becomes verifiable without coupling Provelume runtime to GitHub;
- release publication remains separate from ordinary CI;
- GitHub is an initial hosting and attestation provider rather than part of the Instance contract;
- later hardening can pin build inputs, add independent rebuild jobs and platform code signing without changing canonical knowledge formats;
- the future Windows launcher can consume a signed provider-independent manifest rather than a GitHub-specific API contract.
