# Cura information architecture and reference vocabulary

Design contract for `0.11/S01`, owned by [#256](https://github.com/gabned/provelume/issues/256)
under the activated [Cura parent #255](https://github.com/gabned/provelume/issues/255).
This document specifies the target experience; it does not assert that Cura is implemented,
qualified, the default renderer or a published release. The implementation package stays `0.10.1`
until its separate release preparation. Campaign state and qualification receipts remain with
the parent; this document is not another operational ledger.

## Sources and evidence boundary

The controlling product requirements are the [Cura roadmap](../roadmap.md#0110--daily-use-ux-unified-capture-action-center-and-multilingual-interface),
[UX program #247](https://github.com/gabned/provelume/issues/247), the parent's frozen slice map,
the absorbed preferences/menu/tray requirements in [#167](https://github.com/gabned/provelume/issues/167)
and the bounded release cue in [#217](https://github.com/gabned/provelume/issues/217).
Existing contracts remain authoritative for [Browser data](knowledge-browser.md),
[Inbox and operation evidence](operation-log-and-local-inbox.md),
[representations and corrections](universal-representations.md),
[maintenance recovery](maintenance-catalogue-and-reindex-recovery.md) and
[Windows preferences and endpoint](windows-shell-and-endpoint.md).

The source inventory is pinned to `a4c7fd827ff9caef7a43ca6c70f2b03a5c22d5a2`.
At that base, `core/provelume/web.py::_navigation` lists 32 destinations in five groups.
Source enrollment, Google connection, search, rendered/raw/Original views, durable recovery,
EN/IT, appearance, shell preference transfer and tray behavior already exist in bounded forms.
Cura joins and extends these contracts; their existence must not be described as a new feature.
The current `/inbox` is an evidence/Drop guidance view; source inventory found no Browser upload
form there. Backend recovery support does not by itself prove an end-to-end Browser recovery path.

Source findings are `SOURCE_EVIDENCE` or `SOURCE_INFERENCE`. Runtime observations, measured task
outcomes, accessibility testing and linguistic review are separate evidence classes. Neither
source markup nor a referenced test is an observed PASS. Missing measurements stay `NOT_MEASURED`;
unsupported/inapplicable scenarios require a reason, rather than being counted as successful.
The [S01 baseline](../qualification/cura-s01-baseline.md) records actual observations separately
from this target design; complete original evidence remains outside source. Completing S01
analysis does not qualify the final default. Mandatory findings retain the exact S02–S09 owners
below; an unobserved or deferred case cannot become PASS through that assignment.

## Seven journey contracts

Each scenario uses synthetic or privacy-safe data, a declared starting state and an exact item,
Source or job identity. Success includes understanding the result and knowing the next action.
The following are final journey acceptance criteria, not measured baseline results.

| ID | Entry and task | Observable success criterion | Recovery/negative criterion |
| --- | --- | --- | --- |
| J1 | Overview → add first Folder or supported Connector Source | User validates scope, registers one stable Source, sees its state, initiates supported intake and opens the first acquired item with provenance. Record registration and time to first readable item separately. | Unavailable path, denied permission or expired provider authorization has a specific explanation and safe action; entered non-secret values survive and no duplicate Source is created. |
| J2 | Capture → submit/import one item | A supported submission yields one durable submission identity, a truthful accepted/queued/attention result and a link to its acquired item or exact pending work; user distinguishes submitted from processed. | Offline/replayed/interrupted submission reconciles before retry, preserves Original/Acquisition evidence and never reports an unacknowledged local outbox item as acquired. |
| J3 | Search → find a known document | User reaches the expected Document Version from a bounded local query, can inspect its evidence and return to the same query, filters and result position. | Blank query, no matches, unavailable index and denied access are distinct; a degraded index has an honest limit and a permitted browse/recovery path. |
| J4 | Knowledge → discover without an exact query | User navigates Area/Project/Collection or a disclosed facet to a relevant item and can explain its placement and return context. | Empty scope, conflicting filters and missing derived preview explain what remains available; clearing one filter preserves the others. |
| J5 | Document → inspect Original, representation and provenance | User identifies preserved bytes versus derived output, selects an available version/representation, follows Source→Acquisition→Original→Version→Derived evidence and explicitly downloads an authorized Original. | Unsupported/degraded preview never implies missing Original; unavailable evidence and permission denial stay visible; authored content cannot trigger network access. |
| J6 | Needs attention → recover failed/interrupted acquisition | User identifies the exact failed attempt/checkpoint, chooses a supported safe action and verifies its terminal receipt without duplicate acquisition or Original loss. | Failed, blocked, interrupted, resumable and restart-only are distinguishable; stale/denied actions reconcile instead of replaying blindly. |
| J7 | Management → Settings | User changes language, appearance, privacy/notification choice and independent background/login behavior; sees effective versus restart-pending values; explicit choices survive restart/upgrade. | Denied, stale or expired preference writes preserve current settings; reset/import preview lists scope and preserved state, and atomic failure leaves a coherent preference set. |

## Stable routes and navigation

The five everyday destinations have the same names and order at desktop, reduced width and
mobile. Management is a secondary destination. Fewer visible navigation entries do not remove
capabilities or authorization checks. Every current bookmarked route and deep link remains valid.
Labels can change without changing canonical IDs, API fields or domain enum values.

| Everyday destination | Route | First content and primary action |
| --- | --- | --- |
| Overview | `/` (existing) | Continue working, recent knowledge, items needing attention; add first Source/capture when empty. System metrics are secondary. |
| Knowledge | `/browse` (existing) | Readable library/hierarchy and recent context; disclose specialized views and technical facets. |
| Capture | `/inbox` (existing, extended) | Add supported content, view outbox/submission progress and its authoritative result; link to Source setup for recurring intake. |
| Search | `/search` (existing) | Query first, readable results, optional filters; preserve query/filter context through detail and return. |
| Needs attention | `/attention` (proposed additive route) | Typed review/recovery items ordered by explicit attention state; direct link to each canonical item/attempt. |

`/management` is a proposed additive landing route for Sources & Connectors, Operations &
Maintenance, Diagnostics, Settings and About & Credits. It adds presentation, not a new registry.
S02/S03 own final additive-route registration. The compatibility mapping below covers all 32
current navigation destinations; nested item routes inherit their owner and remain addressable.

| Target owner | Existing route inventory | Contextual access |
| --- | --- | --- |
| Overview | `/` | Always available; onboarding and exact attention links. |
| Knowledge | `/browse`, `/bundles`, `/representations`, `/photos`, `/audio`, `/video`, `/file-families` | Specialized library views and document evidence; bundles/representations are secondary details. |
| Capture | `/inbox` | Submission list and recurring Source setup links. |
| Search | `/search` | One preserved query/filter state shared with return navigation. |
| Needs attention | `/duplicates` | Existing duplicate evidence remains reachable; only actual decision items enter the new queue. |
| Management → Sources & Connectors | `/sources`, `/connectors`, `/google/connect`, `/email`, `/transcripts`, `/ocr` | Setup and capability controls; related transcript/OCR evidence is also linked from the Document/review item. |
| Management → Operations & Maintenance | `/operations`, `/scheduler`, `/assurance`, `/rebuild`, `/maintenance` | One job/schedule entry with evidence links to existing specialized views. |
| Management → Diagnostics | `/components`, `/knowledge-health`, `/perceptio`, `/qualification`, `/security/installation`, `/security/network`, `/security` | Effective support, health and truthful installation/network evidence; Settings links to relevant privacy evidence. |
| Management → Settings | `/settings`, `/settings/shell` | Appearance & Language; Capture folders; Privacy & Notifications; Background; advanced Endpoint; preference transfer/reset. |
| Management → About & Credits | `/about` | Local product/version/channel/build, real links, human credits, licenses and notices. |

Document routes `/documents/{id}` and `/documents/{id}/provenance`, operation routes
`/operations/{operation_id}`, bundle routes `/bundles/{version_id}` and connector evidence
routes keep exact identity. Deep-link responses expose current location and an understandable
return path even when opened from tray/notification or without previous Browser history.
Technical facets remain linkable. A safe return context contains route/query/filter information,
not secrets or an arbitrary external redirect. Language switching preserves that context.

## Progressive disclosure and interaction rules

- Overview emphasizes a next useful action, recent knowledge and recoverable work. Health counts
  have explanatory detail and never displace the task entry points.
- Knowledge initially shows readable titles, placement and availability. Source-locator areas
  remain distinct from canonical Areas; advanced Source/MIME/disposition/technical filters are
  available behind named disclosure. Active filters remain visible and individually removable.
- Search initially shows query and results. Expandable filters retain explicit state and counts;
  a user never has to infer that a hidden filter explains an empty result.
- Document detail begins with content and clear Original/derived labels. Version, representation,
  correction history, hashes and provenance are one linked evidence path, not disconnected stores.
- Forms expose required choices first, preserve safe entered values on failure and associate
  inline errors with fields. Plain-language summary precedes exact error codes and diagnostics.
- Every consequential action shows scope, expected effect, authority, reversibility and evidence
  before confirmation. Unsupported controls are absent; the capability explanation remains visible.
- Only one top-level menu opens at once. Opening another, outside pointer/touch, Escape,
  navigation or focus leaving its context dismisses it; keyboard focus returns predictably.
- Landmarks, skip link, visible focus, current location, labelled icons and logical keyboard order
  survive layout changes. Error focus and polite status announcements do not steal ongoing input.
- Lucide is a locked, vendored MIT subset with repository-owned provenance/notices. The existing
  Provelume brand mark remains separate. No runtime CDN, remote font, telemetry or account is needed.

## One authoritative model; first-class action and recovery states

Application services own canonical identities, permitted actions and revisions. The Browser,
Capture receipt, Action Center, Operations view, API, notification and tray consume the same
authoritative read contracts. A frontend may retain a query or pending upload, but cannot invent
canonical knowledge, queue decisions, job state, permissions or a parallel hierarchy.

Keep these state dimensions separate: submission delivery, acquisition outcome, review decision,
job execution, representation availability and authorization. For example, upload accepted is
not review accepted, an unavailable representation is not Original loss, and a paused job is not
a rejected acquisition. A view references existing records; it does not copy them into a second
queue. Counts, links and transitions reconcile to the same record/revision across all surfaces.

Each review item shows its typed queue, current state, proposed action, exact Version/Original
hash and provenance, reason/confidence when supplied, impact, reversibility and bounded choices.
Unknown confidence is shown as unknown, never synthesized from model temperature. Typed queues
cover intake, classification, exact/probable duplicate, version conflict, extraction error,
Source change and retention. The following is a target presentation vocabulary; S03 binds it to
the closed backend transition contract rather than renaming existing enums implicitly.

| Dimension/state | Required explanation and permitted next step |
| --- | --- |
| Outbox: pending / sending / awaiting acknowledgement | Explain device-local versus server-confirmed status; show retry eligibility and reconcile the idempotency key before retry. |
| Review: awaiting review | Preview the current proposal; confirm, correct or reject only where that item contract allows; ignoring causes no destructive action. |
| Review: accepted / rejected / superseded | Preserve decision receipt and evidence. Rejection quarantines under explicit retention; superseded points to replacement evidence. Neither implies purge. |
| Stale or conflicting decision | Explain changed input/policy; reload the exact current proposal before a new choice; a stale confirmation cannot mutate newer state. |
| Job: queued / running / pausing / paused | Show scope, progress and honest resource wait; offer only contract-supported run, pause, resume or cancel. |
| Job: blocked / failed | Distinguish missing permission/resource/configuration from a failed attempt; explain the exact prerequisite or bounded retry with next retry time. |
| Job: interrupted / resumable / restart-only | Show last durable checkpoint and its validity; recommend resume or an explicit safe restart using the actual recovery contract. |
| Job: completed | Show terminal receipt, result and affected item links; completion does not imply later review acceptance or language qualification. |
| Presentation: empty / loading / degraded | State what is absent or pending and what remains usable; retain safe context, avoid false success and provide an applicable next action. |
| Authorization: denied / expired / revoked | Identify the boundary without leaking secrets; reconnect, reauthenticate or refresh a one-time form as appropriate; never automatic escalation. |

Permissions are enforced by the server/service on reads, downloads and every mutation; a hidden
menu is not authorization. Loopback settings guards remain distinct from paired-device capture
scopes and provider consent. An expired one-time form is not automatically an expired login or
provider session. Device/bot revocation blocks future capture without deleting acquired knowledge.

OCR/transcript correction uses synchronized page/image/audio/video evidence, low-confidence
navigation, keyboard editing, segment merge/split, speaker-label proposals and before/after diff.
Save creates a versioned annotation bound to the exact engine/model result and page/time/region
anchors. It cannot rewrite the Original, silently retrain, identify a person or assert a fact.

Heavy maintenance previews show item count, bytes, temporary disk and authority boundary.
Repair has its own preview/backup/confirmation. Capacity pressure may pause new ingestion;
it cannot authorize automatic deletion of Originals, derived state, logs or old backups.

## EN/IT reference glossary

These are proposed contextual reference strings, not an approved translation catalog.
`S` marks safety/privacy/deletion/network/credential/recovery-sensitive copy requiring real
reviewed translation before publication; `—` marks ordinary terminology. Every resulting string
still needs catalog/context checks. Completeness, automated checks and human linguistic review
are separately recorded; S01 makes no human-review claim. Technical identifiers remain English.

| Semantic key / context | English | Italian | Meaning and sensitive-copy flag |
| --- | --- | --- | --- |
| `nav.overview` / primary | Overview | Panoramica | Continue/recent/attention entry; — |
| `nav.knowledge` / primary | Knowledge | Conoscenza | Browse the existing library, not an AI answer claim; — |
| `nav.capture` / primary/action entry | Capture | Acquisisci | Submit supported material; acquiring is distinct from approving; — |
| `nav.search` / primary | Search | Cerca | Local bounded retrieval; — |
| `nav.attention` / primary | Needs attention | Da esaminare | Review and recovery items; no implied failure or deletion; — |
| `nav.management` / secondary | Management | Gestione | Service/setup/settings destinations; — |
| `nav.sources` / management | Sources & Connectors | Fonti e connettori | Source configuration and connector capabilities; — |
| `nav.operations` / management | Operations & Maintenance | Operazioni e manutenzione | Scheduled/running work and safe maintenance; — |
| `nav.diagnostics` / management | Diagnostics | Diagnostica | Sanitized technical evidence; — |
| `nav.settings` / management | Settings | Impostazioni | Preferences with explicit effective/restart state; — |
| `nav.about` / management | About & Credits | Informazioni e riconoscimenti | Local identity, humans, licenses and notices; — |
| `source` / enrollment | Source | Fonte | Stable scoped origin of acquisitions; distinct from its filesystem path; — |
| `connector` / setup | Connector | Connettore | Adapter capability; a configured connection is a ConnectorInstance; — |
| `connection` / account/device setup | Connection | Connessione | Specific configured identity/device; consent/revoke explanation is S |
| `submission` / Capture receipt | Submission | Invio | One submitted payload and delivery status; not yet an Acquisition; — |
| `acquisition` / provenance | Acquisition | Acquisizione | Preserved occurrence from a Source, including duplicate occurrences; — |
| `document` / retrieval | Document | Documento | Stable canonical identity spanning versions; — |
| `original` / download/evidence | Original | Originale | Exact preserved acquired bytes; modification/preservation promises are S |
| `version` / detail | Version | Versione | Exact canonical version linked to Original; not renderer version; — |
| `representation` / detail | Derived view | Vista derivata | Readable label for a Representation; reproducible output, not Original; — |
| `bundle` / evidence detail | Representation bundle | Pacchetto di rappresentazione | Technical group of derived outputs and anchors; — |
| `provenance` / detail | Provenance | Provenienza | Attributable Source/Acquisition/Original/Version/Derived chain; — |
| `area`, `project`, `collection` / placement | Area; Project; Collection | Area; Progetto; Raccolta | Canonical hierarchy identities, not arbitrary Source folders; — |
| `operation`, `job` / evidence | Operation; Job | Operazione; Lavoro | Operation attempt/receipt versus scheduled execution; — |
| `state.blocked` / recovery | Blocked | Bloccato | Missing prerequisite; changing that prerequisite may permit progress; S |
| `state.interrupted` / recovery | Interrupted | Interrotto | Incomplete attempt; inspect checkpoint before acting; S |
| `state.failed` / recovery | Failed | Non riuscito | Attempt ended unsuccessfully; no claim that it produced no effects; S |
| `action.resume` / valid checkpoint | Resume | Riprendi | Continue from a verified supported checkpoint; S |
| `action.retry` / failed attempt | Retry | Riprova | Bounded new/reconciled attempt; not blind replay; S |
| `action.restart` / restart-only work | Restart safely | Riavvia in sicurezza | Show discarded derived progress and preserved state before starting; S |
| `action.reject` / review | Reject | Rifiuta | Quarantine under retention policy, without purging Original; S |
| `action.archive` / lifecycle | Archive | Archivia | Change active visibility while preserving knowledge; S |
| `action.remove_projection` / lifecycle | Remove library copy | Rimuovi copia dalla libreria | Remove rebuildable projection only; original/metadata preserved; S |
| `action.trash` / lifecycle | Move to trash | Sposta nel cestino | Recoverable disposition governed by policy; S |
| `action.purge` / lifecycle | Permanently purge | Elimina definitivamente | Irreversible exact-scope destruction; separate explicit decision; S |
| `action.undo` / receipt | Undo | Annulla modifica | Exact available undo/compensation, with limits stated; S |
| `permission.denied` / protected action | Permission required | Autorizzazione necessaria | Current authority does not permit the action; no client-side bypass; S |
| `permission.expired` / provider session | Connection authorization expired | Autorizzazione della connessione scaduta | Provider reconnection needed; distinct from expired form; S |
| `form.expired` / guarded form | This form has expired. Reload it to continue. | Il modulo è scaduto. Ricaricalo per continuare. | Reload/reconcile before resubmission; S |
| `privacy.network` / capture consent | This content will pass through {provider}. | Questo contenuto passerà attraverso {provider}. | Explicit transport disclosure before transfer; placeholder preserved; S |
| `autonomy.prompt` / capability + scope | How much can Provelume decide? | Quanto può decidere Provelume? | Scope-specific authority; not a global AI setting; S |
| `disabled` / authority mode | Disabled | Disattivato | This capability performs no automated decision; S |
| `proposal-only` / authority mode | Suggest only | Proponi soltanto | Produce proposals, apply none; S |
| `confirm-each` / authority mode | Ask before each change | Chiedi prima di ogni modifica | Every permitted change requires confirmation; S |
| `controlled-automatic` / authority mode | Apply within approved rules | Applica entro le regole approvate | Only allowed reversible action/scope/rule; no authority from confidence alone; S |
| `settings.system` / appearance/language | System | Sistema | Deterministic supported host preference; explicit fallback explained; — |
| `settings.theme` / appearance | Light; Dark | Chiaro; Scuro | Persisted appearance choice; — |
| `settings.preview` / maintainer preference | Preview interface | Interfaccia in anteprima | Local renderer selection with presentation-only rollback; — |
| `settings.reset` / confirmation | Reset settings | Ripristina impostazioni | Complete declared preferences reset; never knowledge/credential reset; S |
| `settings.transfer` / preference file | Export settings; Import settings | Esporta impostazioni; Importa impostazioni | Non-secret versioned preferences; import preview before mutation; S |
| `settings.background` / close behavior | Keep running when the window closes | Continua l'esecuzione alla chiusura della finestra | Independent from start at login; S |
| `settings.login` / Windows | Start at Windows login | Avvia all'accesso a Windows | Explicit persisted startup choice; S |
| `tray.exit` / lifecycle | Exit Provelume | Esci da Provelume | Stops the local runtime; not merely hides its window; S |
| `notification.preview` / queue | {count} items need attention | {count} elementi da esaminare | Catalog must supply actual plural/select forms; no titles/content by default; S |

EN/IT reference semantics drive all seven shipped catalogs. UI language support is independent
from document, OCR, transcription, classification and model/provider language support. System
locale uses the supported registry deterministically with English fallback; explicit language
survives restart/upgrade. Ordinary selection loads only packaged repository-owned data.

## Mandatory requirement-to-slice map

Every row is mandatory unless it explicitly records the parent's optional/deferred decision.
`Sxx` means `0.11/Sxx`; the lead owns implementation and later slices integrate/qualify it.
Rows define acceptance coverage, not permission to open slices out of the parent's order.

| ID | Contract to preserve/deliver | Lead; dependencies/integration |
| --- | --- | --- |
| C01 | Seven end-to-end baseline journeys; steps, backtracking, clarity and all declared states/devices/input modes | S01; existing Browser; compare in S09 |
| C02 | Route/screen inventory, five everyday destinations, Management, progressive Knowledge/Search and useful Overview | S01 design → S02; stable existing routes/read models |
| C03 | Shared shell, coherent menu dismissal/focus, labelled icons, landmarks/current location, responsive overflow | S02; S01; qualify S09 |
| C04 | Locked/vendored Lucide subset, MIT/provenance/notices, separate canonical brand mark | S02; existing component contract; S09 icon/cache/upgrade matrix |
| C05 | Offline About & Credits: actual identity, repository/release links, human/first-party credits/licenses/notices; metadata is not authentication | S02; Emendatio #253/#254 |
| C06 | Local explicit auditable/server-rendered Preview; restart/upgrade persistence; same routes/backend/canonical state; presentation rollback | S02; S01; default activation only S09 |
| C07 | Tiny accessible NEW cue from canonical publication timestamp, visible only at age <24h; no network/user tracking or automatic release-note opening | S02; #217; clock/timezone/cache/theme/input checks S09 |
| C08 | One Action Center read model with typed intake/classification/exact/probable duplicate/version conflict/extraction/Source-change/retention queues | S03; existing canonical and operation evidence; S05/S06 consumers |
| C09 | Closed review transitions; accepted/rejected/superseded preserve Originals/evidence; ignored items do nothing destructive | S03; S05 decisions, S06 write journal |
| C10 | Proposal-before-mutation with preview, provenance/hash, reason/confidence, impact, reversibility and bounded choices | S03 structure → S05 decisions; exact input/revision guards |
| C11 | Shared accessible capability/scope-specific disabled/proposal-only/confirm-each/controlled-automatic modes; color never sole meaning; temperature never authority | S03 structure → S05 policy; S08 wording; later AI owners stay separate |
| C12 | Separately configurable disabled/in-app/host desktop/browser/PWA notifications; content/title minimization, quiet hours, aggregation and exact queue links | S03; S06/S07 channel integration; later provider channel requires explicit configuration |
| C13 | All schedules/jobs: scope/policy, last attempt/success, next due, progress/throughput/checkpoint/resource wait/retry time/terminal receipt | S04; durable scheduler; S03 attention links |
| C14 | Queued/running/pausing/paused/blocked/interrupted/resumable/restart-only/failed/completed states; supported run/pause/resume/retry/cancel/safe restart | S04; existing per-job capabilities; exact checkpoint/recommended action |
| C15 | Incremental/full reindex, library rebuild, Source reconciliation, validation, Original assurance, duplicate scan, backup verification, redacted diagnostic bundle | S04; maintenance catalogue; bind explicit backup destination/verification inputs; current unavailability is not a final-release exemption |
| C16 | Heavy-work count/bytes/temp-space/authority previews; distinct repair preview/backup/confirmation; capacity can pause intake without automatic deletion | S04; resource/maintenance contracts; S06 intake integration |
| C17 | Confirm/correct Area/Project placement and reusable scoped non-destructive routing rules; destructive/identity changes never become rules | S05; S03 + hierarchy; no autonomous classification grant |
| C18 | Exact occurrence linking retains every Acquisition; probable duplicates stay separate until explicit new-version/separate/related decision | S05; duplicate/version evidence + S03 |
| C19 | OCR/transcript synchronized page/image/audio/video correction, low-confidence navigation, keyboard edits, merge/split, speaker proposals, before/after diff | S05; representations/anchors; S03 queue |
| C20 | Corrections are versioned annotations bound to exact engine/model result and page/time/region; no Original rewrite, retraining, identification or canonical fact change | S05; existing correction contract; S08 sensitive text |
| C21 | Responsive Capture Inbox/PWA; bounded append-only endpoint for files/photos/scans/screenshots/PDFs/URLs/text/audio/voice notes | S06; S03 state model and S05 review; declared effective type support |
| C22 | Exact Original preservation, capture time, submitting device/channel, optional note/Area/Project and Acquisition provenance | S06; durable intake/read models; no automatic Claim/Decision/Task/CalendarEvent |
| C23 | Short-lived QR pairing, revocable scoped per-device credentials; revoke device/bot stops future capture | S06; server authorization; S07 clients |
| C24 | Upload limits/type verification/malware-safe boundary; duplicate/replayed/oversized/malformed/unauthorized inputs fail safely | S06; server validation, Original preservation and audit |
| C25 | Durable offline outbox, cancellation and idempotent retry; queued/replayed submissions reconcile without duplication | S06; durable acknowledgements; S07 clients |
| C26 | Separately scoped Inbox write API, idempotency/audit journal, CSRF/session protection; server permissions on every write | S06; existing local guards; S03/S05 decisions |
| C27 | Distinct archive/remove-projection/trash/purge and supported undo/compensation; rejection quarantine with explicit retention, never implicit purge | S06; S03/S05; existing disposition/retention semantics |
| C28 | iOS Share Sheet Shortcut, Android share-target reference client, direct camera/file picker and watched Drive-drop fallback | S07; S06; existing Google scope/consent remains bounded |
| C29 | Mobile recent captures, bounded full-text search, provenance/version preview, explicit authenticated Original download; no persistent device cache by default | S07; S06 authorization + J3/J5 read contracts |
| C30 | Each device/drop folder/bot/chat distinct Source or ConnectorInstance; provider-neutral relay contract | S07; S06 scopes; optional Telegram adapter DEFERRED by #255 |
| C31 | LAN first; off-LAN requires explicit trusted network/VPN/hardened HTTPS; no mandatory relay; visible provider transit disclosure | S06 boundary → S07 paths; no new public exposure implied |
| C32 | One governed registry/catalog, complete packaged en/it/de/es/fr/pt/ro; ordinary use/switching offline; future packs data-only | S08; S02–S07 exact string inventory |
| C33 | Deterministic System locale/English fallback, persistent override; UI-language matrix distinct from content/engine/model support | S08; S09 clean install/reset/upgrade qualification |
| C34 | Key/placeholder/markup/escaping/plural/select/terminology/context/layout/sorting/date/number/fallback checks; actual sensitive-copy translation review recorded separately | S08; glossary + complete exact batch; S09 integrated language matrix |
| C35 | Persisted System(default)/Light/Dark without wrong-theme startup flash; focus/contrast/states/diagrams/evidence in every shipped catalog | S09; S02 components + S08 catalogs |
| C36 | Independent close-to-tray/login startup, first-close explanation, Open/Status/Pause/Settings/Exit, real runtime exit, no hidden work with background disabled | S09; existing Windows lifecycle; S04 pause contract |
| C37 | Content-minimizing tray status/queue view, exact attention links, distinct Instance scopes, accessible text/reduced motion; no second queue truth | S09; S03/S04 authoritative read model; #167 |
| C38 | Atomic confirmed complete application-preference reset: System language/theme, menu/layout and safe notification/background defaults; exact scope/impact and privacy-minimizing receipt | S09; #167 + existing preference validation; preserve Originals/Documents/Versions, Sources, credentials, queue/job history, backups and selected Instance |
| C39 | Non-secret schema-versioned export/import with preview; first-run summary; explicit reset scopes/short-lived undo only where atomic and supported | S09; #255/#167 + existing shell transfer contract; restart-required/partial-failure reporting |
| C40 | EN/IT and all final languages; keyboard/screen reader, 200% zoom, desktop/reduced/mobile/PWA, high contrast/reduced motion and every journey state | S09; all slices; actual observations distinct from automated checks |
| C41 | Default activation only after primary journeys pass; legacy renderer removed later by bounded cleanup after proven default | S09; C01/C06/C40, complete evidence; no premature rollback removal |
| C42 | No private-chat reading, mandatory Cloud/GitHub/provider runtime, WhatsApp integration, autonomous classification/durable writes or full cross-platform background agent | Every slice; roadmap exclusions and #255 optional decisions |

The ordered dependency path is S01 → S02 → S03 → S04 → S05 → S06 → S07 → S08 → S09.
Existing hierarchy, durable ingestion/Sources/refresh, job, representation and security contracts
are prerequisites throughout. Settings/tray consume S03/S04 truth; capture clients consume S06
authority; S08 checks the whole string surface; S09 integrates rather than silently omitting a
cross-cutting row. Reassignment requires a parent scope decision with the same acceptance coverage.

The next owners must resolve these bounded implementation choices without narrowing the map:

| Decision still to bind | Owner and fixed boundary |
| --- | --- |
| Additive Management/attention handler and exact item URLs | S02/S03; proposed `/management` and `/attention`; all existing routes/deep links stay stable. |
| Presentation-state mapping to closed backend enums and revision tokens | S03; separate delivery/review/job/authorization dimensions and one authoritative read model. |
| Explicit destination and verification parameters for backup verification | S04; current catalogue unavailability requires implementation, not an invented destination or exemption. |
| Complete preference manifest, exact safe reset defaults and supported undo scopes | S09; retain existing shell boundaries, atomic non-secret transfer and every preservation invariant in C38/C39. |

## Baseline-to-final measurement contract

Use the same fixture identities/content, scenario scripts, entry conditions and route tasks on
the baseline and final candidate. Record build/commit, platform/browser/viewport, locale/theme,
input/accessibility mode, observation time, run order and assistance. Count each intentional user
navigation/form/action as one step; record typed query as one submission, and report keystrokes
separately for keyboard access. Backtracking means returning to a prior surface to repair or
rediscover the path; intentional evidence inspection is not a penalty. Waiting time is separate
from active task time. If first-run learning affects comparison, disclose order and use repeats.

| Metric | Baseline recording | Proposed final comparison/acceptance |
| --- | --- | --- |
| J1–J7 completion | Completed/attempted per scenario and mode; assisted/blocked separate | All required scripted journeys complete; no critical safety/authority loss; no unsupported baseline scenario converted into a rate improvement. |
| J1 first value; J2 receipt; J3 retrieval | Registration, server acknowledgement and readable-item times separately; active versus waiting time | Report actual before/after values; propose lower median active time on matched successful runs, with no invented percentage promise. |
| Steps and backtracking | Per-journey raw counts with entry/end boundaries | No avoidable regression in matched journeys; eliminate documented detours and explain any extra safety-confirmation step. |
| J6 recovery | Safe completed recoveries/attempted recoverable cases, checkpoint/action chosen, repeated effects | Every supported recovery scenario completes without duplicated Acquisition/Original loss; unsupported cases explain the safe limit. |
| Language clarity and fallback | Unclear terms/help requests; exact surfaced key/locale/context; intentional versus unintended fallback | Zero unintended fallback on primary journeys; all seven catalogs complete; sensitive-copy review independently evidenced. |
| Navigation/context | Wrong destination visits; lost query/filter/scope/position; ambiguous item/job links | Exact item and return context preserved; no second queue/read-model discrepancy. |
| Accessibility and responsive behavior | Actual keyboard/screen-reader, 200% zoom/reflow, focus/contrast and mobile observations | No blocking task defect in required modes; source tests do not replace user-visible observations. |
| Preference/lifecycle correctness | Saved/effective/restart values; close/login/exit outcome; existing export/import/reset capability | Explicit choices survive restart/upgrade; reset/import atomic within declared scope; background policy honored. |

Each journey records happy, empty, loading, degraded, permission-denied, interrupted and
session-expired cases, including which kind of authorization expired. Publish numerator,
denominator and unmeasured/blocked/deferred cells beside aggregate metrics. Baseline gaps remain
visible; native Windows/PWA or human linguistic observations cannot be inferred from desktop
Browser source or synthetic fixtures. S09 owns final evidence, default activation and remaining
explicit limitations; this design document supplies no qualification result.
