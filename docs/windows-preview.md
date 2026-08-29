# Windows product shell preview

Provelume `0.7.0` is the published Vinculum Windows preview for provider-independent connector
identity, guarded HTTP(S) transport and explicit manual web acquisition. Download
[`Provelume-Setup-0.7.0-x64.exe`](https://github.com/gabned/provelume/releases/download/v0.7.0/Provelume-Setup-0.7.0-x64.exe)
from the official GitHub prerelease and run it as the current user. Git and a separately installed
Python are not required.

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
runtime after installation. `0.7.0` adds connector containers to the existing schema-2 Instance
without a new whole-Instance migration and retains the registered schema-1 to schema-2 migration
from `0.6.0`, including deep preflight and a verified automatic backup. The official release
evidence installs the immutable public `0.6.1` executable, creates a synthetic Instance and
launcher settings, installs `0.7.0` in place and verifies stable AppId, exact current-schema
Instance/settings preservation, startup and uninstall. The published installer is `18,464,821`
bytes with SHA-256 `46d7df0f94f3e9431685741594489ffcc99e0edf3f4880644c87e280fdecd5cb`.

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

No background check is enabled by default. `0.7.0` never applies an update silently.

## Recovery and limitations

If a selected Instance was moved or removed, the launcher reports the problem and keeps Choose and
Create available instead of silently creating a replacement. If a configured external Inbox
folder disappears, Inbox processing fails without creating a replacement directory. If an update
check or download fails, the installed runtime and Instance are unchanged. A partial file is not
promoted to the final installer name. The user can retry or download a release asset manually.

The preview installer is not Authenticode-signed. Windows may show SmartScreen. SHA-256 agreement
with metadata fetched through the same release transport is consistency evidence, not independent
publisher authentication. Automatic rollback, interrupted-install recovery, offline update
bundles and signed publisher identity remain later milestones.
