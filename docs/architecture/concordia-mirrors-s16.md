# Concordia S16 — shared one-way mirror contract

This PRODUCT owner develops S16 under the [ordered development authority](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974).
It consumes the unaccepted S15 candidate `aef710d0a06b26147da726a1b5fa666f5decb4df`
and preserves the ordinary main merge `fadeb47f84004d48b282046e36bb3081cd1d878b`.
The S07 CPU finding remains open. The maintainer [explicitly deferred unsupported
Asana/Tududi writes from 0.15.0](https://github.com/gabned/provelume/issues/383#issuecomment-6711131611);
the original provider failures remain unchanged and those connectors stay read-only.
Development, automatic conformance and acceptance are separate states.

The payload defaults to readable Markdown and bounded portable metadata selected
by Instance, Area or Project. Every mirror has an independent identity, destination,
scope, revision and disabled/manual/scheduled policy. Credentials and destination
secrets stay in the device OS vault, outside canonical knowledge and portable data.
Imported policies have no authority on another device/root.

The shared implementation captures selected content under the existing lifecycle
boundary, seals a complete immutable generation and independently verifies its
inventory before exposing it to a transport. It never hands a live Instance tree
to Git, rsync or a filesystem destination. Missing, truncated, changed or over-limit
content fails the whole preparation. Originals, private attachments and AI receipts
have distinct explicit include rules; they are absent by default.

A dry run binds the complete source and destination inventories, destination
identity/visibility, policy, include rules, findings and limits. Any change requires
a new preview. Unknown visibility blocks private payload. A public payload needs
an exact path/hash allowlist and explicit confirmation, including scheduled use.
Known secret patterns block publication; sensitive content requires the configured
finding policy and confirmation. A scan never certifies that arbitrary prose is
free of secrets or personal data.

S16 supplies no qualified transport. Missing transport capability is visible and
cannot dispatch a network request or process. S17–S22 separately qualify Git,
GitHub, GitLab, Gitea, local-folder and rsync/SSH activation and recovery. A final
receipt requires an exact independently checked destination manifest. Interruption,
ambiguous outcome and malformed receipts cannot become success or replay authority.
Deletion, bidirectional sync, canonical storage and backup/restore claims are absent.

Before the first qualification, the implementation fixes finite limits for records,
files, individual bytes, total generation bytes, manifests, plans and operation
time: 20,000 canonical records and 256MiB aggregate JSON, 1,000 selected Documents,
5,000 files, 32MiB per file, 256MiB per generation, 2MiB manifests, 16 retained plans,
8 retained generations, 32 identities/destinations and 60 seconds per preparation.
Full Original verification also admits at most 256MiB total and 32MiB per Original.
These are refusal bounds, not claims that every supported machine completes the
largest combination within the time budget. The operator receives limit findings;
there is no silent truncation or
automatic split/retry. Tests cover changed inventory/consent, different identities,
scope isolation, optional includes, secret/sensitive content, tampering, interrupted
staging, replay, offline operation and unavailable transports. Frozen automatic
qualification uses disposable synthetic local data only. Human checks remain
DEFERRED_BY_MAINTAINER / NOT_RUN until the official release on the maintainer PC.

## Operator path / percorso operatore

EN: Mirrors start disabled. Enable mirror access on this device, then separately
allow GitHub or rsync/SSH when needed. Create an identity and destination with
`mirror-identity` and `mirror-configure`, reading their configuration from an
external device file; secret references and target locators go only to the OS
vault. Select `instance`, `area` or `project` and exact optional include IDs.
The Cura/Current mirror page and `mirror-prepare` prepare local staging and show
the inventory, bytes and privacy findings. A local preview explicitly reports
destination visibility/permissions/content NOT_OBSERVED. It grants no publication.
`mirror-schedule` connects scheduled policies to the existing scheduler; S16 only
prepares local generations. S17–S22 supply independently qualified publication.

IT: I mirror sono disabilitati per impostazione iniziale. Consenti l'accesso su
questo dispositivo e, separatamente, GitHub o rsync/SSH se necessari. Identità,
destinazione, ambito Instance/Area/Project e inclusioni esplicite restano distinti.
Cura/Current e `mirror-prepare` mostrano lo snapshot locale completo, inventario,
dimensioni e rilievi; non attestano visibilità o permessi remoti. La pianificazione
S16 prepara soltanto generazioni locali. Nessuna pubblicazione diventa disponibile
prima della qualifica separata del trasporto.

No GET unlocks the vault, reads a destination, invokes Git/rsync or scans document
content. Revocation disables future operations without deleting knowledge or
remote history. An imported policy is ineffective at a new device/root. Plans
expire after fifteen minutes and bind access, identity/grant, policy, source
generation and exact destination observation. Single durable dispatch claims and
UNKNOWN records are shared primitives; only a separately qualified transport may
call them. The final receipt contains hashes/counts/bytes, no target locator or
content, and asserts neither destination deletion nor backup validity.

Interrupted staging is never complete. Explicit discard/forget/drop removes only
local derived plans/generations; unresolved dispatches cannot be forgotten. These
actions never remove destination data. At capacity, choose exact completed/discarded
local material to remove; the system does not silently prune evidence or retry.

`--ocr-command mirror-qualify <fresh-target>` runs the actual Core services in a
frozen executable over fresh synthetic local data: two identities, three scopes,
complete inventories, restart/replay/UNKNOWN receipt and portable reconstruction
without imported grants. The permanent installed offline Windows job executes it.
Its PASS explicitly retains `real_transports: NOT_RUN` and
`publication: TRANSPORT_NOT_QUALIFIED`. Native/browser/frozen/live-provider and
human observations retain separate evidence and no inherited-head acceptance.
