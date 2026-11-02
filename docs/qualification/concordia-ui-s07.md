# Concordia S07 — daily journeys and personal setup

Owner: `product/0.15-s07-ui-setup`, PRODUCT / REPOSITORY_POLICY, PR-local legacy.
Baseline: main `0f61868514e043fa5463f4958eaff992dc6e31ea`, accepted S01–S06
integration #433. Protocol source remains
`02317e02767958faa3de5bb6d245ca3440360d9e`; Lifecycle v2 remains deferred.
Application identity stays 0.14.0 / Entitas / development.

Scope is #379: Acquisizione, Sorgenti, Documento and the six personal setup
screens, consuming the existing preservation, OCR, review and scheduler services.
Decision K in `docs/architecture/concordia-step-0.md` governs progress, effects,
revision checks, readback and recovery. No setup draft grants replay authority.
S08 and the subsequent Concordia workstreams retain their ordered acceptance
and separate owners. No provider, mirror or final publication belongs to S07.

Source requirements: #379 comments 6241142182 (six screens and AC01–AC15),
6241608718 (T01–T48), 6245685981 (handoff), and the accepted step-0 contract.
Every new candidate result starts NOT_RUN. Automatic source tests, actual browser
observations, installed Windows tests and human observations are separate.

The maintainer is the sole user and will perform manual checks on his Windows 11
Pro 25H2 production PC. VMs, other accounts, Home machines and extra testers are
not prerequisites. Manual, screen-reader, linguistic and real 200% zoom results
remain ASSIGNED_TO_MAINTAINER / NOT_RUN until actually observed. This does not
qualify the wider historical Windows support matrix.

Implementation and qualification are in progress. No UI, runtime, accessibility
or integration PASS follows from this preparation record.
