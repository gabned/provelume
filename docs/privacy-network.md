# Privacy and network baseline

The Provelume 0.2.0 local runtime can perform its implemented functions without an external
network connection after its runtime dependencies are installed.

The first slice includes no analytics, telemetry, CDN resources, remote fonts, external AI calls or hidden update checks. Source files are read locally and preserved into the selected Instance.

The Security/build-identity surfaces—`provelume build-info`, `GET /api/v1/build-info` and `/security`—read only metadata packaged with the installed runtime. They do not contact GitHub, Provelume Cloud, an update service or an AI provider. The returned verification object records `network_used: false` for this read operation.

The About surfaces—`provelume about`, `GET /api/v1/about`, `/about` and the Windows launcher
dialog—are also offline. They describe that an update capability exists without invoking it.

`provelume check-updates`, the Windows **Check now** action and a launcher startup check explicitly
enabled by the user are the first built-in operations that make a network request. The initial
transport contacts GitHub Releases over HTTPS, sends no Instance content, and is separate from
ordinary Core use. Startup checking is disabled by default. Downloaded installers are bounded and
checked by size/SHA-256, but the unsigned preview does not independently authenticate its publisher.
When startup checking is enabled, the launcher records the `https://api.github.com` origin in the
selected Instance's declared capability inventory and sets both `network.external_access` and
`network.update_checks` to `true`, so `/security/network` does not hide or contradict that policy.
Disabling startup checking sets both flags back to `false`. A startup worker also rechecks both
flags locally and fails closed before making a request if they are not enabled.

The Instance-aware Privacy & Network Activity surfaces—`provelume network-status <instance>`, `GET /api/v1/security/network` and `/security/network`—read local configuration only. They enumerate the built-in update-check capability, configured Sources, and any connector/provider declarations. Filesystem Source paths are never returned. External HTTP(S) endpoints are shown only as safe origins, and declared data-category identifiers are shown only when configured.

The effective state is `local_only`, `external_access_allowed` or `attention`. The default schema-2
Instance is `local_only` with zero enabled external components. Enabled update checks without an
endpoint, enabled external components while external access is disabled, malformed declarations
and unknown component types are reported explicitly as conflicts.

This is configured-capability transparency, not traffic monitoring. `observed_activity.status: not_instrumented` means runtime traffic has not been measured. It must never be presented as a zero-traffic verdict. Reading any of these surfaces performs no network request and mutates no Instance state.

Package installation and container-image construction may require access to public dependency registries. Official release publication and external attestation verification also involve the selected distribution provider. That build/install/verification traffic is separate from runtime knowledge processing and from reading embedded identity.

The optional `0.9/S02` OCR path is a local-only runtime capability. Its capability report and every
request/run/bundle record state `network_required: false`, `runtime_downloads: false` and
`remote_fallback: false` as applicable. Provelume never installs Tesseract, a language pack,
pypdfium2/PDFium or Pillow while probing or processing a document. Operator installation and the
explicit CI provisioning step may use package repositories; that traffic is outside OCR runtime.
Enabling OCR therefore does not enable `network.external_access` and does not add a provider origin.

The unreleased `0.9/S03` local email path has the same explicit offline boundary. Creating a local
email Source stores one operator-selected EML file or Maildir path in local configuration, leaves
the Source disabled and performs no probe, enumeration or intake. Capability discovery, exact-byte
reads, MIME parsing, body selection, attachment extraction, durable replay, derived removal/rebuild
and read-only inspection set `network_access: none`, make no DNS or socket call and have no remote
fallback. Enabling the Source or scheduling explicit local intake does not enable
`network.external_access` or add a provider origin.

Email HTML and MIME observations are untrusted input. Provelume does not render active HTML, follow
links, resolve `cid:` references, submit forms, load remote CSS, images, avatars or tracking pixels,
execute attachments or expand archives. There is no HTML-to-text fallback in the S03 baseline: when
an acceptable bounded `text/plain` body is unavailable, the exact HTML remains only in the message
Original and the derived body is explicitly unavailable. Attachment OCR eligibility is descriptive
only and never enables, queues or runs OCR.

The configured physical path is excluded from read-only API views, scheduler receipts and operation
records. The local CLI and CSRF-protected Browser configuration view may show the escaped path to
the operator. Operational records also omit subject, body, addresses, filenames and caller text,
retaining only opaque IDs, counts and closed codes. Explicit local detail views may show derived
message observations to the operator but never execute their content.
Gmail, Google Drive, IMAP, POP, SMTP, account/credential discovery and every remote-mailbox fallback
remain absent; Gmail/Drive are only the unactivated `0.9/S04` forecast.

Connector definitions and instances introduced by `0.7/S01` are explicit local declarations.
`0.7/S02` adds independent enabled/removed lifecycle state: a disabled or tombstoned connector is
never counted as an enabled external component even when its retained policy says `explicit`.
These declarations appear on this surface without resolving an address or exposing an external
credential reference. Their configured network mode remains subordinate to
`network.external_access`. The separate connector inventory may show the validated external
reference kind/name to the local operator, while secret-free operation evidence and the
privacy/network inventory omit it.

The `0.7/S04` connector web transport remains an explicit operator action behind the current
Instance, connector and Source gates. It performs no background access, proxy discovery or
credential fallback; its fixed typed failures omit URLs, tokens, paths and response content.
`0.7/S05` can persist a complete guarded response only after another current-policy check under a
short configuration lock. Its operation evidence retains opaque canonical IDs, safe status codes
and bounded metrics, never the requested/final URL, response body, credential reference or physical
path. This does not turn configured-capability transparency into traffic monitoring: runtime
network-event auditing remains future work and must feed the same surface without collapsing
configured capability into observed activity. Future update services and AI providers must likewise
remain explicit choices and add their component type to the public declaration registry before they
can be treated as understood.
