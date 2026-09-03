from __future__ import annotations

import binascii
import hashlib
import json
import math
import os
import platform
import re
import struct
import sys
import tempfile
import zlib
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from fractions import Fraction
from pathlib import Path
from typing import Any

from .audio_profiles import (
    AudioContractError,
    WhisperCppAdapter,
    _normalise_transcript,
    inspect_audio_bytes,
)
from .ocr_contract import (
    OcrContractError,
    OcrPageRequest,
    OcrRendererCapability,
    OcrSettings,
    OcrSourcePageIdentity,
    ocr_settings_from_config,
    settings_fingerprint,
)
from .ocr_process import minimal_child_environment, run_bounded_process
from .ocr_tesseract import TesseractCliAdapter
from .paths import safe_instance_path
from .representations import (
    MAX_REPRESENTATION_ANCHORS,
    RepresentationBundleManager,
    RepresentationContractError,
    canonical_json_bytes,
)
from .storage import InstanceStore, utc_now
from .transcript_contract import TranscriptContractError, TranscriptLimits
from .transcript_parsers import BoundedTranscriptParser

VIDEO_SCHEMA_VERSION = 1
VIDEO_PROFILE_ID = "perceptio-video-v1"
VIDEO_RECIPE_ID = "provelume.video-profile"
VIDEO_RECIPE_VERSION = "1"
VIDEO_JOB_SCHEMA_VERSION = 1

FFMPEG_VERSION = "9.0.1"
FFMPEG_SOURCE_SHA256 = "cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635"
FFMPEG_SOURCE_SIZE = 12_036_420

VIDEO_FORMATS = ("MP4", "MOV", "MKV", "WEBM", "AVI")
VIDEO_MEDIA_TYPES = {
    "MP4": "video/mp4",
    "MOV": "video/quicktime",
    "MKV": "video/x-matroska",
    "WEBM": "video/webm",
    "AVI": "video/x-msvideo",
}
VIDEO_ERROR_CODES = (
    "video_not_found",
    "video_unsupported_format",
    "video_invalid_container",
    "video_input_limit_exceeded",
    "video_duration_limit_exceeded",
    "video_stream_limit_exceeded",
    "video_dimension_limit_exceeded",
    "video_frame_rate_limit_exceeded",
    "video_selection_invalid",
    "video_encrypted",
    "video_decoder_unavailable",
    "video_decoder_incompatible",
    "video_process_failed",
    "video_output_limit_exceeded",
    "video_cancelled",
    "video_contract_violation",
    "video_job_state_invalid",
)

MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_DURATION_MS = 2 * 60 * 60 * 1000
MAX_STREAMS = 32
MAX_CHAPTERS = 128
MAX_SUBTITLE_STREAMS = 8
MAX_CUES = 10_000
MAX_SELECTED_FRAMES = 16
MAX_SCENES = 64
MAX_SCENE_SAMPLES = 120
MAX_FRAME_EDGE = 1_600
MAX_SOURCE_EDGE = 7_680
MAX_FRAME_PIXELS = 33_177_600
MAX_FRAME_RATE = 120
MAX_PROBE_BYTES = 4 * 1024 * 1024
MAX_STDERR_BYTES = 256 * 1024
MAX_FRAME_BYTES = 32 * 1024 * 1024
MAX_PPM_BYTES = MAX_FRAME_EDGE * MAX_FRAME_EDGE * 3 + 1024
MAX_SUBTITLE_BYTES = 32 * 1024 * 1024
MAX_AUDIO_BYTES = 256 * 1024 * 1024
MAX_PROCESS_SECONDS = 300
SCENE_THRESHOLD_PPM = 160_000
SCENE_SAMPLE_WIDTH = 64
SCENE_SAMPLE_HEIGHT = 36

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_LANGUAGE = re.compile(r"(?:auto|[a-z]{2}(?:-[A-Z]{2})?)\Z")
_STREAM_KINDS = {"video", "audio", "subtitle", "attachment", "data"}
_SUBTITLE_CODECS = {"subrip", "webvtt", "mov_text"}
_VIDEO_CODECS = {"h264", "vp9", "mjpeg"}
_AUDIO_CODECS = {"aac", "opus", "pcm_s16le"}


class VideoContractError(ValueError):
    """Closed, content-free failure for bounded video profiling."""

    def __init__(self, code: str, message: str):
        if code not in VIDEO_ERROR_CODES:
            raise ValueError("video error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path, *, maximum: int = 1024 * 1024 * 1024) -> str:
    try:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise OSError("component path is not an explicit regular file")
        if not 1 <= path.stat().st_size <= maximum:
            raise OSError("component size is outside its boundary")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()
    except OSError as exc:
        raise VideoContractError(
            "video_decoder_unavailable", "configured video component is unavailable"
        ) from exc


def _bounded_label(value: Any, *, maximum: int = 200) -> str | None:
    if value is None or value == "" or value == "N/A":
        return None
    if not isinstance(value, (str, int, float)):
        raise VideoContractError("video_invalid_container", "video label is invalid")
    selected = str(value)
    if not 1 <= len(selected) <= maximum or any(ord(character) < 32 for character in selected):
        raise VideoContractError("video_invalid_container", "video label is invalid")
    return selected


def _mp4_top_level_types(data: bytes) -> list[bytes]:
    kinds: list[bytes] = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            raise VideoContractError("video_invalid_container", "video atom is truncated")
        size = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        header = 8
        if size == 1:
            if len(data) - offset < 16:
                raise VideoContractError("video_invalid_container", "video atom is truncated")
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header = 16
        elif size == 0:
            size = len(data) - offset
        if size < header or size > len(data) - offset:
            raise VideoContractError("video_invalid_container", "video atom size is invalid")
        kinds.append(kind)
        offset += size
    return kinds


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _ppm_to_png(data: bytes) -> bytes:
    match = re.match(rb"P6[\t\r\n ]+(\d+)[\t\r\n ]+(\d+)[\t\r\n ]+255[\t\r\n ]", data)
    if match is None:
        raise VideoContractError("video_process_failed", "selected frame PPM is invalid")
    width = int(match.group(1))
    height = int(match.group(2))
    if (
        width < 1
        or height < 1
        or width > MAX_FRAME_EDGE
        or height > MAX_FRAME_EDGE
        or width * height > MAX_FRAME_PIXELS
    ):
        raise VideoContractError("video_dimension_limit_exceeded", "selected frame is oversized")
    pixels = data[match.end() :]
    row_size = width * 3
    if len(pixels) != row_size * height:
        raise VideoContractError("video_process_failed", "selected frame PPM is truncated")
    filtered = b"".join(
        b"\x00" + pixels[offset : offset + row_size] for offset in range(0, len(pixels), row_size)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    result = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(filtered, level=9))
        + _png_chunk(b"IEND", b"")
    )
    if len(result) > MAX_FRAME_BYTES:
        raise VideoContractError("video_output_limit_exceeded", "selected frame is oversized")
    return result


def identify_video_bytes(data: bytes) -> str:
    if not data or len(data) > MAX_INPUT_BYTES:
        raise VideoContractError(
            "video_input_limit_exceeded", "video input exceeds its closed byte limit"
        )
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        if int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise VideoContractError("video_invalid_container", "AVI boundary is invalid")
        return "AVI"
    if data.startswith(b"\x1aE\xdf\xa3"):
        probe = data[: min(len(data), 4096)].lower()
        if b"webm" in probe:
            return "WEBM"
        if b"matroska" in probe:
            return "MKV"
        raise VideoContractError("video_invalid_container", "EBML document type is missing")
    if len(data) >= 8 and data[4:8] == b"ftyp":
        kinds = _mp4_top_level_types(data)
        if not kinds or kinds[0] != b"ftyp" or b"moov" not in kinds:
            raise VideoContractError("video_invalid_container", "ISO media structure is invalid")
        brand = data[8:12]
        return "MOV" if brand in {b"qt  ", b"qt\x00\x00"} else "MP4"
    raise VideoContractError(
        "video_unsupported_format", "video signature is outside the candidate matrix"
    )


def _selected_timestamps(values: Sequence[int], *, duration_ms: int | None = None) -> list[int]:
    if (
        isinstance(values, (str, bytes))
        or len(values) > MAX_SELECTED_FRAMES
        or any(type(value) is not int or value < 0 for value in values)
    ):
        raise VideoContractError(
            "video_selection_invalid", "selected frame timestamps are outside their boundary"
        )
    selected = list(values)
    if selected != sorted(set(selected)):
        raise VideoContractError(
            "video_selection_invalid", "selected frame timestamps must be unique and sorted"
        )
    if duration_ms is not None and any(value > duration_ms for value in selected):
        raise VideoContractError(
            "video_selection_invalid", "selected frame timestamp exceeds video duration"
        )
    return selected


def _fraction(value: Any) -> float | None:
    if value is None or value in ("", "0/0", "N/A"):
        return None
    try:
        result = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError) as exc:
        raise VideoContractError("video_invalid_container", "video frame rate is invalid") from exc
    if not math.isfinite(result) or result <= 0:
        raise VideoContractError("video_invalid_container", "video frame rate is invalid")
    return result


def _milliseconds(value: Any, *, allow_none: bool = False) -> int | None:
    if (value is None or value in ("", "N/A")) and allow_none:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise VideoContractError("video_invalid_container", "video timestamp is invalid") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise VideoContractError("video_invalid_container", "video timestamp is invalid")
    milliseconds = round(seconds * 1000)
    if milliseconds > MAX_DURATION_MS:
        raise VideoContractError(
            "video_duration_limit_exceeded", "video duration exceeds its closed limit"
        )
    return milliseconds


def _codec_qualified(format_name: str, kind: str, codec: str) -> bool:
    matrix = {
        "MP4": {"video": {"h264"}, "audio": {"aac"}, "subtitle": {"mov_text"}},
        "MOV": {"video": {"h264"}, "audio": {"aac", "pcm_s16le"}, "subtitle": {"mov_text"}},
        "MKV": {
            "video": {"h264"},
            "audio": {"aac", "opus"},
            "subtitle": {"subrip", "webvtt"},
        },
        "WEBM": {"video": set(), "audio": set(), "subtitle": set()},
        "AVI": {"video": {"mjpeg"}, "audio": {"pcm_s16le"}, "subtitle": set()},
    }
    return codec in matrix[format_name].get(kind, set())


def _rotation(raw: Mapping[str, Any], tags: Mapping[str, Any]) -> int | None:
    candidate: Any = tags.get("rotate")
    side_data = raw.get("side_data_list", [])
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, Mapping) and item.get("rotation") is not None:
                candidate = item["rotation"]
                break
    if candidate is None or candidate in ("", "N/A"):
        return None
    try:
        selected = round(float(candidate))
    except (TypeError, ValueError) as exc:
        raise VideoContractError("video_invalid_container", "video rotation is invalid") from exc
    if not -359 <= selected <= 359:
        raise VideoContractError("video_invalid_container", "video rotation is invalid")
    return selected


def _normalise_probe(value: Any, *, format_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("format"), Mapping):
        raise VideoContractError("video_invalid_container", "ffprobe result is incomplete")
    raw_streams = value.get("streams")
    raw_chapters = value.get("chapters", [])
    if (
        not isinstance(raw_streams, list)
        or not 1 <= len(raw_streams) <= MAX_STREAMS
        or not isinstance(raw_chapters, list)
        or len(raw_chapters) > MAX_CHAPTERS
    ):
        raise VideoContractError(
            "video_stream_limit_exceeded", "video stream or chapter count is invalid"
        )
    duration_ms = _milliseconds(value["format"].get("duration"), allow_none=True)
    streams: list[dict[str, Any]] = []
    seen: set[int] = set()
    encrypted = False
    for raw in raw_streams:
        if not isinstance(raw, Mapping):
            raise VideoContractError("video_invalid_container", "video stream is invalid")
        index = raw.get("index")
        kind = raw.get("codec_type")
        codec = raw.get("codec_name") or "unknown"
        if (
            type(index) is not int
            or index < 0
            or index in seen
            or kind not in _STREAM_KINDS
            or not isinstance(codec, str)
            or not 1 <= len(codec) <= 100
        ):
            raise VideoContractError("video_invalid_container", "video stream identity is invalid")
        seen.add(index)
        tags = raw.get("tags") if isinstance(raw.get("tags"), Mapping) else {}
        dispositions = raw.get("disposition") if isinstance(raw.get("disposition"), Mapping) else {}
        codec_tag = str(raw.get("codec_tag_string", "")).casefold()
        if (
            codec_tag in {"enca", "encv"}
            or codec.casefold() in {"enca", "encv"}
            or any("encrypt" in str(key).casefold() for key in (*raw.keys(), *tags.keys()))
        ):
            encrypted = True
        width = raw.get("width") if kind == "video" else None
        height = raw.get("height") if kind == "video" else None
        average_rate = _fraction(raw.get("avg_frame_rate")) if kind == "video" else None
        nominal_rate = _fraction(raw.get("r_frame_rate")) if kind == "video" else None
        frame_rate = average_rate or nominal_rate
        variable_frame_rate = (
            average_rate is not None
            and nominal_rate is not None
            and abs(average_rate - nominal_rate) > 0.001
        )
        if kind == "video":
            if (
                type(width) is not int
                or type(height) is not int
                or width < 1
                or height < 1
                or width > MAX_SOURCE_EDGE
                or height > MAX_SOURCE_EDGE
                or width * height > MAX_FRAME_PIXELS
            ):
                raise VideoContractError(
                    "video_dimension_limit_exceeded", "video dimensions exceed their limit"
                )
            if frame_rate is not None and frame_rate > MAX_FRAME_RATE:
                raise VideoContractError(
                    "video_frame_rate_limit_exceeded", "video frame rate exceeds its limit"
                )
        stream_duration = _milliseconds(raw.get("duration"), allow_none=True)
        language = str(tags.get("language", "und"))[:35]
        if not re.fullmatch(r"[A-Za-z0-9-]{1,35}", language):
            language = "und"
        profile = _bounded_label(raw.get("profile")) if kind == "video" else None
        level = _bounded_label(raw.get("level")) if kind == "video" else None
        pixel_format = _bounded_label(raw.get("pix_fmt")) if kind == "video" else None
        color_range = _bounded_label(raw.get("color_range")) if kind == "video" else None
        color_space = _bounded_label(raw.get("color_space")) if kind == "video" else None
        color_transfer = _bounded_label(raw.get("color_transfer")) if kind == "video" else None
        color_primaries = _bounded_label(raw.get("color_primaries")) if kind == "video" else None
        hdr = bool(
            kind == "video"
            and (color_transfer in {"smpte2084", "arib-std-b67"} or color_primaries == "bt2020")
        )
        attachment_name = (
            _bounded_label(tags.get("filename"), maximum=255) if kind == "attachment" else None
        )
        attachment_media_type = (
            _bounded_label(tags.get("mimetype"), maximum=255) if kind == "attachment" else None
        )
        channels = raw.get("channels") if kind == "audio" else None
        if channels is not None and (type(channels) is not int or not 1 <= channels <= 64):
            raise VideoContractError("video_invalid_container", "audio channel count is invalid")
        sample_rate_hz = (
            int(raw["sample_rate"])
            if kind == "audio" and str(raw.get("sample_rate", "")).isdigit()
            else None
        )
        if sample_rate_hz is not None and not 1 <= sample_rate_hz <= 768_000:
            raise VideoContractError("video_invalid_container", "audio sample rate is invalid")
        streams.append(
            {
                "index": index,
                "kind": kind,
                "codec": codec,
                "language": language,
                "duration_ms": stream_duration,
                "width": width,
                "height": height,
                "frame_rate": None if frame_rate is None else round(frame_rate, 6),
                "variable_frame_rate": variable_frame_rate if kind == "video" else None,
                "profile": profile,
                "level": level,
                "pixel_format": pixel_format,
                "rotation_degrees": _rotation(raw, tags) if kind == "video" else None,
                "color_range": color_range,
                "color_space": color_space,
                "color_transfer": color_transfer,
                "color_primaries": color_primaries,
                "hdr": hdr if kind == "video" else None,
                "channels": channels,
                "sample_rate_hz": sample_rate_hz,
                "attachment_name": attachment_name,
                "attachment_media_type": attachment_media_type,
                "default": dispositions.get("default") == 1,
                "qualified": _codec_qualified(format_name, str(kind), codec),
            }
        )
    if encrypted:
        raise VideoContractError("video_encrypted", "encrypted video is not processed")
    chapters: list[dict[str, Any]] = []
    for ordinal, raw in enumerate(raw_chapters):
        if not isinstance(raw, Mapping):
            raise VideoContractError("video_invalid_container", "video chapter is invalid")
        start = _milliseconds(raw.get("start_time"))
        end = _milliseconds(raw.get("end_time"))
        if start is None or end is None or end < start:
            raise VideoContractError("video_invalid_container", "video chapter range is invalid")
        chapters.append({"id": f"chapter-{ordinal + 1}", "start_ms": start, "end_ms": end})
    if duration_ms is None:
        durations = [item["duration_ms"] for item in streams if item["duration_ms"] is not None]
        duration_ms = max(durations, default=None)
    if duration_ms is None:
        raise VideoContractError("video_invalid_container", "video duration is unavailable")
    if not any(item["kind"] == "video" for item in streams):
        raise VideoContractError("video_unsupported_format", "container has no video stream")
    return {
        "container": format_name.casefold(),
        "duration_ms": duration_ms,
        "streams": streams,
        "chapters": chapters,
        "encrypted": False,
    }


class FFmpegAdapter:
    """Pinned local FFmpeg/ffprobe pair with no PATH discovery or runtime download."""

    def __init__(
        self,
        *,
        ffmpeg_path: Path | None = None,
        ffprobe_path: Path | None = None,
        declared_version: str | None = None,
        expected_ffmpeg_sha256: str | None = None,
        expected_ffprobe_sha256: str | None = None,
        cancelled: Callable[[], bool] | None = None,
    ):
        self.ffmpeg_path = ffmpeg_path or self._environment_path("PROVELUME_FFMPEG_PATH")
        self.ffprobe_path = ffprobe_path or self._environment_path("PROVELUME_FFPROBE_PATH")
        self.declared_version = declared_version or os.environ.get("PROVELUME_FFMPEG_VERSION")
        self.expected_ffmpeg_sha256 = expected_ffmpeg_sha256 or os.environ.get(
            "PROVELUME_FFMPEG_SHA256"
        )
        self.expected_ffprobe_sha256 = expected_ffprobe_sha256 or os.environ.get(
            "PROVELUME_FFPROBE_SHA256"
        )
        self.cancelled = cancelled
        self._verified_paths: tuple[Path, Path] | None = None

    @staticmethod
    def _environment_path(name: str) -> Path | None:
        value = os.environ.get(name)
        return Path(value) if value else None

    @staticmethod
    def _qualified_platform() -> bool:
        if not sys.platform.startswith("linux") or platform.machine().casefold() not in {
            "amd64",
            "x86_64",
        }:
            return False
        try:
            fields = {}
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator:
                    fields[key] = value.strip().strip('"')
            return fields.get("ID") == "ubuntu" and fields.get("VERSION_ID") == "24.04"
        except OSError:
            return False

    @staticmethod
    def _reported_version(path: Path, name: str) -> str:
        with tempfile.TemporaryDirectory(prefix="provelume-video-version-") as directory:
            root = Path(directory)
            try:
                result = run_bounded_process(
                    [str(path), "-version"],
                    temporary_directory=root,
                    timeout_seconds=10,
                    stdout_limit=64 * 1024,
                    stderr_limit=64 * 1024,
                    environment=minimal_child_environment(root),
                )
            except OcrContractError as exc:
                raise VideoContractError(
                    "video_decoder_unavailable", "configured video component cannot execute"
                ) from exc
        try:
            first_line = result.stdout.decode("utf-8", errors="strict").splitlines()[0]
        except (IndexError, UnicodeError) as exc:
            raise VideoContractError(
                "video_decoder_incompatible", "configured video version is invalid"
            ) from exc
        match = re.fullmatch(rf"{re.escape(name)} version ([^ ]+)(?: .*)?", first_line)
        if result.returncode != 0 or match is None:
            raise VideoContractError(
                "video_decoder_incompatible", "configured video version is invalid"
            )
        return match.group(1)

    def capability(self) -> dict[str, Any]:
        self._verified_paths = None
        base = {
            "adapter_id": "ffmpeg-cli-pair",
            "component": "codec.ffmpeg",
            "version": self.declared_version,
            "ffmpeg_sha256": None,
            "ffprobe_sha256": None,
            "qualified_platform": "ubuntu-24.04-x86_64",
            "source_sha256": FFMPEG_SOURCE_SHA256,
            "source_size_bytes": FFMPEG_SOURCE_SIZE,
            "network_used": False,
            "runtime_downloads": False,
            "qualified": False,
        }
        if not self._qualified_platform():
            return {**base, "state": "incompatible", "reason": "unsupported_platform"}
        if (
            self.ffmpeg_path is None
            or self.ffprobe_path is None
            or self.declared_version is None
            or self.expected_ffmpeg_sha256 is None
            or self.expected_ffprobe_sha256 is None
        ):
            return {**base, "state": "unavailable", "reason": "component_missing"}
        if self.declared_version != FFMPEG_VERSION:
            return {**base, "state": "incompatible", "reason": "version_mismatch"}
        if (
            _SHA256.fullmatch(self.expected_ffmpeg_sha256) is None
            or _SHA256.fullmatch(self.expected_ffprobe_sha256) is None
        ):
            return {**base, "state": "incompatible", "reason": "binary_identity_mismatch"}
        try:
            ffmpeg_sha = _file_sha256(self.ffmpeg_path)
            ffprobe_sha = _file_sha256(self.ffprobe_path)
        except VideoContractError:
            return {**base, "state": "unavailable", "reason": "component_missing"}
        selected = {**base, "ffmpeg_sha256": ffmpeg_sha, "ffprobe_sha256": ffprobe_sha}
        if ffmpeg_sha != self.expected_ffmpeg_sha256 or ffprobe_sha != self.expected_ffprobe_sha256:
            return {**selected, "state": "incompatible", "reason": "binary_identity_mismatch"}
        try:
            actual_versions = {
                self._reported_version(self.ffmpeg_path, "ffmpeg"),
                self._reported_version(self.ffprobe_path, "ffprobe"),
            }
        except VideoContractError as exc:
            return {
                **selected,
                "state": "incompatible",
                "reason": (
                    "version_mismatch"
                    if exc.code == "video_decoder_incompatible"
                    else "component_missing"
                ),
            }
        if actual_versions != {FFMPEG_VERSION}:
            return {**selected, "state": "incompatible", "reason": "version_mismatch"}
        self._verified_paths = (self.ffmpeg_path, self.ffprobe_path)
        return {**selected, "state": "ready", "reason": None, "qualified": True}

    def _require(self) -> tuple[Path, Path]:
        if self._verified_paths is not None:
            return self._verified_paths
        capability = self.capability()
        if capability["state"] == "unavailable":
            raise VideoContractError("video_decoder_unavailable", "local video pair is unavailable")
        if capability["state"] != "ready":
            raise VideoContractError(
                "video_decoder_incompatible", "local video pair identity is incompatible"
            )
        assert self._verified_paths is not None
        return self._verified_paths

    def bound(self, cancelled: Callable[[], bool] | None) -> FFmpegAdapter:
        return FFmpegAdapter(
            ffmpeg_path=self.ffmpeg_path,
            ffprobe_path=self.ffprobe_path,
            declared_version=self.declared_version,
            expected_ffmpeg_sha256=self.expected_ffmpeg_sha256,
            expected_ffprobe_sha256=self.expected_ffprobe_sha256,
            cancelled=cancelled,
        )

    def _run(
        self,
        command: Sequence[str],
        *,
        root: Path,
        stdout_limit: int = MAX_PROBE_BYTES,
        produced: Mapping[Path, int] | None = None,
    ) -> bytes:
        try:
            result = run_bounded_process(
                command,
                temporary_directory=root,
                timeout_seconds=MAX_PROCESS_SECONDS,
                stdout_limit=stdout_limit,
                stderr_limit=MAX_STDERR_BYTES,
                cancelled=self.cancelled,
                environment=minimal_child_environment(root),
                produced_file_limits=produced,
            )
        except OcrContractError as exc:
            code = (
                "video_cancelled"
                if exc.code == "ocr_cancelled"
                else (
                    "video_output_limit_exceeded"
                    if exc.code == "ocr_output_limit_exceeded"
                    else "video_process_failed"
                )
            )
            raise VideoContractError(code, "local video process failed safely") from exc
        if result.returncode != 0:
            raise VideoContractError("video_process_failed", "local video process exited safely")
        return result.stdout

    def inspect(self, data: bytes, *, format_name: str) -> dict[str, Any]:
        _ffmpeg, ffprobe = self._require()
        with tempfile.TemporaryDirectory(prefix="provelume-video-") as directory:
            root = Path(directory)
            source = root / "input.bin"
            source.write_bytes(data)
            output = self._run(
                [
                    str(ffprobe),
                    "-v",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    "file",
                    "-probesize",
                    str(min(MAX_INPUT_BYTES, len(data))),
                    "-analyzeduration",
                    "10000000",
                    "-show_format",
                    "-show_streams",
                    "-show_chapters",
                    "-of",
                    "json",
                    str(source),
                ],
                root=root,
            )
        try:
            parsed = json.loads(output.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise VideoContractError(
                "video_invalid_container", "ffprobe output is invalid"
            ) from exc
        return _normalise_probe(parsed, format_name=format_name)

    def frame(self, data: bytes, *, stream_index: int, timestamp_ms: int) -> bytes:
        ffmpeg, _ffprobe = self._require()
        with tempfile.TemporaryDirectory(prefix="provelume-video-") as directory:
            root = Path(directory)
            source = root / "input.bin"
            target = root / "frame.ppm"
            source.write_bytes(data)
            self._run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    "file",
                    "-ss",
                    f"{timestamp_ms / 1000:.3f}",
                    "-i",
                    str(source),
                    "-map",
                    f"0:{stream_index}",
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={MAX_FRAME_EDGE}:-2:force_original_aspect_ratio=decrease",
                    "-an",
                    "-sn",
                    "-f",
                    "image2",
                    "-c:v",
                    "ppm",
                    str(target),
                ],
                root=root,
                produced={target: MAX_PPM_BYTES},
            )
            if not target.is_file() or target.is_symlink():
                raise VideoContractError("video_process_failed", "selected frame is unavailable")
            payload = target.read_bytes()
        return _ppm_to_png(payload)

    def gray_samples(
        self,
        data: bytes,
        *,
        stream_index: int,
        duration_ms: int,
    ) -> list[tuple[int, bytes]]:
        ffmpeg, _ffprobe = self._require()
        interval_ms = max(250, math.ceil(max(1, duration_ms) / MAX_SCENE_SAMPLES))
        sample_size = SCENE_SAMPLE_WIDTH * SCENE_SAMPLE_HEIGHT
        with tempfile.TemporaryDirectory(prefix="provelume-video-") as directory:
            root = Path(directory)
            source = root / "input.bin"
            source.write_bytes(data)
            output = self._run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    "file",
                    "-i",
                    str(source),
                    "-map",
                    f"0:{stream_index}",
                    "-frames:v",
                    str(MAX_SCENE_SAMPLES),
                    "-vf",
                    (
                        f"fps=1000/{interval_ms},"
                        f"scale={SCENE_SAMPLE_WIDTH}:{SCENE_SAMPLE_HEIGHT}:flags=bilinear,"
                        "format=gray"
                    ),
                    "-pix_fmt",
                    "gray",
                    "-threads",
                    "1",
                    "-an",
                    "-sn",
                    "-f",
                    "rawvideo",
                    "pipe:1",
                ],
                root=root,
                stdout_limit=sample_size * MAX_SCENE_SAMPLES,
            )
        if not output or len(output) % sample_size != 0:
            raise VideoContractError("video_process_failed", "scene sample output is invalid")
        count = len(output) // sample_size
        if count > MAX_SCENE_SAMPLES:
            raise VideoContractError("video_output_limit_exceeded", "scene sample count is invalid")
        return [
            (
                min(index * interval_ms, duration_ms),
                output[index * sample_size : (index + 1) * sample_size],
            )
            for index in range(count)
        ]

    def subtitle(self, data: bytes, *, stream_index: int) -> bytes:
        ffmpeg, _ffprobe = self._require()
        with tempfile.TemporaryDirectory(prefix="provelume-video-") as directory:
            root = Path(directory)
            source = root / "input.bin"
            target = root / "subtitle.vtt"
            source.write_bytes(data)
            self._run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    "file",
                    "-i",
                    str(source),
                    "-map",
                    f"0:{stream_index}",
                    "-f",
                    "webvtt",
                    str(target),
                ],
                root=root,
                produced={target: MAX_SUBTITLE_BYTES},
            )
            if not target.is_file() or target.is_symlink():
                raise VideoContractError("video_process_failed", "subtitle output is unavailable")
            payload = target.read_bytes()
        if len(payload) > MAX_SUBTITLE_BYTES:
            raise VideoContractError("video_output_limit_exceeded", "subtitle output is oversized")
        return payload

    def audio(self, data: bytes, *, stream_index: int) -> bytes:
        ffmpeg, _ffprobe = self._require()
        with tempfile.TemporaryDirectory(prefix="provelume-video-") as directory:
            root = Path(directory)
            source = root / "input.bin"
            target = root / "audio.wav"
            source.write_bytes(data)
            self._run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    "file",
                    "-i",
                    str(source),
                    "-map",
                    f"0:{stream_index}",
                    "-vn",
                    "-sn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-f",
                    "wav",
                    str(target),
                ],
                root=root,
                produced={target: MAX_AUDIO_BYTES},
            )
            if not target.is_file() or target.is_symlink():
                raise VideoContractError("video_process_failed", "transient audio is unavailable")
            payload = target.read_bytes()
        inspect_audio_bytes(payload)
        return payload


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise VideoContractError("video_contract_violation", "frame PNG is invalid")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width < 1 or height < 1 or width * height > MAX_FRAME_PIXELS:
        raise VideoContractError("video_dimension_limit_exceeded", "frame dimensions are invalid")
    return width, height


class FrameOcrAdapter:
    """Bridge selected FFmpeg PNG frames into the existing Lectio Tesseract contract."""

    def __init__(self, store: InstanceStore, video_capability: Mapping[str, Any]):
        self.store = store
        self.video_capability = dict(video_capability)

    def _settings(self) -> OcrSettings:
        return ocr_settings_from_config(self.store.read_config())

    def _renderer(self) -> OcrRendererCapability:
        ready = self.video_capability.get("state") == "ready"
        version = str(self.video_capability.get("version") or "") or None
        path = os.environ.get("PROVELUME_FFMPEG_PATH") if ready else None
        return OcrRendererCapability(
            adapter_id="provelume.ffmpeg-frame",
            adapter_version="1",
            renderer_id="ffmpeg",
            renderer_version=version if ready else None,
            renderer_available=ready,
            version_compatible=ready,
            resolved_path=path,
            decoder_id="ffmpeg",
            decoder_version=version if ready else None,
            component_versions=(("ffmpeg", version),) if ready and version else (),
            input_media_types=("image/png",),
        )

    def capability(self) -> dict[str, Any]:
        try:
            settings = self._settings()
            if settings.mode == "disabled":
                return {"state": "unavailable", "reason": "disabled_by_configuration"}
            renderer = self._renderer()
            if not renderer.renderer_available:
                return {"state": "unavailable", "reason": "component_missing"}
            with tempfile.TemporaryDirectory(prefix="provelume-video-ocr-") as directory:
                engine = TesseractCliAdapter(settings, renderer, Path(directory))
                capability = engine.capability()
            if (
                capability.engine_available
                and capability.version_compatible
                and set(settings.languages).issubset(capability.installed_languages)
            ):
                return {
                    "state": "ready",
                    "reason": None,
                    "settings_sha256": settings_fingerprint(settings),
                    "engine": capability.as_record(),
                    "contract": "lectio-ocr-region-v1",
                }
            return {"state": "unavailable", "reason": "component_missing"}
        except (OcrContractError, OSError, ValueError):
            return {"state": "unavailable", "reason": "component_missing"}

    def recognise(
        self,
        frame: bytes,
        *,
        version_id: str,
        original_sha256: str,
        ordinal: int,
    ) -> dict[str, Any]:
        settings = self._settings()
        renderer = self._renderer()
        if settings.mode == "disabled" or not renderer.renderer_available:
            raise VideoContractError(
                "video_decoder_unavailable", "selected-frame OCR is unavailable"
            )
        width, height = _png_dimensions(frame)
        with tempfile.TemporaryDirectory(prefix="provelume-video-ocr-") as directory:
            root = Path(directory)
            staged = root / "frame.png"
            staged.write_bytes(frame)
            source = OcrSourcePageIdentity(
                original_sha256=original_sha256,
                version_id=version_id,
                page_number=ordinal,
                page_image_sha256=_sha256(frame),
                source_media_type="image/png",
            )
            request = OcrPageRequest(
                source_page=source,
                staged_media_type="image/png",
                page_width=width,
                page_height=height,
                settings_sha256=settings_fingerprint(settings),
                languages=settings.languages,
                deadline_seconds=settings.limits.max_seconds_per_page,
                max_output_chars=settings.limits.max_output_chars_per_page,
            )
            result = TesseractCliAdapter(settings, renderer, root).recognise_page(request, staged)
        return result.as_record()


def _scenes(samples: Sequence[tuple[int, bytes]], duration_ms: int) -> list[dict[str, int | str]]:
    if not samples:
        raise VideoContractError("video_process_failed", "scene samples are unavailable")
    expected_size = SCENE_SAMPLE_WIDTH * SCENE_SAMPLE_HEIGHT
    boundaries: list[tuple[int, int]] = [(0, 0)]
    first_timestamp, previous = samples[0]
    if first_timestamp != 0 or len(previous) != expected_size:
        raise VideoContractError("video_process_failed", "scene sample dimensions are invalid")
    last_timestamp = first_timestamp
    for timestamp, current in samples[1:]:
        if (
            type(timestamp) is not int
            or timestamp < last_timestamp
            or timestamp < 0
            or timestamp > duration_ms
            or len(current) != expected_size
        ):
            raise VideoContractError("video_process_failed", "scene samples are invalid")
        last_timestamp = timestamp
        score_ppm = (
            sum(abs(left - right) for left, right in zip(previous, current, strict=True))
            * 1_000_000
            // (255 * expected_size)
        )
        if (
            timestamp > boundaries[-1][0]
            and score_ppm >= SCENE_THRESHOLD_PPM
            and len(boundaries) < MAX_SCENES
        ):
            boundaries.append((timestamp, score_ppm))
        previous = current
    result: list[dict[str, int | str]] = []
    for ordinal, (start, score_ppm) in enumerate(boundaries):
        end = boundaries[ordinal + 1][0] if ordinal + 1 < len(boundaries) else duration_ms
        representative = start if end == start else start + (end - start) // 2
        result.append(
            {
                "id": f"scene-{ordinal + 1}",
                "start_ms": start,
                "end_ms": end,
                "representative_ms": representative,
                "score_ppm": score_ppm,
            }
        )
    return result


def _parse_subtitle(data: bytes, *, stream_index: int, language: str) -> dict[str, Any]:
    limits = TranscriptLimits(
        max_file_bytes=MAX_SUBTITLE_BYTES,
        max_cues_per_file=MAX_CUES,
    )
    try:
        parsed = BoundedTranscriptParser().parse(data, profile="webvtt-v1", limits=limits)
    except TranscriptContractError as exc:
        raise VideoContractError("video_process_failed", "subtitle contract is invalid") from exc
    cues = []
    for cue in parsed.cues:
        identity = _sha256(
            canonical_json_bytes(
                {
                    "stream_index": stream_index,
                    "ordinal": cue.ordinal,
                    "start_ms": cue.start_ms,
                    "end_ms": cue.end_ms,
                    "text": cue.text,
                }
            )
        )
        cues.append(
            {
                "id": f"vsub_{identity}",
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": cue.text,
                "status": "machine-unverified",
                "warning_codes": list(cue.warning_codes),
            }
        )
    return {
        "stream_index": stream_index,
        "language": language,
        "format": "webvtt",
        "source_preserved": True,
        "cues": cues,
        "warnings": list(parsed.warning_codes),
    }


def _validate_video_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise VideoContractError("video_contract_violation", "video record is invalid")
    record = dict(value)
    required = {
        "schema_version",
        "kind",
        "profile_id",
        "version_id",
        "original_sha256",
        "format",
        "media_type",
        "byte_length",
        "container",
        "duration_ms",
        "streams",
        "chapters",
        "encrypted",
        "subtitles",
        "transcript",
        "scenes",
        "keyframes",
        "frame_ocr",
        "selection",
        "component",
        "invariants",
    }
    if (
        set(record) != required
        or record.get("schema_version") != VIDEO_SCHEMA_VERSION
        or record.get("kind") != "video-profile"
        or record.get("profile_id") != VIDEO_PROFILE_ID
        or not isinstance(record.get("version_id"), str)
        or _IDENTIFIER.fullmatch(record["version_id"]) is None
        or not isinstance(record.get("original_sha256"), str)
        or _SHA256.fullmatch(record["original_sha256"]) is None
    ):
        raise VideoContractError("video_contract_violation", "video record identity is invalid")
    if (
        record["format"] not in VIDEO_FORMATS
        or record["media_type"] != VIDEO_MEDIA_TYPES[record["format"]]
        or type(record["byte_length"]) is not int
        or not 1 <= record["byte_length"] <= MAX_INPUT_BYTES
        or type(record["duration_ms"]) is not int
        or not 0 <= record["duration_ms"] <= MAX_DURATION_MS
        or record["encrypted"] is not False
    ):
        raise VideoContractError("video_contract_violation", "video source fields are invalid")
    streams = record["streams"]
    if not isinstance(streams, list) or not 1 <= len(streams) <= MAX_STREAMS:
        raise VideoContractError("video_contract_violation", "video streams are invalid")
    indices: set[int] = set()
    stream_fields = {
        "index",
        "kind",
        "codec",
        "language",
        "duration_ms",
        "width",
        "height",
        "frame_rate",
        "variable_frame_rate",
        "profile",
        "level",
        "pixel_format",
        "rotation_degrees",
        "color_range",
        "color_space",
        "color_transfer",
        "color_primaries",
        "hdr",
        "channels",
        "sample_rate_hz",
        "attachment_name",
        "attachment_media_type",
        "default",
        "qualified",
    }
    for stream in streams:
        if (
            not isinstance(stream, Mapping)
            or set(stream) != stream_fields
            or type(stream["index"]) is not int
            or not 0 <= stream["index"] <= 1024
            or stream["index"] in indices
            or stream["kind"] not in _STREAM_KINDS
            or not isinstance(stream["codec"], str)
            or not 1 <= len(stream["codec"]) <= 100
            or not isinstance(stream["language"], str)
            or re.fullmatch(r"[A-Za-z0-9-]{1,35}", stream["language"]) is None
            or type(stream["default"]) is not bool
            or type(stream["qualified"]) is not bool
            or stream["qualified"]
            != _codec_qualified(record["format"], stream["kind"], stream["codec"])
        ):
            raise VideoContractError("video_contract_violation", "video stream contract is invalid")
        if stream["duration_ms"] is not None and (
            type(stream["duration_ms"]) is not int
            or not 0 <= stream["duration_ms"] <= MAX_DURATION_MS
        ):
            raise VideoContractError("video_contract_violation", "video stream duration is invalid")
        if stream["kind"] == "video":
            if (stream["width"] is None) != (stream["height"] is None):
                raise VideoContractError("video_contract_violation", "video dimensions are invalid")
            if stream["width"] is not None and (
                type(stream["width"]) is not int
                or type(stream["height"]) is not int
                or not 1 <= stream["width"] <= MAX_SOURCE_EDGE
                or not 1 <= stream["height"] <= MAX_SOURCE_EDGE
                or stream["width"] * stream["height"] > MAX_FRAME_PIXELS
            ):
                raise VideoContractError("video_contract_violation", "video dimensions are invalid")
            if stream["frame_rate"] is not None and (
                isinstance(stream["frame_rate"], bool)
                or not isinstance(stream["frame_rate"], (int, float))
                or not 0 < stream["frame_rate"] <= MAX_FRAME_RATE
            ):
                raise VideoContractError("video_contract_violation", "video frame rate is invalid")
            if (
                stream["variable_frame_rate"] is not None
                and type(stream["variable_frame_rate"]) is not bool
            ):
                raise VideoContractError("video_contract_violation", "video VFR claim is invalid")
            if stream["hdr"] is not None and type(stream["hdr"]) is not bool:
                raise VideoContractError("video_contract_violation", "video HDR claim is invalid")
            if stream["rotation_degrees"] is not None and (
                type(stream["rotation_degrees"]) is not int
                or not -359 <= stream["rotation_degrees"] <= 359
            ):
                raise VideoContractError("video_contract_violation", "video rotation is invalid")
            if any(
                value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 200)
                for value in (
                    stream["profile"],
                    stream["level"],
                    stream["pixel_format"],
                    stream["color_range"],
                    stream["color_space"],
                    stream["color_transfer"],
                    stream["color_primaries"],
                )
            ):
                raise VideoContractError("video_contract_violation", "video labels are invalid")
        elif any(
            stream[field] is not None
            for field in (
                "width",
                "height",
                "frame_rate",
                "variable_frame_rate",
                "profile",
                "level",
                "pixel_format",
                "rotation_degrees",
                "color_range",
                "color_space",
                "color_transfer",
                "color_primaries",
                "hdr",
            )
        ):
            raise VideoContractError("video_contract_violation", "non-video fields are invalid")
        if stream["kind"] == "audio":
            if stream["channels"] is not None and (
                type(stream["channels"]) is not int or not 1 <= stream["channels"] <= 64
            ):
                raise VideoContractError("video_contract_violation", "audio channels are invalid")
            if stream["sample_rate_hz"] is not None and (
                type(stream["sample_rate_hz"]) is not int
                or not 1 <= stream["sample_rate_hz"] <= 768_000
            ):
                raise VideoContractError("video_contract_violation", "audio sample rate is invalid")
        elif stream["channels"] is not None or stream["sample_rate_hz"] is not None:
            raise VideoContractError("video_contract_violation", "non-audio fields are invalid")
        if stream["kind"] == "attachment":
            if any(
                value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 255)
                for value in (stream["attachment_name"], stream["attachment_media_type"])
            ):
                raise VideoContractError(
                    "video_contract_violation", "attachment fields are invalid"
                )
        elif stream["attachment_name"] is not None or stream["attachment_media_type"] is not None:
            raise VideoContractError(
                "video_contract_violation", "non-attachment fields are invalid"
            )
        indices.add(stream["index"])
    if not isinstance(record["chapters"], list) or len(record["chapters"]) > MAX_CHAPTERS:
        raise VideoContractError("video_contract_violation", "video chapters are invalid")
    if any(
        not isinstance(chapter, Mapping)
        or set(chapter) != {"id", "start_ms", "end_ms"}
        or not isinstance(chapter["id"], str)
        or type(chapter["start_ms"]) is not int
        or type(chapter["end_ms"]) is not int
        or not 0 <= chapter["start_ms"] <= chapter["end_ms"] <= record["duration_ms"]
        for chapter in record["chapters"]
    ):
        raise VideoContractError("video_contract_violation", "video chapter contract is invalid")
    if not isinstance(record["subtitles"], list) or len(record["subtitles"]) > MAX_SUBTITLE_STREAMS:
        raise VideoContractError("video_contract_violation", "video subtitles are invalid")
    cue_count = 0
    for subtitle in record["subtitles"]:
        if not isinstance(subtitle, Mapping) or not isinstance(subtitle.get("cues"), list):
            raise VideoContractError("video_contract_violation", "video subtitle is invalid")
        for cue in subtitle["cues"]:
            cue_count += 1
            if (
                not isinstance(cue, Mapping)
                or type(cue.get("start_ms")) is not int
                or type(cue.get("end_ms")) is not int
                or cue["start_ms"] < 0
                or cue["end_ms"] < cue["start_ms"]
                or cue["end_ms"] > record["duration_ms"] + 2000
            ):
                raise VideoContractError("video_contract_violation", "subtitle cue is invalid")
    if cue_count > MAX_CUES * MAX_SUBTITLE_STREAMS:
        raise VideoContractError("video_contract_violation", "subtitle cue count is invalid")
    transcript = record["transcript"]
    transcript_fields = {
        "state",
        "reason",
        "audio_stream_index",
        "language",
        "engine",
        "model",
        "segments",
        "contract",
    }
    if (
        not isinstance(transcript, Mapping)
        or set(transcript) != transcript_fields
        or transcript.get("state") not in {"available", "unavailable"}
        or transcript.get("contract") != "perceptio-audio-v1"
        or not isinstance(transcript.get("segments"), list)
        or len(transcript["segments"]) > 20_000
    ):
        raise VideoContractError("video_contract_violation", "video transcript is invalid")
    if transcript["state"] == "unavailable" and (
        transcript["reason"] is None
        or transcript["engine"] is not None
        or transcript["model"] is not None
        or transcript["segments"]
    ):
        raise VideoContractError("video_contract_violation", "unavailable transcript is invalid")
    if transcript["state"] == "available" and (
        transcript["reason"] is not None
        or not isinstance(transcript["engine"], Mapping)
        or not isinstance(transcript["model"], Mapping)
    ):
        raise VideoContractError("video_contract_violation", "available transcript is invalid")
    if any(
        not isinstance(segment, Mapping)
        or type(segment.get("start_ms")) is not int
        or type(segment.get("end_ms")) is not int
        or not 0 <= segment["start_ms"] <= segment["end_ms"] <= record["duration_ms"] + 2_000
        or not isinstance(segment.get("words"), list)
        for segment in transcript["segments"]
    ):
        raise VideoContractError("video_contract_violation", "video transcript segment is invalid")
    scenes = record["scenes"]
    keyframes = record["keyframes"]
    frame_ocr = record["frame_ocr"]
    if (
        not isinstance(scenes, list)
        or len(scenes) > MAX_SCENES
        or not isinstance(keyframes, list)
        or len(keyframes) > MAX_SCENES
        or not isinstance(frame_ocr, list)
        or len(frame_ocr) > MAX_SELECTED_FRAMES
    ):
        raise VideoContractError("video_contract_violation", "video frame evidence is invalid")
    previous_end = 0
    for ordinal, scene in enumerate(scenes, start=1):
        if (
            not isinstance(scene, Mapping)
            or set(scene) != {"id", "start_ms", "end_ms", "representative_ms", "score_ppm"}
            or scene["id"] != f"scene-{ordinal}"
            or type(scene["start_ms"]) is not int
            or type(scene["end_ms"]) is not int
            or type(scene["representative_ms"]) is not int
            or type(scene["score_ppm"]) is not int
            or scene["start_ms"] != previous_end
            or not scene["start_ms"]
            <= scene["representative_ms"]
            <= scene["end_ms"]
            <= record["duration_ms"]
            or not 0 <= scene["score_ppm"] <= 1_000_000
        ):
            raise VideoContractError("video_contract_violation", "video scene is invalid")
        previous_end = scene["end_ms"]
    if scenes and previous_end != record["duration_ms"]:
        raise VideoContractError("video_contract_violation", "video scene coverage is invalid")
    if len(keyframes) != len(scenes):
        raise VideoContractError("video_contract_violation", "video keyframe count is invalid")
    for ordinal, (keyframe, scene) in enumerate(zip(keyframes, scenes, strict=True), start=1):
        if (
            not isinstance(keyframe, Mapping)
            or set(keyframe) != {"id", "timestamp_ms", "frame_sha256", "output"}
            or keyframe["id"] != f"keyframe-{ordinal}"
            or keyframe["timestamp_ms"] != scene["representative_ms"]
            or _SHA256.fullmatch(str(keyframe["frame_sha256"])) is None
            or keyframe["output"] != f"keyframe-{ordinal:03d}.png"
        ):
            raise VideoContractError("video_contract_violation", "video keyframe is invalid")
    selected = (
        record["selection"].get("timestamps_ms")
        if isinstance(record["selection"], Mapping)
        else None
    )
    if (
        not isinstance(record["selection"], Mapping)
        or set(record["selection"]) != {"timestamps_ms", "continuous", "scene_recipe"}
        or record["selection"].get("continuous") is not False
        or record["selection"].get("scene_recipe") != "gray64x36-fixed-interval-mad-v1"
        or not isinstance(selected, list)
    ):
        raise VideoContractError("video_contract_violation", "video selection is invalid")
    _selected_timestamps(selected, duration_ms=record["duration_ms"])
    if (
        not all(isinstance(item, Mapping) for item in frame_ocr)
        or [item.get("timestamp_ms") for item in frame_ocr] != selected
    ):
        raise VideoContractError("video_contract_violation", "frame OCR selection is not exact")
    for ordinal, item in enumerate(frame_ocr, start=1):
        if (
            set(item) != {"id", "timestamp_ms", "frame_sha256", "state", "reason", "regions"}
            or item["id"] != f"frame-ocr-{ordinal}"
            or item["state"] not in {"available", "unavailable"}
            or not isinstance(item["regions"], list)
            or len(item["regions"]) > MAX_REPRESENTATION_ANCHORS
            or (
                item["frame_sha256"] is not None
                and _SHA256.fullmatch(str(item["frame_sha256"])) is None
            )
        ):
            raise VideoContractError("video_contract_violation", "frame OCR contract is invalid")
        if item["state"] == "available" and (
            item["reason"] is not None or item["frame_sha256"] is None
        ):
            raise VideoContractError("video_contract_violation", "available frame OCR is invalid")
        if item["state"] == "unavailable" and (item["reason"] is None or item["regions"]):
            raise VideoContractError("video_contract_violation", "unavailable frame OCR is invalid")
        for region in item["regions"]:
            box = region.get("box") if isinstance(region, Mapping) else None
            if (
                not isinstance(region, Mapping)
                or set(region) != {"id", "text", "status", "confidence", "box"}
                or not isinstance(region["text"], str)
                or not 1 <= len(region["text"]) <= 100_000
                or region["status"] not in {"machine-unverified", "needs-review"}
                or not isinstance(box, Mapping)
                or set(box)
                != {
                    "left",
                    "top",
                    "width",
                    "height",
                    "page_width",
                    "page_height",
                    "coordinate_space",
                }
                or box["coordinate_space"] != "source-pixels"
                or any(type(box[key]) is not int for key in box if key != "coordinate_space")
                or box["left"] < 0
                or box["top"] < 0
                or box["width"] < 1
                or box["height"] < 1
                or box["left"] + box["width"] > box["page_width"]
                or box["top"] + box["height"] > box["page_height"]
            ):
                raise VideoContractError("video_contract_violation", "frame OCR region is invalid")
    component = record["component"]
    if (
        not isinstance(component, Mapping)
        or component.get("adapter_id") != "ffmpeg-cli-pair"
        or component.get("component") != "codec.ffmpeg"
        or component.get("source_sha256") != FFMPEG_SOURCE_SHA256
        or component.get("source_size_bytes") != FFMPEG_SOURCE_SIZE
        or component.get("qualified_platform") != "ubuntu-24.04-x86_64"
        or component.get("network_used") is not False
        or component.get("runtime_downloads") is not False
    ):
        raise VideoContractError("video_contract_violation", "video component claim is invalid")
    expected_invariants = {
        "derived": True,
        "original_immutable": True,
        "canonical_records_immutable": True,
        "network_used": False,
        "runtime_downloads": False,
        "remote_inference": False,
        "continuous_frame_ocr": False,
        "speaker_or_face_identity": False,
        "summary_or_classification": False,
        "source_writeback": False,
    }
    if record["invariants"] != expected_invariants:
        raise VideoContractError("video_contract_violation", "video invariants are invalid")
    return record


def validate_video_record(value: Any) -> dict[str, Any]:
    return _validate_video_record(value)


class VideoProfileManager:
    """Bounded video jobs and universal derived-profile lifecycle."""

    def __init__(
        self,
        store: InstanceStore,
        *,
        video_adapter: Any | None = None,
        asr_adapter: Any | None = None,
        ocr_adapter: Any | None = None,
    ):
        self.store = store
        self.bundles = RepresentationBundleManager(store)
        self.video_adapter = video_adapter or FFmpegAdapter()
        self.asr_adapter = asr_adapter or WhisperCppAdapter()
        self.ocr_adapter = ocr_adapter or FrameOcrAdapter(store, self.video_adapter.capability())
        self.root = store.paths.state / "video"
        self.jobs = self.root / "jobs"

    def capability(self) -> dict[str, Any]:
        decoder = self.video_adapter.capability()
        return {
            "schema_version": 1,
            "profile_id": VIDEO_PROFILE_ID,
            "candidate_formats": list(VIDEO_FORMATS),
            "matrix": [
                {
                    "format": name,
                    "inspect": "bounded-signature",
                    "video_codecs": sorted(
                        codec for codec in _VIDEO_CODECS if _codec_qualified(name, "video", codec)
                    ),
                    "audio_codecs": sorted(
                        codec for codec in _AUDIO_CODECS if _codec_qualified(name, "audio", codec)
                    ),
                    "subtitle_codecs": sorted(
                        codec
                        for codec in _SUBTITLE_CODECS
                        if _codec_qualified(name, "subtitle", codec)
                    ),
                }
                for name in VIDEO_FORMATS
            ],
            "decoder": decoder,
            "asr": self.asr_adapter.capability(),
            "frame_ocr": self.ocr_adapter.capability(),
            "windows": {
                "preserve": "available",
                "inspect": "bounded-signature",
                "decode": "unavailable",
                "reason": "unsupported_platform",
            },
            "network_used": False,
            "runtime_downloads": False,
            "mutated": False,
        }

    def _source(self, version_id: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        version = self.store.read_canonical("versions", version_id)
        if version is None:
            raise VideoContractError("video_not_found", "video DocumentVersion was not found")
        original = self.store.read_canonical("originals", str(version.get("original_id", "")))
        if original is None:
            raise VideoContractError("video_not_found", "video Original was not found")
        data = self.store.original_bytes(str(original["id"]))
        digest = _sha256(data)
        if (
            digest != original.get("sha256")
            or digest != version.get("content_hash")
            or len(data) != original.get("size_bytes")
            or len(data) != version.get("size_bytes")
        ):
            raise VideoContractError(
                "video_contract_violation", "video Original identity verification failed"
            )
        return version, original, data

    def _record_for_bundle(self, bundle: Mapping[str, Any]) -> dict[str, Any] | None:
        if bundle.get("recipe", {}).get("id") != VIDEO_RECIPE_ID:
            return None
        output = next(
            (item for item in bundle["outputs"] if Path(item["storage_ref"]).name == "video.json"),
            None,
        )
        if output is None:
            return None
        try:
            path = safe_instance_path(self.store.paths.root, str(output["storage_ref"]))
            return validate_video_record(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _derive(
        self,
        version_id: str,
        *,
        timestamps_ms: Sequence[int] = (),
        transcript_language: str = "auto",
        frozen_settings: Mapping[str, Any] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[dict[str, tuple[str, bytes]], dict[str, Any], list[dict[str, Any]], bool]:
        if cancelled is not None and cancelled():
            raise VideoContractError("video_cancelled", "video job was cancelled")
        _version, original, data = self._source(version_id)
        format_name = identify_video_bytes(data)
        selected = _selected_timestamps(timestamps_ms)
        if _LANGUAGE.fullmatch(transcript_language) is None or transcript_language not in {
            "auto",
            "en",
            "it",
        }:
            raise VideoContractError("video_contract_violation", "transcript language is invalid")
        video_adapter = (
            self.video_adapter.bound(cancelled)
            if isinstance(self.video_adapter, FFmpegAdapter)
            else self.video_adapter
        )
        video_capability = video_adapter.capability()
        asr_capability = self.asr_adapter.capability()
        ocr_capability = self.ocr_adapter.capability()
        identities = {
            "video": video_capability,
            "asr": asr_capability,
            "ocr": ocr_capability,
        }
        if frozen_settings is not None:
            if frozen_settings.get("component_identity") != identities:
                raise VideoContractError(
                    "video_decoder_unavailable", "video rebuild components no longer match"
                )
            selected = _selected_timestamps(frozen_settings.get("timestamps_ms", []))
            transcript_language = str(frozen_settings.get("transcript_language"))
        if video_capability.get("state") == "ready":
            inspected = video_adapter.inspect(data, format_name=format_name)
        else:
            inspected = {
                "container": format_name.casefold(),
                "duration_ms": 0,
                "streams": [
                    {
                        "index": 0,
                        "kind": "video",
                        "codec": "unknown",
                        "language": "und",
                        "duration_ms": None,
                        "width": None,
                        "height": None,
                        "frame_rate": None,
                        "variable_frame_rate": None,
                        "profile": None,
                        "level": None,
                        "pixel_format": None,
                        "rotation_degrees": None,
                        "color_range": None,
                        "color_space": None,
                        "color_transfer": None,
                        "color_primaries": None,
                        "hdr": None,
                        "channels": None,
                        "sample_rate_hz": None,
                        "attachment_name": None,
                        "attachment_media_type": None,
                        "default": True,
                        "qualified": False,
                    }
                ],
                "chapters": [],
                "encrypted": False,
            }
        selected = _selected_timestamps(selected, duration_ms=int(inspected["duration_ms"]))
        video_stream = next(
            (
                item
                for item in inspected["streams"]
                if item["kind"] == "video" and item["qualified"]
            ),
            None,
        )
        subtitles = []
        subtitle_payloads: dict[str, tuple[str, bytes]] = {}
        if video_capability.get("state") == "ready":
            for stream in inspected["streams"]:
                if stream["kind"] != "subtitle" or not stream["qualified"]:
                    continue
                if cancelled is not None and cancelled():
                    raise VideoContractError("video_cancelled", "video job was cancelled")
                raw = video_adapter.subtitle(data, stream_index=int(stream["index"]))
                parsed = _parse_subtitle(
                    raw,
                    stream_index=int(stream["index"]),
                    language=str(stream["language"]),
                )
                subtitles.append(parsed)
                subtitle_payloads[f"subtitle-{stream['index']}.vtt"] = ("text/vtt", raw)
        transcript: dict[str, Any]
        audio_stream = next(
            (
                item
                for item in inspected["streams"]
                if item["kind"] == "audio" and item["qualified"]
            ),
            None,
        )
        if (
            video_capability.get("state") == "ready"
            and asr_capability.get("state") == "ready"
            and audio_stream is not None
        ):
            if cancelled is not None and cancelled():
                raise VideoContractError("video_cancelled", "video job was cancelled")
            wav = video_adapter.audio(data, stream_index=int(audio_stream["index"]))
            try:
                raw_transcript = self.asr_adapter.transcribe(
                    wav, language=transcript_language, threads=1
                )
                normalised = _normalise_transcript(
                    raw_transcript, duration_ms=int(inspected["duration_ms"])
                )
            except AudioContractError as exc:
                raise VideoContractError("video_process_failed", "video ASR failed safely") from exc
            transcript = {
                "state": "available",
                "reason": None,
                "audio_stream_index": int(audio_stream["index"]),
                "language": normalised["language"],
                "engine": {
                    "id": asr_capability["adapter_id"],
                    "version": asr_capability["version"],
                    "binary_sha256": asr_capability["binary_sha256"],
                },
                "model": {
                    "id": asr_capability["model_id"],
                    "sha256": asr_capability["model_sha256"],
                    "quantization": asr_capability["quantization"],
                },
                "segments": normalised["segments"],
                "contract": "perceptio-audio-v1",
            }
        else:
            transcript = {
                "state": "unavailable",
                "reason": (
                    "audio_stream_unavailable"
                    if audio_stream is None
                    else str(asr_capability.get("reason") or "component_missing")
                ),
                "audio_stream_index": None if audio_stream is None else int(audio_stream["index"]),
                "language": transcript_language,
                "engine": None,
                "model": None,
                "segments": [],
                "contract": "perceptio-audio-v1",
            }
        scenes = (
            _scenes(
                video_adapter.gray_samples(
                    data,
                    stream_index=int(video_stream["index"]),
                    duration_ms=int(inspected["duration_ms"]),
                ),
                int(inspected["duration_ms"]),
            )
            if video_stream is not None
            else []
        )
        frame_payloads: dict[str, tuple[str, bytes]] = {}
        keyframes: list[dict[str, Any]] = []
        frame_cache: dict[int, bytes] = {}
        if video_stream is not None:
            for ordinal, scene in enumerate(scenes, start=1):
                if cancelled is not None and cancelled():
                    raise VideoContractError("video_cancelled", "video job was cancelled")
                timestamp = int(scene["representative_ms"])
                frame = video_adapter.frame(
                    data, stream_index=int(video_stream["index"]), timestamp_ms=timestamp
                )
                frame_cache[timestamp] = frame
                name = f"keyframe-{ordinal:03d}.png"
                frame_payloads[name] = ("image/png", frame)
                keyframes.append(
                    {
                        "id": f"keyframe-{ordinal}",
                        "timestamp_ms": timestamp,
                        "frame_sha256": _sha256(frame),
                        "output": name,
                    }
                )
        frame_ocr = []
        for ordinal, timestamp in enumerate(selected, start=1):
            if video_stream is None:
                frame_ocr.append(
                    {
                        "id": f"frame-ocr-{ordinal}",
                        "timestamp_ms": timestamp,
                        "frame_sha256": None,
                        "state": "unavailable",
                        "reason": "codec_unqualified",
                        "regions": [],
                    }
                )
                continue
            frame = frame_cache.get(timestamp)
            if frame is None:
                frame = video_adapter.frame(
                    data, stream_index=int(video_stream["index"]), timestamp_ms=timestamp
                )
                frame_cache[timestamp] = frame
                frame_payloads[f"selected-frame-{ordinal:03d}.png"] = ("image/png", frame)
            if ocr_capability.get("state") == "ready":
                page = self.ocr_adapter.recognise(
                    frame,
                    version_id=version_id,
                    original_sha256=str(original["sha256"]),
                    ordinal=ordinal,
                )
                regions = []
                for region_ordinal, span in enumerate(page.get("spans", []), start=1):
                    if span.get("box") is None:
                        continue
                    regions.append(
                        {
                            "id": f"frame-region-{ordinal}-{region_ordinal}",
                            "text": span["text"],
                            "status": span["status"],
                            "confidence": span["confidence"],
                            "box": span["box"],
                        }
                    )
                frame_ocr.append(
                    {
                        "id": f"frame-ocr-{ordinal}",
                        "timestamp_ms": timestamp,
                        "frame_sha256": _sha256(frame),
                        "state": "available",
                        "reason": None,
                        "regions": regions,
                    }
                )
            else:
                frame_ocr.append(
                    {
                        "id": f"frame-ocr-{ordinal}",
                        "timestamp_ms": timestamp,
                        "frame_sha256": _sha256(frame),
                        "state": "unavailable",
                        "reason": str(ocr_capability.get("reason") or "component_missing"),
                        "regions": [],
                    }
                )
        record = validate_video_record(
            {
                "schema_version": VIDEO_SCHEMA_VERSION,
                "kind": "video-profile",
                "profile_id": VIDEO_PROFILE_ID,
                "version_id": version_id,
                "original_sha256": str(original["sha256"]),
                "format": format_name,
                "media_type": VIDEO_MEDIA_TYPES[format_name],
                "byte_length": len(data),
                **inspected,
                "subtitles": subtitles,
                "transcript": transcript,
                "scenes": scenes,
                "keyframes": keyframes,
                "frame_ocr": frame_ocr,
                "selection": {
                    "timestamps_ms": selected,
                    "continuous": False,
                    "scene_recipe": "gray64x36-fixed-interval-mad-v1",
                },
                "component": video_capability,
                "invariants": {
                    "derived": True,
                    "original_immutable": True,
                    "canonical_records_immutable": True,
                    "network_used": False,
                    "runtime_downloads": False,
                    "remote_inference": False,
                    "continuous_frame_ocr": False,
                    "speaker_or_face_identity": False,
                    "summary_or_classification": False,
                    "source_writeback": False,
                },
            }
        )
        anchors: list[dict[str, Any]] = []
        for subtitle in subtitles:
            anchors.extend(
                {"kind": "time", "start_ms": cue["start_ms"], "end_ms": cue["end_ms"]}
                for cue in subtitle["cues"]
            )
        anchors.extend(
            {"kind": "time", "start_ms": item["start_ms"], "end_ms": item["end_ms"]}
            for item in transcript["segments"]
        )
        for segment in transcript["segments"]:
            anchors.extend(
                {"kind": "time", "start_ms": word["start_ms"], "end_ms": word["end_ms"]}
                for word in segment.get("words", [])
            )
        anchors.extend(
            {"kind": "time", "start_ms": item["start_ms"], "end_ms": item["end_ms"]}
            for item in scenes
        )
        anchors.extend(
            {"kind": "time", "start_ms": item["timestamp_ms"], "end_ms": item["timestamp_ms"]}
            for item in keyframes
        )
        for ordinal, item in enumerate(frame_ocr, start=1):
            anchors.append(
                {"kind": "time", "start_ms": item["timestamp_ms"], "end_ms": item["timestamp_ms"]}
            )
            for region in item["regions"]:
                box = region["box"]
                anchors.append(
                    {
                        "kind": "region",
                        "page": ordinal,
                        "x": box["left"],
                        "y": box["top"],
                        "width": box["width"],
                        "height": box["height"],
                    }
                )
        if len(anchors) > MAX_REPRESENTATION_ANCHORS:
            raise VideoContractError(
                "video_output_limit_exceeded", "video anchor count exceeds its closed limit"
            )
        timeline = {
            "schema_version": 1,
            "version_id": version_id,
            "original_sha256": original["sha256"],
            "subtitles": subtitles,
            "transcript": transcript,
            "scenes": scenes,
            "keyframes": keyframes,
            "frame_ocr": frame_ocr,
            "reopen": {"authority": "exact-original", "time_region_pairs": True},
        }
        settings = {
            "format": format_name,
            "timestamps_ms": selected,
            "transcript_language": transcript_language,
            "scene_recipe": "gray64x36-fixed-interval-mad-v1",
            "component_identity": identities,
            "limits": {
                "max_input_bytes": MAX_INPUT_BYTES,
                "max_duration_ms": MAX_DURATION_MS,
                "max_streams": MAX_STREAMS,
                "max_scenes": MAX_SCENES,
                "max_scene_samples": MAX_SCENE_SAMPLES,
                "max_selected_frames": MAX_SELECTED_FRAMES,
            },
        }
        payloads = {
            "video.json": ("application/json", canonical_json_bytes(record)),
            "timeline.json": ("application/json", canonical_json_bytes(timeline)),
            "subtitles.json": ("application/json", canonical_json_bytes(subtitles)),
            **subtitle_payloads,
            **frame_payloads,
        }
        if transcript["state"] == "available":
            payloads["transcript.json"] = ("application/json", canonical_json_bytes(transcript))
        fully_available = video_capability.get("state") == "ready" and video_stream is not None
        return payloads, settings, anchors, fully_available

    def create(
        self,
        version_id: str,
        *,
        timestamps_ms: Sequence[int] = (),
        transcript_language: str = "auto",
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        payloads, settings, anchors, available = self._derive(
            version_id,
            timestamps_ms=timestamps_ms,
            transcript_language=transcript_language,
            cancelled=cancelled,
        )
        expected_outputs = {
            name: {"media_type": media_type, "sha256": _sha256(payload), "size_bytes": len(payload)}
            for name, (media_type, payload) in payloads.items()
        }
        for existing in self.bundles.list(
            version_id=version_id, recipe_id=VIDEO_RECIPE_ID, limit=500
        ):
            actual_outputs = {
                Path(str(output["storage_ref"])).name: {
                    "media_type": output["media_type"],
                    "sha256": output["sha256"],
                    "size_bytes": output["size_bytes"],
                }
                for output in existing["outputs"]
            }
            if (
                existing["recipe"]["version"] == VIDEO_RECIPE_VERSION
                and existing["recipe"]["settings"] == settings
                and actual_outputs == expected_outputs
            ):
                return existing
        try:
            return self.bundles.materialize(
                version_id,
                recipe_id=VIDEO_RECIPE_ID,
                recipe_version=VIDEO_RECIPE_VERSION,
                recipe_settings=settings,
                output_payloads=payloads,
                implementation={
                    "component": "provelume.core",
                    "component_version": "0.9.0",
                    "adapter": "perceptio-video-profile",
                    "adapter_version": "1",
                    "settings": {
                        "mode": "offline",
                        "decoder": "ffmpeg",
                        "frame_ocr": "explicit-only",
                    },
                },
                warnings=() if available else ("video_decode_unavailable",),
                anchor_targets=anchors,
                availability_state="available" if available else "degraded",
                availability_reason=None if available else "component_missing",
                missing_component=None if available else "codec.ffmpeg",
            )
        except RepresentationContractError as exc:
            raise VideoContractError("video_contract_violation", str(exc)) from exc

    def queue(
        self,
        version_id: str,
        *,
        timestamps_ms: Sequence[int] = (),
        transcript_language: str = "auto",
    ) -> dict[str, Any]:
        self._source(version_id)
        selected = _selected_timestamps(timestamps_ms)
        if _LANGUAGE.fullmatch(transcript_language) is None or transcript_language not in {
            "auto",
            "en",
            "it",
        }:
            raise VideoContractError("video_contract_violation", "transcript language is invalid")
        processing_identity = {
            "video": self.video_adapter.capability(),
            "asr": self.asr_adapter.capability(),
            "ocr": self.ocr_adapter.capability(),
            "settings": {
                "timestamps_ms": selected,
                "transcript_language": transcript_language,
            },
        }
        identity = _sha256(
            canonical_json_bytes(
                {
                    "version_id": version_id,
                    "recipe": VIDEO_RECIPE_ID,
                    "version": VIDEO_RECIPE_VERSION,
                    "processing_identity": processing_identity,
                }
            )
        )
        job_id = f"video_{identity}"
        self.jobs.mkdir(parents=True, exist_ok=True)
        target = self.jobs / f"{job_id}.json"
        if target.exists():
            return {"scheduled": False, "job": self.get_job(job_id)}
        job = {
            "schema_version": VIDEO_JOB_SCHEMA_VERSION,
            "id": job_id,
            "kind": "video.profile",
            "version_id": version_id,
            "processing_identity": processing_identity,
            "status": "queued",
            "checkpoint": {"phase": "queued", "sequence": 0},
            "requested_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "representation_id": None,
            "error_code": None,
            "cancel_requested": False,
            "retry_count": 0,
        }
        self.store._atomic_json(target, job)
        return {"scheduled": True, "job": job}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        if re.fullmatch(r"video_[0-9a-f]{64}", job_id) is None:
            return None
        try:
            value = self.store._read_json(self.jobs / f"{job_id}.json")
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return value if value.get("id") == job_id else None

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.jobs.exists():
            return []
        result = []
        for path in sorted(self.jobs.glob("video_*.json"), reverse=True):
            value = self.get_job(path.stem)
            if value is not None:
                result.append(value)
            if len(result) >= min(max(limit, 1), 500):
                break
        return result

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise VideoContractError("video_not_found", "video job was not found")
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            raise VideoContractError(
                "video_job_state_invalid", "completed video job cannot be cancelled"
            )
        job["cancel_requested"] = True
        if job["status"] == "queued":
            job.update(
                {
                    "status": "cancelled",
                    "completed_at": utc_now(),
                    "checkpoint": {"phase": "cancelled", "sequence": 1},
                }
            )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        return job

    def retry(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise VideoContractError("video_not_found", "video job was not found")
        if job["status"] not in {"failed", "cancelled"}:
            raise VideoContractError("video_job_state_invalid", "video job is not retryable")
        job.update(
            {
                "status": "queued",
                "checkpoint": {
                    "phase": "queued",
                    "sequence": int(job["checkpoint"]["sequence"]) + 1,
                },
                "started_at": None,
                "completed_at": None,
                "representation_id": None,
                "error_code": None,
                "cancel_requested": False,
                "retry_count": int(job["retry_count"]) + 1,
            }
        )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        return job

    def run(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise VideoContractError("video_not_found", "video job was not found")
        if job["status"] == "succeeded":
            return job
        if job["status"] != "queued":
            raise VideoContractError("video_job_state_invalid", "video job state is invalid")
        if job["cancel_requested"]:
            return self.cancel(job_id)
        job.update(
            {
                "status": "running",
                "started_at": utc_now(),
                "checkpoint": {
                    "phase": "deriving",
                    "sequence": int(job["checkpoint"]["sequence"]) + 1,
                },
                "error_code": None,
            }
        )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        identities = job["processing_identity"]

        def cancelled() -> bool:
            current = self.get_job(job_id)
            return current is not None and current.get("cancel_requested") is True

        try:
            if (
                identities["video"] != self.video_adapter.capability()
                or identities["asr"] != self.asr_adapter.capability()
                or identities["ocr"] != self.ocr_adapter.capability()
            ):
                raise VideoContractError(
                    "video_decoder_unavailable", "queued component identity changed"
                )
            settings = identities["settings"]
            bundle = self.create(
                str(job["version_id"]),
                timestamps_ms=settings["timestamps_ms"],
                transcript_language=str(settings["transcript_language"]),
                cancelled=cancelled,
            )
        except VideoContractError as exc:
            job.update(
                {
                    "status": "cancelled" if exc.code == "video_cancelled" else "failed",
                    "completed_at": utc_now(),
                    "error_code": exc.code,
                    "checkpoint": {
                        "phase": "cancelled" if exc.code == "video_cancelled" else "failed",
                        "sequence": int(job["checkpoint"]["sequence"]) + 1,
                    },
                }
            )
            self.store._atomic_json(self.jobs / f"{job_id}.json", job)
            return job
        current = self.get_job(job_id)
        if current is not None and current.get("cancel_requested") is True:
            with suppress(RepresentationContractError):
                self.bundles.remove(str(bundle["representation_id"]))
            current.update(
                {
                    "status": "cancelled",
                    "completed_at": utc_now(),
                    "representation_id": None,
                    "checkpoint": {
                        "phase": "cancelled",
                        "sequence": int(current["checkpoint"]["sequence"]) + 1,
                    },
                }
            )
            self.store._atomic_json(self.jobs / f"{job_id}.json", current)
            return current
        job.update(
            {
                "status": "succeeded",
                "completed_at": utc_now(),
                "representation_id": bundle["representation_id"],
                "checkpoint": {
                    "phase": "published",
                    "sequence": int(job["checkpoint"]["sequence"]) + 1,
                },
            }
        )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        return job

    def read_model(self, *, version_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        profiles = []
        for bundle in self.bundles.list(recipe_id=VIDEO_RECIPE_ID, limit=500):
            record = self._record_for_bundle(bundle)
            if record is None or (version_id is not None and record["version_id"] != version_id):
                continue
            profiles.append(
                {
                    "representation_id": bundle["representation_id"],
                    "availability": bundle["availability"],
                    "record": record,
                    "outputs": bundle["outputs"],
                }
            )
            if len(profiles) >= min(max(limit, 1), 500):
                break
        return {
            "schema_version": 1,
            "profile_id": VIDEO_PROFILE_ID,
            "support": self.capability(),
            "profiles": profiles,
            "jobs": self.list_jobs(limit=limit),
            "privacy": {
                "local_only": True,
                "speaker_or_face_identity": False,
                "source_writeback": False,
            },
            "network_used": False,
        }

    def get(self, representation_id: str) -> dict[str, Any] | None:
        bundle = self.bundles.get(representation_id, deep=True)
        if bundle is None:
            return None
        record = self._record_for_bundle(bundle)
        if record is None:
            return None
        return {
            "representation_id": bundle["representation_id"],
            "availability": bundle["availability"],
            "record": record,
            "outputs": bundle["outputs"],
        }

    def remove(self, representation_id: str) -> dict[str, Any]:
        bundle = self.bundles.get(representation_id, deep=True)
        if bundle is None or bundle.get("recipe", {}).get("id") != VIDEO_RECIPE_ID:
            raise VideoContractError("video_not_found", "video representation was not found")
        try:
            return self.bundles.remove(representation_id)
        except RepresentationContractError as exc:
            raise VideoContractError("video_not_found", str(exc)) from exc

    def rebuild(self, representation_id: str) -> dict[str, Any]:
        receipt_path = self.bundles.history / f"{representation_id}.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            bundle = receipt["bundle"]
            if bundle["recipe"]["id"] != VIDEO_RECIPE_ID:
                raise KeyError("wrong recipe")
            version_id = str(bundle["version"]["id"])
            settings = dict(bundle["recipe"]["settings"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VideoContractError(
                "video_not_found", "video removal history was not found"
            ) from exc
        payloads, _settings, _anchors, _available = self._derive(
            version_id,
            timestamps_ms=settings["timestamps_ms"],
            transcript_language=str(settings["transcript_language"]),
            frozen_settings=settings,
        )
        raw = {name: value[1] for name, value in payloads.items()}
        expected = {Path(item["storage_ref"]).name for item in bundle["outputs"]}
        if set(raw) != expected:
            raise VideoContractError(
                "video_decoder_unavailable", "video rebuild outputs no longer match"
            )
        try:
            return self.bundles.rebuild(representation_id, raw)
        except RepresentationContractError as exc:
            raise VideoContractError("video_contract_violation", str(exc)) from exc


__all__ = [
    "FFMPEG_SOURCE_SHA256",
    "FFMPEG_SOURCE_SIZE",
    "FFMPEG_VERSION",
    "VIDEO_ERROR_CODES",
    "VIDEO_FORMATS",
    "VIDEO_PROFILE_ID",
    "FFmpegAdapter",
    "FrameOcrAdapter",
    "VideoContractError",
    "VideoProfileManager",
    "identify_video_bytes",
    "validate_video_record",
]
