# Cura notification preferences and foreground acknowledgements

S03 implements the C12 foundation over the authoritative Action Center read model.
This contract does not add a review queue, decision authority, provider, operating-system
permission grant or background service. C11 capability/scope authority belongs to the
Action Center/domain owner; notification acknowledgement never grants it.

## Settings and compatibility

`NotificationPreferences` owns one closed payload, schema 1: independent `in_app`,
`host_desktop`, `browser` and `pwa` switches; `preview=counts_only`; explicit quiet-hour
start/end/IANA timezone and enabled flag; aggregation seconds. Defaults are in-app on,
all outward channels off, quiet hours disabled (22:00–08:00 UTC when explicitly enabled),
and a 60-second aggregation interval. Unknown fields/types, sensitive-preview modes,
invalid timezone/clocks, a full-day quiet interval and unbounded intervals are rejected.

`ShellSettingsManager.configure_notifications(preferences, expected_revision=..., source=...)`
is the explicit schema-4 promotion path. It reuses the existing process lock, bounded
atomic replacement and revision transaction. Schema 1/2/3 reads do not rewrite their
documents; ordinary legacy preference writes remain at their compatible schema. An
interface selection promotes schema 2 only to 3; it preserves schema 4 if already selected.
Schema-4 ordinary writes and Current/Preview rollback preserve notifications and the
existing interface receipt. Desktop `asdict` reconstruction preserves the same fields.

Schema 4 adds `shell.notifications` and `shell.notifications_change`, retaining the existing
top-level shape and preference owner. The change receipt contains revision, UTC time,
local source kind, before/after preference digests and whether they differ. No item content,
path or credentials are included. Stale saves fail. An invalid persisted launcher uses the
existing safe-default warning; notifications fail closed, and notification configuration
cannot silently repair the file by discarding unrelated settings.

Existing schema-1 preference export/import keeps its declared fields. Import preserves
notifications, interface selection and receipts outside that transfer scope. **Complete
notification export/import/reset integration remains mandatory S09 work under C38/C39**,
including a versioned transfer contract and safe defaults; credentials, selected Instance,
knowledge and queue history must retain their declared protection. An old S02 binary is
not claimed to parse launcher schema 4. Presentation rollback is not binary downgrade.

## Channel truth

`channel_states()` returns desired preference, supported/effective state and permission
state independently. In-app delivery is foreground-only and needs no separate OS
permission. Host desktop, browser and PWA remain `integration_pending`, `supported=false`,
`enabled=false`, permission `unknown`, even if a stored desired switch is true. Reading or
configuring these fields does not request permission, install software or enable a tray,
login startup, device credential, remote listener or provider. The UI explains unavailable
channels rather than presenting an effective permission switch.

The existing native tray icon/status/lifecycle remains intact. Its Win32 icon add/update
evidence is not evidence of a delivered queue notification. S06 owns Capture/browser/PWA
integration, S07 reference mobile paths and scoped retrieval, and S09 host delivery/tray
and actual native/PWA qualification. Pending integration is never a release exemption.

## Pure preview and exact navigation

`NotificationService(instance_root, instance_id).preview(snapshot, loaded_settings, now=...)`
consumes the same Action Center snapshot dictionary as the Browser/API. It verifies the
Instance manifest/binding and uses only item ID, input revision and review state from at
most 100 supplied items. It ignores producer titles, content and supplied URLs. The result
contains minimized item references and a localized message key/count, not document text.

`count` means this notification batch; `queue_count`, `count_relation` and completeness
retain the authoritative selection's meaning before pagination. A 100-item page cannot
become the total of all unresolved items. Each supplied page may be consumed independently;
acknowledging its batch does not acknowledge another page. The overall Action Center
remains visible when every notification channel is disabled or notifications are quiet.
The route carries its explicit offset through both preview and fresh acknowledgement
snapshot. An incomplete page without observed members is `unavailable`, never proof of
an empty queue; known members on an incomplete page retain the honest count relation.

Item URLs are generated as `/attention/items/{item_id}?instance_id=...&revision=...`.
The UI appends its governed language and resolves the relative path on the current service
origin. Single and aggregate views use those same exact authoritative details. Root's
notification batch page compares its requested batch ID to the current preview and
explains stale membership. The detail owner checks current Instance/input state and normal
access; opening a link never decides an item or automatically downloads an Original.

Preview reads never create settings, a journal, a lockfile, acknowledgements or canonical
data. The in-app consumer renders this foreground projection with an explicit acknowledgement
control. No worker, native toast, push subscription, cloud or runtime network is introduced.

## Quiet hours and aggregation

Quiet hours concern notification presentation, not scheduler job eligibility. Shared
scheduler timezone utilities resolve local intervals, with the latest instant for an
ambiguous end and the first valid instant after a skipped end. Cross-midnight windows
and the complete repeated end interval are respected. After an acknowledgement, new
pending revisions aggregate until that receipt's time plus the configured interval;
quiet hours can defer that instant further. The initial foreground batch is immediately
eligible outside quiet hours. No polling read persists a guessed first-observed time.

States distinguish `ready`, `empty`, `disabled`, `aggregating`, `deferred_quiet`,
`clock_reversed` and `unavailable`, with an exact next eligible time where applicable.
Clock reversal cannot resend an acknowledged revision. Once eligible, the next foreground
read recomputes current membership; it does not replay all historic transitions. A display
or acknowledgement does not prove external delivery or that every item was read.

## Explicit acknowledgement and bounded recovery

`acknowledge(snapshot, loaded_settings, batch_id=..., expected_revision=...,
expected_settings_revision=...)` writes only `state/action-center/notifications.json`.
The route owner supplies a fresh server snapshot, local request protection, CSRF and a
one-use nonce. The service independently validates Instance binding, exact batch/input
references, settings revision, journal revision and current eligibility. It reuses the
existing OS lock/path guards and atomic JSON writer. A stale batch cannot acknowledge a
newer input revision; it never submits an Action Center review decision.
Path guards reject broken symlinks as well as existing links/reparse points, including
the lock and every parent, before any notification metadata is created.

The journal stores up to 512 Instance/channel/item-revision digests, the latest 32 small
acknowledgement receipts and one last-reset receipt, within 64 KiB. It contains no copied
review state or item content. A repeated guarded acknowledgement returns its existing
receipt without another write. Later item revisions remain independently eligible across
restart. Corrupt/mismatched metadata stays explicitly unavailable, never silently reset.

Receipts rotate without removing acknowledged-item digests. There is no age-based pruning:
a missing item in a bounded page is not evidence that it was resolved. Capacity reports
`notification_journal_full` before the UI offers an acknowledgement that cannot fit.

Recovery is an explicit metadata-only action:
`reset_acknowledgements(loaded_settings, expected_revision=...,
expected_settings_revision=..., confirm_redelivery=True)`. The UI must explain that
**unchanged items become notifiable again** and require its own confirmation/nonce. The
service checks both revisions and a literal true confirmation under the journal lock.
It clears acknowledgement metadata, preserves a bounded last-reset receipt with the prior
canonical journal digest and counts, and works at the item-history capacity. Replaying
that reset returns its existing receipt. Subsequent acknowledgements retain the last
reset receipt. No Original, Document, Version, Source, review decision or operation is
reset, pruned or deleted; disabled channels stay disabled. Invalid journals require
explicit diagnosis/repair rather than this path discarding unknown history.

Reference EN/IT notification, scope and recovery copy is sensitive; S08 owns actual
linguistic review. S09 owns the complete appearance/input/device and native/PWA matrix.
Synthetic tests and foreground observations do not claim those later qualification results.
