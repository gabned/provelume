# ADR 0025: bounded local video profiles

- Status: accepted for `0.10/S05`
- Date: 2026-09-03

## Decision

Use one explicitly configured external pair: FFmpeg and ffprobe `9.0.1`, built from the official
`ffmpeg-9.0.1.tar.xz` source whose SHA-256 is
`cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635` and size is
12,036,420 bytes. The operator supplies absolute paths, declared version and both binary hashes.
Provelume neither discovers the pair on `PATH` nor bundles, downloads, updates or remotely
replaces it. Real decode qualification is limited to Ubuntu 24.04 x86-64; Windows remains
absent-safe.

The closed matrix admits only MP4/H.264/AAC/mov_text, MOV/H.264/AAC-or-PCM/mov_text,
MKV/H.264/AAC-or-Opus/SubRip-or-WebVTT, WebM/VP9/Opus/WebVTT and AVI/MJPEG/PCM. Other streams
remain preserved and inspected without a higher capability claim. Subtitles reuse the bounded
Lectio parser, transient PCM reuses S04 ASR, and OCR uses the existing Lectio region contract only
for an explicit sorted timestamp list. Scene changes are selected by a deterministic bounded
first-party comparison over 64×36 FFmpeg-decoded grayscale samples.

## Consequences

Derived bundles contain stream, subtitle, transcript, scene, keyframe and selected-frame OCR
evidence with exact time and paired time/region reopening. Process output, duration, stream,
chapter, cue, frame, pixel, rate, temporary-byte and deadline limits fail closed; process trees
are terminated on cancellation. PyAV and PySceneDetect are rejected for this slice. No live feed,
DRM bypass, continuous OCR, remote inference, identity inference, summary, source edit or network
protocol is introduced.
