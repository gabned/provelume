# Protocol 1.4.6 — verified evidence reuse

This orchestration overlay reduces duplicate connector reads while keeping engine
1.4.2, lifecycle 1.2, campaign/handoff schema 2 and every existing gate. It changes
neither test selection nor production authority. The Work dependency inventory
remains eight files; the implementation and tests extend the existing collector.

## Reuse contract

| Evidence | Collection rule |
| --- | --- |
| Git commits and complete trees | Exact repository, object SHA and query shape; original observation retained |
| Source commit anchor and default refs | Fresh reads on every source acquisition; unchanged offline tree/blob verification |
| Terminal CI attempts and jobs | Fresh complete exact-head run inventory first; exact run/attempt/head and complete job pages |
| Running CI, unavailable responses or truncated trees | Never installed as reusable evidence |
| PR identity/files, policy, reviews and required-check selection | Fresh through the existing operational flow |
| Authority, local checks, binding, merge and post-merge readiness | Existing independent validation and execution; never inferred from cache |

Use the complete bootstrap in [the Work guide](agent-development-v1.4.3-work.md).
It creates `evidence` with `createEvidenceCollector` and passes its `readTree` to
source collection. Keep that collector for the bounded operation. All actual
responses are persisted before validation or caching. Each hit persists a separate
reuse record containing the original observation and a distinct `reused_at`;
the original `observed_at` never changes. Storage failure stops the operation.

For operational CI collection, call `await evidence.collectRuns(exactHeadSha)`.
This reads every run page, then every attempt from 1 through the observed current
attempt and every jobs page. It retains failed, cancelled and successful histories.
Only complete terminal histories enter the cache. A new attempt always receives
its own observations. If the current attempt becomes live or its conclusion
changes, its cached entry is discarded. Malformed identity, duplicates, incomplete
pagination and exhausted bounds fail explicitly; there is no automatic retry.

The result has `history_only: true` and `push_qualified: false`. Its inventory and
original attempt/jobs observations feed the unchanged operational validator;
collection itself cannot establish which workflows are required, qualify a head,
replace trusted-base or candidate CI, or authorize a merge. Observe the live gate
again at the existing decision boundary. A run starting after an observation
does not make older history proof of current readiness.

`readImmutable("commits", sha)` and `readTree(sha, recursive)` return
`{observation, reused}`. They accept no branch names or arbitrary endpoints.
The source path deliberately keeps its commit anchor fresh, even when an
operational caller separately reuses the same commit as historical evidence.
Typed file/blob acquisition retains the existing independently rehashed blob
cache; this overlay does not add decoded-file or PR-file caching.

## Resume and provenance

`evidence.snapshot()` returns the cache as a JSON string. Save these exact bytes
with the raw observation history using the [recovery archive](agent-development-v1.4.5-work.md),
and independently retain their SHA-256 and provenance outside candidate content.
Before loading a restored snapshot, establish the actual authorized host origin.
An archive hash or self-declared provenance is insufficient to authenticate data.

Pass the exact `cacheSnapshot` string, `expectedCacheSha256` and a trusted host
`sha256(text)` callback into `await createEvidenceCollector(...)`. The callback
must calculate SHA-256 over the UTF-8 bytes using the host's standard cryptographic
runtime. No crypto implementation or network fallback is embedded in this module.
Digest, repository, schema, key, timestamp, object and complete terminal-history
validation precedes insertion. A corrupt or mismatched snapshot fails closed;
explicitly starting a new cold collection is a separate host decision.
The host selects the snapshot and expected digest independently of candidate
files, just as it independently selects original user authority.

In-memory entries are immutable serialized strings; returned objects are copies.
Cache state is observational only. It cannot store policy, reviews, PRs, local
test receipts or authorization. Restoring it does not refresh those gates or
execute scripts. Limits remain finite: 10,000 calls/entries maximum, 100 pages
and attempts maximum, and a 64 MiB imported snapshot limit.

## Measurement and adoption

`evidence.metrics()` reports actual `connector_reads`, `reused_reads`, and
`100 * reused_reads / (connector_reads + reused_reads)`. The denominator is the
same sequence of logical reads without reuse. Cache verification, persistence,
fresh inventories, source checks and CI execution remain real work. A synthetic
two-pass terminal-history scenario performs four connector reads instead of six
(33.3%); that narrow fixture is not a prediction for a complete campaign.

Measure the actual workload separately. Report connector counts and payload
volume as such; do not relabel them as token, active-model-time or credit savings.
Historical replay stays outside public source unless all inputs are synthetic
or public. Workloads with few repeats may save little or nothing.

After canonical acceptance, run the unchanged `sync-adopter` entrypoint from
the accepted revision. It synchronizes all eight Work pins, four operational
helpers, manifest/provenance and the generated current 1.4.6 sections. Previous
1.4.5 sections and receipts remain historical; repeating 1.4.6 synchronization
is a no-op, while edited generated sections require explicit reconciliation.
Every adopter runs its existing complete local checks and final integration
gates. The campaign closes only after the canonical five-repository audit.
