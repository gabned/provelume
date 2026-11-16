# Concordia S18 — independently qualified GitHub mirrors

This PRODUCT workstream consumes unaccepted S17
`0298f541f8bf8487476fdfcd8317f3bd34cdf269` (including the separate #453 allocation
repair) under the [ordered development authority](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974).
No predecessor acceptance, personal account or remote publication authority is
inferred. Protocol 1.5.2/pin02317e0/97 canonical bytes, PR-local legacy, deferred
Lifecycle v2 and 0.14.0/development identity remain unchanged. Original S07/S08
results and #439's original BIND are preserved; this work does not accept them.

## Profile and independent observations

The first profile is GitHub.com REST API version 2022-11-28 plus the independently
qualified native Git HTTPS transport. Enterprise/other hosts and unqualified API
or Git versions fail visibly. GitHub, GitLab and Gitea never inherit one another's
qualification. Git remains optional and all local/offline personal behavior works
without any hosted profile. Disabled/local-only/no-GitHub gates precede vault,
process and network access; passive pages do not probe or repair.

Each explicit operation binds the actual repository ID, canonical owner/name and
HTTPS clone URI, observed visibility and actual credential access. Missing,
contradictory or unknown visibility blocks private payload. Repository transfers,
replacement, changed account/credential/grant/policy/scope/branch/ref invalidate
dependent write previews. A repository permission boolean alone cannot prove a
token's write capability.

The documented immutable blob-create endpoint requires Contents write permission.
An explicit, separately described check writes only a fixed public synthetic
permission-probe blob, validates HTTP 201 and its exact Git object ID, and never
changes a ref or sends Source content. Read-only/expired/wrong-account credentials
must fail before Source publication. Probe bytes and any public probe consent are
part of the reviewable authorization, never an implicit side effect of a GET.

Credentials and their references remain external to canonical/portable data.
The device OS vault stores provider credentials and immutable logical account or
installation-access identity. Explicit credential renewal preserves logical
identity only after independent validation, invalidates pending write previews,
and may enable read-only UNKNOWN reconciliation; it never grants a resend.
Tokens never enter URLs, argv, environment, ordinary output, public evidence or
CI. Dedicated bounded stdin/credential-protocol pipes carry secrets only between
the authorized parent, native HTTP worker and fixed owned Git helper. Repository,
system and ambient Git helpers/config/hooks/prompts remain disabled.

## Complete public payload and ownership

Private is the default requested visibility. Public publication additionally
requires a fresh exact allowlist and confirmation for the entire actual transfer:
selected payload files, complete manifest, active pointer, owned namespace marker,
permission-probe bytes and explicit commit identity. Logical Markdown-only
allowlisting cannot authorize unseen control metadata. No credential, target
locator, local device/path or secret-bearing reference is an ownership marker.

The owned namespace has a random nonsecret tag bound externally to the current
destination/grant. Foreign/unknown/incomplete namespaces cannot be silently
adopted or overwritten. Initial publication atomically introduces its marker,
complete generation and active pointer in one native ref update. Unrelated paths
and all previous valid history remain. Native direct-parent proof and exact ref
lease remain mandatory; no automatic force/NFF repair, merge/rebase or deletion.

Fresh visibility/account/permission/ref observations precede a single claimed
send. Post-send ref, full SHA-256 inventory and provider observations determine
the receipt. Changed or incomplete observations stay UNKNOWN; historical receipts
do not attest current state. Read-only recovery verifies the operation-specific
commit and complete generation, including after same-root restore. Source and
canonical knowledge remain unchanged by mirror operations.

## Bounds, surfaces and qualification

Preserve S16's staging limits and S17's 120-second operation / 30-second command,
2MiB metadata, 32MiB blob and 512MiB local Git object-store bounds. HTTP calls run
in an owned worker with a 20-second DNS/request deadline within the same operation
deadline, fixed HTTPS origins, no redirects, bounded responses and closed routes.
No retry, larger limit, observer-cost subtraction or inferred provider capability
is a fallback. Limits for API pagination and credentials remain explicit and finite.

CLI, local CSRF UI in both shells/seven catalogues, scheduler, source/frozen helper
and installed qualification use the same backend and default refusals. Public
scheduled work cannot approve a newly changed payload automatically. Credential
expiry, revoke, unknown visibility, wrong target/identity, public-content drift,
NFF, interruption, read-only recovery, missing components and offline/default-off
behavior all have independent negative/recovery cases.

Synthetic contract/native-loopback tests are labeled as such. They do not qualify
a real GitHub account or publication. The scoped real-endpoint driver is prepared
with a fresh synthetic corpus, exact proposed destinations and complete public
payload before any authorization request. The approved contract says: “Use
synthetic fixtures only; no live credentials or personal paths in source/logs/CI.”
No credential-bearing CI or real remote action is authorized by this document.
Any such action needs its specific existing or newly explicit maintainer authority.
Human/manual checks remain DEFERRED_BY_MAINTAINER / NOT_RUN until the completed
official release on the maintainer's Windows 11 Pro 25H2 PC; no intermediate
installation on that PC is performed.

## Authoritative sources read

- [GitHub blob creation](https://docs.github.com/en/rest/git/blobs?apiVersion=2022-11-28#create-a-blob): immutable Git blob objects, Contents write permission,
  supported token types and HTTP 201 response.
- [Repository metadata](https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#get-a-repository): repository identity, canonical URI, visibility and permission observations.
- [Installation repository access](https://docs.github.com/en/rest/apps/installations?apiVersion=2022-11-28#list-repositories-accessible-to-the-app-installation): installation-token repository grant and pagination.

Implementation and exact-candidate qualification are in progress. Hosted
publication is NOT_RUN; no release identity or official publication is changed.

## Implemented operation contract

`mirror-github-connect` reads an explicitly selected external JSON file containing
`name`, the closed `target`, `token`, `mode` (`user` or `installation`) and optional
existing `identity_id` for renewal. It requires `--confirm --probe-confirm` and,
for public repositories, `--public-probe-confirm`. The worker sends only the fixed
synthetic probe before an external credential slot is created. No token or slot
reference appears in the result; the returned local identity ID is used by the
existing `mirror-configure` command. The external configuration file stays outside
every Instance; operators manage its lifetime. Browser pages never accept tokens.
`mirror-github-disconnect` revokes the local identity and deletes its credential;
it does not falsely claim remote token revocation.

Targets are closed scalar records: transport `github`, canonical `owner/name`,
positive actual `repository_id`, requested `private`/`public` visibility, API
version, random 32-hex nonsecret `namespace`, branch, path and explicit commit
name/email. `mirror-github-prepare`, `mirror-github-publish` and
`mirror-github-reconcile` share S17's one-send/external-claim/ref-lease engine.
A public publish additionally requires the exact `--expected-transfer-sha256` from
the complete preview, as well as S16's exact logical inventory allowlist. The
physical descriptor is independently rebuilt before the claim. The current
profile refuses public scheduled publication; an operator must explicitly review
and publish each public generation. Private schedules use the existing fixed
single-attempt scheduler and persistent conflict/UNKNOWN fence.

Both local shells render the GitHub identity/visibility and complete physical
transfer with seven explicitly UNVERIFIED language catalogues. CSRF controls use
the same backend; passive GETs only read local previews/receipts. The fixed helper
validates Git's HTTPS host/path, current device/grant and material epoch before
reading a credential. Raw credentials travel through a dedicated pipe only.
Credential renewal invalidates a write preview but preserves read-only recovery
for the same independently revalidated logical repository/account/grant.

`github-mirror-qualify` is wired through the actual frozen operator and permanent
installed Windows qualification. Its explicit evidence labels are synthetic API
responses, native file Git, synthetic credential-protocol pipe and an actual owned
HTTP worker refusing an invalid endpoint. It proves neither real GitHub HTTPS
interoperability nor a real account grant. Separate source tests cover public
logical/physical approval, drift, read-only token, namespace ownership, renewal,
interruption/real same-root restore and no replay. Exact-candidate full native,
browser, CI, installed and review results remain required before acceptance.

### Owned helper OS-vault context correction

A controlled source-level negative on 4ebe162 showed that a valid synthetic
Windows vault locator was lost when building the owned Git environment; the
child locator was unavailable. The D-Bus session locator was also absent. This
was a locator simulation, not native DPAPI or a real-account test. Its original
negative evidence is retained. The transport now forwards only the local Windows
LOCALAPPDATA or local Unix D-Bus/runtime locators, never token-bearing ambient
variables; remote/multi-transport bus addresses and remote/malformed Windows
vault roots fail visibly before helper dispatch.

The permanent installed GitHub qualification additionally creates an isolated
synthetic LOCALAPPDATA, stores only new synthetic slots through actual current-user
DPAPI, invokes the actual source/frozen helper through native `git credential fill`,
checks its secret-pipe reply in memory without logging it, and revokes the synthetic
local identity/credential. It contacts no remote and leaves personal credential
storage untouched. Linux reports this Windows-only native case NOT_RUN. Synthetic
API/native file Git PASS still does not qualify real GitHub HTTPS or a real account.
