# Entitas S06 warm latency investigation

This temporary diagnostic continuation belongs to the existing
`entitas-final-release` workstream, final owner #402 / original PR #403, on
`product/0.14-final-release`. It descends normally from accepted main
`cba9ff6c653bb53327ba397edf980099af90472a`, which retains that original owner
and the accepted #407 correction history. It does not change the PROTOCOL PR #409.

The failing original is #409 source
`ea4b6e07b2d9b0a283d1d8a29d5edcec64dfa8bb`, run `39799577294`, attempt 1,
Windows job `119896122376`, artifact `12434899752`. The complete original ZIP
has SHA256 `c871a45c83baf3bba1ab6166dc6f7aab0deed99c8eedcafcd257096a499d81ad`;
the final report has SHA256
`2654a96fe8799c2acc12ce1adfa9821c4642a732b97a2f6f448c0f218ccfd100`.
It remains 27/28, with `s06_governed=FAIL` and network PASS.

The third warm first-output predicate is 5.843999999999937 seconds against
the unchanged 5-second bound. Native prefill contributes 4.514999999999986
seconds (6.5625 process CPU seconds), model admission 1.2339999999999236
seconds. The earlier warm prefills are 2.1720000000000255 and
1.8279999999999745 seconds; all three reuse 170 tokens, with 112, 107 and
113 remaining input tokens. These measurements localize the variation but do
not establish its historical cause. Scheduler contention, frequency, native
batch behavior and model verification must not be asserted as proven causes.

This continuation adds per-decode wall/CPU observations and retains the exact
synthetic governed requests in the existing observer report. It preserves the
three cold/warm pairs, admission, model, context, affinity, priority, native
configuration, corpus, network controls and every evaluator predicate. No
inference is retried or discarded. All instrumented results are DIAGNOSTIC /
NOT_ACCEPTED, including any green workflow or report. They cannot replace the
failed original or qualify #409. There is no runtime correction proposed yet.

The existing permanent CPU workflow is the execution location. Its first new
attempt supplies Windows evidence without rerunning the failed #409 candidate.
After the fixed diagnostic cohort, examine every batch and its exact synthetic
input before selecting any correction. A correction, diagnostic cleanup and
fresh ordinary source/main qualification remain separate requirements. No
publication signal, tag, release or upload is part of this investigation.
