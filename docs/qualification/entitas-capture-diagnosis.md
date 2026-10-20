# Entitas Capture and Windows qualification

PRODUCT owner [#407](https://github.com/gabned/provelume/pull/407), coordinated
under [#402](https://github.com/gabned/provelume/issues/402). These observations
retain their individual source identity; they do not accept a later head.

The original adoption candidate `3f2b76bfef57c7468ce7d37bd702e9a1fed1b918`
failed Windows S06 in run `39302706024`, job `118231745353`, artifact
`12213645106`. The final, post-WFP `s05-real.json` SHA256 is
`420b12b780ad6cbf62464bd86e6951830d9c3ed12d5cdd95cfc15f81826de1a4`.
Its 28 gates contain only `s06_governed=FAIL`; network is PASS.
The observed Capture time is 0.281 seconds against the calculated 0.226 limit.
The historical cause remains **NON_DIMOSTRATA**. The earlier JSON in its log is
intermediate and does not replace that final report.

The bounded profile on `0cd70e952620680b51475fbf51b8feca2df3ec36` identified
repeated temporary-file allocation while staging unpublished transaction payloads:
18 `mkstemp` calls took approximately 0.1 seconds under the synthetic busy load.
This is a measured staging cost, not proof of the original failure's cause.
That candidate had 15 runs, 15 attempts and 49 jobs: 38 successful, 10 skipped
by their trigger conditions and one failed. Its Windows CPU report passed all
28 gates, while Linux failed S06. Both outcomes remain recorded.

The correction creates candidate and preimage files exclusively in the new
private transaction directory and flushes/fsyncs them before publishing the
prepared marker. Redundant temporary-file renames before publication are removed.
The writer joins, directory barriers, atomic markers, live-path checks, recovery
format and rollback remain. Tests exercise fsync, exclusive creation, the private
POSIX mode and existing failed-writer recovery.

Candidate `c7868cbf50eeecc7e813c2e81475c33dcc4fe4c1` passed the Linux CPU
gates but failed Windows S08: cold first output took 22.062 seconds against
20 seconds, with 17.016 seconds measured in native prefill. Its Windows S06
and final network gates passed. A separate Windows Core shard exceeded its
unchanged 540-second deadline. Its incomplete receipt remains failed;
[the allocation evidence](windows-ci-20261019.md) records the relevant correction.
Neither the observed runner CPU difference nor Python version establishes a cause
for these historical failures.

A fixed six-child diagnostic on
`39b08cf5324aa8e6d4c26551081b67f3a78cda94` compared microbatch sizes
128, 192, 256, 256, 192, 128 on the unchanged first synthesis envelope and model.
Run `39333327545`, job `118336615169`, artifact `12226285572` contains all
six reports and logs; every one of its 13 members was read and CRC-checked.
The parent report SHA256 is
`d7e8356586a23a4f5701145b588a1407787bcf1b85a24bfd2e03710051563799`.

| Microbatch | First output seconds, in execution order | Peak RSS bytes |
| --- | --- | --- |
| 128 | 5.922; 6.078 | 1736368128; 1735155712 |
| 192 | 5.922; 7.281 | 1742192640; 1741971456 |
| 256 | 5.843; 6.359 | 1748013056; 1748328448 |

These samples do not show a consistent benefit. No runtime microbatch, model,
configuration identity, quality corpus, deadline or memory threshold is changed.
The diagnostic is NOT_EVALUATED for qualification and its network observation is
UNOBSERVED. Its temporary job and script are removed after recording all results.

The ordinary, separate 28-gate CPU reports on that source passed on both platforms.
Linux artifact `12225997473` has final report SHA256
`051b8afdcbda2b7cf315dbfa520c881181311368cf3a730f62d7ceadfb83ec74`;
Windows artifact `12225872417` has final report SHA256
`929666be2d8becaff568d6b5c2207e1d9dbdbb8d27ecb5a2fe60f5de7fc91cc1`.
Both archives were read in full, including the final network observation.
The full run inventory contains 16 runs, 16 attempts and 55 jobs:
45 successful and 10 skipped by trigger conditions. Local native checks recorded
4805 passed, 53 skipped and 407 subtests passed. These results do not transfer
to the cleanup commit, an eventual merge, the Protocol adoption or the release.

The Windows package additionally records the actual frozen `python312.dll` bytes
and version alongside the exact installer identity. On `c7868cb` it was 3.12.10,
while the Linux release builder used 3.12.14. Dependency applicability is a
separate bounded assessment; this divergence does not explain S06.
