# ADR 0020: Windows shell identity and configurable loopback endpoint

- Status: Accepted for the unreleased `0.9/S07` product slice
- Date: 2026-09-01
- Owners: product workstream issue #155 under tracker #137
- Public identity: unchanged `0.8.0`

## Context

Lectio needs a coherent installed Windows shell and one explicit local endpoint contract before
release preparation. The prior launcher chose an ephemeral port on each start, had no notification
area lifecycle, used generic executable resources, and exposed a crowded flat Browser navigation.
Those choices were acceptable for an early preview but are not a stable product boundary.

The post-merge S06 Public repository CI run `33520782921` also exhausted the permanent 10-minute
Windows Core job in three attempts. Jobs `99899187383`, `99902830064`, and `99906749116` reached
approximately 81%, 96%, and 88% of the suite. Their interrupted stacks were respectively in
ordinary storage, YAML scanning, and temporary-file work rather than one common test or wait. The
evidence therefore identifies cumulative serial Windows filesystem cost inside the whole-job
budget, not a demonstrated single deadlock. The failed/cancelled S06 gate remains recorded as such.

## Decision

### Identity and signing truth

`Provelume.Desktop` is the stable AppUserModelID. `Provelume` is the visible application,
installer, uninstaller, Start Menu and optional desktop-shortcut name. Executable version resources
remain truthfully `0.8.0`; S07 does not change package, runtime, embedded or published identity.

The public `assets/windows/provelume.svg` source and standard-library generator produce a checked-in
ICO containing 16, 20, 24, 32, 40, 48, 64, 128 and 256 pixel images. PyInstaller, Inno Setup,
shortcuts, Tk windows, taskbar and tray consume that family. If a tray cannot load the packaged
asset it tries the executable resource and only then a controlled system fallback. Every action
retains a visible EN/IT text label and accessible native name.

Development executables, installers and uninstallers are explicitly unsigned. Inno `AppPublisher`
and version resources are descriptive metadata, not publisher authentication. The signing verifier
has two explicit modes: unsigned development must be exactly `NotSigned`; a future signed release
fails closed unless the exact artifact has a valid Authenticode status, the authorized publisher,
a timestamp certificate and an exact SHA-256. No certificate, key, password or secret is stored.
Until authorized signing material and permanent exact-artifact evidence exist, Windows may show
`Unknown publisher`; S07 does not claim otherwise.

### Shell preference contract

Launcher state is a closed schema-2 JSON document under the platform state directory. It retains
the compatible schema-1 launcher fields and adds:

- a monotonic `revision`;
- `endpoint.host`, fixed to `127.0.0.1`;
- `endpoint.port`, `last_good_port`, and `restart_required`;
- independently selected `tray_enabled`, `login_startup`, and `theme` values.

Unknown fields, remote hosts, invalid types, oversize documents, symlinks and Windows reparse
points fail to safe defaults with a visible warning. Loading never rewrites corrupt state. A
cross-platform non-blocking OS lock, exact expected revision, bounded one-time Browser reference,
CSRF check, same-process service authorization and atomic write/replace protect mutation. Temporary
writes are fsynced; explicit recovery removes at most 32 abandoned temporary files under the lock.

Portable shell preference export contains only port, tray, login-startup preference, theme and
language. It excludes Instance path and every Original, Document, Version, Acquisition, Source,
provider value and secret. Import validates the closed contract before one atomic apply. Upgrade
preserves compatible settings; uninstall removes runtime and an unusable login Run entry while
preserving preferences and Instance data. User data deletion requires a separate future consented
operation.

### Endpoint

The stable default is `127.0.0.1:44851`. Ports 1–1023 are reserved; accepted explicit values are
1024–65535. There is no host setting, wildcard/LAN bind, firewall action, automatic discovery,
random fallback or hidden alternate port.

Precedence is:

1. an explicit process-only `--port` override, validated but not persisted;
2. a valid persisted schema-2 port;
3. `44851` for missing, legacy or corrupt endpoint state.

On a new install, the advanced page accepts an explicit bounded port. Immediately before file copy,
Setup runs a fail-closed IPv4-loopback socket bind using only the already parsed decimal port; an
occupied port, an unavailable system probe or a non-zero probe result stops Setup before runtime or
preferences are written. The installed executable repeats the occupied-port check before its atomic
settings apply, closing the preflight-to-apply race. Failure aborts and rolls back setup; it does not
propose or select another port. Upgrade skips the page and preserves existing settings. CLI and the
protected local Browser validate availability before persistence. A port change records the previous
known value and requires an explicit restart. Successful startup promotes the configured value to
known good. Failed startup may restore that exact previous value but does not restart or choose a
value automatically. Concurrent/stale changes fail visibly.

The API adds only `GET /api/v1/shell`, returning effective endpoint, service state, sanitized
configuration, capabilities, schemas, limits, warnings and provenance. It has no mutation route.
Browser mutation remains outside `/api/v1`, accepts only a loopback client and form content, and
requires CSRF, a one-time reference and the current revision.

### Tray and process lifecycle

Installed Windows mode enables the notification area by default; the user can explicitly opt out.
Starting at Windows login is a separate unchecked choice. Closing the main window with tray mode
enabled hides it and leaves exactly one child service. Tray actions open the Browser, show service
state and endpoint, open shell settings, restart the service, and exit. Open/reopen never creates a
second child. Restart first terminates and waits for the prior child. Exit waits four seconds,
terminates, then performs a bounded two-second kill/wait fallback. Crash is visible and does not
silently restart. A process mutex prevents a second shell.

### Browser usability and accessibility

Primary navigation is grouped into Knowledge, Operational status, Configuration, Maintenance, and
Diagnostics & support. Existing functions remain labelled. Server-rendered `data-theme` applies
system/light/dark before useful paint. Focus remains visible; native landmarks, heading order, skip
link, form labels/descriptions, live status/error regions, keyboard-native disclosure controls,
forced-colors support, reflow and reduced-motion rules apply in EN and IT. Color, icon, hover and
position are never the sole signal. Jinja autoescaping and the existing script-free CSP keep
markup, URLs, formulas, escape sequences and script-like values inert.

### Windows Core budget

The protected Public CI workflow and its 10-minute job remain unchanged. Only the bare Windows full
suite is partitioned into two concurrent subprocesses using `SHA-256(nodeid) mod 2`. The partitions
are stable, disjoint and complete; targeted invocations are untouched. Each subprocess receives an
isolated state directory. The parent has a 420-second bounded deadline, replays at most 2 MiB per
shard, reports only shard index/count/duration/exit code, and terminates the process tree on timeout.
Child pytest processes receive an explicit `--rootdir` anchored to the versioned configuration
directory and derived collection roots are never appended. The bounded harness selects a tracked,
non-recursive node ID under that same root; cross-volume forced targets are not part of the bare
full-suite production contract.
No test is marked skipped or removed from the union. A permanent Windows shell workflow separately
builds and exercises the exact-head installer, identity, collision rollback, loopback service,
the installed frozen executable's real Win32 notification add/update/action/delete lifecycle, the
deterministic service harness, cleanup and unsigned boundary.

## Consequences

- S07 adds product state outside an Instance without changing Core canonical authority.
- Port changes require an explicit restart and can be blocked by a current listener.
- Unsigned artifacts remain unsuitable for a future public signed-release claim.
- Successful candidate and post-merge Windows evidence is required before the timeout finding can
  be called resolved; the implementation alone is not positive exact-head evidence.
- `0.9.0` publication, version alignment, tagging and release assets remain a separate unauthorized
  workstream.
