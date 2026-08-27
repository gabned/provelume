# Public product roadmap

This roadmap is the canonical public planning surface for Provelume Core. Published tags,
dated changelog history and package identity remain immutable. Planned versions are governed
by [`changelog-policy.md`](changelog-policy.md).

## Release lane

| State | Version | Scope | Canonical issue |
| --- | --- | --- | --- |
| Published preview | `0.1.0` | Local provenance-first Instance and verified release foundation | #40 (completed) |
| Published preview | `0.2.0` | Local Installation Trust and Privacy & Network Activity transparency | #50 (merged) |
| Implemented; release preparation pending | `0.3.0` | Anchored Local Installation Trust | #52 |

The package, embedded identity and latest tag remain `0.2.0`. Completing the `0.3.0` product
implementation does not authorize a version bump, tag, release or publication. Those
identities change only in a separate reviewed release-preparation change after the product
exit gates pass.

## 0.3.0 — Anchored Local Installation Trust

The only product scope assigned to `0.3.0` is the release-bundle portion of #20:

- accept an explicit operator-supplied local release bundle through the CLI or trusted
  server-start configuration;
- verify the existing bounded bundle contract without network access;
- validate the released wheel and its internal `RECORD`;
- compare installed Core package bytes with the released wheel bytes;
- preserve RECORD-only verification when no bundle is supplied;
- expose the same evidence layers through CLI and a startup-cached read-only API/EN/IT browser
  surface without accepting local paths from HTTP clients.

Evidence must remain layered. Local RECORD agreement proves consistency with installed
metadata. Bundle self-consistency plus installed/released byte agreement strengthens release
linkage but does not authenticate the publisher. Official-origin authentication may be
reported only when the bundle matches an independently trusted manifest hash or a future
signature accepted by an explicit trust policy.

See [`releases/0.3.0.md`](releases/0.3.0.md) for the bounded release plan.

## Later, unnumbered work

These workstreams remain open but are not part of `0.3.0`:

- #1 — repository protection and security settings audit;
- #5 — optional local OCR and any later ingestion increments;
- #24 — immutable OCI builder lock and pinned-container cross-job rebuild evidence;
- detached provider-independent signing, key rotation and revocation;
- observed runtime network-activity instrumentation;
- runtime dependency, plugin, container and Windows installer verification;
- semantic/vector search, external AI, cloud connectors, SaaS, billing and advanced editing.

Unnumbered work receives a version only through one atomic planning change. If an unplanned
release is inserted ahead of an already numbered future release, every later unreleased slot
shifts according to the repository's forward-shift contract.
