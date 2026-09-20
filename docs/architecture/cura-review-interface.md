# Cura local review interface

The same domain review pages serve Current and Preview presentation through the
existing base layout. Document and Action Center links open
`/review/decisions/<domain>/<subject>`. The interface offers labelled selections
for Area/Project placement, secondary associations, routing Source/path, duplicate
participants, eligible Versions and explicit capability scopes. Users do not
write JSON. Hashes and retained receipt details are available in expandable
evidence sections.

`/review/capabilities` lists effective persisted domain grants; a separate
configuration review changes a selected grant. Missing grants remain disabled.
Scope controls distinguish selected objects from an explicit all-current-and-
future-objects choice, and allow Source restrictions. Controlled automatic mode
only offers routing application. Saving a routing rule and granting application
permission remain distinct decisions. `/review/routing` lists revisioned rules
and creates a new, unpersisted identity for a rule form.

The local browser session is held only in bounded memory. Page reads create no
Instance plans, directories or lock files. Preview POST accepts closed JSON
generated from the form controls, requires exact Origin and the page's local
session token, and retains the resulting server plan. It publishes no effect.
The response shows exact before/after choices, impact, effective reversibility,
actual or unknown confidence and bound evidence. It identifies ambiguous routing
as requiring explicit confirmation.

The user must check the confirmation acknowledgement and activate the explicit
confirmation button. A field change invalidates the displayed preview, including
a response arriving after a newer selection. Confirmation submits only retained
plan/revision/request identities; it cannot supply effect bytes, actor, grant or
replacement parameters. The server consumes the session once and asks the shared
coordinator to revalidate authority and evidence under the normal lifecycle lock.
An uncertain response disables another submission and directs the user to fresh
retained history; the interface does not replay a possibly committed effect.

All inserted dynamic preview text uses `textContent`, and Jinja escapes form and
history values. The script is an external local resource with exact SRI admitted
by the existing CSP. Native labelled controls, fieldsets, live status, preview
focus and keyboard confirmation work without pointer-only controls. If JavaScript
is unavailable the page explains that no change was made. English and Italian
catalogue values are authored application translations; automatic catalogue
parity and route checks are not human linguistic review.

`ActionCenter.review_projection` supplies actual retained domain history alongside
legacy inspection state. The HTML/API projection and decision links do not mutate
the old inspection receipt schema or claim that a historical effect is still the
current plan. UI integration tests exercise the real registered routes and
coordinator; browser rendering and native visual observations remain separate
qualification evidence.
