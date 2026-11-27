# Concordia S14 Tududi reading

S14 consumes the exact S13 development candidate under the
[ordered development/testing authorization](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974).
Dependencies remain NOT_ACCEPTED. This work does not change S07's CPU finding,
native/CI/review/main requirements, manual deferral or final publication gates.

## Reviewed public profile

The supported public profile is the stable
[Tududi v2.1.0 release](https://github.com/chrisvel/tududi/releases/tag/v2.1.0),
published 6 November 2026, annotated tag object
`b3c26b12cf6d46a9e7050cad216e23a0ca033978`, dereferenced commit
`e03bc361bc7fa49a475fca9952b345822d1d5f11`. Public source was read without
executing it or transplanting provider implementation into Provelume. The reviewed
[route registration](https://github.com/chrisvel/tududi/blob/e03bc361bc7fa49a475fca9952b345822d1d5f11/backend/app.js)
defaults to `/api/v1`; custom API versions and reverse-proxy path prefixes are
unsupported rather than guessed. Independent HTTPS site roots/accounts are
supported; redirects and non-HTTPS connections are refused. The configured proxy
and CA trust remain in use.

The [task routes](https://github.com/chrisvel/tududi/blob/e03bc361bc7fa49a475fca9952b345822d1d5f11/backend/modules/tasks/routes.js)
define paged `/tasks`, `/task/:uid` and `/task/:uid/subtasks`. Reviewed file:
36,257 bytes, SHA-256
`0ddd89797d4c89e0968aadc7d6876f857f98452ece78f0a3dafc0b6ec8ce6782`.
The [task serializer](https://github.com/chrisvel/tududi/blob/e03bc361bc7fa49a475fca9952b345822d1d5f11/backend/modules/tasks/core/serializers.js)
preserves UID, project/assignee, date-only due date, optional local due clock,
parent and Original name. `/projects?status=all` is a bounded nonpaginated
catalogue; `/task/:uid/comments` supplies the complete bounded comment/reply tree.
The [comment routes](https://github.com/chrisvel/tududi/blob/e03bc361bc7fa49a475fca9952b345822d1d5f11/backend/modules/comments/routes.js)
and [controller](https://github.com/chrisvel/tududi/blob/e03bc361bc7fa49a475fca9952b345822d1d5f11/backend/modules/comments/controller.js)
were checked independently of the older Swagger examples. Wire-shape incompatibility
is a visible failure, not an empty or completed Source.

The server's health/API endpoints do not independently prove its installed release.
The administrator must explicitly declare `server_version: 2.1.0`; the persisted
connection and qualification receipt retain `server_version_verified: false`.
Schema probes are compatibility observations, not version attestation. Unknown or
different declared versions fail before any HTTP/credential publication. Actual
deployment version evidence remains a separate live qualification requirement.

Personal tokens use the public bearer scheme. The reviewed authentication path
does not independently prove read-only token scopes. Consequently the UI and
receipt explicitly retain `token_scopes_verified: false`: a token can hold broader
account authority. Provelume exposes only GET operations for this adapter. No task,
comment, project, token-management or account mutation is available through its
transport. External OS-vault storage has no plaintext fallback; canonical data,
portable packages and backups contain neither token nor grant reference.

## Identity, Source and traversal

Multiple endpoints/accounts have separate ConnectorInstances, vault slots,
account bindings, policies, pending plans and complete checkpoints. A fresh
`/profile` binds authorization to the endpoint and account. Reconnecting the same
identity requires its exact revision and original account/endpoint; publication
failure restores only the owned pointer and preserves previous authority.
Disconnection removes the local grant and retains acquired observations. It does
not claim server-token revocation: the UI directs that separate action to Tududi
account settings. Revoked/expired tokens fail visibly without advancing a cursor.

Account, project and individual-task scopes become independent Sources. Project
selection uses the explicit catalogue; single-task selection accepts a same-server
durable task link. The selected project and each root task's project are checked
independently. Reads include subtasks recursively and comments/replies, retaining
their complete response Originals. Source/task IDs remain stable across replay,
new versions and portable reconstruction. Repeated unchanged intake is a semantic
no-op. Different Sources retain independent observations rather than being merged.

Root enumeration requests `type=all`, `status=all`, a 25-item limit, offset and
documented creation-date ordering. Completed tasks are not silently excluded.
Every pagination field, total, overlap and progress is checked. After task
acquisition the complete root inventory is read again and must match. Each task
is independently reread before promotion. These observations do not assert an
atomic provider-wide snapshot. Changed/incomplete traversals remain incomplete;
the previous complete checkpoint is retained. Absence in a later completed
traversal becomes historical membership and never fabricates completion/deletion.

Each job has at most 50 HTTP responses, 8 MiB of response bytes and 60 seconds.
Each response is at most 1 MiB; the owned worker has a 20-second parent wall timeout
including DNS. No redirect or automatic retry occurs. Plans are at most 2 MiB,
5,000 task identities and 20,000 responses. Partial completion retains durable
continuation and is displayed separately from Source completion. Scheduled reading
requires separate scheduled consent. A 429 persists a grant-revision cooldown;
no equivalent request runs during the required wait. Policy/identity changes,
revoke or cancellation during a response prevent final promotion/checkpoint.
Explicit full reset preserves the previous complete evidence and invalidates
only the pending traversal.

Tududi serializes timed due values in the account's current timezone. The traversal
therefore reads profile/account/zone before acquisition and checks it again before
each task promotion. Changed zones or accounts fail visibly. These metadata reads
count toward all request/byte/time bounds, but unrelated profile settings and
possible provider secrets are not persisted as task Originals. Only the checked
account binding and zone remain in the private traversal plan. Task, comment,
subtask, project and inventory responses retain exact source bytes.

Date-only values stay dates. Timed values use shipped timezone data; a missing or
ambiguous DST offset is not guessed. Source state, archived status, start context,
assignees, parents, recurrence settings, comments/replies and durable links remain
visible with the read-only Task and links to its Original response evidence.
Archived does not falsely imply completed. The common Task representation keeps
the explicit provider context alongside its neutral state. `updated_at` is a weak
observed revision, not an atomic conditional write primitive.

## Qualification and outstanding provider gate

Current and Cura expose `/tududi/connect`. Passive GET views and acquired Task
consultation do not read the vault or contact a server. Controls require loopback,
bounded forms, CSRF, explicit confirmation and the displayed revision. CLI device
configuration reads bounded JSON outside the Instance, with `endpoint`, `token`
and `server_version`; credentials are never accepted as command arguments.
Unsupported versions/capabilities have a visible closed diagnostic.

Synthetic automatic tests exercise actual scheduler/intake/objects, independent
accounts/endpoints, all Source scopes, Original bytes, comments/subtasks, date-only
and timed dates, DST/zone/account changes, pagination, partial continuation,
revocation/rate waits, external-vault failure, policy races, full resync and
seven-language views. `--ocr-command tududi-qualify <fresh-target>` exercises the
installed synthetic path, exact replay, offline/portable reconstruction and the
real frozen HTTP worker's typed endpoint refusal. The permanent installed offline
Windows job invokes it under its existing network boundary. Browser productivity
cells include the Tududi controls and acquired Task/Source provenance.

Real Tududi endpoints/accounts, installed version, token permissions and provider
behavior remain NOT_RUN without their specific authorization/evidence. Human
manuals remain DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official release
on the maintainer's Windows 11 Pro 25H2 PC. No intermediate personal installation
occurs. Automatic conformance is not live-provider acceptance.

The reviewed public PATCH task handler loads the current row and calls an
unconditional `task.update(taskAttributes)`; its request contract has no atomic
revision condition. Merely reading `updated_at` then PATCHing would allow a race
and cannot satisfy S15. The [approved L decision](concordia-step-0.md) requires a
safe provider primitive or an explicit scope decision before release. This
development candidate neither invents that primitive nor silently drops write-back.
