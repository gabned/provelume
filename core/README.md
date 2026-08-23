# Provelume Core

`core/` contains reusable, instance-agnostic Provelume behavior.

The first executable slice implements public domain contracts, filesystem Instance storage, local filesystem ingestion, deterministic versioning/provenance and rebuildable full-text indexing. It has no runtime dependency on Nexus, GitHub or an external AI provider.

Core must not contain personal reference-instance data or paths, instance credentials, SaaS billing/tenant logic, or cloud-only dependencies required merely to run self-hosted Provelume.
