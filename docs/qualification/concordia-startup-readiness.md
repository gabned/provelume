# Concordia S01 startup qualification matrix

This is a test/support contract, not a PASS receipt. The single owner of
[#393](https://github.com/gabned/provelume/issues/393) records exact source, tree, environment,
artifact hashes, original results and actual-main acceptance in its PR ledger. No exception
or human qualification is inherited from Entitas. [EN](../architecture/startup-readiness.md) /
[IT](../architecture/startup-readiness.it.md) architecture.

## Pre-test identities and controls

- Application package identity stays 0.14.0 during S01; development installer bytes are not an
  official 0.15.0 release. Final 0.15 identity and 0.14/0.13 upgrade matrices belong to the final
  exact artifact, and cannot be claimed by testing development bytes now.
- Source reference uses the repository's CPython/Node runtime and canonical bootstrap.
  Windows CI uses its recorded Server 2025/CPython/build inputs; it is not Windows 11.
- Installed input closes wheel, frozen executable, Setup, dependency lock, CPython patch,
  architecture, schema, image/runtime versions, SHA-256, unsigned-development boundary and
  source/build identities before testing. The existing build/installer smoke supplies those
  inputs. No external Python is needed by the installed application.
- The frozen control uses the runner's PowerShell 7/.NET toolchain. That is a test-control
  dependency, not a new application/runtime requirement. Only disposable synthetic state,
  local NTFS directories and selected loopback ports are used.
- Native Windows 11 25H2 x64 **Home and Pro have separate rows**, fresh local per-user test
  accounts/fixtures and original OS/build evidence. A personal installation is not silently
  replaced or inspected. Real accounts/files and remote effects require their own authority.

## Evidence families

| Case | Automatic/source controls | Installed/native/human controls still required |
| --- | --- | --- |
| Bootstrap | Bounded frame, short reads/EOF, duplicate/extra/version/type/encoding errors; no key in argv/environment/diagnostics | Exact windowed executable receives framed stdin with `sys.stdin=None`; no key file or inherited bootstrap channel |
| Readiness | Starting/ready schema/status, framed HMAC, stale nonce, wrong proof/port/Instance/root, generic 200/HTML, redirect, oversized/chunked/ambiguous body | Normal Panel-owned child, foreign listener/race and actual frozen invalid-initialization cases |
| Critical initialization | Modified installation blocks before Instance open; ordinary `/health` remains deep; optional OCR absent does not add a gate | Exact installed integrity/schema/recovery errors, new/existing synthetic Instance and independent identity/readback |
| Root identity | Real directory identity, replacement detection/denial and handle release; no path-string binding | Windows aliases, reparse chains, changed parent/root, NTFS permission/unsupported identity cases on each supported profile |
| Time and work | Fake monotonic phases, 10/5/60/75 limits, one probe, 240 maximum, slow-drip absolute probe limit, no late READY | Recorded cold/warm normal times and delayed/failed cases; normal 30-second smoke unchanged; no invented SLA |
| Cancellation | Stop during preparation/spawn/probe, late child cleanup, no page opening, no concurrent retry | Actual Panel/tray Stop/Restart/Quit during these boundaries, no orphaned processes/sockets/locks |
| Windows ownership | Native attempt event and inherited Job membership; Job escalation proves zero active processes | Exact packaged managed launcher with active synthetic work, interrupted commits and recovery/Original preservation |
| Unknown cleanup | Retained worker/process/resources, truthful unconfirmed UI, blocked restart/switch/Quit, later reconciliation | Native OS fault cases and operator-visible recovery; absence of observation remains UNKNOWN |
| Preferences | Existing revision-guarded endpoint receipts; later preference edits remain authoritative | Normal and failed pending-port restart, rollback readback and preserved other settings |
| Pages | Empty/whitespace Search and About avoid deep summary; positive Search and `/health` retain checks | Internal browser: managed start → Search/About → result/document/back, empty/error/slow cases, actual keyboard interaction |
| UI/languages | Seven complete offline catalogs, closed diagnostics and tray state; automatic parity is not linguistic review | EN/IT semantics, other-language review, System, keyboard/focus, supported themes/DPI and actual presentation |
| Compatibility | Existing API/browser/installation regressions; ordinary unbootstrapped serve has no private route | Clean/existing candidate install, reinstall/uninstall; final exact 0.15 upgrades repeated in final workstream |

`scripts/test_windows_startup_readiness.ps1` is called by the permanent Windows shell smoke
after executable identity validation. It independently computes FileIdInfo/framed HMAC using
.NET/Win32, checks the bounded frozen response, requests cooperative stop and records owned
test-child cleanup. Its report explicitly does **not** qualify the managed Panel UI or Windows
11. The same control also runs in the common Windows installer/upgrade driver, including
native-library distribution wheels, after independent installed identity checks. It retains
`startup-readiness-<previous-version>.json` for each synthetic public baseline so a different
installer composition never inherits the base installer's result. The original report is
embedded in `windows-shell-evidence.json` and the installer summary; source subprocess,
TestClient, screenshots, generic HTTP success and Server 2025 are not substituted for the
internal-browser/Windows 11 rows.

## Gate before acceptance

Run the full native Ruff/pytest/diff gates on the unchanged committed candidate, complete all
CI runs/attempts/jobs and required original rereads, inventory every review/finding/thread,
retain the original effect binding and perform fresh normal integration preflight. Missing
mandatory native/browser/human inputs block acceptance; they are not waivers or green checks.
Only after normal merge and actual-main checks may S01 be accepted and #377 start. Scope,
version/publication, OCR/Inbox/UX/search changes and Protocol lifecycle v2 remain separate.
