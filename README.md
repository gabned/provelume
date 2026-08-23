# Provelume

**Knowledge you can trace.**

Provelume is a provenance-first personal knowledge intelligence system for building durable, connected and traceable knowledge from files, email, web sources and other inputs.

This repository is the public, clean-room home of the reusable **Provelume Core** and the self-hosted **Provelume Instance** distribution. It does **not** contain the private Nexus reference instance, personal data, private product documentation or Nexus Git history.

## Status

Provelume is in pre-release development. Public APIs, configuration formats and packaging may change before 1.0.

## Product boundaries

| Area | Repository | Purpose |
| --- | --- | --- |
| Provelume Core + self-hosted Instance | `gabned/provelume` | Public source-available product code and public operator documentation |
| Nexus | `gabned/nexus` | Private personal archive and private reference instance |
| Official website + managed cloud/SaaS | `gabned/provelume.com` | Private website, control plane and cloud-specific code |

`provelume.com` must consume released/versioned Provelume Core artifacts; it must not vendor or copy the Core source tree.

## Repository layout

- `core/` — reusable, instance-agnostic product code. During bootstrap this contains boundary documentation only.
- `instance/` — public self-hosted packaging, configuration examples and deployment glue. No user data or secrets.
- `docs/` — documentation required to understand, install, operate and contribute to the public product.
- `.github/` — contribution policy and clean-room CI guardrails.

The private product roadmap, commercial strategy, research, licensing analysis, brand working files, cloud/privacy decisions and architectural decision records live outside this public repository in `gabned/nexus/Provelume/`.

## Principles

- provenance first;
- self-hosted and privacy-first;
- portable source data;
- reconstructable derived indexes;
- explicit source tracking;
- local processing where practical;
- cloud services optional for self-hosted users;
- no hidden dependency on the private Nexus instance.

## Clean-room rule

Do not copy private Nexus data, secrets, generated knowledge, private documentation, deployment state or Git history into this repository. New public implementation work must be created from public product requirements and sanitized interfaces. See [`docs/clean-room.md`](docs/clean-room.md).

## License

Provelume is **source-available**, not OSI open source. Non-commercial use is licensed under PolyForm Noncommercial 1.0.0. Commercial use requires a separate commercial license.

See [`LICENSE`](LICENSE) and [`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md).

## Website

The canonical product website is https://provelume.com.
