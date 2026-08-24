# Agent Development Protocol v1.2 — Core subset

This repository adopts the common v1.2 contract through lightweight, pull-request-local
ownership. GitHub remains the executable source of truth. No `AGENT_STATUS.md`, global
lock, private checkpoint, or runtime dependency on Nexus is introduced.

The protocol does not replace clean-room, Linux/Windows, deterministic-build, release,
offline-verification, least-privilege or publication controls. It only makes discovery,
identity binding, effect classification and reconciliation explicit and fail-closed.

## One bounded reconciliation

At the beginning of a new or resumed workstream, observe once:

1. current `main` SHA and the proposed branch merge base;
2. the single owner pull request and exact head SHA;
3. CI, requested review, unresolved threads and mergeability;
4. package version, tag/release state and relevant roadmap issue;
5. the last relevant workflow outcome when the workstream can affect a release.

Observe again only after a real head, CI, review, merge, tag or release event. An
inaccessible fact is `UNKNOWN`; it is never inferred from absence.

## PR-local lifecycle

The lifecycle is deliberately light:

- `CLAIMED`: a real branch exists from the verified base; no owner PR exists yet;
- `BOUND`: exactly one owner PR exists and its current head has an exact effect report;
- `MERGED`: GitHub proves the owner PR merged and the merge/default ancestry;
- `RELEASED`: a separate, authorized release workflow proves tag and publication state.

The branch and PR are the shared state. Reports and connector snapshots stay under
ignored `.agent/`; they are never committed as a second checkpoint.

Identifiers are closed and undecorated. PRs use `#N`, SHAs use complete lowercase
40-character values, and unavailable values use closed sentinels such as `NONE`,
`UNBOUND`, `UNASSIGNED`, `NOT_APPLICABLE`, `PENDING`, or `UNKNOWN`.

## Exact effect binding

`tools/agent_protocol.py predict` consumes an exact, sorted, duplicate-free changed-path
set and binds repository, base SHA, head SHA, policy, path list, path SHA-256 and effect.

Effects are:

- `NO_PRODUCTION`: documentation, protocol tooling, tests and the existing CI connector;
- `PRODUCTION`: Core source, package/release identity, release scripts or any other
  workflow capable of affecting build, release or publication;
- `UNKNOWN`: incomplete or invalid path evidence.

`NO_PRODUCTION` authorizes only `NO_PRODUCTION`. `REPOSITORY_POLICY` can admit a known
`PRODUCTION` delta only to the repository's existing product/release gates; it never
publishes or grants release authority. `UNKNOWN` cannot bind.

## Connector-only evidence

`validate-connector` validates a caller-supplied schema-2 snapshot without making a
network request. It requires exact repository/default/base/head/merge-base identity,
owner PR, successful CI, required review, resolved threads, mergeability and base
ancestry. Critical `UNKNOWN` values fail closed.

The snapshot must explicitly prove that credentials and production environments were
not accessed. The tool has no credential, environment, workflow-dispatch, release or
runtime capability.

## Observational reconciliation

`reconcile` consumes supplied post-merge evidence. It can prove only:

- owner PR state `MERGED`;
- binding-basis ancestry;
- merge SHA presence on `main`;
- current default SHA identity.

The observed workflow/release outcome may remain `UNKNOWN`; merge identity can still
be proven, but no success, publication or production state is inferred. Reconciliation
cannot dispatch/rerun workflows, create tags, publish artifacts or write runtime data.

## Workflow matrix

| Workflow/group | Classification | Rationale |
| --- | --- | --- |
| `.github/workflows/ci.yml` | `KEEP_AND_HARDEN` | retain clean-room, Linux/Windows tests and deterministic dry run; add the offline v1.2 contract inside the existing CI |
| permanent release/dry-run/publish workflows | `KEEP` | preserve all current names, permissions and specialist release controls |
| refresh/build-input lock workflow | `KEEP` | preserve its repository-local release-input role |
| replacement candidates | `REPLACE` | none in this rollout |
| temporary or one-shot workflows | `REMOVE_AS_OBSOLETE` only with evidence | none removed by this rollout; future removal requires origin, useful-delta and replacement proof |

## Verification

```bash
python tools/agent_protocol.py self-test
python -m ruff check core tests scripts tools
python -m pytest -q
git diff --check
```

The executable entry point has Git mode `100755`. CI verifies that mode and confirms
that `.agent/` is ignored and no global `AGENT_STATUS.md` exists.

## Product boundary

Protocol rollout and product development never share a PR. At rollout time, product
PR `#37` remains a separate blocked workstream: it is divergent, its Linux/Windows lint
checks fail, and four current review threads remain unresolved. Reconstruct or update
that product delta only in its own homogeneous workstream after this protocol layer is
clean.
