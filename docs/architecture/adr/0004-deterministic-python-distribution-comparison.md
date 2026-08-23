# ADR 0004: compare isolated Python distribution builds

- Status: Accepted
- Date: 2026-08-23
- Deciders: Provelume maintainers

## Context

ADR 0003 established a traceable release chain from a public tag and commit to
checksummed, SBOM-described and attested artifacts. Traceability proves where an
artifact came from, but it does not prove that executing the build again will
produce the same bytes.

Calling the whole release reproducible would be premature. Build-tool transitive
dependencies are not yet locked with hashes across future runs, the comparison
currently runs on one Linux/Python target, and no independent rebuilder verifies
the result outside the official workflow.

The next useful assurance increment is narrower: prove that Provelume's Python
wheel and source distribution are deterministic when source, resolved build
inputs, interpreter, platform and environment controls are held constant.

## Decision

Provelume will build the Python distributions twice before an official release.
Both builds must:

1. originate from the same clean `git archive` of the public commit;
2. run in separate source directories and virtual environments;
3. install build tooling from the same pre-resolved wheelhouse with network
   access disabled during the builds;
4. use the commit timestamp as `SOURCE_DATE_EPOCH`;
5. use controlled timezone, locale and Python hash seed values;
6. produce exactly one wheel and one source distribution;
7. produce identical filenames, sizes and SHA-256 digests.

The direct backend/tool inputs are pinned. The wheelhouse file identities and
resolved package set are recorded in `build-comparison.json`. The verified first
output becomes the candidate release distribution; a later unconstrained third
build is not substituted.

The same comparison runs in ordinary pull-request/main CI and in the official
tag workflow. Any mismatch fails closed before publication.

## Assurance statement

A successful report means:

> The Python wheel and source distribution were byte-identical across two
> isolated builds from the same source snapshot, recorded build inputs,
> interpreter and platform.

It does **not** mean:

- arbitrary environments will reproduce the same bytes;
- Linux and Windows builds are byte-identical;
- future dependency resolution will select the same transitive artifacts;
- an independent third party has reproduced the release;
- the complete future Windows installer/runtime is reproducible.

The public assurance level therefore remains **traceable build with deterministic
Python distribution components**, not “reproducible release”.

## Consequences

- release time and CI cost increase because two isolated environments are built;
- build-input files and package resolution become inspectable evidence;
- nondeterministic metadata in the wheel or source distribution blocks release;
- the public manifest/checksum bundle includes the comparison report and schema;
- runtime behavior and the offline/no-AI baseline remain unchanged.

## Follow-up

A later ADR may raise the assurance level only after:

- all transitive build inputs are locked by version and cryptographic hash;
- build images/toolchains are pinned by immutable identity;
- an independent rebuild consumes the published source and input lock;
- equivalence is demonstrated on the platforms covered by the claim;
- verification can be performed without trusting a single hosting provider.
