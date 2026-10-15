# ADR 0055 — Cura primary and explicit backup preferences

Status: independent 0.13 campaign candidate, #354, parent #349; qualification pending.

Fresh product defaults already select Cura (`preview` in the compatibility wire
vocabulary). An old stored `current` value without an interface selection receipt
is an inherited default, not evidence of an explicit backup choice. After validating
the complete original schema and receipt, the existing settings reader projects
such a value to Cura and promotes schemas 1/2 to schema 3. Reading creates no file,
lock, revision or selection receipt. The next existing authorized settings
transaction persists the migration. Invalid receipts still fail validation.

A valid explicit Previous interface (`current`) receipt preserves that selection
across restart, upgrade, unrelated preferences and subsequent saves. The existing
interface selector records each explicit choice, including a return to Cura, in
one existing transaction. Appearance/all reset semantics continue to select the
product default. Notification-only resets do not broaden their scope. No wire
enum, second preference store, application, queue, scheduler, Action Center or
Knowledge/Originals copy is introduced.

Failed preference side effects restore the exact stored preimage, including legacy
schema and formatting, rather than serializing the reader's projected defaults.
The existing atomic publication/OS lock is reused. If no settings file existed,
rollback restores absence. Historical receipts are not rewritten or invented.

The existing seven shipped catalogs already label Cura as the standard interface
and the backup as Previous interface. The browser selector remains available at
`/settings/shell#interface-mode-heading`; the launcher/local panel already opens
that same settings route. Native and browser controls retain one settings owner.
This candidate changes inheritance/migration, not the catalog text or queue model.

Before acceptance, qualify clean install/reset/upgrade/explicit backup/return,
preservation of Instance, Knowledge, Originals, credentials, jobs, relevant
preferences and AI/network permissions; backup critical journeys; all shipped
catalogs; keyboard, screen reader, zoom/reflow, themes/contrast and native Windows
launcher/installed behavior. Automatic contracts and a responsive viewport do not
substitute for missing human/hardware evidence. Historical attestations do not
automatically qualify the changed default/migration contexts. No release identity
changes or publication occur here; 0.13 final qualification includes this work.
