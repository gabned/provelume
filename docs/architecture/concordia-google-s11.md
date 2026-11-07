# Concordia S11 Google read intake

S11 extends the [S10 conformance boundary](concordia-connectors-s10.md).
Development is authorized by [the campaign exception](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974);
acceptance, main integration and publication still require the full
[ordered manifest](concordia-step-0.md). It does not accept S07/S08 or change their
CPU findings. No mail sending or Calendar mutation is implemented.

## Authority and device credentials

The additive `google-readonly-concordia` definition, adapter version 1.1.0,
supports independent Gmail, Drive and Calendar grants. Existing definitions remain
immutable. Explicit Calendar connection upgrades a compatible identity definition;
viewing a page does not upgrade, read credentials, authorize or acquire anything.
An identity can select multiple Calendar Sources; a Source selects exactly one
calendar and owns its consent, cursor and generation. Two identities never share
grants, Sources or checkpoints. Disconnecting Calendar leaves Gmail/Drive intact.

Calendar PKCE requests only `calendar.readonly`, with independent scope and account
equality checks. Source execution additionally requires current identity lifecycle,
network policy, capability state and explicit Source read consent. Scheduled work
requires scheduled consent. The OAuth grant and its derived device link live in
the existing external OS vault. New canonical metadata, backup and portable data
contain neither secrets nor grant references. Legacy explicit external references
remain readable. A failed link/CAS publication preserves the previous owned grant;
the new grant is discarded without overwriting a newer device link.

## Bounded acquisition and source completeness

Calendar uses fixed Google HTTPS origins and GET requests. Event pages retain
exact response Originals, even empty pages. The normal scheduler calls this intake;
the guided slice retains its existing two-page, 25-item page limits. Normal slices
also retain their request limits, with the stricter shared 200-item/2 MiB page,
8 MiB session and 60-second admission deadline. Unsupported/oversized/malformed
responses fail visibly. No retry, automatic 410 reset or hidden extra backfill is
performed. A transport timeout remains a failure, never successful completeness.

Continuation pages use the same query, `singleEvents=false`, `showDeleted=true`
and sticky page size. The terminal `nextSyncToken` is required before publishing a
complete Source generation. Incremental reads reuse the original query parameters.
A 410 preserves data and the invalidated cursor and blocks further reads until
explicit reset. At most 32 completed delta ancestors are traversed; the next
generation is a bounded full resync. Reset/revocation/selection/consent changes
invalidate pending admission. Authority is checked after the response and again
before promotion and cursor publication.

Each exact item produces Source-attributed Document/Version/Acquisition evidence
and a read-only canonical Entitas Task/CalendarEvent. Originals and observations
commit before cursor advancement; interruption can leave retained partial data
but cannot label the Source complete. Durable generation member records and the
producer cursor commit together through the registered bounded atomic transaction
and native reopen recovery. Repeated pages deduplicate; A → B → A creates distinct
version history. Semantic no-ops do not create new object revisions. Missing items
in a completed full generation become historical/unconfirmed, never invented
remote cancellation. A completed delta preserves unchanged membership.

Date-only values stay dates. All-day exclusive end dates, TZID/offset/DST,
recurrence rules, recurring parent and original occurrence, cancellations without
times and exact remote revision meaning remain distinct. Long descriptions exceed
neither the established canonical object limit nor a silent truncation rule: the
full acquired source observation is retained and the object resolves it offline.
Source origins and evidence are validated; manual edit routes reject these objects.
Originals, objects and complete-snapshot membership survive backup/portable rebuild.

## Qualification and limits

Automatic synthetic tests exercise the real PKCE manager, scheduler, vault seam,
atomic recovery, canonical graph, portable transfer and seven-language HTTP views.
The browser driver accepts `--include-productivity` to add Calendar controls and
an actual local synthetic all-day object to its 28 rendered cells. No synthetic
provider or Server CI observation qualifies a real Google identity. Real account
qualification remains NOT_RUN pending the specific recorded account authority;
all human rows remain DEFERRED_BY_MAINTAINER / NOT_RUN until the official release
on the maintainer's Windows 11 Pro 25H2 PC. No intermediate installation is needed.

Official API contracts consulted:

- [Calendar authorization](https://developers.google.com/workspace/calendar/api/auth)
- [Events list, page/sync token and 410 semantics](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)
- [Events, recurrence and cancellation](https://developers.google.com/workspace/calendar/api/v3/reference/events)
