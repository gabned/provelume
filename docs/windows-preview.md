# Windows product shell preview

Provelume `0.9.0` is the Lectio Windows preview with the configurable loopback endpoint, coherent
icon/AppUserModelID, tray lifecycle, theme and accessibility contracts described in
[`windows-shell.md`](windows-shell.md). Download `Provelume-Setup-0.9.0-x64.exe` only from the
official [`v0.9.0` GitHub prerelease](https://github.com/gabned/provelume/releases/tag/v0.9.0) and run it as
the current user. Git and a separately installed Python are not required.

## What is installed

The setup places a frozen launcher and bundled runtime under the current user's application
directory and creates a Start-menu shortcut. A desktop shortcut is optional. The first launch
creates `Documents\\Provelume` unless another Instance is selected.

Three locations remain intentionally separate:

| Content | Default location | Removed by uninstall |
| --- | --- | --- |
| launcher and runtime | `%LOCALAPPDATA%\\Programs\\Provelume` | yes |
| launcher settings and downloaded updates | `%LOCALAPPDATA%\\Provelume` | no |
| portable Instance and preserved originals | `%USERPROFILE%\\Documents\\Provelume` | no |

An upgrade replaces only launcher/runtime files. The portable Instance is opened by the new
runtime after installation. `0.9.0` adds derived OCR/email/transcript/qualification state plus
connector and shell settings without making Originals non-authoritative. The registered schema-1
to schema-2 migration from `0.6.0` remains available.

The official release evidence installs the immutable public `0.7.0` executable,
bootstrap a Unicode-path Instance and use the matching immutable public wheel to ingest synthetic
canonical knowledge and an exact Original. Before installing `0.9.0`, the test fingerprints the
complete Instance tree; the `0.9.0` installer must preserve configuration, manifest, canonical records,
Original bytes and durable ingestion state byte-for-byte. First startup must expose the preserved
knowledge while leaving policies, jobs, receipts, maintenance/reconciliation runs and resource
snapshots empty. Stable AppId, launcher settings, startup, reinstall and uninstall remain verified.

## Local Inbox folders

The `0.5.0` browser introduced, and `0.7.0` retains, **Settings** for:

- the Inbox display name;
- the Drop folder;
- the managed-copy folder.

The two folders may remain inside the Instance or use absolute locations elsewhere on the local
filesystem, including another local disk or an available mounted location. Canonical Originals,
knowledge, derived state, indexes, operation logs and reports remain inside the Instance.

A missing external location fails visibly and is not silently recreated. Backing up only the
Instance does not back up unacquired files waiting in an external Drop folder. After Inbox
acquisitions exist, moving the managed-copy folder is blocked until a separately designed verified
relocation workflow is available; the Inbox name and Drop folder may still change.

## Scheduler, folder Sources and maintenance

No scheduler policy or job is created by install, upgrade or startup. A user may explicitly add a
local, removable or already-mounted network folder Source and choose manual, bounded interval or
local-calendar observation. The schedule, timezone, DST behavior, quiet window, retry and
missed-run policy remain visible and independently enabled or paused.

Scheduled work runs only while the current local runtime is active. A network-class folder is a
path the operating system has already mounted; Provelume does not discover shares or negotiate
network credentials. Reconciliation, validation and resource observations do not authorize
repair, deletion, purge, cleanup or provider access. Thresholds report evidence only.

## Version and About

The launcher and local `/about` page show the package version, channel, source tag/commit,
packaging mode and current verification boundary. Reading them is offline. The existing Security
and Verify installation surfaces remain separate because descriptive identity is not an
integrity or signature verdict.

## Update flow

1. The user selects **Check now**, or explicitly enables a startup check.
2. Provelume discloses that it will contact GitHub Releases and sends no Instance content.
3. The transport selects the highest compatible semantic version in the chosen Preview or Stable
   channel and downloads the bounded `provelume-windows-update.json` asset.
4. Version, tag, commit, channel, platform, architecture, name and size must match the release.
5. On request, the installer downloads to launcher state, is bounded by the declared size and is
   accepted only when its SHA-256 matches.
6. Provelume requires another confirmation before starting the normal installer and closing the
   local server.

No background check is enabled by default. `0.9.0` never applies an update silently.

## Recovery and limitations

If a selected Instance was moved or removed, the launcher reports the problem and keeps Choose and
Create available instead of silently creating a replacement. If a configured external Inbox or
folder Source disappears, processing changes to visible missing/error state without creating a
replacement directory or deleting acquired knowledge. If an update check or download fails, the
installed runtime and Instance are unchanged. A partial file is not promoted to the final installer
name. The user can retry or download a release asset manually.

The preview installer is not Authenticode-signed. Windows may show SmartScreen. SHA-256 agreement
with metadata fetched through the same release transport is consistency evidence, not independent
publisher authentication. Automatic rollback, interrupted-install recovery, offline update
bundles and signed publisher identity remain later milestones.

The Lectio release contains a fail-closed signing verifier and explicitly classifies the generated
executable, installer and uninstaller as unsigned. Descriptive Publisher/version
metadata does not eliminate `Unknown publisher`. Authentic qualification remains blocked on an
authorized certificate, valid chain, expected publisher, valid timestamp and permanent
verification of the exact artifact; no key or certificate is included here.

## Rollback and removal

Export shell preferences and make a verified Instance backup before upgrading. To roll back,
uninstall `0.9.0`, install an earlier immutable official installer, and restore only a backup that
was created by or proved compatible with that version into a separate directory. There is no
silent schema downgrade. Uninstall removes program files, shortcuts and registration but preserves
launcher settings, downloaded-update state and every Instance; delete those only as a separate,
explicit data-removal decision.
