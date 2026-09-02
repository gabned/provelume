# Windows shell and local endpoint architecture

This document defines the English architecture contract implemented by `0.9/S07` and published
with Lectio. The public product identity is `0.9.0`.

## Boundaries

The shell owns only launcher location, explicit update preference, language, loopback port, tray
behavior, login startup and visual theme. It cannot modify an Instance's Originals, Documents,
Versions, Acquisitions, Sources, provider state or canonical configuration. Shell state lives in
`%LOCALAPPDATA%\Provelume\launcher.json`; runtime files live under
`%LOCALAPPDATA%\Programs\Provelume`; the default Instance remains
`%USERPROFILE%\Documents\Provelume`.

| Surface | Read | Mutation | Authority |
| --- | --- | --- | --- |
| `GET /api/v1/shell` | sanitized endpoint/service/capabilities | none | public read-only API |
| `/settings/shell` GET | local settings view | none | loopback Browser |
| `/settings/shell` POST | current revision | bounded preferences | loopback + CSRF + nonce + revision |
| shell CLI | effective settings/diagnostics | explicit set/reset/import | local process + lock |
| installer | existing-state check | initialize new preferences | per-user setup, rollback on failure |
| tray | state and endpoint | open/restart/quit | single installed shell process |

## Closed configuration

Schema 2 accepts only the documented top-level, endpoint and shell fields. `host` must equal
`127.0.0.1`; port must be an integer from 1024 through 65535; theme is `system`, `light`, or `dark`;
language is `en` or `it`. Booleans are not accepted as integers. Documents over 64 KiB, unknown
fields, invalid schemas, symlinks and reparse points are rejected. Schema 1 is read compatibly and
migrates only on a later explicit save.

Missing/invalid state produces safe values plus `settings_missing_using_defaults` or
`settings_invalid_using_safe_defaults`. It never rewrites the input while reading. State mutation
uses a non-blocking platform lock, revision check, same-directory temporary file, flush/fsync and
atomic replace. Explicit crash recovery removes a maximum of 32 matching temporary files and no
other path.

## Endpoint lifecycle

- Default: `http://127.0.0.1:44851`.
- Explicit override: process-only `--port`, highest precedence.
- Persisted override: validated, reversible and retained over upgrade.
- Missing, legacy or corrupt endpoint: default `44851` with a warning where applicable.
- Occupied port: a fail-closed installer loopback bind stops before file copy; installed code
  rechecks before atomic apply, and configuration is not changed during preflight.
- Race after preflight: service startup fails, may restore the exact previous known port, and waits
  for an explicit restart.
- Successful startup: clears `restart_required` and records the same port as known good.
- No random port, remote host, wildcard bind, DNS discovery, firewall rule or network fallback.

The service uses Uvicorn only on an explicitly validated loopback host. Local Web middleware also
rejects untrusted Host values. Every mutative Browser request uses service authorization,
loopback-client validation, the existing script-free same-origin policy, CSRF, a ten-minute
one-time reference (maximum 64 active), and an exact expected revision. A consumed, replayed or
stale request cannot mutate state. Unknown, missing-required or duplicated fields fail before the
one-time reference is consumed. Inspection reports active service and configured restart endpoints
separately.

## Tray and service state

One named mutex guards the shell. The installed default creates one native notification icon and
starts one child service without opening a random endpoint. Closing the window hides it only when
the configured tray is available; opt-out performs controlled exit. Open and settings actions
reuse a ready child. Restart stops/waits before starting a replacement. Crash is announced as a
state and is not automatically retried. Quit deletes the tray icon, stops/waits/kills within the
documented limits and destroys the window. Login startup is an independently persisted choice and
uses one quoted absolute installed executable in the per-user Run key; uninstall removes only that
unusable Run entry. Its explicit `--tray` mode hides the initial window only after the native tray
has started successfully; a controlled visible window remains when the tray is unavailable.

## Identity, packaging and signing

`assets/windows/icon-manifest.json` binds the public SVG, deterministic generator, ICO and complete
size list. PyInstaller embeds the ICO and truthfully fixed `0.9.0` version resources; Inno uses it
for setup/uninstall and explicit shortcut icon resources. Both shortcuts carry
`Provelume.Desktop`. The process sets the same AppUserModelID before creating Tk windows.

All S07 development artifacts are unsigned. The manifest and diagnostics say `unsigned` or
`publisher_authentication: not_established`. Descriptive `Neobeta` metadata cannot authenticate a
publisher. Release signing is blocked until an authorized certificate/private-key process outside
the repository can provide a valid chain, timestamp, expected subject and exact-artifact permanent
evidence. The verifier rejects invalid/unexpected signatures even in development mode.

## Preference transfer and privacy

Export/backup schema 1 contains only endpoint port, tray, login-startup preference, theme and
language. Import/restore validates size, fields, path type and port availability before atomic
apply. It never contains the Instance path, source/provider data or credential references.
Diagnostics contain schema/capability/status codes, bounds, endpoint and signing state only; no
URL query, document content, source path, token, CSRF value or nonce is logged.

## UX and accessibility

Five labelled navigation groups—Knowledge, Operational status, Configuration, Maintenance, and
Diagnostics & support—separate content from operations, configuration, maintenance and support.
Icons supplement text. System/light/dark variables preserve focus and contrast; system
choice follows `prefers-color-scheme`; `forced-colors`, 200% zoom/reflow and
`prefers-reduced-motion` have explicit rules. All forms have labels/help, errors use `role=alert`,
saved state uses a polite live region, and native menus/disclosures remain keyboard accessible.
English and Italian catalogs expose the same semantic keys.

## Qualification

The exact-head matrix requires Ruff, all local tests, deterministic icon check, endpoint/security/
accessibility regressions, Public CI, trusted-base guard, Windows shell smoke, cross-source,
transcript, OCR, email and Google synthetic smokes. Candidate Windows Core must complete within the
permanent job budget. Any failure, cancellation or timeout remains a failed gate.
