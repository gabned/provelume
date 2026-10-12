# Cura functional audit and AI completion (#339 / #340)

Baseline: accepted main `1ed289e6cacbc08c4425d461dfce72e37fe0ca30`, published 0.12.0.
This updates the [Cura S01 inventory](cura-s01-baseline.md) and existing
[information architecture](../architecture/cura-information-architecture.md).
The changes belong to **Unreleased**, requested together for the next release;
its number and release activation remain to be determined. Package identity stays
0.12.0 until separately qualified release preparation. No forecast is renumbered.

The matrix inventories existing user journeys, not every internal API mutation as
a separate feature. Presence/reachability does not establish that a missing model,
account, component or permission is installed/authorized. **S** means source
inspection; **H** rendered HTTP/contract tests; **B** actual browser interaction.
Candidate test/browser results are recorded separately in the owner PR. No private
user paths, documents or screenshots enter the audit.

## Functional matrix

| Task | Cura entry / route | Presentation and actions | Finding / disposition |
| --- | --- | --- | --- |
| Overview | Overview `/` | Native Cura status/recent documents/next action | Present (S/H) |
| Knowledge | Knowledge `/browse` | Native filters, hierarchy, disposition and specialized views | Present (S/H); advanced tools remain disclosed |
| Search | Search `/search` | Native query/filter and document context | Present (S/H); AI round-trip lost context, now corrected |
| Reading / provenance | `/documents/{id}` and provenance link | Shared viewer, original download, versions and source trace | Present (S/H); authoritative data independent of layout |
| Capture / intake | Capture `/inbox` | Shared import/capture and pairing entry points | Present (S/H); paired mobile PWA remains separately authenticated |
| Sources / connectors | Management `/sources`, `/connectors`, `/google/connect` | Shared existing intake and explicit Google connection | Present (S/H); real accounts not exercised |
| Email | Knowledge → specialized views `/email` | Shared supported intake/review | Present (S/H); no future connector implied |
| OCR / transcripts | Specialized views `/ocr`, `/transcripts` | Shared extraction/evidence workflows | Present (S/H); components remain a prerequisite |
| Media / file families | Specialized views `/photos`, `/audio`, `/video`, `/file-families`, `/perceptio` | Shared galleries/players and bounded representations | Present (S/H); existing 0.12 readable task cards retained |
| Bundles / duplicates / representations | Specialized views `/bundles`, `/duplicates`, `/representations` | Shared knowledge tools | Present (S/H) |
| Placement / text corrections | Document → `/review/decisions/placement/{id}`, `/review/annotations` | Shared reviewed decisions and corrections | Present (S); existing qualified workflows retained |
| Attention / operations | Needs attention `/attention`; Management `/operations`, `/scheduler` | Cura grouping of Action Center and shared explicit job controls | Present (S/H); no second queue |
| Maintenance / recovery | Management `/maintenance/overview`, `/maintenance`, `/assurance`, `/rebuild` | Cura overview/shared backup, retention and recovery tools | Present (S/H); destructive actions retain plans/consent |
| Components / diagnostics | Management `/components`, `/security`, `/security/installation`, `/security/network`, `/knowledge-health`, `/qualification`, `/about` | Shared licenses, trust, privacy and diagnostics | Present (S/H); unavailable states remain truthful |
| AI configuration | Management → AI & Privacy `/settings/ai` | Shared local/import and advanced provider settings | Previously reached through folder settings; direct entry added (S/H/B) |
| Model acquisition / lifecycle | AI & Privacy → guided setup / Advanced | Download/import, progress/cancel, verification/test and permitted remove/rollback | Snapshot-only gap fixed by read-only observer; fresh terminal actions (S/H/B) |
| AI session | AI & Privacy → current state | Shared explicit enable/pause/off | Present (S/H); operation completion refreshes displayed session state |
| AI document work | Document → `/documents/{id}/ai`, `/documents/{id}/synthesis` | Shared private preview, restrictions, explicit consent and synthesis | Present (S/H); originating search context now retained |
| AI results / evidence / receipts | Management `/operations/ai` and linked result/evidence | Shared existing result, discard/regenerate, source evidence and receipts | Direct Management entry added; context preserved (S/H) |
| Appearance / language / interface | Management `/settings/shell` | Shared explicit save, revision guard and receipt | Standard naming, guided upgrade and reversible choice (S/H/B) |
| Reset / transfer / notifications | Management `/settings/preferences`, `/settings/notifications` | Shared preview/confirm/import/reset/undo and notification controls | Direct entries added; existing transactions preserved (S/H) |
| Tray / installer updater | Native Windows shell | Deliberately native | Not a missing web renderer; installed qualification remains separate |
| Classification / Knowledge Objects / RAG / MCP | Future roadmap lanes | Not implemented capabilities | Remain future; no dummy menu or delivery claim |

Ordinary server-rendered page templates use the selected base layout. No existing
task family was found to require the previous renderer. This is a source and
reachability conclusion, not manual observation of every state/action/device.
Current remains a presentation-only rollback. The finite correction scope is live
model progress, direct Management links, AI retrieval-context continuity and guided
standard-interface adoption; no missing task family requires a second renderer.

## Progress and authorization boundaries

`/settings/ai/model/status` observes only the displayed running operation and checks
local access, service-session and operation identity. Reads do not acquire, hash or
load model weights, probe providers or authorize AI. Terminal responses supply
escaped server-rendered operation actions/session status. Unrelated fields and
focus remain intact.

Polling has one request at a time, timeout/backoff, hidden-page pause, page-exit
abort and terminal stop. Stale identity requires manual refresh. Bytes are readable;
reaching the artifact size shows indeterminate verification, not false completion.
The cancellation nonce renews at most once per five minutes/operation so long
downloads remain cancellable without evicting other forms on every observation.
Connection-observation errors are distinct from actual operation failure.

## Default and reversible upgrade matrix

| Starting condition | Behavior | Reversal / preservation |
| --- | --- | --- |
| Fresh settings | Cura, the existing default | Explicit Previous interface save |
| No shell manager | Cura presentation fallback | Rendering creates no preference file |
| Schema 1/2, no selection evidence | Previous layout plus guided choice | GET never migrates; existing explicit transaction |
| Schema 3/4 Current, no receipt | Same guided choice; provenance remains ambiguous | No assumed deliberate selection |
| Explicit Current receipt | Keep Previous interface; no repeated offer | Cura remains available in settings |
| Explicit Cura receipt | Keep Cura | Save Previous interface to record rollback |
| Restart | Saved selection/receipt retained | No new AI/network authority |
| Preference import/reset/undo | Existing preview/confirm rules; reset uses current defaults | Existing undo restores the earlier payload |

Without a receipt, inherited and externally selected Current cannot reliably be
distinguished. The user chooses once; explicitly keeping Current also records a
receipt and dismisses the notice. Knowledge, selected Instance, language, theme,
notifications and AI permissions remain outside this presentation choice.

## User path for the next release

1. Open **Management → AI & Privacy**. Explicitly allow network access if downloading,
   or use offline import. Start acquisition and follow its automatic progress.
2. After acquisition, explicitly verify/enable local AI. Download completion does
   not enable it, and AI returns off after service restart.
3. From **Knowledge** or **Search**, open a document and choose **Document synthesis**.
   Review text/scope/consent before execution. Find AI results/receipts in Management.
4. On an older installation, follow the interface notice or open **Shell settings →
   Interface**, select **Cura · standard interface** and save. Select **Previous
   interface** in the same location to return. Other open pages change on navigation
   or reload; no service restart is needed.

## Verification scope

`tests/test_cura_ai_completion.py` covers read-only progress, identity, cancellation
nonce renewal, terminal actions, exact CSP/SRI, seven-language destination
reachability, search round-trips, schema 1–4 upgrades, real form selection/rollback,
restart, preservation and absent-manager fallback. Existing AI setup/synthesis,
Cura reset/import/undo and catalog tests retain their authority/recovery coverage.

`tests/test_ai_model_progress_js.py` executes the shipped script with delayed
responses, backoff/recovery, stale identity, non-overlap, page hiding/exit/resume.
Actual Chromium evidence separately exercises DOM replacement, drafts/focus,
terminal errors/cancellation and responsive navigation using synthetic operations.

No live model acquisition/inference, real external account, new Windows installer
observation, human linguistic review or screen-reader attestation is claimed by
this audit. Native CI and final installed-release checks remain separate; previous
attestations are not extended to changed views.

## Warm-measurement precondition found after integration

PR #341 merged as `9d0ea66a6fbceaaee9ee5fca38b4e89e2edc7b9d` with its qualified
tree unchanged. Both Windows CPU attempts of run `38092776501` then failed only
`warm_first`: six intended warm samples actually reported `cold=true`, reaching
6.735 s and 7.984 s on two Intel runners. Candidate AMD measurements had no such
cold samples and passed. All original reports and failures remain authoritative;
neither a rerun nor this correction retroactively promotes them.
The second Intel attempt also had one genuinely warm `it02` result at 5.594 s,
above the unchanged 5 s limit. This is a real latency failure, not explained away
by the preparation correction; future native runs must still reject such a sample.

Full-file authority renewal can outlast the existing five-second idle timeout.
Qualification now records an explicit fixed synthetic preparation after renewal
and at the start of each corpus run, then measures every original corpus case.
All 60 scored samples must actually be warm. Each preparation remains in the raw
report, bound to the next case and the same worker, and must pass the existing
cold or warm time limits, model-load/RSS bounds and its fixed expected answer.
Missing or failed preparation blocks qualification. No outlier is dropped, no
threshold is increased and no product runtime, authority or idle policy changes.
Native qualification of the corrected measurement is recorded in its owner PR;
this does not extend a measured host's performance claim to other hardware.

## Follow-up #342: execution refusal and Capture I/O

The original `3c1a2b482395d6c7a5663a431c57ea43a9fd7ee4` qualification remains
failed. [CPU run 38095557507](https://github.com/gabned/provelume/actions/runs/38095557507)
passes all 27 Windows AMD gates, but Linux concurrent Capture takes 0.635 s in
S06 and 0.669 s in S07 against 0.449 s; S08 cold Capture takes 2.085 s against
0.557 s. Its 60 genuinely warm samples and six retained preparations pass, with
maximum first response 2.419 s. Search, citations, quality and abstention pass.

[Installed run 38095557425](https://github.com/gabned/provelume/actions/runs/38095557425)
fails its first `en-summary-facts` synthesis: one attempt, `ai_execution_blocked`,
`NOT_SENT`, 94 ms. The following 31 cases pass. Acquisition, model integrity,
self-test, independent AppContainer token observation, activation and explicit
enablement pass; parent death and restart were not reached. The original
`synthesis_quality` diagnostic is not evidence of a model-quality cause.
[Artifact 11686820875](https://github.com/gabned/provelume/actions/runs/38095557425/artifacts/11686820875)
and both job logs are retained; neither failure is retried or replaced.

The native adapter previously acquired the runtime ownership lock without waiting.
The idle timer uses that same lock while stopping its worker. A deterministic
interposition of idle cleanup reproduces a refusal before any preflight/inference;
the supervisor's existing bounded admission handles that state, but the adapter
bypassed it. This mechanism is compatible with the first-only installed refusal;
the original record does not preserve the provider code and cannot retrospectively
prove which refusal occurred. The adapter now reserves the sole request through
that same admission, waits at most the existing two seconds for cleanup, and checks
cancellation/deadline while waiting. Other requests still fail immediately. There
is no queue, repeated inference, added warm-up, idle-policy or model change.
Waiting consumes the original 60-second adapter budget as well as the job deadline.
Closed provider causes are now retained in the job while the receipt remains
generic. Installed qualification distinguishes execution failure from quality.

The retained Linux profile attributes a busy diagnostic Capture of 0.709 s to
49 fsync calls, with 0.502 s in fsync. Atomic journal preparation now overlaps
independent candidate/preimage writes with at most four I/O threads. Ordered
target replacement overlaps its directory flushes with the same bounded pool.
Every original file and directory flush still runs. All payload writers join
before the prepared marker; all target flushes join before the committed marker
or acknowledgement. Failures join pending work before rollback/removal, so no
late writer can race restoration. Candidate/preimage directories additionally
flush before preparation. Bounds, paths, digests, preimages and recovery remain
mandatory. Crash recovery still starts from the durable prepared journal.

Local focused checks: 346 passed, 16 skipped, plus five closed-cause/accounting
regressions passed. Three idle-admission cases fail before the correction. New
barrier tests cover delayed/failed publication flushes and failed preparation
with another writer still active, alongside existing interruption, tampering,
real-link/junction, Capture, consent and recovery tests. The sandbox's initial
HTTP runs were interrupted and retained after a blocking TestClient observation;
the diagnostic case passes when sandbox network access is enabled. These are
environment observations, not a promoted native qualification.
The first full local run retained one failure, 4030 passes and 40 skips: the
recovered virtualenv contained pypdf 6.19.0, below the declared minimum 6.20,
and accepted the adversarial 17-filter PDF. Canonical bootstrap installed 6.20.0;
no PDF code or test was relaxed. The dependency correction requires a fresh full
run on the final candidate, not promotion of that failed run.

That fresh local suite on `985827743a88336c4d2cd1093e28a5b1947c84a0` passed:
4036 tests, 40 skipped, 10 warnings. Its remote
[core CI 38125089333](https://github.com/gabned/provelume/actions/runs/38125089333)
retains failed Ubuntu Core and native workspace jobs. Both failures are in the
new regression's exact floating-point subtraction: `started + 60` is the actual
deadline, but subtracting retained starts 94.196329987 and 127.046597189 gives
60.000000000000014. The test now checks `deadline == started + 60` directly;
no product budget, responsiveness threshold or timeout is changed. Both failed
jobs remain FAIL; complete checks must qualify the correction's new head.

On that same `9858277` source,
[CPU run 38125089349](https://github.com/gabned/provelume/actions/runs/38125089349)
passes all 27 gates on Linux AMD EPYC 9V45 and Windows AMD Family 26 Model 2.
Each host records all 60 genuinely warm scored samples and all six preparations;
maximum warm first response is 1.956/2.094 s respectively. Linux Capture maxima
are 0.218 s S06, 0.217 s S07, 0.211 s S08 cold and 0.228 s S08 warm, with inference
observed. Linux/Windows artifacts 11697495799/11697375966 bind that source and
retain every sample. The
[non-root offline container lifecycle 38125089295](https://github.com/gabned/provelume/actions/runs/38125089295)
also passes. These observations do not qualify other hardware or the subsequent
test correction. The ordinary installed Windows cycle and complete exact-head
and post-merge evidence are recorded in the owner PR; pending or failed results
cannot be promoted through this audit.

The subsequent `e53f9afc55efb7527cd7a6a6d3f20ed371bb2da3` passes local full checks
(4036 tests, 40 skipped), all core CI and the offline container. Linux CPU passes
27 gates, including Capture maxima 0.249 s S06, 0.225 s S07 and 0.251 s S08 cold.
Its Windows Intel Family 6 Model 207
[CPU job 114432056336](https://github.com/gabned/provelume/actions/runs/38126572458/job/114432056336)
remains FAIL, with [artifact 11697878428](https://github.com/gabned/provelume/actions/runs/38126572458/artifacts/11697878428)
and log retained. It completes 26/27 gates: all 60 genuinely warm scored samples
pass (maximum first response 4.782 s), with ten retained preparations. The sole
failure is S05 `deterministic`: the third probe has `worker_observed=false`.
All three Capture latencies pass (maximum 0.109 s against 0.288 s), as do search,
S06/S07/S08, quality and references. This is missing concurrency evidence, not
an observed responsiveness-limit failure.

S05 used a fixed 20 ms sleep after starting its existing generation thread.
That cannot establish that the request has reached native inference: verification
and an idle reload can outlast it, or the operation may finish before the probe.
S05 now waits for the supervisor-validated `native_prefill` event of the current
request within the existing 20-second cold-first bound. It checks the same live
worker/request before and after the entire Capture/search flow and binds the
observed event to the completed inference's event and timestamps. All three
original probes and inference requests remain; a missing/late phase still keeps
its failed sample. Missing, stale, late or nonoverlapping evidence cannot pass,
nor can an incomplete or extra cohort. No preparation, retry, added inference,
changed product source, idle policy, corpus, latency limit or integrity relaxation
is introduced. Complete native checks must qualify this new measurement head.

The `9858277` ordinary installed Windows
[run 38125089297](https://github.com/gabned/provelume/actions/runs/38125089297)
also completes PASS: all 12 checks, 32 valid/gold syntheses with one attempt each,
including the first `en-summary-facts` (LOCAL, 18.422 s attempt). Independent
AppContainer/no-capability/no-loopback observation, parent death in 0.187 s and
restart with session off and no replay pass. Evidence artifact 11697886848 and
exact exercised development installer artifact 11697647473 remain bound to that
source. The original 94 ms refusal remains failed, with its causal limit above;
these results do not replace exact-head qualification of the measurement change.

The six unfiltered local synthetic Capture samples before/after have medians
0.090799/0.084574 s. These are development measurements without native inference,
not proof that Linux's acceptance gate passes. Complete unchanged-candidate
checks and native Linux/Windows/installed qualification remain binding. Current
outcomes and exact candidate/main identities are recorded in the owner PR #342;
integration remains blocked until those real checks complete. Changes remain
Unreleased, with no version assignment, tag or release publication.

## Reconciled completion and release follow-up — 11 October 2026

The preceding pending/blocked states retain their historical coordinates. #342 is
now merged as `854550fbddb3f0e9e2550e777e2cd708035e2498`; its qualified candidate is
`3847b0e1ca4e4c41aad4da5383d8107bc708b2d8`, with the same tree
`de424eb52f4b6b4915d414e78bcb84c7cdf1aa38`. The
[final owner audit](https://github.com/gabned/provelume/pull/342#issuecomment-6108892619)
records all 14 actual-main push workflows successful on attempt 1, 4048 tests
passed / 40 skipped, real CPU 27/27 gates per recorded host and installed Windows
12/12 checks / 32 valid first-attempt syntheses. The prior failures and all causal/
hardware/human limitations above remain unchanged. This paragraph reconciles the
functional audit; it does not rewrite old results or qualify unobserved hardware.

The exercised Windows artifact is development, not a release delivery. #340 stays
open for publication of this scope and #339 together. The separate
[Unreleased release preparation](unreleased-cura-ai.md) and
[Cura/AI guide](../releases/unreleased-cura-ai.md) bind the finite follow-up and
require qualification on the future official pipeline's own distribution installer.
No version, tag or publication is assigned here.

## Windows integration and release-owner resume — 12 October 2026

#344 is integrated by normal expected-head merge at
`df19f7b651855546eee43ec57be26f44196907d5`, tree
`7a36978342c7b5195682a2bd46f717b98e2e4197`, parents
`854550fbddb3f0e9e2550e777e2cd708035e2498` and
`d1456f6ba965813f644fc6084b61c5dd0e6f6807`. Its
[final audit](https://github.com/gabned/provelume/pull/344#issuecomment-6113855145)
records 18/18 PR workflows and 15/15 main workflows successful, all attempt 1;
main has 36 successful jobs and one inapplicable skip, suite 4049/45 and ordinary
installed Windows 32/32 first-attempt syntheses / 12 checks on Family 25 Model 1.
The 336 real frozen layouts across four upgrades have minimum contrast 7.1069.
The PR pipeline source was the distinct synthetic merge `c11bcd1`; the subsequent
main package binds `df19f7b`. Neither identifies the future release.

Windows now distinguishes **Apri Provelume** (browser) from **Pannello locale**
(native launcher), explains service actions, adapts layout to DPI and corrects
channel controls/menu in the dark theme. First-head Tk initialization failures
remain failed: the correction isolates every retained probe in its own process,
without removing themes/assertions or changing thresholds. Human visual review,
Narrator, an actual high-contrast host and linguistic review remain unverified.

The release owner remains #343 / `product/cura-ai-release-preparation`, original
baseline `854550f`, binding basis `8658d89`, retained blocked head `bd9eac7`.
Both ordinary Windows failures remain FAIL, 31/32 on AMD Family 25 Model 1:
`en-summary-conflict` / `ai_local_stopped` / 45297 ms on `8658d89` and
`en-key-points-injection` / `ai_local_stopped` / 51140 ms on `bd9eac7`.
The reports do not retain the native cause; these elapsed values alone do not
prove a timeout. Family 25 and Family 26 successes on #344/main are mixed evidence,
not diagnosis or cancellation of those failures. See the
[blocked owner audit](https://github.com/gabned/provelume/pull/343#issuecomment-6113081015).

The same owner reconstructs its candidate by merging the actual main without
rebasing or replacing historical bindings/receipts. Every head-dependent gate and
the exact distribution installer require new observations; no preceding installer
or synthetic merge is reused as the new candidate's identity. The
[release preparation record](unreleased-cura-ai.md) distinguishes these new results,
the missing original local receipt bytes and unresolved native diagnosis from
historical passes. Complete-bundle local transport above 32 MiB remains limited.
All changes are Unreleased; 0.12.1 is only the Custodia patch proposal and 0.13.0
remains Iudicium. #340 stays open until future release delivery.
