# Provelume Instance

`instance/` contains the public self-hosted distribution layer around Provelume Core: example configuration, container/deployment manifests, adapters and operator-facing defaults.

An Instance may depend on released Core components. Core must never depend on a specific Instance.

No real user data, credentials, private hostnames, private paths or private reference-instance state may be committed here. Configuration committed to this directory must be safe example material.
