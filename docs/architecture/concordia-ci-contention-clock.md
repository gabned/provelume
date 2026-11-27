# Concordia native CI — shared synthetic contention clock

This homogeneous PRODUCT qualification-harness correction starts from accepted
main `9c6d89c035e009e342d2c6d5c9ed3081fbcb77e8`. It changes no product runtime,
AI budget, scheduler recovery rule, request limit, test timeout, Protocol byte or
release authority. Protocol1.5.2/pin02317e0/97 canonical files and PR-local legacy
remain; Lifecyclev2 is deferred. Normal native/CI/review/expected-head merge and
actual-main checks remain mandatory.

The exact S20 `f3e53f9` native run retained a real failure in
`test_real_process_contention[False]`: both children reported a historical claim,
where the test expected one. Its complete original native log remains. The failed
temporary Instance was not retained after later pytest temporary-directory
cleanup, so the original interleaving cannot be independently reconstructed.

The harness gives each child its own job's created_at as its logical claim clock.
Those instants differ for distinct jobs. A deterministic synthetic control shows
that claiming the later job first, then moving to the earlier job's instant,
triggers the scheduler's existing backward-clock recovery. It releases the first
reserved, never-dispatched attempt and may accept the second claim, leaving one
active reservation and exactly 18,432 units. Two historical claims in that control
are not two authorized transmissions or a capacity overrun. No inference or
network was executed. This demonstrates a confounding input allowed by the test;
it does not reconstruct the lost original interleaving or explain S07's CPU FAIL.

The correction supplies one shared logical UTC instant, selected after both jobs
are enqueued and before either process leaves its barrier. It preserves both
same-job/different-job cases, actual spawn/process contention, exact assertions,
budgets and all existing 20/30-second waits. No retry loop, sleep or increased
limit is introduced. The original failure remains separate from fresh candidate
verification. This repair does not accept S07/S08 or any feature owner.

Manual checks remain DEFERRED_BY_MAINTAINER / NOT_RUN until the completed official
release on the maintainer Windows11Pro25H2 PC; no intermediate installation.
Product identity remains 0.14.0/development; publication NOT_TRIGGERED.
