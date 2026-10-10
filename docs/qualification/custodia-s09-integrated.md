# Custodia S09 integrated qualification

[Owner #335](https://github.com/gabned/provelume/issues/335) follows accepted S08
at main `8b2403a091f927debd3718ba3ae0ea90ece657ee`.
[ADR 0052](../adr/0052-custodia-integrated-lifecycle.md) fixes the integrated design
before scoring. This is development evidence, not a published release or model
promotion. The package remains 0.11.0 until the separate release-preparation change.

| Required observation | Current S09 status |
| --- | --- |
| Inherited 26 real-runtime gates, both observed platforms | Run 38053390064 FAIL: model-hash authority overhead violates timing; engineering correction fixed in ADR 0052, new observation PENDING |
| Genuine Windows PDF dependency resolution, other pins retained | Windows run 38049242831 PASS; exact proposal applied, pypdf 6.20.0; final installer PENDING |
| Native install/import, exact verification and cancellation | Windows installed offline import PASS at 8f0690f; public network transfer PENDING; source cancellation regressions PASS |
| Global network revocation across restart and acquisition | Restart, global/component separation and zero-transport-denial regression PASS; installed transfer PENDING |
| Ordinary installed Windows AppContainer, creation-time Job and parent lifetime | Run 38053390090 PASS at 8f0690f; expanded 32-document ordinary HTTP path PENDING |
| Non-root Linux/container install, offline execution and persistence | Source image build and 12 GiB/4 CPU non-root admission PASS; 4 GiB correctly refused; full offline lifecycle PENDING |
| Both native resource trees, notices/SBOM and independent offline reconstruction | Both closed inputs ship in actual installer; source SBOM regressions PASS; run 38053390387 independent composition FAIL, corrected clean-source rebuild PENDING |
| Guided setup, freshness, explicit consent and retired-model removal | Source regression PASS; final artifact/browser observation PENDING |
| Backup/restore/export/import, disable/remove/rollback and crash recovery | Source orphan crash/explicit quiescence/cleanup and stale-action regressions PASS; integrated matrix PENDING |
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
The frozen Windows worker's later installed observation is recorded below. Each
new S09 configuration identity is fixed in ADR
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

## Retained integrated observations

On commit `8f0690f61fad360ca885b3eb2ebf9d377542925a`, installed Windows
[run 38053390090](https://github.com/gabned/provelume/actions/runs/38053390090),
job 114216886818, attempt 1 passed offline import, self-test, activation,
independent AppContainer token inspection and actual parent-process termination.
Artifact 11670287749 has archive SHA-256
`bb9d316f2936bd8362f73a4a57cbda62f029731ff15057090f29ec91ab823baf`.
The original harness checked eventual worker exit; its expanded successor also
requires an observed **live** process handle immediately before killing the parent.
It adds all 32 unchanged public document cases through ordinary forms, explicit
consent, the scheduler and persisted result/citation views. No adapter replacement.

Retain the three earlier installed failures at Win32 process creation, recorded
in ADR 0052, and both separate failures on 8f0690f: native timing run 38053390064
and offline composition run 38053390387. The latter built byte-identical candidate
wheel/sdist and a working Windows package, but the separate source composition
did not match. Candidate source gates populate ignored `.agent/` caches; the
independent runner does not. Both build lanes now materialize the exact reviewed
Git archive before composition, exclude temporary caches/acquisition ZIPs, and
retain failed rebuild reports. The composition comparison remains mandatory.

Working-source regressions passed 293 tests (one platform skip), covering native
verification deadlines/cancellation, model stores, guided setup, private synthesis
recovery, native SBOM and independent packaging. A real disposable producer
process exits immediately after writing a private body; cleanup remains denied
until the original owner explicitly reconciles quiescence. Cleanup then removes
only that body, leaving jobs, receipts, unknown usage and Originals unchanged.
An absent job, live lease, unreconciled outcome, changed body/authority or symlink
is not deletion permission. Failed input previews preserve the current document,
supported task/language, safe selection and a fresh form nonce without consent.

The non-root image includes the closed native pair and no weights. Its separate
model volume survives recreation; the permanent offline lifecycle workflow must
observe that claim before acceptance. Managed-cloud build/admission observations
do not imply that a model was run there. Container HTTP qualification uses actual
in-container loopback and does not broaden privileged remote administration.
