# AGENTS.md — Provelume Core

These instructions apply to the entire `gabned/provelume` repository. They are public, repository-local, and complete without access to any private repository.

## Source of truth and boundaries

- GitHub is the executable source of truth for the default branch, commit SHAs, branches, issues, pull requests, checks, tags, releases, and release assets.
- This repository contains the public clean-room Provelume Core and self-hosted Instance packaging. It must remain usable without Nexus, Provelume Cloud, GitHub at runtime, or an external AI provider.
- Repository documentation defines public contracts. Private planning material may provide optional context only to an already-authorized agent; it is never required to understand, build, test, or release this repository.

## Clean-room rule

- Never copy or infer private Nexus code, data, paths, configuration, fixtures, generated knowledge, operational state, prompts, or Git history into this repository.
- Reimplement product behavior from public requirements, sanitized interfaces, and synthetic or public fixtures.
- Do not introduce a runtime or build dependency on Nexus.
- Treat private examples as requirements to sanitize, not material to transplant.

## Preflight

Before making a change, verify once against GitHub:

1. the default branch and its current SHA;
2. the working branch, head SHA, and merge base;
3. open pull requests that overlap the proposed release or workstream;
4. the current owner pull request, if any;
5. relevant CI and release workflow state;
6. the package version, existing tags, and published releases affected by the change.

Do not rely on a prompt's cached SHA when GitHub has advanced. If the verified base differs from the required base, stop and explicitly rebase or reconstruct the delta before continuing.

## Ownership and concurrency

- Each active release or homogeneous workstream has exactly one owner pull request.
- Do not open or maintain competing pull requests for the same outcome.
- Overlapping pull requests are inputs to absorb, defer, or close as superseded; they are not an implicit parallel backlog.
- Record an ownership change only after the new branch and pull request actually exist.
- Keep unrelated releases and product work out of a scoped protocol or documentation pull request.

## Delivery and release discipline

- Start from the verified default-branch SHA and keep the pull-request delta minimal.
- Use the repository's permanent workflows. Remove `one-shot`, `apply-*`, temporary bootstrap/patching workflows, and other branch-mutating transitional mechanisms before merge. Do not remove supported local setup helpers such as `scripts/bootstrap.py`.
- A pull request must not create an official release.
- Create a semantic release tag only from the reviewed pull-request result commit already present on `main`, including an approved squash-merge commit; the tag, package version, changelog, and embedded identity must agree.
- Candidate construction, rebuild, verification, and assembly remain read-only. Publication privileges belong only to the final trusted tag path.
- Do not weaken clean-room, least-privilege, offline verification, deterministic-build, or cross-platform gates to make a check pass.
- Check GitHub at preflight, after a real change, or immediately before an irreversible action. Do not poll CI, pull requests, or Actions continuously.

## Local verification

Use Python 3.12 or newer. Bootstrap the development environment when needed:

```bash
python scripts/bootstrap.py
```

For ordinary Core changes, run:

```bash
.venv/bin/python -m ruff check core tests scripts tools
.venv/bin/python -m pytest -q
git diff --check
```

On Windows, use `.venv\Scripts\python.exe`. For release-chain changes, also exercise the exact repository release dry-run and offline verifier paths defined by the checked-in workflows and release documentation; do not replace them with a weaker ad hoc test.

## Pull-request handoff

A handoff must state the verified default SHA, required base SHA, owner pull request and head SHA, intended version, checks run, remaining blockers, and whether any tag or release action remains. GitHub remains authoritative if that handoff later becomes stale.
