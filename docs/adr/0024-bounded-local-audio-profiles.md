# ADR 0024: Bounded local audio profiles and one ASR path

## Status

Accepted for 0.10/S04.

## Context

Provelume preserves audio Originals but had no media-specific inspection, waveform or citable local
speech transcript. The existing Lectio SRT/WebVTT contract covers supplied transcript files; it
does not attest that text came from audio. S04 must add derived evidence without making a codec or
model canonical knowledge, silently downloading software, or presenting uncertain speech as fact.

## Decision

Core identifies and bounds WAV, FLAC, MP3, M4A/AAC, OGG/Opus and OGG/Vorbis by signature and
container structure. Only signed 16-bit little-endian PCM WAV with one or two channels is the first
qualified decode baseline. It receives a deterministic integer waveform and an explicitly recorded
mono/16 kHz resample recipe. Other candidate cells remain inspect-only with a typed unavailable
state; this slice does not introduce FFmpeg ahead of S05.

The one selected ASR path is external `whisper.cpp` 1.9.2 at source commit
`306c88f4d1286aec1bf96e544632897886af5501`, CPU-only, temperature zero, with the multilingual
`ggml-tiny-q5_1` model. The model must be exactly 32,152,673 bytes with SHA-256
`818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7`. An operator must configure
absolute binary/model paths, the exact engine version and the installed binary SHA-256. A mismatch
is incompatible, not available. Provelume bundles and downloads neither component.

ASR output remains a derived observation. Segment and qualified word timestamps, confidence and
low-confidence warnings map back to the exact Original through universal time anchors. Speaker
identity is always absent. Lectio's correction contract is referenced without changing transcript
Originals or canonical records. A different binary, model, language or thread setting creates a
different recipe identity and preserves prior evidence.

## Consequences

- Inspection and PCM waveform remain useful when ASR is absent.
- Derived bundles, jobs and checkpoints are portable, removable and equivalently rebuildable.
- No remote speech, diarization, summary, classification, source write or runtime download exists.
- Additional decode cells or another ASR engine require a later explicit decision.
