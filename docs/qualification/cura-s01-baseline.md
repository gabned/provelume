# Cura S01: existing-interface baseline

This is an evidence and design input for [activation #255](https://github.com/gabned/provelume/issues/255)
and [S01 #256](https://github.com/gabned/provelume/issues/256), following planning #247.
It does not qualify the Cura interface, approve translations or change the default renderer.
The [information architecture and glossary](../architecture/cura-information-architecture.md)
map every mandatory release requirement to its ordered owner slice.

## Binding and method

The observed application is accepted Core commit
`a4c7fd827ff9caef7a43ca6c70f2b03a5c22d5a2`, tree
`718107567bbf3a74f759f0c7c3fb633417ac06cc`, package/runtime `0.10.1`.
It includes #254 after the immutable published `v0.10.1` commit; these observations therefore
do not relabel the older release evidence. The application ran in an isolated Ubuntu 24.04
Instance, Python 3.12.3, reached by Chrome on Windows through an explicit loopback port.
No real accounts, provider credentials, documents or existing Instance state were used.

Browser observations were recorded on 2026-09-12, approximately 17:40–17:55 UTC, with individual
UTC timestamps and the source SHA in the retained observation journal. Captures include actual
AX snapshots and browser viewport PNGs. Source inspection, HTTP observations and visible
interaction are separate evidence types. The desktop browser used its default viewport;
additional explicit viewports were 390×844 and 900×900 CSS pixels, then reset to default.
EN and IT were exercised; this is neither a novice user study nor a human linguistic review.

The fixture contains two small UTF-8 files in a synthetic folder Source: `Projects/cura-orchid.md`
and `notes.txt`. The Orchid Original SHA-256 is
`37564f45ecef52c2bdd87225b2bb2f4737f7d50a03e58075c73d82aa1c7f9770`.
A separate two-byte invalid UTF-8 input provoked a real extraction failure while retaining its
acquisition evidence. Fixtures and state are sacrificial; no reset permission extends to real data.

Original evidence remains outside source under the campaign's `s01-browser` and `s01-automatic`
directories: unedited snapshots/PNGs, observation journal, scripts, HTTP response bodies and
SHA-256s, test command, full log and JUnit result. The parent receipt/evidence record identifies
their inventory. Repository text summarizes outcomes without importing generated Instance data,
local machine paths, credentials or the full logs.

## Seven journey observations

An action count describes only the stated segment. Navigation, filling a field and submitting
an action each count once. Waiting and fixture preparation are separate. These single scripted
observations establish repeatable tasks; no measured active-time median or completion-rate
improvement is claimed. Full end-to-end completion remains unmeasured where the endpoint was
not exercised, including the Original download and Windows background lifecycle.

| Journey and entry/end boundary | Executed observation | Friction and next owner |
| --- | --- | --- |
| J1: Home → first Source → indexed result | Source navigation, name, path, validation and registration take five intentional actions on the clean registration segment. A deliberately missing path produces an actionable error and preserves entered values. Correcting it validates and registers successfully. Observe and Queue refresh add two actions; the scheduler acquires both files and Search later retrieves Orchid. | Registration and queue success display raw `registered:`/`queued:` identifiers without a direct job/result link. Quiescence and scheduling remain distinct from registration. S02/S04 provide connected progress and result paths. |
| J2: Inbox → submit material → receipt/result | The empty Inbox renders its configured drop location, counters, Settings and Operations. There is no browser file/text submission control. Folder ingestion from J1 works, but does not prove browser capture. | Browser-only capture is blocked in this baseline. S06 owns the actual Capture form, receipt, outbox and idempotent delivery; S07 owns mobile entry paths. |
| J3: Inbox → known-item search → readable document | Four actions: navigate to Search, enter `orchid`, submit, open the result. The snippet and Document content match the fixture. | Four technical filters are initially visible. The Document breadcrumb returns to Home/Browse, without the prior query context. S02 retains query/context and progressively discloses filters. |
| J4: Browse → discover a Project item | Browse shows the acquired files. With the menu closed, select `Projects` in Area and apply; the resulting query filters to Orchid. | The IT apply button says `Dettagli`, and Source-locator Area competes with canonical library hierarchy terminology. An earlier interaction reached Audio unexpectedly; its cause was not established and it is retained as an unsuccessful attempt, not a proved routing defect. S02/S08 own clarity and contextual navigation. |
| J5: Document → representation and provenance | Rendered, Raw Markdown, Original text and Original download controls are visible. Provenance shows Source/Acquisition/Original/Version/Derived records, the fixture hash and acquired timestamp. The browser session did not execute the download. A separate automatic fixture verifies exact Original bytes. | Evidence is available but exposed through technical IDs/edges; the provenance chain remains English in IT. S02/S05 link a readable evidence trail; S08 owns contextual catalog coverage. Automatic byte verification is separate from a clicked browser download. |
| J6: failed/interrupted acquisition → safe recovery | A real synthetic Inbox extraction failure appears in Operations and its linked timeline. The IT page shows translated headings alongside English technical status/messages and raw JSON. Existing selected recovery tests separately exercise durable retry/interruption semantics. | The visible failed operation offers neither an applicable retry nor a recommended safe next step; the Home error lacks an exact operation link. No successful browser recovery is claimed. S03/S04 own the authoritative attention/recovery path. |
| J7: Settings → language/appearance/privacy/background | Save Light and Italian: the form reports a saved revision and renders in Italian. A new Home request without `lang` renders English despite the saved preference; Light remains effective. Privacy & Network shows offline-only configuration and distinguishes capability from uninstrumented observation. | Technical endpoint/schema details precede everyday preferences. Linux correctly disables Windows login startup. Native close/tray/exit and restart/upgrade persistence were not observed here. S08 owns language resolution; S09 owns complete preferences and Windows lifecycle. |

## State matrix and automatic evidence

`B` is browser-observed; `A` is an automated response or existing test; `M` means missing in this
baseline; `N/A` means the baseline has no such exposed capability, not that Cura may omit it.
Rows are scenario coverage rather than a cross-product pass claim. Each final journey must
exercise its applicable new states on the final candidate.

| State | Evidence and scope | Remaining observation |
| --- | --- | --- |
| Happy | B: folder enrollment/acquisition, search/document, Browse filter, provenance, preference save. A: synthetic HTTP read/enrollment paths. | J2 browser capture; clicked Original download; completed browser recovery; native background lifecycle. |
| Empty | B: initial Sources/Inbox/Operations and initial Browse hierarchy. A: empty Browse/Search/document/search APIs. | New Capture/attention/maintenance/mobile empty states in their owning slices. |
| Loading/in progress | B: Source quiescing and queued refresh statuses. | M: controlled slow browser requests, announced pending state and interrupted navigation. A queued label is not proof of accessible loading behavior. |
| Degraded | B: unavailable folder and extraction failure. A: missing Source, unavailable/unreadable path. | Source reconnection/recovery guidance and partial representation availability across new surfaces. |
| Permission denied | A: missing/invalid CSRF gives 403; nonlocal peer gives 403; untrusted Host gives 400; unreadable folder validation gives 400. | M: visible keyboard/error-focus recovery for each boundary; new device scopes in S06/S07. |
| Interrupted | A: existing durable partial/interrupted ingestion recovery tests pass. B: failed operation evidence is readable. | M: successful browser resume/retry with exact checkpoint and no duplicated effects. Failure is not interruption. |
| Session expired | A: a token from a prior app instance is rejected (403), a newly obtained token is accepted; synthetic expired Google callback redirects to a generic `google_callback_invalid` diagnostic. | M: full visible reconnect journey and actionable expiry-specific wording on this baseline. The form token is app-lifetime, not a timed login session; no timed expiry is invented. Mobile authorization is N/A before S06. |

The automated baseline run recorded **28 HTTP observations**, all matching their expected
status, on 2026-09-12T17:50:57.277038Z–17:51:07.385367Z. The selected existing test run completed
at 17:51:27.176522Z with **18 passed**, with the exact command and full log retained. This was
not FULL and is not a substitute for unchanged-candidate native and remote CI gates.

A separate two-response automatic Original-download check brings the retained total to **30
HTTP observations**: local download returned 200 and exactly matched the synthetic 47-byte input;
untrusted Host returned 400. That independent fixture digest is
`06be917970aabaf64ff06d44022cbba168a5b10da11443bc8b0215eb91b4251a`.
The 46-file automatic evidence inventory SHA-256 is
`5cf569865552532465bdaf85fdd4e041f76fad95cf48c801c9ebe63876d89c66`.

The matrix denied real outbound sockets and observed zero real provider/network calls. Google
expiry used only a fake adapter and in-memory credential vault. Original real Google evidence
retains its historical scope/timestamps; no consent was repeated. A valid local peer, trusted
Host and real CSRF token permit the tested read-only validation even with a different Origin
header: the baseline does not claim a separate Origin-header denial. Future scoped Capture
authorization must be qualified against its own explicit contract.

## Accessibility, layout and unresolved findings

| ID | Actual observation | Owner and closure condition |
| --- | --- | --- |
| B01 | Keyboard Tab reaches Skip to main content; Enter moves focus to `main-content`. | S02 preserves this observed path and validates focus for the new shell. This proves neither screen-reader speech nor the full keyboard journey. |
| B02 | Knowledge and Operational status can remain open together. Escape and an outside heading click leave both open. Expanded menus cover content/filters on desktop. | S02 fixes exclusivity, outside/Escape/navigation/focus dismissal and deterministic focus. Regression tests plus actual interaction required. |
| B03 | At 390×844, expanded Knowledge occupies almost the initial viewport before the main task. Closing it exposes Browse. At 900×900, the closed-menu filter/card layout reflows without obvious horizontal clipping in the inspected image. | S02/S09 exercise every primary journey at mobile/reduced geometry, overflow, touch and keyboard. This single screenshot does not certify all surfaces. |
| B04 | Browser zoom key commands did not change measured CSS viewport or device-pixel ratio. The retained `zoom-attempt` image therefore is not a 200% observation. | S09 must obtain actual 200% zoom evidence; this baseline cell is NOT_EXECUTED, never PASS or inherited DEFERRED. |
| B05 | No actual screen-reader speech session was available. AX semantics and keyboard interaction were observed separately. | S09 retains an explicit screen-reader observation obligation. |
| B06 | Native tool inventory succeeded, but automatic safety review stopped native browser control because it could not determine the new window's URL confidently. No native Provelume screenshot or tray action was performed. | Native observation is NOT_EXECUTED. Resolve the actual tool/human boundary before qualification; Emendatio's native deferral does not apply to Cura. |
| B07 | IT contains misleading/untranslated task labels, technical errors and provenance vocabulary; saved language is not applied to a plain Home request. | S08 supplies complete contextual catalogs and deterministic persistent selection; actual sensitive-copy linguistic review remains independent. |
| B08 | Submission, scheduled work, operation history and errors require disconnected visits, with raw IDs in success messages and no visible recovery action. | S03/S04/S06 consume one authoritative model and link exact item/job/evidence/recovery without a second queue truth. |

Two capture names are explicitly non-results: `browse-filtered-it` is the unsuccessful Audio
navigation attempt, and `browse-it-zoom-attempt` did not reach 200%. The saved-preferences image
is named for its EN entry scenario but shows the resulting IT state. Evidence consumers must
use the recorded URL/state rather than infer a result from a filename.

No generated translation is called human reviewed. No baseline visual omission is waived.
S01 completion records this evidence, analysis and the complete requirement map; implementation
and release-default qualification must resolve the applicable requirements in the named slices.
