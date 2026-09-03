# Perceptio 0.10/S07 qualification map

Status: completed by #180/#182 and merged as `444cec893dc9a4f286f0fadacc5c0cc0a2c9a783`.
This historical S07 record describes the final implementation-slice gates; publication is governed
separately by #183 and the [0.10.0 release qualification](0.10.0.md).

| Required evidence | Permanent evidence path | Closed result |
| --- | --- | --- |
| One service/CLI/API/Browser model; GET-only detail and anchors | `tests/test_perceptio_integration.py`; `perceptio-final-qualification.yml` | Exact model parity, bounded 1–500 reads, no mutation |
| EN/IT, keyboard semantics, reflow and hostile text | integration test; `docs/accessibility.md`; existing CSS/accessibility suite | Equal catalog keys, native semantics, escaped data |
| Photo, audio, video and exactly CSV/XLSX/ZIP | profile contracts and permanent photo/audio/video/file-family smokes | No family, codec, engine or model added by S07 |
| Offline/privacy/GPS/active content | integration test plus profile hostile-input/no-network tests | No network/writeback; GPS default excluded; content inert |
| Uncertainty, correction and exact reopening | universal bundle validation and integrated detail/anchor tests | Warnings preserved; corrections annotations and reversible |
| Resource/process limits and interrupted recovery | profile limit/cancel/retry suites; Public repository CI | Existing bounded failures stay closed; no new worker |
| Remove/rebuild, backup/restore, portable transfer | representation and each profile recovery suites | Derived state recoverable; authority bytes unchanged |
| Components, licenses and release SBOM | component inventory suite and release pipeline | Local state remains `unavailable` until final SBOM supplied |
| Clean install, N-1 upgrade/rollback, uninstall | release dry run/pipeline and Windows shell smoke | Published `0.9.0` is the only N-1 baseline |
| Publication identity and assets | separate release-preparation PR and trusted release workflows | S07 cannot version, tag or publish |

The integrated result also carries the exact 14-profile universal support registry and the
byte-unchanged Lectio compatibility projection. The four S07 family rows correspond only to the
six Perceptio profile implementations; they do not hide the eight universal/compatibility rows or
invent a fifteenth profile. The packaged `perceptio_qualification.json` and its JSON Schema bind
the seven state names, two permanent platform cells, all ten release exits and their evidence
paths. It is a qualification contract, not a substitute for exact-head workflow results.

The candidate matrix is deliberately asymmetric. Photo supports bounded JPEG/PNG/TIFF/BMP with an
optional pinned Pillow preview. Audio provides bounded WAV processing and only the selected
operator-supplied whisper.cpp/model path; other admitted containers can remain inspect-only.
Video real decoding is qualified only for the selected Ubuntu FFmpeg cell and is absent-safe on
Windows. File families are exactly UTF-8 CSV cells, cached-value XLSX sheets/cells and ZIP member
metadata. Every unsupported cell remains visible rather than falling back remotely.

The mixed test archive is public-contract synthetic data containing representative metadata,
prompt-like text and inert HTML/formula/archive payloads. No private fixture, credential, location
or user content is required. Workflow timeouts bound the qualification job; operational limits
remain the stricter per-profile constants recorded in the profile schemas and guides.
