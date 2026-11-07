# Concordia S13 Asana reading

This PRODUCT workstream consumes the exact S12 development candidate under the
[ordered S09–S23 development authorization](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974).
It does not accept its predecessors. The [complete manifest](concordia-step-0.md),
S07 CPU finding, ordinary native/CI/review/main gates and final publication gates
remain applicable.

## Public contract and authorization

The implementation targets the public Asana API 1.0 at
`https://app.asana.com/api/1.0`. The reviewed public OpenAPI source is
[asana/openapi at e5c7dec74dcea63207156a7cc96d06f82075a1d3](https://github.com/Asana/openapi/blob/e5c7dec74dcea63207156a7cc96d06f82075a1d3/defs/asana_oas.yaml),
blob `e195ce1bf94a7a903d9ccc2d1c8a4110b1eaa19d`, 3,484,426 bytes, SHA-256
`a28f54a1bc30e1e809eab9d8edba64dfadce485a9043fc7fe784aeed17c0d72c`.
The [official OAuth instructions](https://developers.asana.com/docs/oauth) define
the consent, token, token-info and revocation endpoints. Localhost/native flows
require PKCE; this adapter uses S256 and the exact registered loopback callback.

Each OAuth identity has independent external-vault grants and selected Sources.
Only `tasks:read`, `stories:read`, `projects:read`, `teams:read`, `workspaces:read`
and `users:read` are requested. Token introspection must independently report an
active token with exactly these scopes. A separately fetched profile binds the
grant to its original account. Broader scopes, changed accounts, replayed state,
wrong callbacks and expired pending sessions cannot replace an existing grant.
Refresh repeats scope/account checks. No task write scope is requested.

The application OAuth contract adds the closed `asana-scoped-pkce-v1` profile for
this exact adapter/version and official endpoints. Asana does not document the
Google-style `prompt=consent` parameter. Its explicit local consent and official
authorization page are therefore validated under this provider profile. The
existing default consent contract is unchanged; another provider cannot claim
the Asana profile.

Client configuration, access/refresh tokens and the per-device grant pointer use
the external OS vault, without plaintext fallback. Canonical data, portable
packages and backups contain no grant reference. Grant publication checks the
current authority under the connector policy guard; failure restores only the
owned pointer and retains the previous grant. Refresh and all HTTP happen outside
canonical commit guards. A disconnected/restored Instance retains its readable
source observations without reacquiring credentials. Reauthorization is explicit.

## Selection, bounded reading and recovery

Current and Cura expose `/asana/connect` through Connectors. Viewing controls or
an acquired task performs no provider HTTP or vault read. Loopback, bounded forms,
CSRF, explicit confirmation and displayed revisions protect actions. Only this
connection page permits the official Asana consent host in its form policy.
The callback removes the query before access logging and never echoes codes.
Seven governed language catalogues expose connection, selection, reading,
continuation, scheduling, reset, disconnection and remote revocation. Automatic
rendering checks do not constitute human or linguistic acceptance.

The explicit catalogue reads workspaces/organizations, then visible projects and
teams for a selected workspace. `/workspaces` uses its documented nonpaginated
operation; project/team operations use bounded `limit` and server offsets.
Organization/workspace, team and project selections create independent Sources.
Project and team membership are independently checked against the selected
workspace before acquisition. Workspace/organization reading includes visible
project tasks and tasks assigned to the authenticated user, including unprojected
ones. This coverage is displayed: it does not claim access to private or invisible
tasks. Duplicate tasks within a Source are visited once; different Sources retain
independent provenance and canonical objects.

The scheduler uses `productivity.intake` with one automatic attempt. Every provider
response becomes an exact SourceSnapshot Original before its durable continuation
advances. The planner reads root tasks, task details, all comment pages and all
subtask pages recursively, then verifies the task again before emitting its mapped
observation. A changed verification response is incomplete and cannot promote the
task or complete the Source. This is a bounded, observed full traversal rather
than a claim of provider-wide point-in-time isolation.

Each job is at most 50 API responses, 8 MiB and 60 seconds; a single response is at
most 1 MiB. Owned HTTP processes enforce a 20-second wall bound including DNS and
inherit the configured proxy/CA trust. HTTPS has no redirects or retries. The
transport accepts GET plus POST solely to the three exact OAuth endpoints; a task
write is refused before opening a connection. The frozen executable has an
explicit worker entry and needs no external Python. Planner state is bounded to
2 MiB, 5,000 tasks/projects and 20,000 responses. Root pages request 25 tasks;
comment/subtask/catalogue pages remain bounded. Only opaque server offsets are
used; `next_page.uri` is never followed. Repeated cursors, oversized/incomplete
responses and ambiguous mappings fail visibly.

Partial jobs retain exact acquired observations and a resumable Source generation
without publishing a complete checkpoint. The UI displays continuation separately
from completion. A complete new traversal publishes membership only after every
response/item is durable. Repeated unchanged acquisition is a semantic no-op.
An explicit reset invalidates the pending planner while preserving the previous
complete evidence. Tasks absent from a later complete snapshot become historical
observations; absence never fabricates remote completion/deletion.

The [official rate-limit contract](https://developers.asana.com/docs/rate-limits)
uses HTTP 429 with `Retry-After` seconds and per-token limits. A refusal persists a
cooldown tied to the current grant revision and Source. No equivalent request is
made during that wait; a newly authorized grant is independently scoped. Failures
have retained job receipts and a closed Source status, without private payloads in
errors. Scheduled reading requires separate scheduled consent. Disable, policy
change or revoke during acquisition prevents canonical promotion/checkpoint
publication under the final policy guard.

## Canonical meaning and qualification limits

Tasks retain exact descriptions, completion, date-only `due_on` versus UTC
`due_at`, assignees, parents, projects, comments and safe durable links. Friendly
names accompany stable provider identifiers. Task objects are Source-attributed
and read-only; comments, Source and links to all retained response Originals are
visible offline. Index/portable rebuild verifies Source-specific evidence hashes.
Provider `modified_at` is an observed revision, not an atomic compare-and-set
primitive and not S15 write authority. The pinned update operation documents no
conditional revision parameter; S15 still needs independent proof of a safe
conditional write primitive or the explicit scope decision required by L.

Synthetic automatic qualification exercises real PKCE/session management, external
vault publication, all four Source scopes, scheduler, partial continuation,
Originals, Task objects, comments, replay, rate-limit/revocation, policy races and
portable/offline reconstruction. `--ocr-command asana-qualify <fresh-target>` runs
the synthetic installed package path and proves the actual HTTP worker's typed
endpoint refusal; a missing worker cannot satisfy this check. The permanent
installed offline Windows qualification invokes it inside its existing network
boundary. Browser productivity cells additionally render the Asana controls and
retained Task provenance in both modes, seven languages and two viewport widths.

These are synthetic automatic checks. Real Asana OAuth/accounts and provider
behavior remain NOT_RUN pending their specific authorization and evidence. Human
manuals remain DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official release
on the maintainer's Windows 11 Pro 25H2 PC. No intermediate personal installation
is authorized or required. S13 remains a development candidate until all applicable
gates and its dependency acceptances are satisfied.
