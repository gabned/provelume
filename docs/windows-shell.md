# Windows shell installation, endpoint and recovery guide

This guide covers the Windows shell published with the `0.9.0 — Lectio` preview. Package,
executable, installer and uninstaller metadata all use `0.9.0`.

## Install

The per-user installer shows the Provelume identity and uses the versioned icon. A desktop shortcut
is optional. **Use the system tray by default** is selected; **Start at Windows login** is a
separate unchecked task. A new install uses `44851`. The advanced endpoint page may accept one
explicit port from 1024 to 65535. Final installed-code validation rejects an occupied port and
rolls setup back. Before copying files, Setup also performs a fail-closed bind to IPv4 loopback with
the already validated decimal port. Failure to run that system probe is treated like a collision;
the installed launcher repeats the check before atomically applying preferences to cover a race.
Setup never opens the firewall, changes the host or chooses another port.

Existing compatible launcher settings cause the endpoint page to be skipped. Upgrade replaces
only runtime files and reconciles the existing login preference. It does not rewrite the endpoint,
theme, tray choice, Instance or provider data.

## Daily lifecycle

Normal installed startup creates one shell, starts one loopback service and exposes the native
tray. Closing the main window hides it. The native menu provides Open Provelume, current service
state, active local endpoint, Shell settings, Restart local service and Exit Provelume. Exit stops
and waits for the child; crash remains visible and requires an explicit restart. Tray opt-out makes
window close perform controlled exit. Login startup can be enabled or disabled independently; its
`--tray` launch starts hidden only when the configured native tray is actually available.

## Endpoint CLI

```text
provelume shell-config
provelume validate-endpoint 44851
provelume set-endpoint 49152 --expected-revision 3
provelume reset-endpoint --expected-revision 4
provelume shell-restart-plan
provelume shell-diagnostics
provelume recover-shell-settings
```

`set-endpoint` persists only after range and occupied-port checks. It records a restart plan but
does not restart automatically. `reset-endpoint` restores `44851`; it can fail if that port is
occupied. An explicit `provelume serve INSTANCE --port N` overrides the persisted value for that
process only. Host remains loopback.

Browser settings at `/settings/shell` offer the same port, tray, login, language and theme choices
only to the local authorized Browser. A mutation is rejected when its CSRF token, one-time
reference or revision is invalid/stale, or when a field is unknown or duplicated. The page and
`GET /api/v1/shell` distinguish the active service endpoint from a configured restart target;
there is no public API mutation.

## Theme and accessibility

System, Light and Dark are persisted outside the Instance and applied on the root HTML element
before useful rendering. The Browser provides visible focus, skip navigation, landmarks/headings,
labelled controls, live errors/status, keyboard-native grouped navigation, reflow, forced-colors
and reduced-motion behavior. EN and IT have equivalent controls. Icons never replace text.

## Backup, export and restore

```text
provelume backup-shell-preferences shell-preferences.json
provelume restore-shell-preferences shell-preferences.json --expected-revision N
provelume export-shell-preferences shell-preferences.json
provelume import-shell-preferences shell-preferences.json --expected-revision N
```

The portable file excludes Instance/source paths and content. Restore validates the closed schema,
size, symlink/reparse boundary and port availability, then applies once under the lock. Back up the
portable Instance separately; shell transfer does not include Originals or canonical knowledge.

## Upgrade, rollback and uninstall

Upgrade preserves compatible preferences and Instance data. Uninstall stops/removes the runtime,
shortcuts, product registration and stale login Run entry. It deliberately leaves launcher
preferences and every Instance. Lectio offers no combined “delete my data” option; deletion
requires separate explicit informed consent.

Before upgrading, make a verified Instance backup and export shell preferences separately. A
rollback means uninstalling Lectio, installing an earlier immutable official installer and then
opening only an Instance compatible with that earlier version. Provelume does not silently
downgrade schemas or canonical records; if compatibility cannot be established, restore the
matching verified backup into a separate directory. Never overwrite the current Instance as a
rollback shortcut.

## Signing and Publisher blocker

Lectio Windows release artifacts are explicitly unsigned. `Neobeta` in file or Add/Remove Programs
metadata is descriptive and does not authenticate the Windows publisher. `Unknown publisher` can
remain. Signed-release mode requires an authorized certificate, valid chain, expected
publisher, valid timestamp and verification of the exact SHA-256 artifact in permanent evidence.
No private signing material belongs in this repository.

## Errors and recovery

- `port_unavailable`: stop the conflicting local process or explicitly choose another bounded
  port; no automatic alternative is selected.
- `stale_configuration`: reload current settings and deliberately resubmit.
- `configuration_busy`: wait for the current local mutation to finish.
- invalid/corrupt settings: safe `44851`/tray/system defaults are used with a warning; the corrupt
  file is not silently overwritten.
- failed service after a port change: the exact previous known port may be restored, but restart is
  still explicit.
- abandoned atomic temporary files: `recover-shell-settings` removes at most 32 matching files
  under the lock and reports counts only.

Diagnostics are bounded and sanitized. They include endpoint, checksums/status, counts, schema and
unsigned state, never source content, URL query data, paths, credentials, CSRF tokens or nonces.
