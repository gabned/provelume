# Privacy and network baseline

The Provelume 0.2.0 development baseline can perform its implemented functions without an
external network connection after its runtime dependencies are installed. This describes the
checked-in development line, not a published 0.2.0 release.

The first slice includes no analytics, telemetry, CDN resources, remote fonts, external AI calls or hidden update checks. Source files are read locally and preserved into the selected Instance.

The Security/build-identity surfaces—`provelume build-info`, `GET /api/v1/build-info` and `/security`—read only metadata packaged with the installed runtime. They do not contact GitHub, Provelume Cloud, an update service or an AI provider. The returned verification object records `network_used: false` for this read operation.

The Instance-aware Privacy & Network Activity surfaces—`provelume network-status <instance>`, `GET /api/v1/security/network` and `/security/network`—read local configuration only. They enumerate the built-in update-check capability, configured Sources, and any connector/provider declarations. Filesystem Source paths are never returned. External HTTP(S) endpoints are shown only as safe origins, and declared data-category identifiers are shown only when configured.

The effective state is `local_only`, `external_access_allowed` or `attention`. The default schema-1 Instance is `local_only` with zero enabled external components. Enabled update checks without an endpoint, enabled external components while external access is disabled, malformed declarations and unknown component types are reported explicitly as conflicts.

This is configured-capability transparency, not traffic monitoring. `observed_activity.status: not_instrumented` means runtime traffic has not been measured. It must never be presented as a zero-traffic verdict. Reading any of these surfaces performs no network request and mutates no Instance state.

Package installation and container-image construction may require access to public dependency registries. Official release publication and external attestation verification also involve the selected distribution provider. That build/install/verification traffic is separate from runtime knowledge processing and from reading embedded identity.

Future connectors, update services and AI providers must be explicit operator choices and add their component type to the public declaration registry before they can be treated as understood. Runtime network-event auditing remains future work and must feed the same surface without collapsing configured capability into observed activity.
