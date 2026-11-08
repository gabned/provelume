# SSH mirrors

This optional transport sends complete mirror generations in one direction.
The destination keeps its earlier generations. A verified active-generation
pointer is the receipt boundary; an rsync exit code alone is insufficient.
Mirror data is derived readable data, not canonical storage or a backup.

The initial remote filesystem profile is a private local Linux directory with
the qualified no-follow and renameat2 primitives. Native rsync3.5.2/protocol33
and the exact qualified SSH profile are required. Missing or unsupported tools
refuse before credential access or connection. Windows uses the separately
pinned MSYS2 input and its complete DLL set; a generic Cygwin installation is
not substituted. The checked-in Windows input is qualification metadata, not
a bundled executable or a native Windows PASS. Its installed diagnostic checks
the complete input set, a real local copy and the system SSH version separately.
An observed Windows SSH version remains unadmitted until actual authentication
and rsync/SSH qualification are complete. See
[the S22 contract](architecture/concordia-rsync-s22.md) for current evidence.

1. Enable mirrors and the separate rsync permission explicitly. Create a
   dedicated identity with `mirror-rsync-create-identity INSTANCE name.json
   --confirm`; the external file contains only `{"name":"SSH mirror"}`.
   The command returns a public Ed25519 key. Its private seed stays in the OS
   secure store and is never put in a key file, command argument or environment.
2. Obtain the remote host's complete Ed25519 public key independently from its
   owner. Verify the fingerprint. A newly observed network key is insufficient
   authority to change the pin.
3. On the specifically approved remote account, install the reviewed helper
   package and prepare a fresh private control directory and a separate absent
   payload directory. `provelume-rsync-helper enroll config.json --confirm`
   checks the native component and known canonical/control/backup exclusions.
   The input names `config_directory`, `root`, `source` (`instance_id` and
   `device_sha256`), a32-hex `namespace`, `client_public_key`, `rsync_binary` and
   `excluded_roots`. The public output gives the configuration hash, exact
   restricted authorized-key line and subsystem declaration. Installing that
   line/configuration is an explicit operation on that specific account; the
   client does not deploy it. Keep other account access and public serving
   outside this private namespace.
4. Configure a mirror destination with profile `rsync-ssh`, current scope and
   explicit include rules. Its flat target fields are `transport="rsync-ssh"`,
   `host`, integer `port`, `username`, `host_key` (base64 of the complete
   Ed25519 SSH public blob), `namespace`, `configuration_sha256`,
   `bandwidth_kib`, `window_start_minute_utc`, `window_end_minute_utc`.
   UTC minutes use `[start,end)` within0…1440; `[0,1440)` is all day. There is
   no implicit overnight split, limit increase or credential import.
5. `mirror-rsync-initialize` requires the exact destination hash and confirmation
   before creating the fresh enrolled payload namespace. Then use
   `mirror-rsync-prepare`, review the complete inventory/findings and publish
   with both the original plan hash and rsync plan hash. Local CSRF controls in
   both shells call the same backend. Public payload is not an initial SSH
   profile; filesystem privacy does not attest an unrelated web server.

Native SSH uses its own short-lived agent. The agent verifies the pinned host's
session binding and signs one exact user-authentication request. The remote
forced-command helper accepts a closed versioned protocol; neither client nor
remote caller supplies an arbitrary command. The complete immutable local
generation is reread before transfer; remote hashes/inventory are checked before
its separate activation. Prior active data is retained.

After interruption, `mirror-rsync-reconcile INSTANCE PLAN --confirm` is read-only.
`mirror-rsync-resume INSTANCE PLAN --expected-rsync-plan-sha256 HASH --confirm` is an
explicit operation within the original plan expiry, current scope/key binding,
UTC window and bandwidth. It requires a durable stopped-receiver record and
proof activation never began. A verified stage proceeds to its first activation
without another transfer. An uncertain activation remains UNKNOWN until a
read-only specific-operation proof resolves it; it is never replayed. Restoring
Root cannot remove the external one-attempt claim or scheduled-failure fence.

Scheduling waits outside the configured UTC window. An actual failure pauses
that destination for manual intervention; there is no automatic resume. Disabling
mirrors/rsync causes no probe, process or credential read. Passive inventory/status
does not contact the target. Disconnect revokes the local seed and grant; remote
authorized-key removal is a separate account operation. Target adoption, reverse
sync, pruning, deletion and a backup/restore claim are outside this transport.

Source/synthetic, actual native wire, frozen/installed, rendered browser and
human evidence remain distinct. Human observations stay
DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official release on the
maintainer's existing Windows11Pro25H2 PC, with no intermediate installation.
