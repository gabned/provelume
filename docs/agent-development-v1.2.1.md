# Agent Development Protocol v1.2.1 — Core change-control overlay

This repository applies v1.2.1 as a narrow, pull-request-local change-control
overlay on the v1.2 Core contract. It does not add a global checkpoint, lock,
`AGENT_STATUS.md`, private state, Nexus dependency, GitHub runtime dependency,
credential access or production-environment access.

The v1.2 lifecycle, schema-2 effect report, binding and reconciliation formats
remain unchanged. The overlay has its own schema-1 report and version
`1.2.1`.

## Closed workstream classes

Every pull request body contains exactly one marker:

```text
WORKSTREAM_CLASS: PRODUCT
```

or:

```text
WORKSTREAM_CLASS: PROTOCOL
```

`PRODUCT` covers every non-protocol change, including public documentation,
dependencies, packaging and release preparation. `PROTOCOL` covers only the
protected agent surfaces below. Missing, duplicated, open or unknown values
fail closed.

## Core protected-path profile

The executable profile is the closed registry in
`tools/agent_protocol.py`. It protects:

- `AGENTS.md`;
- `.github/CODEOWNERS`;
- `.github/pull_request_template.md`;
- `.github/workflows/ci.yml`;
- `.github/agent-protocol/**`;
- `.gitignore`;
- `docs/agent-development-v*`;
- `tests/test_agent_protocol_*`;
- `tools/agent_protocol*`.

All other paths are `PRODUCT_SURFACE`. Any tracked `.agent/**` evidence or
any `AGENT_STATUS.md` is `FORBIDDEN_GLOBAL_STATE`.

A `PROTOCOL` pull request may contain only `PROTOCOL_SURFACE`; a `PRODUCT`
pull request may contain only `PRODUCT_SURFACE`. A rename contributes both
its source and destination. Incomplete, empty or invalid path evidence is
`CHANGESET_UNKNOWN`. Mixed categories fail with `MIXED_SCOPE`; no path is
silently reclassified.

## Connector-only guard

The permanent `Public repository CI` workflow keeps its existing job names.
For a pull-request event, its clean-room job:

1. uses the event's exact base and head SHAs;
2. produces complete NUL-delimited Git name-status evidence with rename
   detection;
3. invokes `tools/agent_protocol.py change-control` offline;
4. cross-binds repository, owner PR, base, head, body class and path set;
5. records that credentials and protected environments were not accessed.

The tool makes no network request, dispatches no workflow, writes only ignored
`.agent/**` evidence and exits non-zero on every blocker.

## Stop and `PROTOCOL_ESCALATION`

An agent working in a `PRODUCT` pull request must stop when it encounters a
possible protocol defect or a need to edit a protected path. It must not repair,
weaken, extend or waive the protocol in that product pull request.

The offline escalation report uses mode `PROTOCOL_ESCALATION`, an exact owner
PR and head SHA, one closed finding code, blocker
`PROTOCOL_ESCALATION_REQUIRED`, and action
`OPEN_SEPARATE_PROTOCOL_PR`. Product work resumes only after a separate
`PROTOCOL` pull request or an explicit human decision.

Finding and blocker identifiers come only from the closed registries in
`tools/agent_protocol.py`. An unknown synonym is invalid, not advisory.

## Emergency waiver

A waiver is a last-resort human exception. Agents may validate one but must
never author, activate, edit, renew or remove it.

The human places exactly one static JSON object in the pull-request body:

```text
<!-- PROTOCOL_EMERGENCY_WAIVER
{ ... }
PROTOCOL_EMERGENCY_WAIVER -->
```

The object has an exact closed field set. It is valid only when all of these are
true:

- schema `1`, change-control version `1.2.1`, mode
  `EMERGENCY_WAIVER`, source `GITHUB_CONNECTOR`;
- repository, owner PR and current 40-character head SHA match exactly;
- `static`, `active` and `human_only` are true;
- the connector event proves a non-bot repository owner/member/collaborator
  matching `approver_login`;
- reason and waived blocker codes belong to their closed registries;
- every waived blocker is both active and explicitly waivable;
- credentials and production environments were not accessed.

Any head movement invalidates the waiver. Unknown evidence, missing
classification, connector identity defects and forbidden global state are
never waivable.

## Existing gates remain authoritative

This overlay does not weaken or rename:

- `Clean-room and repository hygiene`;
- `Core tests (ubuntu-latest)`;
- `Core tests (windows-latest)`;
- `Deterministic release dry run`;
- build-input lock, offline verifier, release assurance or publication gates.

No protocol pull request creates a tag, release, artifact, deployment or
runtime change. Post-merge reconciliation remains one PR-local, observational
v1.2 reconciliation.
