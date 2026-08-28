# Maintainability boundaries

This document records the focused `0.5.1` maintainability audit. It is a change-risk map, not an
instruction to split files mechanically or a claim that line count alone measures complexity.
Measurements are repository lines at `main@63d22fc6c2b187b09f8f8e5194c1e4f2dc053397` before the
guardrail slice.

## Current pressure map

| Module | Lines | Cohesive responsibility to preserve | Preferred next seam |
| --- | ---: | --- | --- |
| `installation.py` | 1,459 | bounded local RECORD and release-wheel verification | presentation summaries separate from byte/path verification |
| `desktop.py` | 1,109 | Windows launcher state, backend lifecycle, update handoff and Tk shell | pure settings/diagnostics and backend controller before widget layout |
| `bundles.py` | 810 | deterministic document-bundle construction | format renderers behind one bounded bundle writer |
| `ingest.py` | 715 | durable filesystem acquisition and retry lifecycle | enumeration, item processing and canonical commit as tested phases |
| `rebuild.py` | 680 | coordinated derived-state rebuild and agreement evidence | per-derived-kind adapters behind the existing lock/report contract |
| `release_bundle.py` | 610 | standalone offline release-bundle verification | keep self-contained; isolate only pure parsers with standalone tests |
| `release_wheel.py` | 610 | bounded wheel and RECORD verification | keep verification budgets and path safety in one explicit boundary |
| `extractors.py` | 600 | bounded deterministic local extraction | one extractor per format without changing the shared result contract |
| `duplicates.py` | 567 | exact/probable duplicate evidence | candidate generation separate from evidence persistence |
| `inbox.py` | 553 | safe staging, verified commit, optional source move and operation evidence | acquisition orchestration separate from filesystem staging |
| `assurance.py` | 510 | read-only Original/canonical consistency assurance | record loading separate from invariant evaluation |

`service.py` is smaller but strategically central: it is the application facade shared by CLI,
API and browser. It should delegate to cohesive managers and keep only cross-capability
orchestration, filtering and presentation-neutral result assembly. The `0.5.1` guardrail removes
the duplicated post-ingestion index-refresh wiring without changing schemas or responses.

## Change rules

- Add characterization tests before moving an existing responsibility.
- Extract one cohesive seam per homogeneous product PR; do not combine decomposition with a
  capability, dependency upgrade, schema migration or release preparation.
- Preserve canonical JSON bytes, identifiers, error codes, ordering and public CLI/API/browser
  response shapes unless a separately versioned contract explicitly changes them.
- Keep release verifiers standalone and offline-capable where the publication contract requires
  it; smaller files are not worth a weaker trust boundary.
- Treat originals and canonical JSON as authoritative. A refactor never moves authority into a
  derived database, cache or UI model.
- Require full Linux/Windows evidence for seams used by both platforms and Windows installer
  evidence for launcher/package changes.

## Deferred outcomes

- #84 owns a rebuildable index and stable pagination for growing operation history while JSON
  operation records remain authoritative.
- #85 owns broader module decomposition through bounded characterization-first slices.
- #1 owns branch protection, required-check and private-vulnerability-reporting settings that
  repository code cannot enable or certify.

None of these issues is activated by this document, and none authorizes `0.6.0` product work.
