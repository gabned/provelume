# Custodia S09 integrated qualification

[Owner #335](https://github.com/gabned/provelume/issues/335) follows accepted S08
at main `8b2403a091f927debd3718ba3ae0ea90ece657ee`.
[ADR 0052](../adr/0052-custodia-integrated-lifecycle.md) fixes the integrated design
before scoring. This is development evidence, not a published release or model
promotion. The package remains 0.11.0 until the separate release-preparation change.

| Required observation | Current S09 status |
| --- | --- |
| Inherited 26 real-runtime gates, both observed platforms | Runs 38057680589/38058512132: 26/26 PASS each platform; subsequent 38059042758: Windows PASS, Linux S08 warm-first 5.646 s FAIL; revised hash-loop polling in ADR 0052 requires fresh qualification |
| Genuine Windows PDF dependency resolution, other pins retained | Windows run 38049242831 PASS; pypdf 6.20.0; candidate installer/rebuild run 38056161287 PASS |
| Native install/import, exact verification and cancellation | Installed run 38056161111: actual HTTPS acquisition, revoke/cancel, verification, removal and offline import PASS; revised configuration PENDING |
| Global network revocation across restart and acquisition | Source regressions and actual installed transfer denial/revocation in run 38056161111 PASS; revised configuration PENDING |
| Ordinary installed Windows AppContainer, creation-time Job and parent lifetime | Run 38056161111: all 12 named checks PASS, including 32/32 gold, token, live-worker parent death and ordinary HTTP restart Off without replay; revised configuration PENDING |
| Non-root Linux/container install, offline execution and persistence | Runs 38058512159/38059042705 PASS, including actual HTTP restart, 32/32 gold and separate model persistence; 38057680651 failure retained; revised configuration PENDING |
| Both native resource trees, notices/SBOM and independent offline reconstruction | Run 38056161287 PASS, including complete assembly/offline verifier; original composition failure retained |
| Guided setup, freshness, explicit consent and retired-model removal | Source and production browser regression PASS; artifact-bound human observation PENDING |
| Backup/restore/export/import, disable/remove/rollback and crash recovery | Source crash/quiescence/stale-action regressions PASS; synthesis extraction, actual restore and same-Instance portable import PASS; newer liabilities and foreign-Instance refusal retained |
| Immutable 0.10.1/0.11 Windows upgrade inputs | Run 38056161287 PASS for 0.10.0, 0.10.1 and 0.11.0; final 0.12 version transition is separate |
| Seven-catalog browser, keyboard, pointer/touch, zoom/reflow and themes | Production-source 28836df: 402 observations PASS, zero page errors, including real 200% zoom and inline consent labels; unchanged UI dependencies only, human artifact review separate |
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

On `9056b2c8faadb46618b6e4bb00e4ba02a33c417f`, installed Windows run
[38055192806](https://github.com/gabned/provelume/actions/runs/38055192806)
passed all 32 ordinary document cases, eight required abstentions and a live
AppContainer worker's parent-death check (0.125 seconds). Artifact 11671805665
has archive SHA-256 `92eadd78beca05f5c85240cca3a5ae84552d61ee7022d7c73a81aaeeae007c22`.
Non-root container run
[38055192869](https://github.com/gabned/provelume/actions/runs/38055192869)
passed the same corpus and Linux pidfd parent-death observation (0.235 seconds),
with a read-only root, no external network, dropped capabilities and separate
Instance/model volumes. Artifact 11670996024 has archive SHA-256
`7fb610527eda2f47a5c893c52b4f0e4aaaecf0280c6fdf9f0defd06b43fc6f86`.
Those original restart checks constructed the setup owner; later harnesses require
an actual ordinary HTTP service restart, no worker and an unchanged job journal.
Neither original run is evidence of the subsequent actual HTTPS acquisition test.

Release dry run
[38056161287](https://github.com/gabned/provelume/actions/runs/38056161287)
passed build, independent offline reconstruction, Windows upgrades and assembly.
Its source is PR merge candidate `64743729d60bbe4fc545cea733c8f1ab7513f045`,
parents accepted main `8b2403a` and head `ff562b2`; it is not an actual-main merge.
Independent rebuild artifact 11671296445 has archive SHA-256
`6fcf9cdd96d4809915adcd62ca5f9b036f8048763c168cdb50a916c08c1a7c68`.
The identical wheel/sdist include the exact 12 native members, 19,333,560 bytes,
lock and notices without model weights. Both jobs use separately provisioned
runners from the same CI provider; this does not claim an independent provider.
Windows artifact 11670928063 has archive SHA-256
`4de5d3c979429e84b6669cdc050ca233b2c09c66da5fecc5e945678dbd15eec4`.
All three immutable baseline upgrades preserve their complete public Instance
tree fingerprints through startup, reinstall and uninstall, with one AppId,
preserved shell settings and disabled default automation. Seven-language DPI
probes pass; subjective appearance and Windows 10 22H2 remain unobserved.

The 034a7ef browser matrix uses actual production templates, CSS and scripts,
with public synthetic stored-result fixtures and no inference claim. It covers
both layouts, all seven catalogs, three themes, 1280/390 px, real browser 200%
zoom, touch, no JavaScript, forced colors and reduced motion. All 402 observations
pass without page errors. Retain the first navigation-timeout attempt and a
later harness assertion made before the error-response DOM was ready; explicit
navigation synchronization resolves the latter with the same production source.
These automated observations do not establish human screen-reader or linguistic
approval. The installed lifecycle workflow retains its exact successfully
exercised installer and identity reports for that final, artifact-bound review.

The later `f09d39d` unchanged-source checkout passes 3,969 tests (38 skips),
Ruff and diff checks. Its native Windows run passes all 26 gates, while Linux
EPYC 7763 retains the 5.646-second S08 warm-first failure described in ADR 0052.
The revised 100 ms read-loop configuration passes 143 focused cancellation,
deadline, source/consent, setup, network and synthesis/job regressions. In a
separate engineering-only 128 MiB inert-file study using the public 32-document
authority graph, alternating 20/100/100/20 ms reads took 0.439/0.261/0.289/0.422
seconds, with 12/4/5/12 complete probes and unchanged full hashes. An earlier
study run overlapped the test suite and is retained separately; it is not a
controlled timing comparison. Neither study runs native inference or supplies
qualification for the new execution configuration.

The ready-for-review check subsequently found that Generate renewed local proof
for every hybrid configuration, including an external primary whose local
fallback was already unavailable in the consent preview. The correction selects
the frozen primary route's actual configuration before renewing local evidence.
Four reproductions failed before the change; regressions cover absent and expired
local proof, an installed but expired model, and loss of a previously eligible
fallback. The last case still requires a new preview rather than silently restoring
fallback authority. Local and local-first hybrid previews retain explicit renewal.
Remote qualification in these regressions is test-owned synthetic evidence; no
live external provider is newly qualified.

On 2026-10-10 the maintainer explicitly instructed: "salta narratore e passa a
pubblicare la prossima versione". This supersedes the pending human handoff for
this release. Narrator remains NOT_RUN, and unobserved human linguistic or visual
checks remain UNVERIFIED. The [decision record](https://github.com/gabned/provelume/pull/336#issuecomment-6099628733)
authorizes proceeding through normal integration, actual-main qualification and
the separate official 0.12 publication workflow; it does not turn skipped checks
into successful observations or relax automated acceptance gates.


## Subsequent fixed-threshold observations

On `57544c475e8f726d11ac258659122db238f0ed74`, native run
[38068333064](https://github.com/gabned/provelume/actions/runs/38068333064)
passed all 26 Windows gates. Linux EPYC 9V74 passed 24, including every model
quality/reference/abstention check, but failed the two concurrent-Capture timing
gates. Capture took 0.944434 s against 0.476050 s in S05, and 0.499871 s against
0.417535 s in S08. S08 warm first response itself passed at 2.448230 s.
The subsequent diagnostic showed substantial fsync time, but did not observe a
live worker for its labelled busy rows; it cannot establish causal attribution.
The original report and failures remain retained. No threshold, corpus, runtime
lock, model or execution-configuration identity is changed by the follow-up.

Public CI [38068333058](https://github.com/gabned/provelume/actions/runs/38068333058)
failed one Windows synthetic HTTP job before dispatch (`ai_execution_blocked`).
Its internal exception was not captured, so the precise cause remains unknown.
A diagnostic rerun passed that group, but the aggregate correctly rejected the
incomplete current-attempt pair. Groups from different attempts are not combined;
a complete new run is required. Twenty unchanged Linux repetitions passed.

Inspection found a separate reproducible journal-reader hazard: the default
Windows CRT handle prevents atomic replacement while a UI reader holds the file.
Journal reads now explicitly permit delete sharing on Windows, retaining the
already-open file snapshot and closing the descriptor even after a decoding error.
Writes retain their original locks, fsync and atomic replacement. The regression
keeps the reader open until the writer completes; its Windows-only negative control
uses the original CRT handle and requires an actual sharing failure. The change
does not claim to prove the unknown CI exception. An exclusive reader-lock approach
was rejected because an existing regression showed that it blocked navigation.

The unchanged 57544c4 local suite retained 3,973 passes, 38 skips and one failure:
a pre-cancelled Tesseract request returned engine-unavailable after probing the
engine. Its isolated rerun passed, but a deterministic no-process regression failed
before the correction. Recognition now honors an existing cancellation before any
capability subprocess or temporary output is started; ordinary deadlines and
in-flight cooperative cancellation remain unchanged. New exact-head checks are
required for both corrections before integration and release preparation #337.


The subsequent 4282568 Windows Core run
[38070550111](https://github.com/gabned/provelume/actions/runs/38070550111)
passed the original synthetic HTTP path and group 0, but the new real Windows
snapshot regression exposed a limitation: delete sharing alone did not allow
`os.replace` to replace an open target (WinError 5). That candidate is not qualified.
The correction closes the complete byte snapshot before JSON decoding and permits
only a bounded 200 ms retry of the identical atomic rename for Windows sharing/
access-denied errors. Other errors retain immediate failure; no write transaction
or inference is replayed. A real Windows negative control keeps the old CRT handle
open and must still fail, while a second test releases a transient reader after an
observed native conflict and requires successful replacement. Search remains
available while the journal's mutation lock is held. The superseded local full
suites were interrupted after this native finding; they are not successful checks.
