# ADR 0056 — Installed preparation observations

Status: diagnostic candidate #356, prerequisite of campaign #349.

Original artifact 11845515491 belongs to #353 at
248ed997f5d3fff43cfdce5cdbb641ae7937ac1e. Its independently verified ZIP SHA256
is 9ff4e8d626d9938e6e4ec1de79108f7935e0fdc3ee49431e4bb48ba34baeabb7.
The retained report has phase `parent_death`, `ValueError/model_operation`, a
final ordinary self-test with error `timeout`, and no `parent_death_seconds`.
The unchanged harness calls that self-test before killing the parent. The
failure therefore does not establish an orphan, a measured termination-bound
failure, or a runtime cause. Nine preceding checks, including the complete
ordered 32-case synthesis corpus, remain PASS in their original scope.

The diagnostic owner separates `parent_death_prepare` from `parent_death`.
Only a completed ordinary warm-up and external observation of a live worker
advance the phase. Failed preparation creates no parent-death measurement or
passing check. This corrects attribution, not runtime recovery.

The existing ordinary driver retains elapsed time with each terminal model
operation, including repeated self-tests in its original ordered history. The
one extra cancellation experiment also records only closed job/attempt phase
and boolean quiescence observations. Missing facts remain null. It continues
to report NOT_OBSERVED unless the original cancellation diagnostic is actually
observed; there is no additional distribution gate, consent, request or retry.

The model, runtime, corpus, twelve Installed controls, request and termination
limits, native/CI suites and workflow timeouts remain unchanged. No private
prompt, output, exception, path or stderr trace is added. Real Windows diagnosis
uses the permanent Installed workflow and exact candidate, preserving every
attempt/job. Synthetic tests prove observation contracts only. No runtime fix
or qualification of #353 is inferred from this diagnostic candidate.

#348 retains its independent concluded NON_DIMOSTRATA diagnosis and original
FAIL. This owner neither reopens that experiment nor attributes new data to its
old host. No provider, pin, classifier quality, next slice, version or publication
change follows; real classification quality remains NOT_EVALUATED.
