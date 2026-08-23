# Provelume Core

`core/` is reserved for reusable, instance-agnostic Provelume behavior.

Core must not contain:

- personal Nexus data or paths;
- instance credentials or deployment state;
- website/SaaS billing, marketing or tenant-control-plane code;
- assumptions that a specific private repository exists;
- cloud-only dependencies required merely to run self-hosted Provelume.

During the clean-room bootstrap this directory intentionally contains only the public boundary contract. Implementation will be introduced incrementally from public requirements rather than copied from the private reference instance.
