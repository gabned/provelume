# S08 Capture responsiveness correction

S08 remains unaccepted after merging #333 as
`06769f677ce2928de707d374a33c6de06c4916b4`. The merge tree equals its qualified
candidate, but fresh [actual-main qualification](https://github.com/gabned/provelume/pull/333#issuecomment-6096401876)
passes 26/26 gates on Windows and 24/26 on Linux. All 32 S08 selections and eight
required abstentions pass on both hosts. The two Linux failures concern Capture
latency during inference, not semantic quality or output repeatability.

The unchanged Capture bound is `min(1 second, 2 × idle median + 0.1 second)`.
Linux's idle median of 0.217019654 seconds gives 0.534039308 seconds; one base
concurrent sample takes 0.559418465 seconds and S07 cold Capture takes
0.581232324 seconds. Preservation, search visibility and dispatch isolation pass.
Original reports, run/attempt identities and artifact hashes remain in the linked
ledger. This failed main observation is not replaced by the preceding head's PASS.

## Bounded correction

The synthetic diagnostic identifies repeated catalog and path metadata reads.
With 21 Documents, Capture followed by search reads 126 canonical Document
records: each of the two index observations reads the catalog three times.
Retention validation and index selection now share one fresh catalog per call,
reducing those reads to 42. Disposition records are still validated against all
Documents; there is no persistent cache and later calls observe trash, restore
and corrupt/orphaned records afresh. The two duplicate-I/O regressions fail on
the preceding source and pass with the correction.

Atomic commit path checks now inspect each existing path component once, rather
than repeatedly resolving the same chain per entry. The absolute Instance root
was resolved by InstanceStore on open; each subsequent check still freshly
observes the entire path, including root ancestors. Symbolic links, Windows
junctions, non-directory parents and unreadable components fail closed. Missing
components remain admissible without creating them during validation. The same
checks run during add, preparation, replacement and recovery; observations never
survive between those boundaries. Real-link tests also reproduce the previous
acceptance of a root or ancestor replaced with a symbolic link after open.

The journal schema, file and directory flushes, byte/digest/preimage checks,
replacement order, rollback/recovery, bounds, authorization and acknowledgement
semantics are unchanged. A diagnostic timing is not native qualification: local
elapsed times vary, and these changes do not establish that the failed latency
gate now passes.

## Required acceptance

Keep the selected model/runtime/profile and configuration digest
`1b53e5b0ea86803e13f8c516ad348f73a49631e855d3aa530c087440002c529f`, both corpora,
all 26 numeric gates and the twenty-minute native ceiling unchanged. Run full
native tests, capture/retention/recovery and real Windows junction/long-path
regressions, complete exact-head CI/reviews, normal expected-head merge, then
fresh actual-main qualification. Do not rerun unchanged failures or close #332
before that final acceptance. S09 remains dependent; no version, publication,
Recommended promotion or change to released 0.11 assets is included.
