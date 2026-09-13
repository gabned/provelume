# Cura S03 Action Center qualification scope

PRODUCT #262 implements C08–C12 of the
[Cura information architecture](../architecture/cura-information-architecture.md).
Package/runtime remains 0.10.1. The exact candidate, FULL, CI, findings, normal expected-head
merge and post-merge verification are bound by the append-only #255 release-train receipts.
This document does not qualify its own commit or mark an unexecuted observation as passed.

## Integrated behavior

Both Current and Preview use `/attention` and its exact item routes, with queue/state filters,
bounded pagination, visible completeness and unknown counts. Preview Overview and
`/api/v1/action-center` consume the same Instance-scoped read model. Detail pages separate
human-readable proposals and effects from optional exact evidence and receipt details.
Stale links show current evidence but do not present a decision form for the earlier revision.

Local forms require the existing authorized loopback boundary, a form token, a single-use
nonce, the exact Instance and relevant input/settings/authority revisions. Requests are
bounded, reject duplicated or unknown fields, and never repeat an expired form implicitly.
The core still independently checks the exact evidence under its mutation guards.

`/attention/authority` changes one queue and Instance/Source scope with explicit confirmation.
Controlled-automatic remains visibly unsupported for these evidence-only actions. S05 owns
canonical classification, duplicate/version handling and routing; S06 owns intake quarantine.
No placeholder action reports success. The explicit version-conflict producer is the public
`ActionCenter.propose_version_conflict` core method, bound to supplied current Version and
Original evidence; merely receiving several Versions does not manufacture a conflict.

`/attention/notifications` displays minimized local batches with exact item links, including
later pages. Dismissing a batch changes only delivery metadata, never review or ingestion.
`/settings/notifications` persists the in-app preference, quiet hours, time zone and aggregation.
Explicit saves promote the launcher document to schema 4; reading legacy settings does not.
Current/Preview switching preserves those settings. This is presentation rollback inside Cura,
not a promise that an older application binary understands schema 4.

Notification acknowledgement history has a bounded, explicit recovery page. It requires
confirmation that unchanged open items can become notifiable again, records a reset receipt,
and changes no canonical record, review receipt or user preference. Corrupt evidence is
unavailable; it does not become an empty queue or an invitation to silently erase state.

## Verification boundaries

The new automated tests exercise real synthetic producer records, canonical preservation,
closed decisions, authority, replay and stale conflicts, producer bounds/corruption/races,
cross-process duplicate writer contention, notification restart/quiet/DST/minimization and
explicit recovery. HTTP integration tests exercise both renderers and reference languages,
protected forms, current item links, unknown-state rendering and pagination. The HTTP
101-item pagination fixture explicitly substitutes a synthetic snapshot while retaining the
real notification journal; it is not evidence of 101 real acquisitions.

Development test outputs are retained outside source with original timestamps, commands,
failures and digests. They are distinct from the required unchanged-candidate FULL execution.
Browser observations must bind their actual candidate and disposable fixture, preserve the
before/after canonical/Original bytes, and distinguish visual inspection from API assertions.
New forms require keyboard/label and reduced-width observations; package qualification checks
that the new Python modules and templates are actually installed and frozen.

Seven governed catalogs and actual linguistic review remain mandatory S08 work. Host desktop,
browser/PWA permission and outward delivery, authenticated mobile use, actual native Windows
tray behavior and the complete accessibility/default matrix retain their S06/S07/S09 owners.
Generated EN/IT reference copy, browser screenshots and headless packaging do not qualify those
observations. Existing Emendatio Google evidence remains in its original scope and timestamps;
the old native visual deferral supplies no Cura waiver.
