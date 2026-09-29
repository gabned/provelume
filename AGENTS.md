# Provelume Core agent entry

These instructions apply to all of `gabned/provelume`. GitHub is the executable
source of repository, branch, commit, PR, checks, tag and release identity.
The product Core remains here. The independent Agent Protocol source and current
operational/Work revision are selected by .github/agent-protocol/pin.json.

## Product boundaries

- This public clean-room Core and self-hosted Instance must work without Nexus,
  Provelume Cloud, GitHub at runtime or an external AI provider. Never transplant
  private code, paths, fixtures, data, operational state or Git history. Use public
  requirements and synthetic fixtures; no private dependency is required here.
- Keep one PR-local owner per homogeneous workstream. There is no AGENT_STATUS.md,
  committed global lock or second checkpoint. Do not interfere with another owner.
- Separate PRODUCT and PROTOCOL. A PRODUCT Protocol defect stops that workstream
  and follows the separate escalation path. Never weaken a gate, fabricate authority
  or author a waiver. Explicit user authorization persists within its actual scope.
- Keep credentials and private data out of source, logs, public evidence and CI.
  No untrusted artifact or candidate code enters a secret-bearing context.
- Preserve offline verification, deterministic builds, least privilege and the
  existing independent release/publication gates. Normal CI does not publish.
  Release identity, package metadata and actual reviewed main commit must agree.

## Read and execute

Start with bounded reconciliation of repository identity, accepted pin, workstream
owner and actual trigger effects. Verify the canonical dependency through
python tools/agent_protocol_v2.py verify and select current documents through
python tools/agent_protocol_v2.py documents --phase START --host CLI --workstream PROTOCOL,
using the actual phase/host/workstream. The selected canonical topic contract and
docs/agent-protocol/operations.md govern new execution. Local PRODUCT policies,
architecture and release gates remain mandatory. Integrity does not establish authority.

Use one signed durable journal per new PR/workstream through an independently
enrolled host. A PR description is a summary. Existing owners and legacy receipts
keep their original supported route; follow docs/agent-protocol/compatibility.md
before any migration. .agent/ contains ignored caches and temporary material.

After each milestone state what is verified, one next action and where it runs,
then the remaining milestones. Continue work already authorized here. Only a real
handoff needs a short resume prompt with owner, durable evidence, expected head,
pin and unresolved gates. Do not start a new PRODUCT objective through closure.

## Native checks

Use the runtime declared in pyproject.toml and the supplied Node runtime. Reuse
valid dependencies; when missing, run python scripts/bootstrap.py. Before
publication run the full native checks on the unchanged candidate:

```bash
.venv/bin/python -m ruff check --cache-dir .agent/ruff-cache core tests scripts tools
.venv/bin/python -m pytest -q
git diff --check
```

On Windows use .venv\Scripts\python.exe. Release-chain changes additionally run
the checked-in release dry-run/offline-verifier paths. Local success is not remote
qualification. Use permanent workflows, complete exact-head CI/reviews, baseline
scope/effect binding and normal expected-head GitHub merge. Reconcile actual merge
identity and required post-merge checks before claiming delivery.
The optional laboratory profile is described in docs/agent-protocol/workspace.md;
it does not replace the native gates or authorize application publication.
