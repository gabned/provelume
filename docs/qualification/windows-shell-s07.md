# S07 Windows shell exact-head qualification matrix

This is the reproducible evidence contract, not a claim that a candidate or release has passed.
Actual candidate head, run IDs, attempts, findings and post-merge results are recorded on issue #155,
its single owner PR and tracker #137. A failure, cancellation or timeout is never converted to
success here.

| Gate | Platform | Exact-head evidence required | Privacy/bound |
| --- | --- | --- | --- |
| Ruff + complete Core suite | Ubuntu, Windows | Public CI success; Windows partition union complete | 10-minute permanent job unchanged |
| Windows shell smoke | `windows-latest` | icon/resources, metadata, AUMID, shortcuts, frozen-executable Win32 tray add/update/actions/delete plus deterministic service harness, endpoint, collision rollback, loopback listener, process/socket cleanup, unsigned state | 45-minute job, synthetic paths only |
| Installer lifecycle | Windows | clean install, custom/default port, upgrade preservation, uninstall preservation | no certificate, credential or Instance content |
| Signing truth | Windows exact artifacts | `NotSigned` accepted only in explicit development mode; release mode fails closed | SHA-256 and status only |
| Browser UX/accessibility | local EN/IT | grouped landmarks, keyboard semantics, live errors, theme, forced colors, zoom/reflow, reduced motion, inert hostile values | script-free CSP, no remote asset |
| Endpoint security | all + Windows installed | default/custom/reserved/occupied/corrupt/concurrent/replay/stale/apply/rollback/reset/transfer | loopback only, no firewall/random/network |
| Cross-source qualification | Ubuntu/Windows | permanent synthetic smoke success | unchanged Source isolation |
| Transcript | Ubuntu/Windows | permanent real-parser synthetic smoke success | no network/provider |
| OCR | qualified permanent matrix | permanent smoke success | no runtime download/remote fallback |
| Email | Ubuntu/Windows profiles | permanent smoke success | exact synthetic bytes, no provider |
| Google | synthetic only | permanent synthetic smoke success | no real credentials or qualification claim |
| Trusted base | GitHub trusted base | exact base/head change-control success | no untrusted workflow execution |

The icon is reproduced by `scripts/generate_windows_icon.py --check`. Windows packaging invokes the
same check, embeds `version_info.txt`, then runs `verify_windows_signature.ps1` against executable
and installer. The shell smoke invokes the installed frozen executable to exercise the real
`WindowsTray` notification-area add, update, bounded actions and delete path, then repeats exact
installed metadata/icon/signature checks. It emits one bounded JSON file with commit, port, PASS
codes and booleans only. A sanitized `qualification_incomplete` record remains uploadable if an
earlier step fails. The collision fixture uses a bounded child CPython socket with the same
`SO_EXCLUSIVEADDRUSE`, IPv4 loopback bind and listen sequence as the application probe, waits for a
synthetic readiness marker, remains alive for at most 120 seconds, fails separately if it expires
before installer validation, and always terminates the holder. Bounded stage-specific failure codes
identify the failed contract without serializing exception text, paths or private content.
For a fresh installation, Inno invokes the frozen executable's closed `--validate-port` mode before
initializing preferences; an unavailable selection raises the localized setup error. Upgrades with
existing compatible settings preserve them and do not probe a potentially running configured service.
The installer first probes the already parsed decimal port with a fail-closed IPv4-loopback socket
bind in `PrepareToInstall`, before any file copy. The frozen launcher performs the second check before
atomic preference apply. The permanent smoke requires the occupied fixture to remain live, a non-zero
installer exit, no installed runtime and no preference residue.

For a pull request the workflow explicitly checks out and records
`github.event.pull_request.head.sha`; it never substitutes GitHub's synthetic test-merge ref for the
candidate head. Push and manual runs use `github.sha`. Checkout, embedded build identity, installer
metadata and smoke evidence must all equal that one qualified SHA.

The S06 timeout finding remains historical evidence: run `33520782921`, jobs `99899187383`,
`99902830064`, `99906749116`, all non-green at the 10-minute job limit. S07 can close that finding
only after the unchanged candidate head completes Windows Core positively and no child process,
socket or file lock remains.
