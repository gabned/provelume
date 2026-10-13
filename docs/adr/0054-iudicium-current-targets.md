# ADR 0054 — Current Iudicium target resolution

Status: S02 prerequisite candidate, #352, parent #349. Not complete S02 delivery.

## Existing identity and current evidence

`ProvelumeInstance.ai_classification_targets` resolves an explicit, closed host
allowlist of 1–64 distinct kind/id pairs. It reuses the existing bounded domain
review reader and canonical hierarchy validator. Area, Project and Collection
labels come from their current records; they remain untrusted display data. No
label search, best match, invented node, new provider or ontology is introduced.

The maintainer delegated the document-type interpretation after the absence of
a canonical semantic taxonomy was identified. The existing `media_type` is used:
the target ID is exactly `media_` plus the existing AI contract digest of that
recorded MIME, matching the existing CATEGORY policy namespace. Only the current
Document MIME can resolve. This is format evidence, not semantic typing such as
invoice, not a MIME detector and not permission to rewrite format metadata.

The immutable observation binds current Instance configuration, exact record bytes
for Document/Version/Original/Source, current placement and the complete bounded
hierarchy. Ancestor moves/renames, any target addition/removal, changed source or
placement and canonical provenance changes invalidate the observation. Two reads
bracket unsupported concurrent edits; the existing lifecycle/CAS boundary remains
mandatory for mutation. Corrupt, missing, mismatched, duplicate, oversized or
linked inputs fail closed. No GET, resolver or template construction writes state,
creates locks, scans external sources or contacts a provider.

An Original metadata binding does not attest a fresh hash of its payload. The
existing context producer must verify payloads before inference. Target resolution
does not collect or replace complete acquisition/policy scope, consent, profile,
locality, task-quality or scheduler authorization. An EN/IT template has complete
selected context and exactly the resolved current targets; no task language is
silently substituted.

## Acceptance boundary

This prerequisite adds the current target contract and service seam only. It does
not execute a classifier, register a proposal, expose a new UI or apply canonical
classification. The next S02 owner composes this accepted contract with the existing
gateway/scheduler and Action Center. S02 stays open until those paths are qualified.
Real classifier quality remains NOT_EVALUATED; synthetic tests cannot promote it.
Rules/application remain S03, derived autonomy S04, release-wide qualification S05
and final integration. Version identity remains 0.12.1 until the release workstream.

The complete native suite and exact-head applicable workflows, attempts/jobs,
binding, reviews/threads, fresh preflight, normal expected-head merge, actual
parents/tree and post-merge gates remain required for this prerequisite candidate.
Historical #348 evidence and published 0.12.1/0.12.0 are independent and unchanged.
