# ADR 0005: verify release bundles without a hosting provider

- Status: Accepted
- Date: 2026-08-23
- Deciders: Provelume maintainers

## Context

The traceable release pipeline publishes a provider-independent manifest,
SHA-256 checksums, a CycloneDX SBOM and deterministic-build evidence. Those
files are useful only if an operator can evaluate them without depending on
GitHub, Provelume Cloud or a network connection.

A future **Settings → Security → Verify installation** experience also needs a
stable application contract. It must distinguish a valid bundle, modified
material and missing verification evidence instead of reducing every failure to
one generic red state.

The current release manifest is not yet protected by a detached,
provider-independent signature. GitHub attestations authenticate provenance
when they can be queried and verified, but they are not part of an entirely
offline verification path today.

## Decision

Provelume Core will provide a local release-bundle verifier with three outcomes:

- `verified` — manifest, checksum inventory, declared files, SBOM and any
  deterministic-build evidence are internally consistent;
- `modified` — expected material exists but violates its integrity or contract;
- `unavailable` — required verification material is missing or unreadable.

The verifier is implemented in the reusable Core application layer and exposed
through a small command-line wrapper. It performs no network calls.

For release manifest schema 1 it verifies:

1. semantic version/tag consistency;
2. a full public source commit and the expected canonical source repository;
3. supported channel, timestamp and assurance metadata;
4. unique, safe flat filenames;
5. exact file sizes and streaming SHA-256 identities;
6. exact `SHA256SUMS` coverage with no missing, unexpected or duplicate entries;
7. CycloneDX 1.6 JSON identity and basic document contract;
8. deterministic Python distribution evidence when it is included and
   checksummed by the release manifest;
9. consistency of the two build runs with the released wheel and source
   distribution.

Symlinks, traversal-like paths, Windows drive-relative paths and untrusted
comparison reports fail closed. Additional local files are reported visibly but
do not invalidate otherwise verified release material.

The machine-readable result has its own public schema so CLI, web UI, MCP and
future managed clients can consume the same semantics.

## Assurance statement

A `verified` result means:

> The bytes in this local bundle are internally consistent with the included
> Provelume release manifest, checksum inventory, SBOM and deterministic-build
> evidence.

It does **not** yet mean:

- the manifest itself was authenticated by an offline trusted signature;
- a hosted provenance attestation was verified without network access;
- the installed runtime files match the downloaded distribution;
- the signer or code-signing certificate was independently validated;
- the complete release was reproduced by an independent builder.

These limits must remain visible in UI and public product language.

## Consequences

- release verification works when GitHub is unavailable;
- integrity failures become structured, explainable findings;
- the future installation-verification UI can reuse Core logic;
- malformed or unsafe bundle metadata cannot redirect verification outside the
  selected directory;
- no telemetry, provider SDK or external AI dependency is introduced;
- a valid but unsigned manifest still requires a later trust-anchor milestone.

## Follow-up

The next trust increment should define a provider-independent detached signature
for the release manifest and an offline trust-root/update policy. A later
installation verifier can then compare installed Core files with an
authenticated release manifest and distinguish Core, plugins and local
configuration.
