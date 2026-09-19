# Cura domain review, placement and routing

The domain review coordinator applies a real prepared effect and its retained
receipt in one registered atomic Instance commit. Action Center's schema-1
inspection acknowledgement/rejection remains a separate contract: it cannot
confirm classification, duplicates, version selection or annotations.

## Integration contract

`ReviewDecisions(store, providers, authority_resolver=..., transaction_factory=...,
mutation_guard=...)` registers a closed set of providers. The pure authority
resolver receives `(domain, subject, action)` and returns a revision SHA256,
`mode`, JSON scope, and boolean `automatic_allowed`. Missing mutation hooks deny
confirmation. Service integration supplies the registered review transaction
factory and recovery guard; an arbitrary unregistered commit profile is never
selected by a provider.

Each provider supplies `domain`, closed `actions`, pure
`preview(subject, action, parameters)`, `allowed_paths(plan, request_id)` and
`prepare(plan, request_id=..., principal=..., recorded_at=...)`. Preview returns
an exact `input_revision`, evidence, reason, confidence (including unknown),
impact and effective reversibility. The coordinator's plan retains this under
`provider`, alongside parameters, effective authority and deterministic plan
revision. Wall-clock commit time is absent from preview digests.

`prepare` returns immutable `PreparedEffect`/`PreparedWrite` values without
publication. A write binds a normalized relative path, exact preimage SHA256 or
`ABSENT`, bounded candidate bytes and immutable/mutable intent. A retained,
immutable domain history record must be among the writes. The result is stored
as JSON bytes internally so a caller cannot change an already prepared result.

Confirmation takes lifecycle, recovers or refuses pending review transactions,
then checks exact request replay. Any secondary domain lock is taken after
lifecycle and before recollecting provider inputs and effective authority.
Changed input/authority/parameters requires a new preview. The coordinator
checks the provider's exact subject allowlist and every preimage before adding
effect and receipt to the same transaction. Reusing a request ID for a different
actor or input conflicts. An interrupted prepared journal is never success;
replay is only accepted after recovery and verification of the retained history
hash. All legacy hierarchy writers share the lifecycle guard; their explicit
`*_locked` variants are for callers already holding that guard.

## Placement and routing

`placement/classify` uses a Document subject and explicit primary Area/Project
plus up to 32 unique secondary hierarchy IDs. The preview binds the current
Document/Version/Original/Source bytes, current classification, hierarchy and
affected provenance edges. It supports unclassified and already classified
Documents. Original and Version bytes and old edges remain unchanged. A new
confirmed classification can restore earlier destinations; history is retained.

Routing actions are `save_rule`, `revoke_rule` and `apply_rule`. Save/revoke use
`routing_<32 hex>` subjects; apply uses a Document and exact `rule_id` parameter.
Rules select one Source and a literal normalized relative path prefix, matching
whole path components. Empty prefix selects that Source; wildcards, absolute
paths and traversal are rejected. Destinations use stable IDs. Save increments
the rule revision and requires an explicit boolean `automatic_enabled`; revoke
disables the rule without deleting history. Rules never change provider data,
Source locator area, Original ownership or Version identity.

`RoutingProvider.candidates(document_id)` is pure discovery for the integration's
post-acquisition hook. A rule is automatically eligible only for an unclassified
Document with one matching enabled rule and explicit rule automation. Effective
`controlled-automatic` authority must independently allow the operation. The
coordinator restricts automatic principals to `rule:routing_<32 hex>` and
`routing/apply_rule`, with that same rule ID in parameters. Multiple matching
rules remain explicit proposals; human classification is never overwritten.
Every application rechecks rules and current authority and has its own receipt.
Discovery alone neither applies a rule nor grants authority.

## Retained records and bounded reads

- `state/review/receipts/review_<32 hex>.json`: immutable committed receipt and
  replay identity; `canonical_mutation` is true only when the effect writes
  `knowledge/`. Retained-only rules/annotations still have real committed effects.
- `state/review/placement/history/<Document>/<receipt>.json`: immutable before/after
  placement history.
- `state/review/routing/rules/<rule>.json`: current revisioned rule.
- `state/review/routing/history/<Document-or-rule>/<receipt>.json`: immutable
  application or rule-edit/revocation history.

Structural definitions are in `review_domain.schema.json`; Python validators
also enforce identity, scope, request, path and semantic relationships that a
structural JSON schema cannot fully express. Missing optional state on an old
Instance is empty. Corrupt/future state, unexpected paths and symlinks/junctions
are unavailable, never silently reset. Domain inventories are bounded to 500
nodes/rules and 32 MiB of observation; receipt history reads at most 10,000 entries
with a byte bound and returns at most 500, exposing incomplete counts. Writes
are bounded to 256 domain records, 8 MiB per record and 32 MiB aggregate, plus
the coordinator receipt within the registered profile.

GET does not ensure directories, create locks, run scans or recover journals.
Pending review transactions make preview/history unavailable until the normal
lifecycle owner recovers them. `ActionCenter.review_projection` adds navigation
and actual domain receipts without copying queue records or asserting historical
receipt inputs are still current. The service remains responsible for effective
capability configuration, authenticated local routes, post-acquisition routing,
deep validation and backup/portable integration.

Effective routing rules must equal the final state of their retained confirmed
revision chain. Discovery and preview validate every revision's before/after,
receipt identity, actor, timestamp, plan, history hash and result. Missing or
divergent state/history/receipts deny routing, including when automatic capability
is otherwise granted. History and receipt bytes participate in the fresh input
revision and the existing 32 MiB observation bound; rule revision history is
bounded to 10,000 entries across observed rules. New confirmations preflight the
history count and reserve space for the next state, history and bounded receipt.
