# Contributing to Provelume

Provelume is developed as a public clean-room product while its original private reference instance remains in a separate private repository.

## Before contributing

- Do not submit personal data, credentials, private emails, generated knowledge stores, deployment state or files copied from a private Nexus checkout.
- Do not import Nexus Git history or preserve private commit metadata in patches.
- Base implementation work on public requirements, public interfaces and reproducible tests.
- Keep instance-specific configuration in `instance/`; keep reusable behavior in `core/`.
- Open an issue before substantial architectural work so the public contract is agreed before implementation.

## Licensing of contributions

The project uses a source-available / commercial dual-licensing model. A final contributor-rights process is still being defined. Until it is published, maintainers may decline or postpone non-trivial external code contributions that would make future commercial licensing ambiguous.

Issues, documentation corrections and design discussion are welcome during this bootstrap phase.

## Pull requests

Pull requests should be focused, explain the public requirement they satisfy, include tests when executable code is added, and pass all required repository checks.
