# Windows product shell preview

Custodia 0.12.0 uses the verified outer installation kit and its unchanged Setup,
with the actual-publication receipt imported offline. Download only from the
[official release page](https://github.com/gabned/provelume/releases)
after its matching installation-readiness marker has been verified.
See [publication metadata installation](publication-installation.md) and the
[release qualification](qualification/0.12.0.md). Preparation of source or a
development installer does not establish public readiness. Historical previews
retain their original contracts.

Provelume `0.12.0` is the Custodia Windows preview with configurable loopback endpoint,
canonical icon/AppUserModelID, authoritative minimal tray, System/Light/Dark,
seven offline languages and the qualified daily-use presentation. Run its unchanged
`Provelume-Setup-0.12.0-x64.exe` as the current user. Git and a separately installed
Python are not required. The original shell contract remains in
[windows-shell.md](windows-shell.md).

## What is installed

### Updating from 0.10.1

The published 0.11.0 release belongs to the **preview** channel. A 0.10.1
installation checking **stable** excludes it and can misleadingly report that it
is up to date. Selecting preview reaches a second, known compatibility boundary:
the 0.10.1 updater accepts only manifest schema 1, while 0.11.0 uses schema 2 with
required publication metadata. The old client reports
`Windows update manifest fields are incomplete or unsupported`.

For this transition, obtain and verify the official 0.12.0 installation kit using
the [publication installation procedure](publication-installation.md). Extract the
complete kit, stop the running Provelume instance and close its launcher, then run
`release/Provelume-Setup-0.12.0-x64.exe` in place. Keep the adjacent release manifest
and `publication/` directory so Setup can import the matching receipt. Upgrade
preserves the separate Instance; do not create a replacement Instance or delete
its existing directory. A normal backup before upgrading remains advisable.

The 0.12 correction cannot change the parser already installed in 0.10.1. Published
0.11.0 assets remain unchanged. The newer reader accepts both existing schemas;
an unknown future schema must stop download and explain the official manual route,
without accepting unknown required fields or bypassing publication finalization.

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
runtime after installation. `0.12.0` retains the derived Perceptio representations and component
evidence and read-only integration over the `0.9.0` contracts without making Originals
non-authoritative. The registered schema-1 to schema-2 migration from `0.6.0` remains available.

The official release evidence installs the immutable public `0.10.0` executable and uses its matching immutable public wheel to prepare the qualified N-1 state. Before installing `0.12.0`, the test fingerprints the complete Instance tree; the `0.12.0` installer must preserve configuration, manifest, canonical records,
Original bytes and durable ingestion state byte-for-byte. First startup must expose the preserved
knowledge while leaving policies, jobs, receipts, maintenance/reconciliation runs and resource
snapshots empty. Stable AppId, launcher settings, startup, reinstall and uninstall remain verified.

## Cura preferences

A clean installation uses the Cura presentation and System language/appearance.
The first-run summary shows the detected language, endpoint, selected Instance and
close-to-tray/login choices. Upgrade preserves existing Current/Preview, language
and background preferences. Current remains an explicit presentation-only rollback.

Appearance/language, notifications/background and all-preferences resets show an
impact preview and require confirmation. Cancellation preserves every preference;
Undo is a fresh forward transaction. All reset scopes preserve Originals, Knowledge,
Sources, credentials, history, backups, pairing/outbox and the selected Instance.
Settings JSON export/import contains non-secret preferences only and previews changes.

Closing the window can keep the runtime active only under the selected tray policy;
first close offers cancellation. Exit stops the runtime and removes the tray icon.
Login startup is a separate opt-in. Tray counts are content-free projections of
the authoritative job/attention queues; Pause/Resume opens their existing controls.

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

For supported Folder Sources, use **Validate path** before **Register Source**. Windows
UNC paths such as `\\server\share\folder` use the network class. Open the same path
in Explorer under the same Windows user/session first. If a mapped drive is missing,
map it in Provelume's session or select the UNC path; elevation can change drive
visibility. EN/IT diagnostics distinguish reachability, permissions, authentication,
unsupported paths and bounded validation timeout. Registration validates again and
does not create a Source for an unavailable mount. Reconnecting at the configured
location retains the Source identity and previously acquired records.

**Sources → Exclusions** shows the Source's versioned safe defaults and individual
rules. Edit a rule, disable it or add an explicit include, inspect **Preview**, then
choose **Apply**. The Windows-hosted and direct local Browser use the same EN/IT
controls and bounded filesystem selection. Excluded subfolder descendants are not
enumerated or counted individually; a changed Source snapshot requires a new
preview. Rules govern future intake and preserve existing Originals, canonical
records and their reindexable content. See [per-Source exclusions](architecture/source-exclusions.md).

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

No background check is enabled by default. `0.12.0` never applies an update silently.

## Recovery and limitations

If a selected Instance was moved or removed, the launcher reports the problem and keeps Choose and
Create available instead of silently creating a replacement. If a configured external Inbox or
folder Source disappears, processing changes to visible missing/error state without creating a
replacement directory or deleting acquired knowledge. If an update check or download fails, the
installed runtime and Instance are unchanged. A partial file is not promoted to the final installer
name. The launcher distinguishes catalogue, manifest, release-identity and installer-download
failures and shows a bounded reason code for rate limiting, HTTP, TLS, timeout, DNS or connection
problems. The user can retry or open the canonical GitHub release archive explicitly to download a
release asset manually.

The preview installer is not Authenticode-signed. Windows may show SmartScreen. SHA-256 agreement
with metadata fetched through the same release transport is consistency evidence, not independent
publisher authentication. Automatic rollback, interrupted-install recovery, offline update
bundles and signed publisher identity remain later milestones.

The Perceptio release retains the fail-closed signing verifier and explicitly classifies the generated
executable, installer and uninstaller as unsigned. Descriptive Publisher/version
metadata does not eliminate `Unknown publisher`. Authentic qualification remains blocked on an
authorized certificate, valid chain, expected publisher, valid timestamp and permanent
verification of the exact artifact; no key or certificate is included here.

## Rollback and removal

Export shell preferences and make a verified Instance backup before upgrading. To roll back,
uninstall `0.12.0`, install an earlier immutable official installer, and restore only a backup that
was created by or proved compatible with that version into a separate directory. There is no
silent schema downgrade. Uninstall removes program files, shortcuts and registration but preserves
launcher settings, downloaded-update state and every Instance; delete those only as a separate,
explicit data-removal decision.
