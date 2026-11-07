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
silently adopted or repaired. The local UI shows branch/path/commit identity,
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
