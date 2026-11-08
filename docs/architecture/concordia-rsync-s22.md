# Concordia S22 — bounded rsync over pinned SSH and owned activation

This homogeneous PRODUCT workstream consumes unaccepted S21
`52205da92145d5a137a035b62aa669885535c227` under #383/6706150974's ordered
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
receiver confined to one operation's staging, without a daemon listener or
arbitrary remote command. The owned adapter checks the exact server arguments
observed from the signed upstream3.5.2 sender; the helper selects its own receiver
executable and stage path independently. Windows uses the fixed `./payload/`
child of the native process's private working directory. The minimal MSYS2 input
has no admitted drive-mount table; no drive conversion or colon is needed.
Activation is a separate exact
expected-pointer operation using the independently qualified native filesystem
primitive. Earlier active generations and destination-only history remain.
There is no destination adoption, deletion, prune, automatic repair, reverse
synchronization or backup/restore claim.

An external one-attempt claim precedes destination effects and binds the complete
transport plan. Interrupted/uncertain activation is reconciled read-only against
the specific operation, including after Root restore, and never retried. Explicit
resume may continue an interrupted transfer only after a durable remote phase
proves its native receiver stopped and activation never started. A fully verified
stage may proceed to its first activation under that same proof, without data
resend. An uncertain activation cannot be replayed.
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

## Initial implementation evidence and remaining gates

The implementation contains the closed Ed25519 signer, private native
socket/Windows named-pipe worker, creation-time process containment and fixed SSH
argument builder. RFC8032, wrong-host/session/user/service/flags, one-signature,
expiry, malformed-frame and actual owned-worker IPC checks are automatic source
evidence. The CLI, local CSRF UI, seven UNVERIFIED catalogues and private scheduler
use the same complete-generation transport, separate verified activation, explicit
resume and read-only recovery. Synthetic-wire tests use real local namespace
state, interrupted-before/after-native-rename, actual Root restore, external
one-attempt claims, scheduling/failure fences and passive GETs. They do not attest
native SSH or rsync. Native Windows/frozen, complete native transport, rendered
browser/installer/CI/review and acceptance still require their own exact-candidate
evidence. The initial remote helper filesystem profile is Linux local renameat2;
Windows native client qualification stays separate.

The source-native diagnostic on `375271e`, run42459181922/a1/job128664583728,
records rsync exit11: its assumed `/d/...` source/destination mapping cannot find
the freshly created Windows directories. This is a concrete path refusal, not
proof of the cause of older sharing violations. The local-copy fixture now uses
fixed relative children under its exact native cwd, matching the transport's
fixed payload child. Actual copy/hash, frozen execution and full Windows wire
qualification remain separate mandatory gates; no component/version is admitted
by this correction alone.

The more specific17e7489 source diagnostic, run42461227798/a1/job128670745843,
passes native copy/inventory/bytes and reaches `native_system_ssh_version`.
Its contained system SSH9.5p2 command returns255 with zero output. A separately
pinned upstream source read at PowerShell/openssh-portable0172cc6 identifies
`init_prog_paths` requiring ProgramData before stdio initialization; missing
ProgramData invokes a fatal exit before diagnostics are available. This source
read does not attest the installed Windows binary or the cause of older failures.
The closed child environment now supplies a private ProgramData equal to its
owned work directory, rather than inheriting global host SSH configuration.
The original Job/handle/command bounds remain. Exact changed-head native evidence
is still required; the observed Windows SSH version remains unadmitted for full
transport until its separate authentication/rsync qualification succeeds.

`rsync-mirror-qualify` uses an exact-source, credential-free Linux fixture image,
fresh internal-only Docker network and native Secret Service. It performs actual
SSH/rsync, independent inventories, full/no-op, wrong host/key, revocation,
controlled before/after activation with actual Root restore, native partial
disconnection/explicit resume, physical tmpfs ENOSPC and a replaced directory with
a copied ownership marker. Each completed case is durably recorded before the
next; incomplete preparation remains UNKNOWN. The finite wrapped partial input
and its configured32KiB/s bandwidth make the declared interruption observable;
product limits and deadlines are unchanged. Fault hooks exist only in the fixture
image, outside the product package.

Frozen Windows has separate diagnostics for native DPAPI/owned agent IPC and the
eleven-file pinned MSYS2 input/native local copy/system OpenSSH version. These
receipts explicitly do not attest native SSH authentication or rsync over SSH.
The diagnostic persists in the installer artifact even if a later case fails.
Source/unit, native Linux, Windows components, rendered synthetic preview and full
Windows transport remain distinct gates; none accepts S22 or its predecessors.

On source00b86db and integrated6a99f1b, local Docker create exceeded its unchanged
30-second preparation bound before any SSH server started. Both named containers
were subsequently observed in Created state and independently removed with their
empty internal networks. Those native journeys remain incomplete, not PASS. The
qualifier had marked creation only after the CLI returned, so a create completed
inside Docker after client timeout escaped its finally cleanup. Fresh fixtures
now carry a unique owner label on container and network; cleanup independently
inspects that label, reconciles both resources and writes its original receipt.
Foreign resources are refused. Missing observations, timeout or failed removal
remain UNKNOWN and block cleanup success. No command, product or Public CI limit
is increased. The interrupted00b86db native suite remains INTERRUPTED; the changed
source needs fresh full qualification. This is fixture ownership recovery, not a
CPU hypothesis, an application timing correction or a Windows transport result.

The official 3.5.2 source archive is 1,977,884 bytes, SHA-256
`a10d591825251e070f74c98df3daad195def4ed81b4a2de16169026aea33f6c8`;
the 273-byte detached signature has SHA-256
`2979e876bd8b75c1fe36da470a7ec6c50672c2e3787a0bdc48ebf52e99e07044`.
The signature verifies with signing subkey
`8EDF88F4731A1E8B45D67FBE6909546B2C52EC2D`, bound to upstream's published
primary fingerprint `C0E1054505704F757D925AB26A64E8AA2EFBCF5D` (Zen Dodd).
The public key was read from keys.openpgp.org through the connected reader;
GitHub release bytes were acquired separately and checked before extraction or
execution. A second Samba-host archive copy was unavailable (proxy403 and direct
DNS failure); no second-copy proof is claimed. A local Linux build uses the
generated configure script with md2man/xxhash/zstd/lz4/OpenSSL-checksum/IDN disabled;
it reports protocol33. It is an ignored qualification input, not yet a shipped
application component or Windows proof. Rsync's GPLv3-or-later terms, complete
source offer and component inventory are required before distribution.
