# Agent Development Protocol v1.2 — Provelume Core subset

Provelume Core uses a deliberately light, **PR-local** protocol. Ownership, effect binding and reconciliation live in the owner PR and its exact reports. This repository does not add `AGENT_STATUS.md`, a global lock, a second checkpoint, or an operational dependency on Nexus.

## Lifecycle

1. Observe `main`, the intended branch, open PRs, CI/review/thread state, version/release state and roadmap once.
2. Claim one homogeneous workstream in its branch/PR description.
3. Produce an exact changed-file effect report bound to the current base and head SHAs. Rename/copy inputs include both source and destination.
4. Reproduce a fresh connector snapshot. Missing identities, required-review state, CI, thread count, mergeability, merge state or ancestry remain `UNKNOWN` and fail closed. An advisory verdict may remain `UNKNOWN` only when repository rules prove that approval is not required.
5. After merge, reconcile observationally. Release the PR-local ownership only after `MERGED`, binding-basis ancestry, merge/default ancestry and the exact default SHA are proven. Workflow or production evidence not exposed by the connector remains `UNKNOWN`; no outcome is inferred.

`tools/agent-protocol` never reads credentials, production environments or private Nexus content. It does not dispatch workflows, deploy, tag, release, modify a runtime, or write repository state.

## Path and workflow policy

Core implementation, release scripts, generated release evidence, dependency and version files are production/release-sensitive. Unknown paths and non-allowlisted workflows fail closed. Documentation, the protocol tool and its contract tests are the reviewed non-production subset for this rollout.

## Workflow decision matrix

| Surface | Decision | Reason |
|---|---|---|
| `.github/workflows/ci.yml` and its existing check names | KEEP | Existing clean-room, Windows/Linux core tests and deterministic release dry-run checks are stronger and remain authoritative. |
| Existing pytest discovery in `ci.yml` | KEEP_AND_HARDEN | The new contract test is discovered without adding or renaming a workflow/check. |
| Existing release and product validation | KEEP | The protocol cannot bypass or replace specialist gates. |
| REPLACE | none | No duplicate workflow is introduced. |
| REMOVE_AS_OBSOLETE | none | Deduplication is deferred until evidence supports it. |

The rollout is protocol-only: no product code, version, dependency, release marker or production surface is changed.
