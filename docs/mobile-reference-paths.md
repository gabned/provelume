# Cura mobile reference paths

Scope: #301, #255 and #247. These paths use the S06 Capture journal, acquisition,
pairing and authoritative receipt. The HTTPS listener remains disabled by default.
Use LAN, a trusted network or VPN; the owner explicitly configures the exact HTTPS
origin and trusted certificate. Do not bypass a certificate warning or expose the
listener publicly to make sharing work. Pairing permits submission and own receipts;
Knowledge needs a separate expiring Source grant.

## iOS Share Sheet: Provelume Capture Shortcut

The reference is a manually assembled native Shortcut, with the following action
sequence and API contract. It needs no relay, paid service, Apple account download
or Shortcut signing service. Assembly and real-device execution have distinct
qualification states; a JSON transport test does not certify an iPhone.

Create `Provelume Capture`, enable **Show in Share Sheet**, and accept one URL, text,
PDF, image or file. Do not accept Safari page contents: sharing a URL captures its
text without fetching the page. Multiple inputs stop with an explanation; select
one or use Capture's file picker. Use **Choose from Menu** to select URL, text or
file, never silently convert an unsupported file. Photo/scan/screenshot can be
shared as a supported PNG/JPEG; camera and microphone permission remain controlled
by iOS or Capture. Cancelling leaves the source item intact.

Before the first submission, run a separate setup branch:

1. Ask for the local owner's current one-use pairing JSON; extract `origin`,
   `instance_id`, `scope`, `challenge` and `expires_at` with **Get Dictionary Value**.
2. Show the exact HTTPS origin, Instance and Capture scope. **Choose from Menu**
   offers Confirm and Cancel. Cancel stops before any network call. Never put a
   credential or challenge in a URL/query, clipboard export or diagnostic output.
3. **Get Contents of URL**: POST `[origin]/capture/pair/redeem`; headers
   `Origin: [origin]`, `Content-Type: application/json`. JSON body has exactly
   `challenge`, `label` (`iOS Shortcut`), and `instance_id`.
4. Inspect the returned origin/Instance/scope against the confirmed values. Keep
   the Capture credential only if the user explicitly chooses device retention.
   Retain at most 30 days, record that expiry and stop/re-pair when reached. Explain
   that saving a credential inside a Shortcut may sync it with the user's Apple
   account; use an unsynced personal device configuration only with explicit consent,
   never an exported/shared Shortcut or a Drive queue. Otherwise prompt for
   configuration for each foreground invocation.
   Local owner revocation still controls every request.

Each foreground invocation then uses this sequence:

1. Check one input, chosen mode, supported type and byte limit against
   `/capture/capabilities`. For URL/text, use UTF-8 bytes; file bytes are kept exact.
   Text is at most 512 KiB, URL 8 KiB, PDF 25 MiB/500 pages, PNG/JPEG 20 MiB/20 million
   pixels, PCM16 WAV 10 MiB/120 seconds/two channels. Server verification is final.
2. **Generate UUID**, lowercase it, and **Current Date** → **Format Date** ISO 8601
   with an explicit offset. Freeze these together with the input bytes for this
   invocation. **Base64 Encode**, with line breaks disabled, creates `payload_base64`.
3. Build a Dictionary with exactly `metadata` and `payload_base64`. Metadata has
   `schema_version: 1`, `client_submission_id: [UUID4]`, `captured_at: [timestamp]`,
   `mode: text|url|file`, `channel: paired_pwa`, `filename: [display basename]`, and
   `declared_mime: [verified supported type]`. `paired_pwa` is the existing scoped
   HTTPS transport identifier, not proof of the client's operating system.
4. Show origin, filename/type/bytes and **Send / Cancel** before **Get Contents of
   URL** POST `[origin]/capture/submissions`, JSON body from the frozen Dictionary.
   Headers: `Origin`, `Content-Type: application/json`,
   `Authorization: Bearer [Capture credential]`, `X-Capture-Device: [device_id]`.
5. An accepted `submission` is admission, not acquisition. POST an empty JSON
   Dictionary to `/capture/submissions/[same UUID]/process` with the same headers.
   Show `receipt.processing.status`, including attention/recovery information;
   only the authoritative acquisition receipt establishes acquired knowledge.
6. For uncertain acknowledgement, inspect GET `/capture/submissions/[same UUID]`
   first. A found submission must match its frozen identity/metadata; then process
   only if needed. Only a definite 404 allows resending the same frozen envelope.
   Auth failure, expiry, revocation, timeout or recovery stops; never generate a
   new UUID as a retry. Keep the source item and the non-secret invocation UUID.
   If Shortcuts aborts before preserving that UUID, ask the local owner to inspect
   retained Capture receipts before another attempt. Do not claim cancellation
   undoes a possibly accepted submission.

This online foreground Shortcut deliberately owns no durable retry queue. Offline,
lost invocation state or unavailable Shortcuts uses the existing browser outbox or
already watched Drive-drop fallback. It never creates another source of queue truth.

Apple documents [Share actions](https://support.apple.com/en-gb/guide/shortcuts/apdaf74d75a5/ios)
and [Get Contents of URL JSON requests](https://support.apple.com/en-euro/guide/shortcuts/apd58d46713f/ios).
Action names can follow the device's language. The sequence must be exercised on an
actual iPhone before recording real iOS acceptance.

## Android reference client: installed Capture PWA

On a supported Android browser, open the explicitly configured HTTPS Capture origin,
pair the device, and install Capture through the browser's own installation dialog.
Its repository-owned manifest registers a multipart POST share target for one
supported file, text or URL. No native SDK, additional account or relay is required.
The [browser's share-target contract](https://developer.chrome.com/docs/capabilities/web-apis/web-share-target)
requires installation; an ordinary tab is not evidence of OS share registration.

From an Android app, choose **Share → Capture**. The installed worker accepts at
most one item with bounded bytes and hands it to the Capture form in memory for at
most two minutes. Inspect the selected input and press **Queue and send**. Only
then does the existing 16-item/64-MiB S06 outbox admit it under the paired identity.
There is no automatic submission or second IndexedDB store. Server type verification,
fingerprint reconciliation, idempotency, cancellation and receipts remain S06's.

If sharing is unsupported, the worker stops, the browser interrupts or a second
handoff arrives while one is pending, no acknowledgement is invented. Keep the
source item, choose a supported file directly or use Drive-drop. Plain HTTP disables
installation/worker/share targets. Synthetic worker tests do not certify an Android
OS share sheet or installed browser.

## Camera, file selection and Drive-drop

Capture shows mode-specific limits before selection. Camera/microphone unavailability
or refusal leaves a supported file alternative; stopping media remains local until
Queue and send. Closing before admission can lose the transient selection; after
admission, use the same outbox's reconciliation. File selection cancellation is not
an acquired item. Untrusted files remain attachments; there is no malware verdict.

Drive-drop means the **existing configured Drive folder Source**, already watched
by the established connector. Save/copy one supported item into that exact folder
using the existing Drive/Files app; then inspect the Source's authoritative sync
job and Acquisition in local Knowledge. Drive's upload progress is not Provelume
acquisition. If no such Source is configured, say unavailable; do not invent a
folder, consent again, change Google scopes or start another watcher. This path
has its own existing Source provenance, not a forged Capture-device occurrence.

## Authenticated consultation

The local owner selects one active paired device, 1–16 existing Sources and a
60–86400-second lifetime, then explicitly confirms Knowledge read and Original
download permission. Paste the separately issued grant into Capture's consultation
panel. It is memory-only, independent from retained Capture pairing, and clears
on hiding/leaving the page, expiry, failure or Clear. Recent acquisitions and literal
search return at most 20 authorized matches. Provenance/version detail is inert
metadata; each exact Original requires an explicit authenticated attachment download.
Downloads are intentional user copies, separate from the disabled content cache.

Revoking the grant or device, origin rebinding, expiry or importing the Instance
without its original host key stops every read. Capture-only devices still cannot
read general Knowledge. Missing/corrupt Originals and unavailable search require
local recovery without repeating ingestion. The public shell worker excludes all
authenticated routes, query results and Originals from its persistent cache.
