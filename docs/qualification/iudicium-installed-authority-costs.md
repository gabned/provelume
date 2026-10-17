# Installed admission authority cost observations

Corrective diagnostic follow-up #365 to merged owner #364 / prerequisite #363,
within campaign #349. This document defines scope, not acceptance. Original
owners, failures and S03 #361 / owner #362 history remain preserved.

Actual main37f6ae2503c9aee23207504cbece065d61b8bb28 ordinary Installed39011769503
attempt1/job117335619300 fails the second self-test at public-inventory after
60860ms. Nine earlier checks pass; explicit parent kill is not reached, timing is
missing and the three final lifecycle gates are unqualified. Its closed public
report measures6863 original checkpoint calls taking49298ms, versus343ms for ACL
calls. It verifies1849files/58973067bytes and completes1285of1939grants before
exhausting the58547ms entry budget. This locates cumulative cost in checkpoints;
the cost of individual live authority components is not yet demonstrated. It does
not attribute the failure to ACL APIs, native error zero, an old host or #348.

An optional complete group records four bounded integer millisecond totals:
checkpoint_configuration_elapsed_ms, checkpoint_control_elapsed_ms,
checkpoint_models_elapsed_ms and checkpoint_selection_elapsed_ms. The existing
current configuration, job control and model-selection reads and native-selection
construction execute exactly once in their original order. Session, runtime and
allowed-model checks retain their original position. All values remain fresh;
no authority or locality result is cached, sampled or reused.

The in-memory observer exists only during an existing public-inventory checkpoint
and is local to its execution context/thread. Nested contexts restore their caller;
finally resets the scope after success, cancellation or any exception. Outside that
scope there are no component clock reads. Existing checkpoint totals include these
component times, so their sum cannot exceed checkpoint_elapsed_ms. Times describe
the measured component calls, including partial work before a failure; they are
not a claim that a failed authority probe completed. No path, policy text, model
content, SID, exception message, new API, journal or telemetry is added.

The four fields are projected only together, alongside the original complete
checkpoint/ACL timing group. Historical maps retain their exact shape when absent;
partial, private, noninteger, negative, excessive or overlapping measurements are
rejected. Clock/recording failures omit timing fields without skipping a live
read or replacing its exception or Win32 error. Only the current owned exception
can reach the existing model-operation markup, form driver and closed CI summary.

All original public-package enumeration, hashing, pinning, integrity-before-ACL,
grant constraints, cancellation/deadline checkpoints, handle lifetime, cleanup,
containment and native selection remain unchanged. There is no runtime correction,
timeout/snapshot/threshold change, retry, permission change or waiver. Synthetic
regressions and source-control-flow comparison prove these bounded properties;
they do not qualify a real Windows lifecycle or infer an old failure's cause.

Before publication run full unchanged native/Ruff/diff and canonical dependency
verification. Reconcile actual GitHub source, complete effect/owner binding, every
applicable workflow/attempt/job/review/finding/thread, fresh preflight, normal
expected-head merge, actual parents/tree and all post-merge gates. Preserve every
historical failure; no unchanged CI recovery or new acquisition probe is authorized.
Reconcile #363 only after the corrected integrated source satisfies all its gates,
then integrate accepted main through the supported route into the same S03 owner
and fully qualify that candidate before continuing S04/S05. Classifier quality
remains NOT_EVALUATED and automatic application denied; omitted human/label work
stays explicitly nonblocking with factual NOT_RUN/UNVERIFIED/NOT_REVIEWED. One
final official0.13.0 follows the included slices and integrated S01/Cura qualification.
