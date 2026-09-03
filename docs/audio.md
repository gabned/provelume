# Local audio profiles

Audio profiling is an explicit local job for one exact DocumentVersion. Provelume never scans a
microphone, recording library or live feed. The bounded inspector recognizes WAV, FLAC, MP3,
M4A/AAC and OGG with Opus or Vorbis. Only PCM16LE WAV, mono or stereo, is decoded in S04; other
cells are inspect-only and report waveform/transcription as unavailable.

    provelume audio-support INSTANCE
    provelume audio-queue INSTANCE VERSION_ID --language auto --threads 2
    provelume audio-run INSTANCE JOB_ID
    provelume audio-profiles INSTANCE

PCM audio produces `waveform.json` with at most 2,000 integer peak/RMS points. A deterministic
integer recipe resamples it to mono PCM16LE at 16 kHz. Container, codec, channel, sample-rate,
duration, warnings and recipe hashes stay attributable to the exact immutable Original.

## Optional local ASR

S04 selects only external `whisper.cpp` 1.9.2 and the multilingual `ggml-tiny-q5_1` model. Set all
four values explicitly before starting Provelume:

    PROVELUME_WHISPER_CPP_PATH=/absolute/path/to/whisper-cli
    PROVELUME_WHISPER_CPP_VERSION=1.9.2
    PROVELUME_WHISPER_CPP_SHA256=<sha256-of-that-exact-binary>
    PROVELUME_WHISPER_MODEL_PATH=/absolute/path/to/ggml-tiny-q5_1.bin

The model must be exactly 32,152,673 bytes and have SHA-256
`818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7`. The binary must match the
configured digest. Missing or mismatched components stay visibly unavailable; the installer and
runtime never fetch or update them.

`transcript.json`, inert `transcript.txt` and `time-map.json` preserve segment and qualified word
timestamps, confidence and warnings. Every time interval reopens evidence in the same exact
Original. Text is an uncertain derived observation, not a verified statement or participant
identity. Speaker identity and diarization are absent.

Use `audio-cancel` and `audio-retry` for job recovery, and `audio-remove` / `audio-rebuild` for the
derived lifecycle. Backup and portable transfer retain jobs, bundles and removal history. They do
not change Originals, canonical knowledge or provider data.

No remote speech service, live capture, source edit, summary, classification, model download or
network fallback is part of this profile. See [ADR 0024](adr/0024-bounded-local-audio-profiles.md)
and the [Italian guide](audio.it.md).
