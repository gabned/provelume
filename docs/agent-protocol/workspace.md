# Isolated laboratory execution

The private laboratory configuration is optional execution infrastructure.
A normal agent environment or qualified CI may execute the same required native
checks; the user's PC and WSL are not ordinary prerequisites. A Linux check cannot
certify Windows-specific behavior, and a manual check that did not run stays NOT_RUN.

The accepted `.github/agent-protocol/workspace.json` selects native runtime sources,
commands and isolated services. Read runtime and lockfiles from this repository;
do not maintain application versions in the laboratory inventory. Qualify profile
changes under the accepted predecessor before candidate execution.

Prepare only the current project and workstream. Keep repositories and concurrent
checkouts separate, preserve uncommitted changes, use synthetic data and private
previews, and expose no operator credentials or Docker socket to candidate tests.
Cache reuse requires native validation and does not establish authority. Services
are temporary, caches reconstructible, and branch/journal/data material durable.

After suspension, inspect real processes and containers; do not assume tests are
still running. Verify rebuild and resume from durable material. The laboratory
commands never replace repository gates or production consent.

No paid Codespace, prebuild, larger runner or spending limit is authorized by a
profile. When provisioning is not separately approved, runtime remains
NOT_PROVISIONED. Complete configuration verification independently.
