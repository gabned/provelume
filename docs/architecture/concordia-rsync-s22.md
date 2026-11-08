# Concordia S22 — bounded rsync over pinned SSH and owned activation

This homogeneous PRODUCT workstream consumes unaccepted S21
`21e337a00a3b085ca38dfcd39259c4cbcd092a9f` under #383/6706150974's ordered
development/automatic-test authority. Acceptance still requires S16/S21. Actual
main is `9c6d89c035e009e342d2c6d5c9ed3081fbcb77e8`; Protocol1.5.2/pin02317e0,
97 canonical files, PR-local legacy and deferred Lifecycle v2 remain. Product
identity is 0.14.0/development. Original S07/S08 outcomes/BIND are preserved;
no concluded causal trial is dispatched. Human observations remain
DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official release on the
maintainer PC; no intermediate installation there is authorized.

The optional initial transport targets rsync 3.5.2 and an explicitly qualified
native OpenSSH client/server pair, never an ambient shell, daemon TCP endpoint or
unqualified older rsync. Official 3.5.2, released 4 November 2026, fixes
CVE-2026-119741; current upstream sources, provenance/signature status, component
licenses and applicability are inputs to qualification. Windows needs its own
actual native rsync/SSH/component evidence; Linux success is not transferable.
Missing components or unsupported versions fail visibly and perform no send.

Only complete, independently verified S16 staging generations are transferred.
Explicit identities/targets bind a dedicated Ed25519 credential reference in the
OS vault, exact user/host/port and full pinned Ed25519 host key, remote owned
namespace, helper/API/version identity, bandwidth and UTC maintenance window.
The owned SSH agent keeps the private key outside argv/environment/temp files,
requires a verified OpenSSH session binding to that host key, and signs only
the predeclared user-authentication request for that identity. Native SSH disables
ambient config, prompts, proxies, forwarding and connection retries. A dedicated
remote forced-command helper confines that key to the enrolled namespace.
Remote installation/configuration on a real account needs its specific authority.

Rsync success alone cannot activate anything. A versioned owned remote helper
admits a fresh private local root, physical namespace ownership, known canonical/
Original/control/backup exclusions, bounded native child containment, no aliases
and a complete manifest/hash reread. Transfer uses an SSH-protected stdin rsync
daemon channel confined to one operation's destination staging, without a public
daemon listener or arbitrary remote command. Activation is a separate exact
expected-pointer operation using the independently qualified native filesystem
primitive. Earlier active generations and destination-only history remain.
There is no destination adoption, deletion, prune, automatic repair, reverse
synchronization or backup/restore claim.

An external one-attempt claim precedes destination effects and binds the complete
transport plan. Interrupted/uncertain activation is reconciled read-only against
the specific operation, including after Root restore, and never retried. Explicit
resume may continue only a partial transfer whose durable remote phase proves
that activation has not started; it cannot replay an uncertain activation.
Scheduling honors the configured UTC window and bandwidth, has one attempt and
fences failures for manual intervention. Resume never runs automatically.

Automatic qualification prepares only fresh local synthetic keys, namespaces,
payloads and owned SSH fixtures. It separates source/unit, actual native
client/server, frozen/installed, cross-platform and human evidence. Required
cases include full inventory comparison, no-op, host-key/credential rejection,
disabled/local-only/no-rsync passivity, interrupted transfer/resume/activation,
disk-full, replaced paths, revoked/stale grants and actual Root-restore replay
protection. CLI, local CSRF UI/both shells/seven UNVERIFIED catalogues and scheduler
must use the same backend. Full native/browser/installer/offline/CI/review and
actual-main gates remain; no release or live destination is authorized here.
