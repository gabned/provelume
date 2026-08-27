# Windows product shell preview

Provelume `0.4.0` is the first release intended to be installed as an ordinary Windows product.
Download `Provelume-Setup-0.4.0-x64.exe` from the official GitHub Release and run it as the current
user. Git and a separately installed Python are not required.

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
runtime after installation; `0.4.0` introduces no Instance schema migration.

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

No background check is enabled by default. `0.4.0` never applies an update silently.

## Recovery and limitations

If a check or download fails, the installed runtime and Instance are unchanged. A partial file is
not promoted to the final installer name. The user can retry or download a release asset manually.

The preview installer is not Authenticode-signed. Windows may show SmartScreen. SHA-256 agreement
with metadata fetched through the same release transport is consistency evidence, not independent
publisher authentication. Automatic rollback, interrupted-install recovery, offline update
bundles and signed publisher identity remain later milestones.
