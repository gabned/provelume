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

Connector definitions and instances introduced by `0.7/S01` are explicit local declarations and
appear on this surface without resolving an address or exposing an external credential reference.
Their configured network mode remains subordinate to `network.external_access`. Future connector
transport, update services and AI providers must remain explicit operator choices and add their
component type to the public declaration registry before they can be treated as understood. Runtime
network-event auditing remains future work and must feed the same surface without collapsing
configured capability into observed activity.
