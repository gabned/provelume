# Windows product shell preview

Provelume `0.5.1` is the current correction preview for the durable local-intake product surface
introduced by `0.5.0`. Download `Provelume-Setup-0.5.1-x64.exe` from the official GitHub Release
and run it as the current user. Git and a separately installed Python are not required.

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
runtime after installation; `0.5.1` introduces no mandatory canonical Instance schema migration.
Legacy search-index metadata is derived state and is rebuilt transparently. Candidate and official
release evidence installs the immutable public `0.5.0` executable, creates a synthetic Instance and
launcher settings, installs `0.5.1` in place and verifies that the stable AppId, Instance bytes and
launcher settings survive upgrade and uninstall.

## Local Inbox folders

The `0.5.0` browser introduced, and `0.5.1` retains, **Settings** for:

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

No background check is enabled by default. `0.5.1` never applies an update silently.

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
