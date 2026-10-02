# Cura S09 shell preferences and qualification

This PRODUCT development candidate follows #255, #247 and #167. It does not
activate the preview interface by default, change the release version, publish
an installer, or establish delivery of the preceding slices. Ordered integration
and post-merge qualification remain required.

## Preferences

The browser uses the existing ShellSettingsManager, OS lock, atomic replacement
and monotonically increasing revision. `/settings/preferences` is local-only.
Reset and JSON import require a server-rendered before/after preview, explicit
confirmation, the existing CSRF token and a single-use mutation nonce. The dialog
supports keyboard cancellation and defaults focus to Cancel. Without JavaScript,
the same explicit confirmation remains available. Cancelling does not mutate
preferences. A revision or preference digest change invalidates confirmation.

The three reset scopes are appearance/language, notifications/background, and all
host preferences. Knowledge, Originals, Sources, credentials, job history,
backups, the selected Instance, Capture pairing and its existing outbox remain
outside this transaction. No Instance data is deleted. Endpoint changes require
an explicit service restart; login registration changes require installed Windows
and roll back the preference transaction on failure.

The complete browser transfer is a bounded, closed, secret-free JSON schema v2.
It includes notification, interface, startup and updater choices, but no paths,
content, credentials or receipts. Import validates duplicate keys, nesting,
types, enumerations and size before displaying a preview. The historical CLI
schema v1 export/import retains its existing partial-transfer semantics. Browser
import accepts v1 and preserves current preferences omitted by that format.

Undo is a new forward transaction, with fresh audit receipts when appropriate.
Its transient plan expires after ten minutes, server restart, a competing change
or one use. Plans are bounded in memory and are not another job queue or durable
settings authority. No previous audit receipt is rewritten.

## Appearance and tray

Persisted System/Light/Dark is rendered in the HTML before styles load. Native
appearance is applied before widgets are created, using the Windows system choice
for System; OS high contrast retains the native palette. There is no theme-change
animation. Close-to-tray and login startup remain independent. The first close
in each process explains continuation in the notification area and permits Cancel.
Exit stops the service, removes the notification icon and destroys the shell.

The compact native menu exposes Open, queue status, Settings, Pause/Resume,
Restart and Exit. Pause/Resume opens existing job selection and confirmation in
Scheduler; it does not create a global pause flag or an independent queue.
Single activation opens this menu; keyboard activation is supported. Explorer's
TaskbarCreated notification re-adds the icon. The existing canonical icon assets
are reused; actual installer, taskbar, upgrade and cache behavior still needs
native Windows qualification.

`/api/v1/shell/queue` is a local-only, no-store projection of Scheduler and
Action Center. It contains only queued/running/paused counts and a complete
attention count. Unknown or content-bearing fields are rejected. Incomplete
attention is unavailable, not zero. Service errors and unavailable observations
remain visible. Polling is bounded, proxy-free, redirect-free and rejects stale
observations from a previous Instance, port or service process. Tray progress is
coarse running/count state; no percentage, age or ETA is inferred from missing
authoritative data. Detailed progress remains in the existing Scheduler UI.

Microsoft's native contracts used here are [Shell_NotifyIconW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw),
[NOTIFYICONDATAW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw)
and [Taskbar creation](https://learn.microsoft.com/en-us/windows/win32/shell/taskbar#taskbar-creation-notification).

## Acceptance matrix

For each of en/it/de/es/fr/pt/ro qualify seven integrated journeys: daily status,
Capture, authenticated Knowledge retrieval, Inbox review, Action Center,
maintenance/recovery, and host preferences/tray. Exercise success, empty, pending,
running, paused, needs-attention, unavailable, rejection, cancellation and recovery
where meaningful, through the existing authoritative operations.

Keep automatic contract tests, actual browser UX, native Windows/tray/installer,
real iOS/Android journeys, screen-reader/high-contrast/200% zoom and linguistic
review as separate evidence. A responsive desktop viewport is not a real mobile
device test; a pure palette or lifecycle model is not a native accessibility test.
Catalog completeness and structural validation are not human linguistic review.
The maintainer attested real S08 review of 1,988 sensitive items in seven languages
in [the durable S08 record](https://github.com/gabned/provelume/pull/304#issuecomment-5946325092).
Those items retain identical text/key/context/reference dependencies here. This
candidate adds 34 sensitive keys (238 items). The maintainer separately confirmed
their human review in [the durable S09 record](https://github.com/gabned/provelume/issues/306#issuecomment-5946619851),
identifying full batch `7d1d1ec14e49c42f23dc14ea25cd1c7a85618dee601dab3decbf2cddf6fba5fb`.
Both records are MAINTAINER_ATTESTED, not reviews performed by the agent.
No automatic-approval consumer policy/grant has been adopted.

The integrated matrix and native observations must be complete before selecting
the new default presentation. This candidate retains the existing default.
