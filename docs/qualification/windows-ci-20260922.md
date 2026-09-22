# Windows full-suite allocation refresh

Issue #279 owns this test-infrastructure correction. It does not qualify a
candidate or release. Complete exact-head and post-merge CI remain required.

The accepted main `84b94a18dd99c4504543140e7f9656004056be04` completed Windows Core
in run [35498405366](https://github.com/gabned/provelume/actions/runs/35498405366),
job `106045602773`, in 473.75 seconds against the unchanged 480-second suite limit.
All 160 module timing records were complete and non-failing. Recorded test-phase
loads across its four processes were 431.27, 443.37, 351.23 and 457.21 seconds.
Later runs `35769194462` and `35771425096` exhausted the same limit; those failures
remain failures and do not supply costs for this refresh.

`core/provelume/pytest_windows_shard.py` now uses every complete successful
baseline record as versioned allocation data: module path, collected test count,
and `max(1, round(total_seconds * 1000))`, where total includes setup, call and
teardown. New modules and changed counts still use the existing count fallback.
The allocation algorithm, module atomicity, complete test union, deterministic
ordering, four processes, timeout bounds and failure propagation are unchanged.
Historical replay predicts about 420.77 test-phase seconds per process for the
baseline inventory. This is a diagnostic estimate, not a new Windows execution.

The exclusion browser happy-path test also waits, bounded to ten seconds, for
the real initial scheduler cycle to finish. It still executes that cycle and all
existing preview/apply, CSRF and read-only assertions. The independent runtime
behavior for an actual competing writer is owned by #277 / #278.

## Preserved workflow and dependency inventory

- `ci.yml` retains its `pull_request`, trusted-base `pull_request_target` and
  default-branch `push` triggers, concurrency rules, permissions and job names.
- Core tests retain Python 3.12, Ubuntu and Windows, the pip dependency cache,
  editable development installation, Ruff and the complete `python -m pytest -q`.
  The job remains bounded to ten minutes and the Windows suite to 480 seconds.
- The pytest plugin remains registered by `pyproject.toml`; source selection,
  targeted invocation behavior and failure cleanup remain unchanged.
- Windows installer and release-foundation jobs, build inputs, cache keys,
  preview artifact producers/consumers and 14-day retention are unchanged.
  No build or release artifact is reused or promoted by timing hints.
- Existing allocation, complete-membership, malformed-hint, timing and process
  lifecycle contracts remain part of the full native and remote suites.
