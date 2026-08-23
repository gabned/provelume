# Privacy and network baseline

Provelume 0.1 can perform its implemented functions without an external network connection after its runtime dependencies are installed.

The first slice includes no analytics, telemetry, CDN resources, remote fonts, external AI calls or hidden update checks. Source files are read locally and preserved into the selected Instance.

Package installation and container-image construction may require access to public dependency registries. That build/install traffic is separate from runtime knowledge processing.

Future connectors, update services and AI providers must be explicit operator choices and will be represented in a dedicated Privacy & Network Activity surface before they become part of the normal runtime experience.
