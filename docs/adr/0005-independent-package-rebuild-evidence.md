# ADR 0005: Independent CI runner evidence for Python package rebuilds

- Status: Accepted
- Date: 2026-08-23

## Context

ADR 0004 requires two byte-identical wheel/source-distribution builds in one controlled job. That continuously detects nondeterministic package output, but both builds share one provisioned runner and one installed environment.

The next useful assurance increment is to compare a package candidate with a rebuild produced by a separately provisioned job. This reduces the risk that state retained inside one job is responsible for the match and establishes the evidence contract later needed by the official release workflow.

The transitive build dependency closure is not yet hash-locked. A second runner may therefore resolve the same currently available dependencies without proving that those inputs will remain immutable in the future. The result must remain narrower than a full reproducible-release claim.

## Decision

A dedicated public workflow will use two jobs:

1. **Candidate builder** — checks out the public commit, installs the declared exact direct build tools, derives `SOURCE_DATE_EPOCH` from that commit, runs the deterministic double-build gate and uploads wheel, sdist and its deterministic report.
2. **Independent rebuild** — receives a separately provisioned runner, checks out the same commit, independently installs the declared build inputs, performs its own deterministic double build, downloads the candidate from the current workflow run and compares the bytes.

The second job does not trust either JSON report. It recomputes candidate and rebuild artifact filenames, sizes and SHA-256 digests from the downloaded files, then verifies that both reports describe those bytes, the same canonical repository, full commit, source epoch and direct build tool versions.

A green comparison emits `independent-rebuild-report.json`. The report is retained as a workflow artifact and records both declared environments, matching artifact identities and limitations.

## Security and trust boundary

- workflow permissions are read-only for repository content;
- the second job receives only `actions: read` in addition to content read access;
- no repository, release or package write occurs;
- no private Nexus source, secret or runtime state participates;
- pull-request code receives no privileged release or signing credentials;
- candidate transfer uses the current workflow run's artifact service rather than an unverified external URL.

## Assurance language

A successful report supports:

> A separately provisioned CI job rebuilt the same public Provelume Python package commit and produced wheel and source-distribution bytes matching the candidate SHA-256 identities.

It does not yet support:

- fully independently reproducible releases;
- immutable or offline-resolvable transitive build inputs;
- independence from the CI provider;
- reproducibility of Windows installers, containers or future platform bundles.

## Consequences

Positive consequences:

- hidden job-local state is less likely to explain matching package outputs;
- candidate evidence is recomputed from bytes rather than trusted from metadata;
- the official release workflow can later reuse the same cross-job contract;
- mismatches stop the workflow and retain a clear diagnostic boundary.

Costs and limitations:

- package builds run four times across two jobs;
- workflow duration and artifact storage increase;
- both jobs still use GitHub-hosted Ubuntu infrastructure;
- exact direct pins are not a replacement for a hash-locked transitive closure.

## Follow-up

The next milestone is a reviewed, hash-locked build dependency set installable from immutable artifacts or an offline wheelhouse. After that, the independent rebuild gate should become a required predecessor of official release publication and retain its report with the final release bundle.
