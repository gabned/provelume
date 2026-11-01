# Concordia: maintainer's production-PC qualification

## Maintainer decision, 1 November 2026

The maintainer explicitly resumed S01 and requested its inclusion with the
already prepared Concordia work. Provelume currently has one user: the
maintainer. He will perform the manual tests directly on his existing production
PC. This is the current product context and qualification profile, not an
assumption that multiple testers or a separate laboratory are available.

The recorded instruction is: "sblocca la s01 e mettila all'interno: farò i test
direttamente io in produzione sul mio pc, senza altre necessità. Ricorda che ad
oggi sono l'unico utente di Provelume".

For this integrated field candidate, Windows 11 Pro 25H2 on that PC is the
maintainer's selected environment. Separate Home/Pro machines, VMs, additional
accounts and external testers are not prerequisites. The earlier requests for
that infrastructure are superseded for this step. The broader support matrix
does not become qualified by this decision.

## One integrated candidate

The candidate combines accepted main/S02 with the complete original feature
histories, using normal Git merges:

- S01, PR #424: `a8d06543ab3506f661362fcdf8d634ab229d424e`, startup
  preparation, private readiness, ownership and recovery.
- S03, PR #429: `36208fc414e7ae8d75d5d4a2776d80bc9f5c67a8`, effective
  search inputs and recoverable calendar validation.
- S04, PR #430: `38e62bcd4b1fa9ac1b72cd2849a742a94b92b8f2`, optional
  offline OCR kit, dedicated frozen worker and release-chain composition.

The integrated PR and embedded build identity select the exact combined source
and installer. The existing installer and optional kit are built from that same
candidate; an old component's PASS does not attest the new artifact. The
application version remains 0.14.0/development until the final release-identity
workstream. This is the integrated candidate for the 0.15 campaign, not a claim
that all remaining Concordia slices have been implemented.

## Execution and evidence

S01 development is resumed for inclusion and maintainer field validation. Its
original PR-local BIND, historical source identities and diagnostic reports are
preserved. The integration has its own owner; it does not rewrite the original
feature owners or their evidence.

Automatic checks run on the combined source and its actual package. Conflicting
search/startup behavior is tested together: initial and invalid searches avoid
the deep archive summary, executable searches retain the existing checks, and
both ordinary startup and explicit OCR dispatch remain available.

Manual desktop/browser/Windows observations are **ASSIGNED_TO_MAINTAINER /
NOT_RUN** until he performs them on the production PC. This decision removes the
separate test-environment prerequisite; it is not a fabricated observation or a
PASS receipt. Original CPU findings and other incomplete automatic observations
remain reported with their actual outcomes. Formal main acceptance and public
release publication retain their own recorded status.

The practical manual paths are normal Panel launch, Search/About and return,
Stop/Restart/Quit, and recovery while preparation is pending. Existing preferences,
Instance identity and Originals remain authoritative. The maintainer uses the
ordinary installer and application; system Python and a development checkout are
not application requirements. Optional OCR provisioning changes no Source consent
and does not enable a new automatic trigger or historical backlog operation.

The assistant prepares and verifies the candidate using synthetic local/CI data.
The maintainer performs the production-PC installation and manual observations.
Results may be recorded against the exact embedded source/Setup identity without
requiring private filenames, document contents, paths or credentials in GitHub.
