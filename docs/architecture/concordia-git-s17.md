# Concordia S17 — one-way Git transport

This homogeneous PRODUCT workstream consumes the unaccepted S16 candidate
`1ef7bd97da7d031dbd13d1e25ff3c20d705f2176` under the [ordered development authority](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974).
It retains ordinary main `fadeb47f84004d48b282046e36bb3081cd1d878b`, S07's original
CPU findings/BIND/results, and the [explicit read-only Asana/Tududi decision](https://github.com/gabned/provelume/issues/383#issuecomment-6711131611).
No predecessor acceptance, real account, remote destination or publication
authority is inferred. Human checks remain DEFERRED_BY_MAINTAINER / NOT_RUN until
the completed official release on the maintainer Windows 11 Pro 25H2 PC.

## Transport and authority

Git consumes only a verified S16 complete immutable generation. Each destination
binds repository, branch, owned path, commit name/email, exact policy/include rules,
device/grant epoch and current ref/inventory. Disabled/local-only/no-GitHub/no-rsync
controls are checked before any process or credential access. Status and passive
pages never run Git. Git remains optional; no-Git personal/offline use is complete.

The local disposable bare-repository profile and each hosted profile have distinct
qualification. S18–S20 prove GitHub/GitLab/Gitea account, permissions and visibility;
their PASS cannot be inherited from a local transport fixture. Unknown visibility
blocks private payload. Public publication requires S16's exact allowlist and
fresh explicit confirmation. SSH transport/host-key support is not guessed.

Credentials remain in the device OS vault. This local-only profile admits only
an empty credential reference; hosted helpers remain unqualified until S18–S20.
No token/password is placed in canonical/portable data, URLs, argv, commit messages,
evidence or ordinary logs. Repository and system Git
configuration, hooks, external protocols and prompts cannot introduce an implicit
credential helper or arbitrary process. Source/frozen helper behavior is qualified
separately on each supported host before being advertised.

## Ref and generation semantics

An independently read ref and complete current owned inventory precede the preview.
Any changed destination/source/policy/identity invalidates it. Repeat publication
of the same active manifest creates no needless commit or payload upload; fresh
native read/fetch verification is still required. A new commit
retains every previous generation and unrelated path, updates the owned active
pointer and has exactly the expected ref as its parent (or no parent for a proved
absent branch). No destination deletion, pruning, history rewrite or automatic
merge/rebase is permitted.

The update uses an explicit expected-ref lease only after proving that direct
parent relationship. Git's documented `--force-with-lease=<ref>:<expected>` pins
the exact old ref (empty requires absence); it grants no non-fast-forward update
in this implementation. A different or concurrently changed ref is a conflict.
The immutable candidate commit/operation claim is persisted before sending once.
Timeout/interrupt is UNKNOWN, with no replay. Read-only reconciliation checks the
recorded candidate and exact active inventory; it never selects a favorable retry.
The claim/terminal receipt resides in S16's external vault ledger: an Instance
restore cannot reopen it. Even when the local operation journal is absent after
restore, read-only reconciliation reconstructs the deterministic candidate from
the predeclared parent/tree/identity/date/operation and verifies the actual ref,
active pointer and every payload SHA-256. Matching payload values alone are not
proof. A missing/old/different ref remains UNKNOWN and never permits replay.
Receipts distinguish direct verification from reconciled current state; receipt
completion time is not a reconstructed publication time (that field stays null).
Last valid remote history and canonical knowledge survive every failure.

## Bounds and qualification

Before qualification the transport fixes: 120 seconds overall per explicit
operation, 30 seconds per ordinary command within that deadline, 64KiB captured
ordinary diagnostic output, 2MiB stdin/structured metadata and up to the unchanged
32MiB S16 bound for a separately verified blob payload; 512MiB admitted local Git
object storage, 5,000 admitted tree files
and the unchanged S16 payload/manifest bounds. Before sending, a conservative
growth admission includes the complete new payload, manifest and 32MiB Git pack/index
overhead within the fixed 512MiB destination cap. An oversized fetched repository,
disk-full, missing Git/version/credential, unsafe root/config/hook/alternate,
unsupported protocol or unproved activation fails visibly before publication.
No retry, limit increase, secret-bearing config or hook is used as a fallback.

CLI controls are `mirror-git-status`, `mirror-git-initialize`, `mirror-git-prepare`,
`mirror-git-publish` and `mirror-git-reconcile`; the actual frozen operator exposes
the same controls. Configuration remains an explicit external JSON file passed to
the shared identity/configure commands. Only a fresh absent private bare root may
be initialized. Existing roots/config/helpers/hooks/alternates/links are never
silently adopted or repaired. Filesystem locality and pinned parents precede all
target metadata probes; physical parent/root paths exclude canonical and registered
Source roots without resolving or contacting those Source inputs. Initialization
rechecks that the actual pinned root is empty before Git may write to it. Any
unexpected preexisting content remains intact. The local UI shows branch/path/commit identity,
exact preview, confirmation, conflict/UNKNOWN and historical receipt limitations.

The existing `mirror.prepare` scheduler publishes this profile only for a current
explicit scheduled policy, with its unchanged 60-second job deadline, single
attempt and interval checks. Inflight claims stop admission before Git starts;
there is no automatic retry or credential fallback. Any conflict, UNKNOWN or
native error fences that policy revision in the external vault before another scheduled Git
attempt, even after its interval expires. An operator must review/reconcile the
outcome and explicitly configure a new policy revision to resume; unresolved
external claims remain blocked regardless. Restoring an older Instance checkpoint
cannot erase the external policy fence. Other profiles retain their
unqualified local-staging behavior. The existing 16-plan/eight-generation capacity
is not enlarged or automatically pruned: exhaustion requires explicit local
operator cleanup or a newly scoped destination.

`git-mirror-qualify` exercises actual native Git and same-root restore through the
dedicated frozen entry. Installed Windows qualification keeps empty PATH for all
previous OCR/personal/connector/shared-mirror cases; the separate Git case admits
only explicit Git installation directories and Windows System32, records the Git
binary identity/version and requires no external Python. Git remains optional
and is not bundled as a new product dependency. POSIX process groups and Windows
creation-time Jobs own descendants; no uncontained Windows fallback is allowed.

Tests and the frozen automatic operator path use fresh synthetic local bare
repositories only. The matrix covers branch/path/commit identity, new and repeated
generations, retained unrelated/history data, changed ref/NFF, rejected credentials,
interruption before/after send, read-only recovery, tampering, capacity, offline
and disabled modes. Real hosted publication remains NOT_RUN until that exact
profile/destination is separately authorized and independently qualified.

The implementation is being developed; native/browser/frozen/CI/review gates have
not yet qualified an S17 candidate. Package identity remains 0.14.0/development.
No Concordia release is published by normal CI or this workstream.

## Exact external Git versions

The closed candidate set is Linux Git 2.52.0 (this development environment), Linux
Git 2.56.0 (observed in the permanent Ubuntu CI and release-source-gate jobs), and
Git for Windows 2.56.0.windows.4 (observed in Windows CI). Each requires its own
native conformance evidence; admission to the candidate set is not qualification.
Any other version, including another patch version, fails before transport work.
No timing/resource/coverage limit or required test is relaxed for a version change.

The original `a209963` Ubuntu and release dry-run source-gate failures are retained:
they correctly reported `git_version_unsupported` on the runner's 2.56.0, which
was missing from the original closed set. The corrected candidate still requires
full exact-head native, CI, installed/frozen, browser and review evidence. Its
Linux 2.52.0 results cannot qualify the runner's 2.56.0 or Windows on another head.

### Pinned workspace image compatibility

The original `0298f54` Public CI run 42417574678 failed its native workspace
profile: 25 Git conformance cases reported the closed unsupported-version refusal;
5,785 other tests passed. These original results remain unchanged. The pinned
image's upstream inventory, at devcontainers/images commit
`71dedcdf66686f9272e01da24299b297d3bdb8e8`, history/2.0.5.md, matches image index
digest `d94c97dd9cacf183d0a6fd12a8e87b526e9e928307674ae9c94139139c0c6eae`
and declares Ubuntu Git `1:2.43.0-1ubuntu7.3`. This is independent provenance,
not a claim that the host runner's 2.56.0 qualified the container.

Exact Git 2.43.0 was separately built from public upstream commit
`564d0252ca632e0264ed670534a51d18a689ef5d`, annotated tag
`c089584ac8dedc3aa7c2c404839bc098050298a2`. The first local conformance run
correctly refused its legacy `branches/` root entry (23 failures, ten passes,
one platform skip). Compatibility now admits only an empty legacy directory;
any file or nested entry is refused before native Git, with its original bytes
preserved. All process/storage/operation limits and the unknown-version refusal
remain unchanged. The corrected native Git 2.43.0 cases passed (34 passed, one
native Windows skip). Full suite and permanent CI must qualify the new exact
candidate, including the actual pinned image and Windows binary independently.
