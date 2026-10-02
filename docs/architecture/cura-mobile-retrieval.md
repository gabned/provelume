# Cura S07: mobile reference paths and scoped retrieval

Owner issue: #301. Parent: #255. This is implementation design, not delivery evidence.
Package/runtime remains 0.10.1. S08 owns governed catalogs; S09 owns final integrated
qualification and default activation.

Capture admission, acquisition, pairing, outbox and idempotency retain S06 authority.
No companion introduces its own durable queue. iOS Share Sheet uses a bounded Shortcut
that submits the S06 JSON envelope, retains the same UUID for uncertain acknowledgement,
and consults that device's authoritative receipt before retrying. Android ACTION_SEND
uses the same protected transport and envelope. Both require explicit pairing and the
configured trusted HTTPS destination; neither receives general Knowledge permissions.
Camera/file selection continues through Capture, with limits and interruption recovery.
The already configured watched Drive-drop Source remains an explicit no-app fallback;
this slice neither consents to Google again nor changes the connector's read-only scope.

Retrieval is separately granted by the local owner to an already paired device, for
an explicit bounded set of existing Sources and a limited expiration. Capture credentials
alone cannot retrieve Knowledge. Grants bind Instance, origin, device and expiry, retain
revocation/audit and fail closed after import without the existing host key. Rebinding
or revoking the device invalidates retrieval. Every request rechecks the current grant,
and responses recheck authorization after reading to reject mid-request revocation.

Recent acquisitions and literal bounded full-text search filter by authorized Sources
before limiting results. Safe detail presents inert text plus exact versions, Original
hashes and bounded Acquisition/provenance data. No remote locator, private operational
configuration, active HTML, PDF embed or automatic Original fetch is exposed. Download
requires a separate explicit action, authorizes the exact DocumentVersion and verifies
stored bytes against canonical size/hash. It returns an attachment with no-store,
nosniff and restrictive security headers. Missing or unavailable content stays visible.

Retrieved content and retrieval credentials are memory-only in the reference browser.
The existing worker allowlists public shell assets only; authenticated routes, queries,
API responses and Originals never enter its cache or the Capture outbox. Leaving,
forgetting, session expiry or failure clears rendered knowledge. Explicit downloads
are user-requested copies outside the default cache guarantee.

LAN/trusted network/VPN and explicitly configured hardened HTTPS boundaries stay visible.
No cloud relay, new public service, paid resource or automatic network configuration.
No automated or emulated test certifies actual iOS/Android or native Windows observation.
Final evidence must enumerate automatic, browser, native and linguistic status separately.
