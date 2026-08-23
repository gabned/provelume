# Privacy and network baseline

Provelume 0.1 can perform its implemented functions without an external network connection after its runtime dependencies are installed.

The first slice includes no analytics, telemetry, CDN resources, remote fonts, external AI calls or hidden update checks. Source files are read locally and preserved into the selected Instance.

The Security/build-identity surfaces—`provelume build-info`, `GET /api/v1/build-info` and `/security`—read only metadata packaged with the installed runtime. They do not contact GitHub, Provelume Cloud, an update service or an AI provider. The returned verification object records `network_used: false` for this read operation.

Package installation and container-image construction may require access to public dependency registries. Official release publication and external attestation verification also involve the selected distribution provider. That build/install/verification traffic is separate from runtime knowledge processing and from reading embedded identity.

Future connectors, update services and AI providers must be explicit operator choices. A dedicated Privacy & Network Activity surface will enumerate configured external capabilities, endpoints, data categories and recent relevant activity before networked integrations become part of the normal runtime experience. The current Security page is a first transparency surface, not yet a complete network-activity monitor.
