# ADR 0030: Reversible Cura presentation and retrieval context

## Status

Accepted for PRODUCT 0.11/S02, #258. Runtime remains 0.10.1; the release-default
decision and integrated accessibility qualification belong to S09.

## Decision

One server-rendered application owns both presentations. A fixed Jinja layout
dispatcher selects Current or Preview from one loaded launcher-settings snapshot
per request. The original Current layout remains byte-identical at `templates/base.html`.
Child templates extend the fixed request-bound `base_layout` choice; Preview uses
`templates/cura/base.html`. There is no request-provided template name.
Preview adds a shared sidebar, a compact in-flow Menu, useful Overview, progressive
Knowledge/Search and grouped Management. Existing endpoints, data models and user
confirmations remain authoritative. The bounded attention view projects recorded
failed operations; S03 owns the unified typed Action Center and local queues.

The explicit, CSRF/nonce/revision-protected interface choice uses launcher schema 3
and an atomic last-choice receipt. It has no service-restart effect. Other open pages
adopt the choice on navigation/reload. A GET never migrates or saves preferences.
An explicit valid language query takes precedence over valid persisted language,
then Instance defaults. S08 owns the expanded governed locale registry.

The fixed first-party `cura-shell.js` enhances the compact navigation and expires
an already server-validated NEW cue. It reads no user content, writes no storage,
performs no network request and evaluates no code. Preview HTML authorizes only
the exact SHA-256 of that packaged file in `script-src` and uses matching SRI.
Current HTML retains `script-src 'none'`. No script origin wildcard, `unsafe-inline`,
`unsafe-eval`, external script or uploaded-document script is authorized. The hash
is bound to the same request snapshot as the template. Safe rendered documents and
their sanitization keep their existing independent boundary.

Navigation uses visible labels, decorative verified Lucide icons, current-location
markers, a skip link and standard landmarks. The compact Menu remains an ordinary
details element if scripting is disabled, stays in document flow and can close with
Escape (returning focus to its summary) or an outside click. Desktop navigation is
always visible. No focus trap, overlay, hover-only route or required animation is
introduced. Theme and reduced-motion/forced-color preferences use local CSS.

Document and provenance links preserve only a bounded local retrieval context:
`/browse` or `/search`, route-specific filter/query keys and a validated result
document fragment. Schemes, hosts, backslashes, control characters, duplicate keys,
arbitrary paths and fragments are rejected. Query values are encoded, displayed
through autoescaping and cannot become markup or script. The context is a link,
never a redirect or server-side fetch. Changing a hierarchy filter keeps other
filters. Result anchors restore the selected document; individual filter chips
remove one condition while preserving the others.

Knowledge keeps Source and Area in the primary filters. MIME type, hierarchy and
disposition remain under More filters, expanded when one is active. This preserves
the baseline Area-to-document path without an extra disclosure action. The measured
journeys and evidence boundaries are recorded in
[S02 qualification](../qualification/cura-s02-shell.md).

About & Credits reads fixed local identity, publication receipt and packaged notice
texts. Public project links are explicitly activated by the user. Actual publication
time and the independently verifiable offline release kit follow ADR 0029; a missing
or invalid receipt never creates a NEW cue. The live page removes NEW on expiry using
both elapsed monotonic time and the wall-clock deadline. S09 owns the complete final
clock/cache/theme/input/native qualification matrix.

## Evidence boundary

Automated route/security/persistence tests, packaged-resource verification, browser
observation, assistive-technology observation and linguistic review are separate.
Current-layout retention does not qualify Preview. S01's historical native deferral
does not qualify these new surfaces; required observations retain their slice owners.
