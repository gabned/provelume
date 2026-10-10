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
