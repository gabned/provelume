# Custodia gateway preflight (0.12/S01)

`ai_contract.py` provides immutable schema-version-1 internal records using existing
dataclass, closed error and canonical JSON conventions. `ai_gateway.py` owns the single
pure resolver and planner. `ProvelumeInstance.ai_explain(...)` is a static internal service
seam: it can be called without opening an Instance, so ordinary startup recovery is not
part of preflight. It adds no CLI, API, UI, persisted configuration or scheduler execution.

## Inputs and trust

The candidate RequestDescriptor contains only capability, exact Instance/Document/Version,
context fingerprint, consent revision, template identity/revision, input byte count and
limits. It accepts no prompt, endpoint, credential reference, paths or extra fields.
The supported planning capability is `structured_output`; vision, embeddings,
transcription and tool calling are explicit reserved capabilities and are denied.
This is not S02 context extraction, tokenization, redaction or result-schema evaluation.

The host supplies three independent inputs outside the request:

- GovernanceSnapshot: current exact context/consent binding, network gate, consent state,
  revision and complete applicable scope inventory. Include every acquisition Source for
  the governed content, every category, primary/secondary Area/Project and inherited
  ancestors. Empty Source/category inventories and duplicate scope identities are invalid.
- PolicyRule records: exactly one unambiguous rule for every scope. A scope with no override
  still supplies an explicit inherit-only rule. Identical repeated rules are idempotent;
  conflicting duplicates, missing rules and unexpected scopes are denied.
- Profiles and LocalityEvidence: declared provider/model and route revisions/capabilities,
  plus independently accepted qualification bound to the full profile fingerprint.

S01 does not collect these snapshots from canonical data or manufacture qualification.
Their producer must establish provenance and completeness from current authoritative state;
a content digest authenticates neither. The internal seam is not exposed as a caller-controlled
execution boundary. Omitting a Source in a future collector is a collector defect, not an
allowable request preference. Future execution requires that authoritative collector and
the later context/job/budget/consent gates; possession of a plan never substitutes for them.

## Resolution and locality

Restrictions apply across all scopes by intersection. Any explicit deny or off wins.
Local-only is an OR of restriction ceilings, including any local-only mode. Allowlists
intersect, and limits take the component-wise minimum. Instance supplies the initial
bounded allowlists and limits; an absent Instance mode means off. Empty allowlists deny.
An inherited preference selects the nearest explicit mode/ordered route in
Instance → Source → category → Area → Project order. Multiple different preferences at
the same scope level conflict and deny. Hierarchy ancestors supplied at the same level
therefore cannot silently choose a winner. This conservative S01 behavior can be extended
only with an explicit qualified hierarchy contract.

Modes are off, local-only, selected remote and expressly ordered fallback. No route is
invented and a denied primary never promotes a fallback. Every fallback is reported with
its original position and independent eligibility under locality, allowlists, capability,
network and limit ceilings. Evaluation sends nothing and performs no retry.

Strict local eligibility requires independent `managed_offline_qualified` evidence for
that exact profile. Remote eligibility requires `remote_qualified` evidence and enabled
external access. Unknown/unqualified/inconsistent or conflicting evidence is denied.
Externally managed endpoints with no accepted qualification stay unqualified. Localhost,
OpenAI compatibility and a provider's name are not evidence; endpoint addresses are absent
from this contract. A qualification revision change invalidates a retained plan.

## Binding, limits and receipts

Canonical serialization reuses sorted-key UTF-8 JSON, compact separators, no NaN and a final
newline. The binding covers request, exact context/version/consent, sorted complete scope
inventory/revision, effective policy and every contributing rule/revision, ordered route,
full selected profiles, qualification evidence, template and limits. Equivalent rule input
permutations and identical duplicate rules yield the same binding. Route order is meaningful.
`revalidate` recomputes the entire plan and refuses any changed input/result as `ai_stale_plan`.

The descriptor envelope caps input at 1 MiB, output at 8,192 tokens, attempts at four and
wall time at 300 seconds. These are planning ceilings, not runtime enforcement or cost
reservations. Each request/profile/policy chooses positive integers within those ceilings.
At most 128 scope associations, 256 rule occurrences, 16 profiles and 32 evidence records
are accepted; the final bound descriptor is capped at 128 KiB. No inference estimates,
provider billing or execution guarantees are inferred from these declarations.

Plans and base receipts expose only closed codes, bounded counts/limits and fingerprints.
They omit input/profile display strings and raw canonical identifiers. A base receipt has
`planned`, `denied` or `simulated` outcome, no attempted route, `transmitted: false`, unknown/
inapplicable usage (`null`) and no canonical mutation. `executed` is reserved and rejected by
the S01 producer. Nothing is persisted or logged by this module.

`tests/ai_gateway_fakes.py` contains the deterministic adapter, outside the installed package.
It recomputes current preflight before incrementing a simulation count and emits only the
fixed synthetic-result contract. Denied/off/stale requests never enter its response path.
The demonstration test covers allowed simulation, remote fallback rejection under local-only
and stale-Version rejection. I/O spies prohibit socket/DNS, filesystem reads/writes,
environment access and subprocess/model discovery while exercising the service and fake.
Full native suites retain deterministic intake, capture, search and reading regressions.

S02 adds bounded context and untrusted-output isolation. S01 deliberately provides no
actual model, transport, user inference path, monetary reservation or canonical-write grant.
