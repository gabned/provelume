# Concordia S21 — local-folder generations and atomic activation

This homogeneous PRODUCT owner consumes unaccepted S20
`bc8e0b36a1c0f5a022876e6c51f6d8cacfd1e588` under the ordered development and
automatic-test authority in #383/6706150974. S16/S20 acceptance remains required
before integration. Actual main is `9c6d89c035e009e342d2c6d5c9ed3081fbcb77e8`;
Protocol 1.5.2/pin02317e0, 97 canonical files, PR-local legacy and deferred
Lifecycle v2 remain. Identity is 0.14.0/development. Original S07/S08 experiments,
FAIL and BIND keep their meaning; no concluded trial is dispatched here.

The folder transport consumes only complete, immutable S16 generations. Enrolment
requires an explicitly confirmed, absent destination under an existing private
local parent. Canonical/Original/backup/control/registered-Source trees, remote
mounts, symlinks/junctions/reparse points, hard-linked payloads and unknown or
already populated roots are refused before transfer. A physical root identity,
random namespace and device/Instance binding establish ownership; a path string
or a folder's display name never grants access. No destination adoption or cleanup
is implicit. No process or network is needed for this transport.

Each send first acquires the existing per-Instance lifecycle guard and an owned
destination lock. It revalidates authority, source generation, physical target,
expected active pointer and the complete old/new manifests. A durable external
one-attempt claim precedes any destination transfer. The candidate is copied to
a unique destination staging directory using bounded, no-follow local handles;
every payload byte and complete inventory is re-read and hashed. Only a complete
verified generation may enter the immutable generations directory. Activation is
one same-filesystem atomic replacement of a small active-pointer file, bound to
the generation and exact operation. Previous generations and destination-only
history remain. There is no in-place rewrite of an active generation, deletion,
automatic prune, remote-to-local write or backup/restore claim.

Repeat no-op needs complete destination verification and writes no new generation.
Interruption, disk-full, stale target/source/authority and unsupported atomic
primitives fail visibly; a partial generation never becomes active. Unknown sends
are never replayed, including after a real same-Root restore. Explicit read-only
reconciliation must verify the specific operation's pointer and every final byte;
absence or an older active pointer cannot become permission to resend. Remaining
staging directories are reported and retained for a distinct future cleanup
decision. Existing S16 size/count/time ceilings remain unchanged.

Native automatic qualification will exercise the actual local filesystem,
initialisation, exact copy/activation, complete-manifest comparison, multi-scope
isolation, no-op, replaced roots, hostile links, concurrent writers, disk-full and
interruptions before and after activation, plus external replay protection after
Root restore. CLI, local CSRF UI in both shells/seven UNVERIFIED catalogues,
scheduler and the actual frozen installed Windows path must use the same backend.
Windows Server runner evidence does not attest Windows 11 Home/Pro 25H2. Human
observations remain DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official
release on the maintainer PC; no intermediate installation there is authorized.
