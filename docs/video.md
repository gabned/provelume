# Local video profiles

Video profiling is an explicit local job for one exact DocumentVersion. Candidate containers are
MP4, MOV, MKV, WebM and AVI, but a preserved container is not a blanket codec promise. The closed
matrix is published in `packaging/video/ffmpeg-9.0.1.json`; unsupported, encrypted, corrupt or
excessive streams remain preserved with higher operations unavailable.

    provelume video-support INSTANCE
    provelume video-queue INSTANCE VERSION_ID --frame-ms 1000 --frame-ms 12000 --language auto
    provelume video-run INSTANCE JOB_ID
    provelume video-profiles INSTANCE

The job records bounded streams and chapters, converts qualified embedded subtitle evidence to
inert WebVTT, reuses the S04 local-ASR contract for transient mono PCM, detects at most 64 scenes
from deterministic 64×36 grayscale samples, and materializes one PNG keyframe per scene. OCR is
never continuous: it runs only for the sorted, unique `--frame-ms` timestamps supplied explicitly
by the operator, at most 16. Subtitle, transcript, scene and frame evidence reopen exact time or
paired time/region anchors in the unchanged Original.

## Optional local FFmpeg pair

S05 selects only FFmpeg/ffprobe 9.0.1 from the official `ffmpeg-9.0.1.tar.xz` source. Set all five
values explicitly before starting Provelume:

    PROVELUME_FFMPEG_PATH=/absolute/path/to/ffmpeg
    PROVELUME_FFPROBE_PATH=/absolute/path/to/ffprobe
    PROVELUME_FFMPEG_VERSION=9.0.1
    PROVELUME_FFMPEG_SHA256=<sha256-of-that-exact-ffmpeg-binary>
    PROVELUME_FFPROBE_SHA256=<sha256-of-that-exact-ffprobe-binary>

The source archive must be exactly 12,036,420 bytes and have SHA-256
`cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635`. Both binaries must match
their configured digests. The Python wheel, source distribution and Windows installer contain
neither binary nor codec payload. The runtime performs no `PATH` discovery, download, update,
remote fallback or network-protocol decode. PyAV and PySceneDetect are deliberately not used.

Use `video-cancel` and `video-retry` for recovery, and `video-remove` / `video-rebuild` for the
derived lifecycle. Backup and portable transfer retain jobs, bundles and removal history without
changing Originals or canonical knowledge. `GET /api/v1/video`, `/api/v1/video/support` and the
local `/video` Browser view are read-only; mutation remains service/CLI-local.

No live camera, microphone or feed, surveillance, DRM bypass, generative media, remote inference,
continuous frame OCR, automatic summary/classification, speaker/face identity or source edit is
part of this profile. See [ADR 0025](adr/0025-bounded-local-video-profiles.md) and the
[Italian guide](video.it.md).
