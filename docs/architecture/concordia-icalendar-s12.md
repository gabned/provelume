# Concordia S12 iCalendar feeds

S12 consumes the exact S11 candidate under the
[ordered development exception](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974).
It does not accept predecessors or relax the [complete manifest](concordia-step-0.md).

Current and Cura expose `/icalendar` through Connectors. Multiple local files and
HTTPS feeds have independent ConnectorInstance/Source identities, consent histories
and complete-snapshot checkpoints. A local file works with external network access
disabled. HTTPS additionally requires the existing Instance/identity network grants
and exact origin; redirects are refused and TLS verification remains enabled.
The complete HTTPS operation runs in an owned worker with a 30-second parent wall
timeout, including DNS. Read chunks also reduce socket timeouts to the remaining
deadline. The worker inherits the configured proxy and CA trust; private response
bytes and connection inputs use a temporary directory removed after completion.
Viewing this page never reads the vault, contacts a provider or starts acquisition.
Actions require loopback, bounded forms, CSRF, confirmation and the displayed
Source consent revision. Human/linguistic review is separate from automatic checks.

Locations, token-bearing HTTPS addresses and Authorization headers reside in the
external OS vault, with no plaintext fallback or canonical/backup/export reference.
The canonical Source keeps an opaque selection digest. Restored data remains
readable offline; explicit device reconnection to the same selection retains
Source and object IDs. A different file/address requires a separate Source.
Reconnection does not grant network access or enable disabled reading.
No credentials are accepted as CLI arguments. HTTPS CLI registration reads a
bounded device-local JSON file outside the Instance with `url` and optional
`authorization`; errors never echo those values.

`icalendar-add`, `icalendar-read`, `icalendar-schedule` and
`icalendar-duplicates` expose the same services. Reading runs through
`productivity.intake` in the normal scheduler, with a single automatic attempt.
Scheduled consent is independently required; a manual read preserves the existing
schedule. Disabled consent blocks future runs. The shared S10 bounded preview and
S11 attributed intake retain exact feed Originals and publish completeness only
after every item is durable. Partial/error outcomes cannot advance the checkpoint.

## Parsing and semantics

Each feed is at most 2 MiB, 30,000 physical lines, 128 KiB per line, 6,500
components, eight nesting levels and 5,000 events. Shared mapped page/session
limits still apply. A separate process parses each immutable feed, preventing
cross-feed VTIMEZONE cache reuse. Its wall timeout is 15 seconds; Linux additionally
enforces CPU/address-space limits. The frozen Windows executable has an explicit
file-based worker entry, with no external Python/PATH requirement. Parse failures
remain closed and do not echo private values. No recurrence expansion, attachment
fetch, alarm execution or following embedded URLs occurs.

UID plus original recurrence instance identifies an item within its Source.
RRULE/RDATE/EXDATE/EXRULE, original TZIDs, DST offsets, exclusive all-day dates,
exceptions and cancellation tombstones remain in the mapped observation and exact
Original. METHOD:CANCEL retains cancellation meaning. Floating times require an
explicit feed zone; known zones use shipped tzdata. Custom VTIMEZONE instants are
mapped to exact UTC and retain the original zone context. Matching UID/instance
across Sources is explained in the duplicate view and never silently merged.
Duplicate identities within one feed and broken/ambiguous values fail visibly.
RFC5545 instantaneous timed events retain equal start/end instants in the
Source-attributed object variant; no artificial duration is added. Existing
manual Entitas objects still require their original increasing interval.

## Dependencies and qualification

The official parser is pinned to `icalendar==7.3.0` (BSD-2-Clause) and its timezone
dependency to `python-dateutil==4.0.0` (BSD-3-Clause). Complete publisher notices are
retained under package runtime notices. `scripts/add_calendar_runtime_lock.py`
generates additive pure-wheel Windows runtime lock proposals and preserves all
existing pins/hashes. A Linux proposal is explicitly
PROPOSED_NATIVE_WINDOWS_NOT_RUN. The permanent native Windows resolution,
hash-install, frozen worker and installed offline qualification must pass on the
exact candidate before acceptance. Existing build-tool locks are unchanged.

Synthetic automatic tests use actual local files, parser child, Core services,
Source consent and scheduler, canonical objects, portable rebuild/reconnection,
seven translated HTTP views, failure/timeout/revocation and duplicates. The browser
driver's productivity cells additionally render the feed controls at 1280/320px.
`--ocr-command icalendar-qualify <fresh-target>` exercises local reads, duplicate
Sources, replay and portable rebuild from the actual installed executable; the
permanent installed offline Windows job invokes it with the same firewall boundary.
This is separate from real HTTPS feed and human observations. Those remain
NOT_RUN without their specific authorization/evidence; all manuals remain
DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official release on the
maintainer's Windows 11 Pro 25H2 PC. No intermediate personal installation occurs.

Sources: [RFC5545](https://www.rfc-editor.org/rfc/rfc5545),
[versioned icalendar API](https://icalendar.readthedocs.io/en/v7.3.0/reference/api/icalendar.cal.calendar.html),
[parser usage](https://icalendar.readthedocs.io/en/latest/how-to/usage.html),
[publisher distribution](https://pypi.org/project/icalendar/).
