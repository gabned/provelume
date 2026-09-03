# ADR 0022: Installed and release component inventory

## Status

Accepted for `0.10/S02`.

## Context

Provelume exposes build identity, notices, release manifests and feature-specific component
evidence, but a user cannot inspect one truthful catalogue covering the effective runtime and the
release evidence that should describe it. A generic environment scan would be incomplete, could
leak paths and would make an offline page execute arbitrary tools.

## Decision

Core ships a versioned, bilingual catalogue. It follows the installed dependency closure from the
Provelume distribution and adds every present transitive runtime distribution with its local
metadata, while excluding optional development extras. Detection is otherwise closed to CPython/
platform metadata, executable presence without paths, or explicit external evidence. Reads perform
no process execution, package-manager action, network request or Instance write. Missing optional
evidence is `unverified` or `missing`, never silently inferred.

An operator may explicitly give the CLI a local CycloneDX SBOM. Its bytes and component count are
bounded; the comparison is deterministic and returns `matched` or the exact component IDs that do
not agree. HTTP clients cannot provide local paths. Latest-known and security state remain
`not_checked`/`unverified` until a later separately gated catalogue-check capability records dated
evidence. A check can never apply an update.

## Consequences

- Service, CLI, API and Browser consume the same model.
- Local executable paths, credentials and Instance content never enter the result.
- Codec and model classes are explicitly `not_selected` in S02 instead of receiving invented
  component identities.
- Release preparation can compare the final generated SBOM through the same bounded contract.
