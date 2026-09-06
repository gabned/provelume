# Guided read-only Google connection

Issue #214 owns `0.10.1/S03`. This development capability keeps package/runtime/Windows
identity at `0.10.0`; it does not publish Emendatio or change the historical
`local-conformance-preview` receipts from Lectio.

## Ordinary connection

Open **Connect Google** from the Google navigation entry, in the ordinary browser on the
computer hosting the Instance. Windows-hosted and direct Browser sessions use the same
service, Source identities and `/api/v1/google/connection` read model.

1. If offline, expand **Instance network access** and explicitly allow external access.
   This is an Instance-wide gate: other explicitly enabled connectors may use the network.
   It changes neither LAN binding nor firewall policy. Going offline blocks subsequent
   authorization, credential resolution, connection tests and intake.
2. Expand the one-time **Set up the Google desktop client** section. Supply the downloaded
   `installed` client JSON from an authorized Google Cloud project with Gmail and Drive APIs
   enabled and the chosen account authorized for its consent-screen testing configuration.
   Web clients, arbitrary OAuth endpoints and overlarge input are rejected. Client setup
   uses the system credential store and never echoes the submitted configuration.
3. Name a connection, select **Gmail** or **Google Drive**, confirm read-only consent, and
   continue in the external browser. To add the other capability to the same account,
   use its separate **Connect** form in that connection.
4. A bounded connection test validates the returned grant and account before authorization
   is committed. Intake remains disabled until **Start bounded intake** is selected.
5. Start, inspect progress, continue from the checkpoint, cancel or retry explicitly.
   Refreshing the page reads local state; it never tests Google or reads credentials.

The ordinary Gmail selection is the authorized `me` mailbox. The ordinary Drive selection is
files directly in My Drive (`root`); it does not silently recurse through folders. Existing
advanced controls retain explicit mailbox/label and file/folder selection. No share discovery,
new provider, Google write, Calendar, email sending or background-agent capability is added.

## OAuth and credential boundary

The existing installed-app authorization engine owns PKCE S256, unpredictable state, exact
high-port HTTP loopback redirect, five-minute lifetime, replay prevention and cancellation.
An explicit capability authority binds the real connector lifecycle, allowlist, global network
policy, individual capability revision and necessary account equality binding. The base
connector remains auth-mode `none`; no fabricated PKCE connector definition or union grant is
created. Cancellation during token exchange prevents the late grant from committing.

| Capability | Sole accepted scope | Connection test |
|---|---|---|
| Gmail | `https://www.googleapis.com/auth/gmail.readonly` | `users/me/profile`, only `emailAddress` |
| Drive | `https://www.googleapis.com/auth/drive.readonly` | `about`, only `user(emailAddress)` |

The profile is transient. Only a connection-scoped SHA-256 equality binding is kept in private
adapter configuration, so reconnecting a different account cannot mix data into an existing
Source. An existing manually configured Source can enter the guided reconnect path only when
its configured account email provides an equality binding. A legacy alias without such a
binding remains available in advanced controls; it cannot silently acquire data from a newly
selected account. No new raw account email or extra identity scope is used. Selected provider IDs and
continuation cursors remain necessary adapter-local configuration; canonical references stay
Source-scoped hashes under the existing adapter contract.

Windows uses native current-user DPAPI with UI disabled. Encrypted credential files live under
the current user's LocalAppData/Provelume/GoogleCredentials, outside the Instance. Symlink and
junction redirection and a credential directory inside the Instance are rejected. Linux uses
the Secret Service backend and macOS uses Keychain through the platform-conditional `keyring`
dependency. Backends are selected explicitly; null/plaintext plugins are not a fallback.
An unavailable or locked store fails visibly. Windows packaging needs no additional keyring
runtime or credential subprocess. Credential slots, refresh material and client configuration
are excluded from Instance backup, export and portable transfer by their storage boundary.

Access tokens refresh only behind the existing execution gates, with exact scopes checked
again. No redirect, automatic OAuth retry or credential-bearing query is used for token or
revocation requests. OAuth transport is limited to the fixed token/revocation endpoints and
the two read-only profile endpoints, 15 seconds per request and 64 KiB per response. Callback
and control input are bounded and duplicate fields fail closed. Both official server launchers
disable access logging; callback query values are not rendered, persisted or put into errors.

## Lifecycle and intake

**Connected**, **expired**, **revoked/disconnected** and **reconnect** are explicit. A temporary
network failure does not masquerade as a revoked grant. Local per-capability disconnect disables
only that service and deletes its managed credential; retained Originals remain available.

Google's remote revocation affects all grants for that Google account and OAuth project,
including other clients. A separate, explicitly confirmed project-revocation action explains
that effect and disconnects the affected local capabilities. It is not presented as independent
remote Gmail-only or Drive-only revocation. Other Google accounts are not grouped merely
because they use the same project.

Guided intake has fixed limits: two pages, 25 items per page, 50 items per run, 32 MiB per item,
64 MiB per run, and the existing metadata/error/cursor/request bounds. Reaching a page/item
checkpoint produces `continuation_available`. The next run resumes the saved provider cursor;
partial pages are not silently skipped. Already committed items remain idempotent on retry.
Source/connector/global gates and cancellation are rechecked before item promotion. Source
re-enrollment reuses existing selection state, preserving identity, cursor and schedule.

## Qualification and human evidence

`tests/test_google_connection.py` covers the actual guided service/HTTP path with synthetic
OAuth responses, exact scope/state/redirect/replay/cancellation bindings, reconnect identity,
privacy through backup/portable transfer, offline gates, bounded continuation and actual Windows
DPAPI restart/tamper/delete. Existing OAuth and Google adapter regressions remain required.
The permanent Windows shell workflow also invokes the installed executable's explicit
`--google-credential-smoke-file` mode to exercise disposable synthetic DPAPI material,
then checks the packaged EN/IT Browser and shared offline read model. It records these checks
in the exact-head Windows shell evidence without requiring real Google credentials.
The permanent Core matrix runs the new tests on Ubuntu and Windows; the existing synthetic
Google smoke continues to verify the historical adapter contract. Synthetic observations are
never relabelled as real-account evidence.

For final real-account qualification, use a development wheel built twice from the verified
GitHub tree of the accepted exact head with the repository's pinned build inputs and
`scripts/deterministic_build.py`. Verify its digest and embedded commit against the accepted
PR head. Install it into an isolated Python 3.12 environment on the account-owning computer
and start `provelume-desktop` or `provelume serve <instance>`. The permanent Windows shell
workflow separately verifies the installed executable at that same exact head. The Public CI
PR merge-ref artifact is a different build and cannot substitute for the accepted head.
Neither this development wheel nor its human observations constitute a published release.

Prepare an authorized test account containing at least one harmless Gmail message and one
small file directly in My Drive; the real evidence must include acquired items, not only an
empty listing. On that build, use the ordinary path above to connect both
services, test both and run bounded intake for both. Disconnect and reconnect a capability in
the same connection, then test again; its Source identity must remain unchanged. Synthetic
failure, privacy and platform evidence remains separate from these real provider observations.

Download the redacted report at
`/google/connect/evidence?expected_head=<accepted-40-character-PR-head>` from the local browser.
It refuses absent/mismatched embedded build identity. `OBSERVED` requires actual REST connection
and test events for both capabilities, successful bounded REST jobs on that build and a stable
reconnect. `INCOMPLETE` identifies missing observations. The report contains no token, raw
account identifier, selected document content or client ID. It explicitly makes no release
qualification claim: the protocol's GitHub-bound acceptance of this human evidence is a
separate gate. The report is also exportable from an installed wheel using
`python -m provelume.google_connection_evidence --instance <path> --expected-head <sha> --output <file>`.

If real consent is the sole missing evidence after autonomous implementation and qualification,
the campaign retains its exact head and uses `STOP_REASON: USER_ACTION_REQUIRED`. It does not
merge S03, activate S04 or rewrite historical receipts in lieu of consent.

Primary provider contracts: [installed-app OAuth/PKCE](https://developers.google.com/identity/protocols/oauth2/native-app),
[Gmail profile](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile),
[Drive about](https://developers.google.com/workspace/drive/api/reference/rest/v3/about/get),
and [system keyring backends](https://keyring.readthedocs.io/).
