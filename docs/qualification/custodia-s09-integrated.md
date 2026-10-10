# Custodia S09 integrated qualification

[Owner #335](https://github.com/gabned/provelume/issues/335) follows accepted S08
at main `8b2403a091f927debd3718ba3ae0ea90ece657ee`.
[ADR 0052](../adr/0052-custodia-integrated-lifecycle.md) fixes the integrated design
before scoring. This is development evidence, not a published release or model
promotion. The package remains 0.11.0 until the separate release-preparation change.

| Required observation | Current S09 status |
| --- | --- |
| Inherited 26 real-runtime gates, both observed platforms | NOT_RUN for changed S09 execution; S08's separate baseline passed |
| Genuine Windows PDF dependency resolution, other pins retained | Windows run 38049242831 PASS; exact proposal applied, pypdf 6.20.0; final installer PENDING |
| Native install/import, exact verification and cancellation | Focused source regression PASS; real installed transfer/import PENDING |
| Global network revocation across restart and acquisition | Restart, global/component separation and zero-transport-denial regression PASS; installed transfer PENDING |
| Ordinary installed Windows AppContainer, creation-time Job and parent lifetime | NOT_RUN |
| Non-root Linux/container install, offline execution and persistence | NOT_RUN |
| Both native resource trees, notices/SBOM and independent offline reconstruction | NOT_RUN |
| Guided setup, freshness, explicit consent and retired-model removal | NOT_RUN |
| Backup/restore/export/import, disable/remove/rollback and crash recovery | NOT_RUN |
| Immutable 0.10.1/0.11 Windows upgrade inputs | NOT_RUN |
| Seven-catalog browser, keyboard, pointer/touch, zoom/reflow and themes | Initial production-source Chromium: 56 views PASS, zero page errors; final artifact, touch/zoom/forced-colors PENDING |
| Exact-artifact human screen reader and linguistic observations | NOT_RUN; prior S07 evidence is not extended |
| Specific live external provider | NOT_RUN; no credentials/cost authority supplied |
| Complete exact-head CI/reviews and actual-main reconciliation | PENDING |

Retain original failed and incomplete observations. Unchanged thresholds do not
transfer old qualification to a changed execution configuration. Record CPU, RAM,
OS, Python, native inventory and model/configuration/corpus digests for each actual
run. Observed hosted profiles do not establish performance on an unmeasured laptop.

The first implementation observation uses working source based on `0e553bb`,
not a clean final candidate: 238 focused model/runtime/setup tests passed (one
platform skip); 131 transport/setup/network tests passed; 12 Linux cgroup/pidfd
tests passed. The production browser exercised both layouts, 1280px/390px,
light/dark and seven languages, including keyboard menu dismissal and table
scrolling. These are bounded source observations, not release acceptance.
The frozen Windows worker is implemented but remains NOT_RUN until the ordinary
installer workflow observes it. New S09 configuration identity is fixed in ADR
0052 before native scoring. Full unchanged-candidate checks remain required.

Native Windows PDF resolution retained all unrelated pins. The proposed lock's
SHA-256 is `043db6eb8a25a13ec7103f0e7410b030b0ca3b72ef051d407c528ab715d03baa`;
the selected universal pypdf wheel is 401,710 bytes with SHA-256
`f003fc2014814d264fe7dd3f9d435c158e23e1a85a2233f87a0a2d6d21c914ad`.
The bounded 17-filter adversarial PDF is preserved as an Original and marked
extraction-failed, while valid 1/16-filter documents remain readable. This is
not a claim that all dependency advisories have been resolved.

The ordinary workflow must explicitly acquire or import the pinned model, verify
and enable local operation, preview exact bounded evidence, obtain consent, execute
through the existing scheduler, and expose cancel/disable/removal/recovery. Restart
and restored Instances remain Off. Deterministic capture, search and preservation
remain useful without AI. Private documents and credentials never enter public
qualification; only synthetic content is used.

The source-build correction for the old updater cannot alter already installed
0.10.1 code. Its schema-1 client needs one manual complete installation-kit upgrade.
Published v0.11 assets stay immutable. S09 candidate install identity and the final
0.11-to-0.12 version transition are separate observations.
