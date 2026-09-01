# S07 Windows shell exact-head qualification matrix

This is the reproducible evidence contract, not a claim that a candidate or release has passed.
Actual candidate head, run IDs, attempts, findings and post-merge results are recorded on issue #155,
its single owner PR and tracker #137. A failure, cancellation or timeout is never converted to
success here.

| Gate | Platform | Exact-head evidence required | Privacy/bound |
| --- | --- | --- | --- |
| Ruff + complete Core suite | Ubuntu, Windows | Public CI success; Windows partition union complete | 10-minute permanent job unchanged |
| Windows shell smoke | `windows-latest` | icon/resources, metadata, AUMID, shortcuts, tray harness, endpoint, collision rollback, loopback listener, process/socket cleanup, unsigned state | 45-minute job, synthetic paths only |
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
and installer. The shell smoke repeats exact installed metadata/icon/signature checks and emits one
bounded JSON file with commit, port, PASS codes and booleans only.

The S06 timeout finding remains historical evidence: run `33520782921`, jobs `99899187383`,
`99902830064`, `99906749116`, all non-green at the 10-minute job limit. S07 can close that finding
only after the unchanged candidate head completes Windows Core positively and no child process,
socket or file lock remains.
