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

Custodia's [S04 lifecycle contract](docs/architecture/ai-model-lifecycle.md) distinguishes
governed artifact metadata from real runtime qualification. Use only tiny synthetic fixtures
for registry/install/update tests; never commit model weights or substitute their success for
S05/S09 model evidence. Run the executable demonstration, complete native checks and existing
S01–S03/SSRF regressions. Preserve actual local-host failures in the sole owner ledger and use
the accepted independent native Linux/Windows qualification route where applicable.

For S06 run `python scripts/demonstrate_ai_jobs.py` in the native virtual environment;
see the [durable execution contract](docs/architecture/ai-durable-jobs.md). It includes
real process contention, crash injection and portable recovery with public fixtures.
For a paired synthetic polling profile, run `python scripts/profile_ai_job_polling.py`
alone without other tests/builds. That profile is not real-model qualification.
The demo also verifies warm prefix divergence, shortening, generated-tail removal,
Instance isolation and closed failure on invalid native truncation. Native S06 warm
samples use changed public document content/bindings, not only identical prompts.
Real governed candidate execution runs separately under the existing native CI
observer. Keep all full-suite, S01–S05, SSRF and lifecycle gates; never substitute a
synthetic PASS for actual runtime/network qualification or change ADR 0031 thresholds.
