# Windows allocation observations, 2026-10-19

PRODUCT owner: [#407](https://github.com/gabned/provelume/pull/407), beneath
[#402](https://github.com/gabned/provelume/issues/402). This is allocation evidence,
not acceptance of an unqualified candidate or a replacement for the original gate.

On candidate `c7868cbf50eeecc7e813c2e81475c33dcc4fe4c1`,
[run39326695589](https://github.com/gabned/provelume/actions/runs/39326695589)
attempt1 group0 exceeded the unchanged540-second deadline at540.344seconds.
The supervisor terminated shard0 during
`test_explicit_browser_rejection_retains_receipt_without_canonical_facts`;
its final shard receipt is absent. Shard1 completed. The other group completed
shards2/3. The aggregate correctly refuses the incomplete execution proof.
Artifacts12223466638 and12222144637 were read in full, including every member/CRC.
The timeout remains failed and is not evidence that its last active test is defective.

The allocation hints still described160modules from September22. Several expensive
modules had changed count or were new, so their allocation fell back to one second
per test. In the failed candidate's completed modules,
`test_agent_protocol_v1_2.py` measured145.379seconds for15tests, against its
15-second allocation fallback; `test_iudicium_journey.py` measured66.910seconds
for9tests, against9seconds; `test_custodia_qualification_failures.py` measured
35.343seconds for7tests, against7seconds. These timings diagnose uneven work;
they do not qualify the interrupted shard.

The refreshed hints come entirely from the already accepted main
`187bd04f7793c0ce037b7e698ed7916b3e91060f`, tree
`119c1fddebda1a4890370cd79ff397510baa945f`, complete successful
[run39209689964](https://github.com/gabned/provelume/actions/runs/39209689964),
attempt1. Both original archives12167337447 and12167043500 were read completely.
Their group durations were310.875 and245.172seconds. The231 complete module
records have unique paths, complete selected counts and no failing phase.
Their setup/call/teardown sums are rounded to integer milliseconds, minimum1.
Modules without complete timing, new modules and count changes retain the existing
count fallback. No interrupted candidate module supplies a measured hint.

The deterministic allocator, four-shard count, complete collection, test bodies,
selected-node identity, outcome/subtest recording, disjoint-union verification,
timeouts and aggregate refusal are unchanged. Fresh Windows execution on the new
source must still prove every required phase before integration. Historical
success and failure remain bound to their own source and attempt.
