# Concordia S16 — shared one-way mirror contract

This PRODUCT owner develops S16 under the [ordered development authority](https://github.com/gabned/provelume/issues/383#issuecomment-6706150974).
It consumes the unaccepted S15 candidate `8699aefe241cf0883643d6b43532e21879a45c5c`
and preserves the ordinary main merge `fadeb47f84004d48b282046e36bb3081cd1d878b`.
The S07 CPU finding and S15 public-provider conditional-write blocker remain open.
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
time. The operator receives limit findings; there is no silent truncation or
automatic split/retry. Tests cover changed inventory/consent, different identities,
scope isolation, optional includes, secret/sensitive content, tampering, interrupted
staging, replay, offline operation and unavailable transports. Frozen automatic
qualification uses disposable synthetic local data only. Human checks remain
DEFERRED_BY_MAINTAINER / NOT_RUN until the official release on the maintainer PC.
