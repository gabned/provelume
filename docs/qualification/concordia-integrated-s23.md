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

## Exact-source observations and visual-artifact correction

At `8762697f62b9096113e01678ee963d0e63d30f75`, native Python 3.12.14 reports
5,988 passed, 65 skipped and 419 subtests in 947.10 seconds. Ruff/diff and the
97 canonical pinned files pass. The integrated synthetic journey passes; public
Asana/Tududi writes remain refused under decision L.

The same source's 42 browser functional cells pass: 28 at100%/1280 or320px and
14 at native200%/1280px. Native settings readback is2, innerWidth640 and DPR2;
canonical/Original data remains unchanged, with zero observed external browser
requests. A separate screenshot review found that Playwright's CSS-sized
full-page capture clips the200% bitmap to640px, despite correct DOM reflow.
Those original screenshots are incomplete visual evidence and remain retained.
A native CDP control observes document/body/client/scroll widths640px, no
overflowing main elements, and captures a full1280px bitmap. The corrected driver
uses native CDP content bounds and verifies the actual PNG dimensions. Its
changed candidate still needs fresh complete browser qualification.

Installed Windows run42456753356/a1/job128657309619 fails at S22 native local
rsync copy with Win32 sharing error32. The independently downloaded/CRC-checked
artifact13608841865 preserves the preceding native DPAPI/owned-agent one-signature
and wrong-host refusal PASS at this exact source, followed by the original FAIL.
The installed integrated S23 command was not reached and remains NOT_RUN.
S22 Linux native nine-case PASS at78491d2 does not qualify8762697 or Windows.
Full Windows SSH/rsync authentication/transport remains NOT_RUN/unadmitted.

Raw evidence is saved with verified export/restore and independently fetched
Git notes, linked from the sole owner PR460; it grants no acceptance or authority.
Current CI cancellations/FAILs/UNKNOWNs and the original S07 findings remain
separate. S23 is NOT_ACCEPTED. No final identity or official Preview was created.
