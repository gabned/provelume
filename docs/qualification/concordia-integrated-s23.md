# Concordia S23 integrated qualification

Status: DEVELOPMENT / NOT_ACCEPTED. The complete contract remains
[step 0](../architecture/concordia-step-0.md), with the explicit
[read-only Asana/Tududi decision](https://github.com/gabned/provelume/issues/383#issuecomment-6711131611).
The ordered development authority does not accept any predecessor or permit
publication before all acceptance gates.

## Material continuity

The original uncommitted S23 worktree based on `090af1a` was not present in the
environment attached on 8 November 2026. The available checkout was `1711f03`.
The maintainer explicitly authorized reconstruction in this chat. This is new
work on the remotely retained S22 lineage, not recovery of the missing patch or
reuse of its unobserved test results. No existing checkout was reset.

## Reproduced integration findings

Two synthetic Gmail regression cases fail on the S22 source: the passive body
selector rejects valid acquired Gmail provenance, and a portable rebuild after
removing derived data does not restore its searchable representation. Original
failures remain in the PR-local evidence. Local-email assumptions in the selector
and manifest reader disagree with the already accepted Google acquisition record.

The correction binds each bundle to its canonical acquisition profile and hashed
provider observation. Offline rebuild preserves the recorded acquisition metadata
and settings digest; it does not claim a new remote fetch or rewrite canonical
records. Only known default profiles, or matching retained explicit settings, can
be reconstructed. Unknown profiles and altered provider bindings remain refused.
Recovery runs only under the existing explicit derived-rebuild authority; ordinary
scoped refreshes retain `recover_missing_derived=False`.

## Required remaining qualification

One integrated synthetic Instance must exercise independent Google identities and
six Gmail/Drive/Calendar grants, independent Asana/Tududi identities, two local ICS
feeds, attributed duplicates, revocation, read-only public task providers, separate
synthetic guard tests, exact local/Git mirror generations, offline operation,
Root restore and portable recovery. Browser, installed/native, security and release
checks retain separate exact-head results. Real providers and remote destinations
need their existing precise scope authorization; synthetic results do not qualify them.

Real browser 200% zoom remains NOT_RUN until the browser reports its actual zoom
factor and the complete journey succeeds. All human methods remain
DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official release on the
maintainer's Windows 11 Pro 25H2 PC. No intermediate installation is authorized.
S07/S08 original FAILs, UNKNOWNs and BIND #439/6654096835 remain unchanged.
Identity stays 0.14.0/development until the final workstream.
