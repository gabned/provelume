from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .paths import safe_instance_path
from .representations import (
    RepresentationBundleManager,
    RepresentationContractError,
    canonical_json_bytes,
)
from .storage import InstanceStore, utc_now

AUDIO_SCHEMA_VERSION = 1
AUDIO_PROFILE_ID = "perceptio-audio-v1"
AUDIO_RECIPE_ID = "provelume.audio-profile"
AUDIO_RECIPE_VERSION = "1"
AUDIO_JOB_SCHEMA_VERSION = 1

AUDIO_FORMATS = ("WAV", "FLAC", "MP3", "M4A", "AAC", "OGG")
AUDIO_MEDIA_TYPES = {
    "WAV": "audio/wav",
    "FLAC": "audio/flac",
    "MP3": "audio/mpeg",
    "M4A": "audio/mp4",
    "AAC": "audio/aac",
    "OGG": "audio/ogg",
}
AUDIO_ERROR_CODES = (
    "audio_not_found",
    "audio_unsupported_format",
    "audio_invalid_container",
    "audio_input_limit_exceeded",
    "audio_duration_limit_exceeded",
    "audio_channel_limit_exceeded",
    "audio_codec_unavailable",
    "audio_asr_unavailable",
    "audio_asr_incompatible",
    "audio_asr_failed",
    "audio_contract_violation",
    "audio_job_state_invalid",
)

WHISPER_CPP_VERSION = "1.9.2"
WHISPER_MODEL_ID = "ggml-tiny-q5_1"
WHISPER_MODEL_SHA256 = "818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7"
WHISPER_MODEL_SIZE = 32_152_673

MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_DURATION_MS = 2 * 60 * 60 * 1000
MAX_CHANNELS = 8
MAX_CONTAINER_RECORDS = 4_096
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_WAVEFORM_POINTS = 2_000
MAX_SEGMENTS = 20_000
MAX_WORDS = 100_000
MAX_TRANSCRIPT_CHARS = 2_000_000
MAX_ASR_STDERR_BYTES = 256 * 1024
MAX_ASR_SECONDS = 2 * 60 * 60

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_LANGUAGE = re.compile(r"(?:auto|[a-z]{2}(?:-[A-Z]{2})?)\Z")


class AudioContractError(ValueError):
    """Closed, content-free failure for bounded audio profiling."""

    def __init__(self, code: str, message: str):
        if code not in AUDIO_ERROR_CODES:
            raise ValueError("audio error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path, *, maximum: int) -> tuple[str, int]:
    try:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise OSError("not an explicit regular file")
        size = path.stat().st_size
        if size < 1 or size > maximum:
            raise OSError("file size outside boundary")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise AudioContractError(
            "audio_asr_unavailable", "configured ASR component is unavailable"
        ) from exc
    return digest.hexdigest(), size


def _bounded_input(data: bytes) -> None:
    if not data or len(data) > MAX_INPUT_BYTES:
        raise AudioContractError(
            "audio_input_limit_exceeded", "audio input exceeds its closed byte limit"
        )


def _duration(value: int | None) -> int | None:
    if value is not None and (value < 0 or value > MAX_DURATION_MS):
        raise AudioContractError(
            "audio_duration_limit_exceeded", "audio duration exceeds its closed limit"
        )
    return value


def _channels(value: int | None) -> int | None:
    if value is not None and (value < 1 or value > MAX_CHANNELS):
        raise AudioContractError(
            "audio_channel_limit_exceeded", "audio channel count exceeds its closed limit"
        )
    return value


def _identify(data: bytes) -> str:
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "WAV"
    if data.startswith(b"fLaC"):
        return "FLAC"
    if data.startswith(b"OggS"):
        return "OGG"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "M4A"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE6 == 0xE2):
        return "MP3"
    if len(data) >= 2 and data[0] == 0xFF and data[1] & 0xF6 == 0xF0:
        return "AAC"
    raise AudioContractError(
        "audio_unsupported_format", "audio signature is outside the candidate matrix"
    )


def _wav_chunks(data: bytes) -> list[tuple[bytes, int, int]]:
    if len(data) < 12:
        raise AudioContractError("audio_invalid_container", "WAV header is truncated")
    declared = int.from_bytes(data[4:8], "little") + 8
    if declared > len(data) or declared < 12:
        raise AudioContractError("audio_invalid_container", "WAV size is invalid")
    chunks: list[tuple[bytes, int, int]] = []
    offset = 12
    while offset + 8 <= declared and len(chunks) < MAX_CONTAINER_RECORDS:
        kind = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        start = offset + 8
        end = start + size
        if size > MAX_INPUT_BYTES or end > declared:
            raise AudioContractError("audio_invalid_container", "WAV chunk is truncated")
        chunks.append((kind, start, size))
        offset = end + (size & 1)
    if len(chunks) >= MAX_CONTAINER_RECORDS or offset > declared:
        raise AudioContractError("audio_invalid_container", "WAV chunk limit is invalid")
    return chunks


def _inspect_wav(data: bytes) -> dict[str, Any]:
    chunks = _wav_chunks(data)
    formats = [row for row in chunks if row[0] == b"fmt "]
    payloads = [row for row in chunks if row[0] == b"data"]
    if len(formats) != 1 or len(payloads) != 1:
        raise AudioContractError("audio_invalid_container", "WAV needs one fmt and data chunk")
    _kind, start, size = formats[0]
    if size < 16 or size > MAX_METADATA_BYTES:
        raise AudioContractError("audio_invalid_container", "WAV fmt chunk is invalid")
    audio_format, channels, rate, byte_rate, block_align, bits = struct.unpack_from(
        "<HHIIHH", data, start
    )
    _channels(channels)
    if rate < 8_000 or rate > 384_000 or block_align < 1 or byte_rate < 1:
        raise AudioContractError("audio_invalid_container", "WAV stream parameters are invalid")
    if bits < 1 or bits > 64 or block_align != math.ceil(bits / 8) * channels:
        raise AudioContractError("audio_invalid_container", "WAV sample layout is invalid")
    if byte_rate != rate * block_align:
        raise AudioContractError("audio_invalid_container", "WAV byte rate is inconsistent")
    _data_kind, data_start, data_size = payloads[0]
    if data_size % block_align:
        raise AudioContractError("audio_invalid_container", "WAV data is not frame-aligned")
    frames = data_size // block_align
    duration_ms = _duration((frames * 1_000) // rate)
    codec = {1: "pcm", 3: "ieee-float"}.get(audio_format, f"wave-format-{audio_format}")
    qualified = audio_format == 1 and bits == 16 and channels <= 2
    warnings = [] if qualified else ["codec_unqualified"]
    return {
        "container": "wav",
        "codec": codec,
        "sample_rate_hz": rate,
        "channels": channels,
        "bits_per_sample": bits,
        "sample_count": frames,
        "duration_ms": duration_ms,
        "metadata_records": len(chunks),
        "decode_state": "qualified" if qualified else "unavailable",
        "warnings": warnings,
        "_pcm": {
            "offset": data_start,
            "size": data_size,
            "block_align": block_align,
        }
        if qualified
        else None,
    }


def _inspect_flac(data: bytes) -> dict[str, Any]:
    offset = 4
    records = 0
    streaminfo: bytes | None = None
    last = False
    while not last and offset + 4 <= len(data) and records < MAX_CONTAINER_RECORDS:
        header = data[offset]
        last = bool(header & 0x80)
        kind = header & 0x7F
        size = int.from_bytes(data[offset + 1 : offset + 4], "big")
        offset += 4
        if size > MAX_METADATA_BYTES or offset + size > len(data):
            raise AudioContractError("audio_invalid_container", "FLAC metadata is truncated")
        if kind == 0:
            if streaminfo is not None or size != 34:
                raise AudioContractError("audio_invalid_container", "FLAC STREAMINFO is invalid")
            streaminfo = data[offset : offset + size]
        offset += size
        records += 1
    if not last or streaminfo is None or records >= MAX_CONTAINER_RECORDS:
        raise AudioContractError("audio_invalid_container", "FLAC metadata is incomplete")
    packed = int.from_bytes(streaminfo[10:18], "big")
    rate = (packed >> 44) & 0xFFFFF
    channels = ((packed >> 41) & 0x7) + 1
    bits = ((packed >> 36) & 0x1F) + 1
    samples = packed & ((1 << 36) - 1)
    if rate < 1 or bits < 1:
        raise AudioContractError("audio_invalid_container", "FLAC stream parameters are invalid")
    _channels(channels)
    duration_ms = _duration((samples * 1_000) // rate if samples else None)
    return {
        "container": "flac",
        "codec": "flac",
        "sample_rate_hz": rate,
        "channels": channels,
        "bits_per_sample": bits,
        "sample_count": samples or None,
        "duration_ms": duration_ms,
        "metadata_records": records,
        "decode_state": "unavailable",
        "warnings": ["codec_unqualified"],
        "_pcm": None,
    }


def _syncsafe(value: bytes) -> int:
    if len(value) != 4 or any(part & 0x80 for part in value):
        raise AudioContractError("audio_invalid_container", "ID3 size is invalid")
    return (value[0] << 21) | (value[1] << 14) | (value[2] << 7) | value[3]


def _inspect_mp3(data: bytes) -> dict[str, Any]:
    offset = 0
    records = 0
    if data.startswith(b"ID3"):
        if len(data) < 10:
            raise AudioContractError("audio_invalid_container", "ID3 header is truncated")
        size = _syncsafe(data[6:10]) + 10
        if size > MAX_METADATA_BYTES or size > len(data):
            raise AudioContractError("audio_invalid_container", "ID3 metadata is invalid")
        offset = size
        records = 1
    limit = min(len(data) - 4, offset + 64 * 1024)
    selected: tuple[int, int, int] | None = None
    while offset <= limit:
        header = int.from_bytes(data[offset : offset + 4], "big")
        if header >> 21 == 0x7FF:
            version_bits = (header >> 19) & 0x3
            layer_bits = (header >> 17) & 0x3
            bitrate_index = (header >> 12) & 0xF
            rate_index = (header >> 10) & 0x3
            if (
                version_bits != 1
                and layer_bits == 1
                and bitrate_index not in {0, 15}
                and rate_index != 3
            ):
                rates = {
                    3: (44_100, 48_000, 32_000),
                    2: (22_050, 24_000, 16_000),
                    0: (11_025, 12_000, 8_000),
                }
                bitrate_table = (
                    (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
                    if version_bits == 3
                    else (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
                )
                selected = (
                    rates[version_bits][rate_index],
                    bitrate_table[bitrate_index - 1],
                    (header >> 6) & 0x3,
                )
                break
        offset += 1
    if selected is None:
        raise AudioContractError("audio_invalid_container", "MP3 frame header was not found")
    rate, bitrate_kbps, channel_mode = selected
    channels = 1 if channel_mode == 3 else 2
    duration_ms = _duration(((len(data) - offset) * 8) // bitrate_kbps)
    return {
        "container": "mp3",
        "codec": "mp3",
        "sample_rate_hz": rate,
        "channels": channels,
        "bits_per_sample": None,
        "sample_count": None,
        "duration_ms": duration_ms,
        "metadata_records": records,
        "decode_state": "unavailable",
        "warnings": ["codec_unqualified", "duration_estimated_cbr"],
        "_pcm": None,
    }


def _inspect_adts(data: bytes) -> dict[str, Any]:
    rates = (
        96_000,
        88_200,
        64_000,
        48_000,
        44_100,
        32_000,
        24_000,
        22_050,
        16_000,
        12_000,
        11_025,
        8_000,
        7_350,
    )
    offset = 0
    frames = 0
    rate: int | None = None
    channels: int | None = None
    while offset + 7 <= len(data) and frames < MAX_CONTAINER_RECORDS:
        if data[offset] != 0xFF or data[offset + 1] & 0xF6 != 0xF0:
            raise AudioContractError("audio_invalid_container", "AAC ADTS frame is invalid")
        rate_index = (data[offset + 2] >> 2) & 0xF
        if rate_index >= len(rates):
            raise AudioContractError("audio_invalid_container", "AAC sample rate is invalid")
        current_rate = rates[rate_index]
        current_channels = ((data[offset + 2] & 1) << 2) | (data[offset + 3] >> 6)
        length = (
            ((data[offset + 3] & 0x3) << 11) | (data[offset + 4] << 3) | (data[offset + 5] >> 5)
        )
        if length < 7 or offset + length > len(data):
            raise AudioContractError("audio_invalid_container", "AAC ADTS frame is truncated")
        if rate not in {None, current_rate} or channels not in {None, current_channels}:
            raise AudioContractError(
                "audio_invalid_container", "AAC stream changes are unsupported"
            )
        rate, channels = current_rate, current_channels
        offset += length
        frames += 1
    if offset != len(data) or frames == 0 or frames >= MAX_CONTAINER_RECORDS:
        raise AudioContractError("audio_invalid_container", "AAC frame boundary is invalid")
    _channels(channels)
    samples = frames * 1_024
    return {
        "container": "adts",
        "codec": "aac",
        "sample_rate_hz": rate,
        "channels": channels,
        "bits_per_sample": None,
        "sample_count": samples,
        "duration_ms": _duration((samples * 1_000) // int(rate)),
        "metadata_records": frames,
        "decode_state": "unavailable",
        "warnings": ["codec_unqualified"],
        "_pcm": None,
    }


def _inspect_ogg(data: bytes) -> dict[str, Any]:
    offset = 0
    pages = 0
    serials: set[int] = set()
    first_payload = b""
    last_granule = 0
    while offset + 27 <= len(data) and pages < MAX_CONTAINER_RECORDS:
        if data[offset : offset + 4] != b"OggS" or data[offset + 4] != 0:
            raise AudioContractError("audio_invalid_container", "Ogg page header is invalid")
        segments = data[offset + 26]
        table_end = offset + 27 + segments
        if table_end > len(data):
            raise AudioContractError("audio_invalid_container", "Ogg lacing table is truncated")
        payload_size = sum(data[offset + 27 : table_end])
        end = table_end + payload_size
        if end > len(data):
            raise AudioContractError("audio_invalid_container", "Ogg page is truncated")
        serials.add(int.from_bytes(data[offset + 14 : offset + 18], "little"))
        granule = int.from_bytes(data[offset + 6 : offset + 14], "little")
        if granule != (1 << 64) - 1:
            last_granule = max(last_granule, granule)
        if not first_payload:
            first_payload = data[table_end:end]
        offset = end
        pages += 1
    if offset != len(data) or pages == 0 or pages >= MAX_CONTAINER_RECORDS or len(serials) != 1:
        raise AudioContractError("audio_invalid_container", "Ogg stream boundary is invalid")
    if first_payload.startswith(b"OpusHead") and len(first_payload) >= 19:
        codec = "opus"
        channels = first_payload[9]
        rate = 48_000
        pre_skip = int.from_bytes(first_payload[10:12], "little")
        samples = max(0, last_granule - pre_skip) if last_granule else None
    elif first_payload.startswith(b"\x01vorbis") and len(first_payload) >= 16:
        codec = "vorbis"
        channels = first_payload[11]
        rate = int.from_bytes(first_payload[12:16], "little")
        samples = last_granule or None
    else:
        raise AudioContractError("audio_invalid_container", "Ogg codec is unsupported")
    _channels(channels)
    if rate < 1:
        raise AudioContractError("audio_invalid_container", "Ogg sample rate is invalid")
    return {
        "container": "ogg",
        "codec": codec,
        "sample_rate_hz": rate,
        "channels": channels,
        "bits_per_sample": None,
        "sample_count": samples,
        "duration_ms": _duration((samples * 1_000) // rate if samples is not None else None),
        "metadata_records": pages,
        "decode_state": "unavailable",
        "warnings": ["codec_unqualified"],
        "_pcm": None,
    }


def _mp4_atoms(data: bytes, start: int = 0, end: int | None = None) -> list[tuple[bytes, int, int]]:
    boundary = len(data) if end is None else end
    offset = start
    atoms: list[tuple[bytes, int, int]] = []
    while offset + 8 <= boundary and len(atoms) < MAX_CONTAINER_RECORDS:
        size = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        header = 8
        if size == 1:
            if offset + 16 > boundary:
                raise AudioContractError("audio_invalid_container", "MP4 atom is truncated")
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header = 16
        elif size == 0:
            size = boundary - offset
        if size < header or offset + size > boundary:
            raise AudioContractError("audio_invalid_container", "MP4 atom size is invalid")
        atoms.append((kind, offset + header, size - header))
        offset += size
    if offset != boundary or len(atoms) >= MAX_CONTAINER_RECORDS:
        raise AudioContractError("audio_invalid_container", "MP4 atom boundary is invalid")
    return atoms


def _inspect_m4a(data: bytes) -> dict[str, Any]:
    atoms = _mp4_atoms(data)
    kinds = {kind for kind, _start, _size in atoms}
    if not {b"ftyp", b"moov"}.issubset(kinds):
        raise AudioContractError("audio_invalid_container", "M4A needs ftyp and moov atoms")
    duration_ms: int | None = None
    tracks = 0
    for kind, start, size in atoms:
        if kind != b"moov":
            continue
        children = _mp4_atoms(data, start, start + size)
        tracks += sum(child[0] == b"trak" for child in children)
        for child_kind, child_start, child_size in children:
            if child_kind != b"mvhd" or child_size < 20:
                continue
            version = data[child_start]
            if version == 0 and child_size >= 20:
                timescale = int.from_bytes(data[child_start + 12 : child_start + 16], "big")
                duration = int.from_bytes(data[child_start + 16 : child_start + 20], "big")
            elif version == 1 and child_size >= 32:
                timescale = int.from_bytes(data[child_start + 20 : child_start + 24], "big")
                duration = int.from_bytes(data[child_start + 24 : child_start + 32], "big")
            else:
                continue
            if timescale:
                duration_ms = _duration((duration * 1_000) // timescale)
    codec = (
        "alac"
        if b"alac" in data[: min(len(data), MAX_METADATA_BYTES)]
        else "aac"
        if b"mp4a" in data[: min(len(data), MAX_METADATA_BYTES)]
        else "unknown"
    )
    return {
        "container": "iso-bmff",
        "codec": codec,
        "sample_rate_hz": None,
        "channels": None,
        "bits_per_sample": None,
        "sample_count": None,
        "duration_ms": duration_ms,
        "metadata_records": len(atoms),
        "track_count": tracks or None,
        "decode_state": "unavailable",
        "warnings": ["codec_unqualified"]
        + (["duration_unavailable"] if duration_ms is None else []),
        "_pcm": None,
    }


def _inspect_internal(data: bytes) -> dict[str, Any]:
    _bounded_input(data)
    selected = _identify(data)
    parsers = {
        "WAV": _inspect_wav,
        "FLAC": _inspect_flac,
        "MP3": _inspect_mp3,
        "M4A": _inspect_m4a,
        "AAC": _inspect_adts,
        "OGG": _inspect_ogg,
    }
    stream = parsers[selected](data)
    track_count = int(stream.pop("track_count", 1) or 1)
    return {
        "format": selected,
        "media_type": AUDIO_MEDIA_TYPES[selected],
        "byte_length": len(data),
        "container": stream.pop("container"),
        "tracks": [
            {
                "index": index,
                "kind": "audio",
                "codec": stream["codec"] if index == 0 else "unknown",
                "sample_rate_hz": stream["sample_rate_hz"] if index == 0 else None,
                "channels": stream["channels"] if index == 0 else None,
                "bits_per_sample": stream["bits_per_sample"] if index == 0 else None,
            }
            for index in range(track_count)
        ],
        "chapters": [],
        **stream,
    }


def inspect_audio_bytes(data: bytes) -> dict[str, Any]:
    result = _inspect_internal(data)
    result.pop("_pcm", None)
    return result


def _pcm16_mono_16khz(
    data: bytes, inspected: Mapping[str, Any]
) -> tuple[bytes, list[dict[str, int]]]:
    pcm = inspected.get("_pcm")
    if not isinstance(pcm, Mapping):
        raise AudioContractError("audio_codec_unavailable", "audio decoder is not qualified")
    start = int(pcm["offset"])
    size = int(pcm["size"])
    source_rate = int(inspected["sample_rate_hz"])
    channels = int(inspected["channels"])
    frames = size // (channels * 2)
    source = memoryview(data)[start : start + size]

    def mono(frame: int) -> int:
        total = sum(
            struct.unpack_from("<h", source, (frame * channels + channel) * 2)[0]
            for channel in range(channels)
        )
        return int(total / channels)

    output_frames = (frames * 16_000) // source_rate
    samples = bytearray(output_frames * 2)
    for index in range(output_frames):
        numerator = index * source_rate
        left = min(numerator // 16_000, frames - 1)
        remainder = numerator % 16_000
        right = min(left + 1, frames - 1)
        value = (mono(left) * (16_000 - remainder) + mono(right) * remainder) // 16_000
        struct.pack_into("<h", samples, index * 2, max(-32_768, min(32_767, value)))
    riff_size = 36 + len(samples)
    wav = (
        b"RIFF"
        + riff_size.to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + struct.pack("<HHIIHH", 1, 1, 16_000, 32_000, 2, 16)
        + b"data"
        + len(samples).to_bytes(4, "little")
        + bytes(samples)
    )

    points: list[dict[str, int]] = []
    source_window = max(1, math.ceil(frames / MAX_WAVEFORM_POINTS))
    for first in range(0, frames, source_window):
        last = min(frames, first + source_window)
        peak = 0
        square_sum = 0
        count = 0
        for frame in range(first, last):
            for channel in range(channels):
                value = struct.unpack_from("<h", source, (frame * channels + channel) * 2)[0]
                peak = max(peak, abs(value))
                square_sum += value * value
                count += 1
        rms = math.isqrt(square_sum // max(1, count))
        points.append(
            {
                "start_ms": (first * 1_000) // source_rate,
                "end_ms": (last * 1_000) // source_rate,
                "peak_ppm": (peak * 1_000_000) // 32_768,
                "rms_ppm": (rms * 1_000_000) // 32_768,
            }
        )
    return wav, points


def _milliseconds(value: Any) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str):
        match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})", value)
        if match:
            hours, minutes, seconds, millis = map(int, match.groups())
            return ((hours * 60 + minutes) * 60 + seconds) * 1_000 + millis
    raise AudioContractError("audio_asr_failed", "ASR timestamp is invalid")


def _normalise_transcript(value: Any, *, duration_ms: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AudioContractError("audio_asr_failed", "ASR output is not an object")
    raw_segments = value.get("segments", value.get("transcription"))
    language = value.get("language")
    if language is None and isinstance(value.get("result"), Mapping):
        language = value["result"].get("language")
    if not isinstance(language, str) or _LANGUAGE.fullmatch(language) is None:
        raise AudioContractError("audio_asr_failed", "ASR language is invalid")
    if not isinstance(raw_segments, list) or len(raw_segments) > MAX_SEGMENTS:
        raise AudioContractError("audio_asr_failed", "ASR segment count is invalid")
    segments: list[dict[str, Any]] = []
    word_total = 0
    text_total = 0
    previous_end = 0
    for ordinal, raw in enumerate(raw_segments):
        if not isinstance(raw, Mapping) or any(
            key in raw for key in ("speaker", "speaker_id", "speaker_label")
        ):
            raise AudioContractError("audio_asr_failed", "ASR segment contract is invalid")
        offsets = raw.get("offsets") if isinstance(raw.get("offsets"), Mapping) else raw
        timestamps = raw.get("timestamps") if isinstance(raw.get("timestamps"), Mapping) else raw
        start = _milliseconds(offsets.get("from", timestamps.get("from", raw.get("start_ms"))))
        end = _milliseconds(offsets.get("to", timestamps.get("to", raw.get("end_ms"))))
        text = raw.get("text")
        if (
            not isinstance(text, str)
            or len(text) > 10_000
            or "\x00" in text
            or start < previous_end
            or end < start
            or end > duration_ms + 2_000
        ):
            raise AudioContractError("audio_asr_failed", "ASR segment boundary is invalid")
        text_total += len(text)
        if text_total > MAX_TRANSCRIPT_CHARS:
            raise AudioContractError("audio_asr_failed", "ASR transcript is oversized")
        raw_words = raw.get("words", raw.get("tokens", []))
        if not isinstance(raw_words, list):
            raise AudioContractError("audio_asr_failed", "ASR words are invalid")
        words: list[dict[str, Any]] = []
        probabilities: list[float] = []
        for word_ordinal, token in enumerate(raw_words):
            if not isinstance(token, Mapping):
                raise AudioContractError("audio_asr_failed", "ASR word is invalid")
            token_text = token.get("text", token.get("word"))
            if (
                not isinstance(token_text, str)
                or not token_text
                or len(token_text) > 500
                or "\x00" in token_text
            ):
                raise AudioContractError("audio_asr_failed", "ASR word text is invalid")
            if token_text.startswith("<|") and token_text.endswith("|>"):
                continue
            token_offsets = (
                token.get("offsets") if isinstance(token.get("offsets"), Mapping) else token
            )
            token_times = (
                token.get("timestamps") if isinstance(token.get("timestamps"), Mapping) else token
            )
            token_start = _milliseconds(
                token_offsets.get("from", token_times.get("from", token.get("start_ms")))
            )
            token_end = _milliseconds(
                token_offsets.get("to", token_times.get("to", token.get("end_ms")))
            )
            probability = token.get("p", token.get("probability", token.get("confidence")))
            confidence = None
            if probability is not None:
                if (
                    isinstance(probability, bool)
                    or not isinstance(probability, (int, float))
                    or not 0 <= float(probability) <= 1
                ):
                    raise AudioContractError("audio_asr_failed", "ASR confidence is invalid")
                confidence = round(float(probability), 6)
                probabilities.append(confidence)
            if token_start < start or token_end < token_start or token_end > end:
                raise AudioContractError("audio_asr_failed", "ASR word boundary is invalid")
            word_id = "aword_" + _sha256(
                canonical_json_bytes(
                    {
                        "segment": ordinal,
                        "word": word_ordinal,
                        "start_ms": token_start,
                        "end_ms": token_end,
                        "text": token_text,
                    }
                )
            )
            words.append(
                {
                    "id": word_id,
                    "start_ms": token_start,
                    "end_ms": token_end,
                    "text": token_text,
                    "confidence": confidence,
                    "timestamp_qualified": True,
                }
            )
            word_total += 1
            if word_total > MAX_WORDS:
                raise AudioContractError("audio_asr_failed", "ASR word count is invalid")
        confidence = raw.get("confidence")
        if confidence is None and probabilities:
            confidence = round(sum(probabilities) / len(probabilities), 6)
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise AudioContractError("audio_asr_failed", "ASR segment confidence is invalid")
        segment_id = "aseg_" + _sha256(
            canonical_json_bytes(
                {"ordinal": ordinal, "start_ms": start, "end_ms": end, "text": text}
            )
        )
        segments.append(
            {
                "id": segment_id,
                "start_ms": start,
                "end_ms": end,
                "text": text,
                "confidence": round(float(confidence), 6) if confidence is not None else None,
                "warning_codes": ["low_confidence"]
                if confidence is not None and confidence < 0.5
                else [],
                "words": words,
                "speaker_identity": None,
            }
        )
        previous_end = end
    return {"language": language, "segments": segments}


class WhisperCppAdapter:
    """Explicit, pinned whisper.cpp CLI adapter with no discovery or download."""

    def __init__(
        self,
        *,
        binary_path: Path | None = None,
        model_path: Path | None = None,
        declared_version: str | None = None,
    ):
        binary = binary_path or (
            Path(os.environ["PROVELUME_WHISPER_CPP_PATH"])
            if os.environ.get("PROVELUME_WHISPER_CPP_PATH")
            else None
        )
        model = model_path or (
            Path(os.environ["PROVELUME_WHISPER_MODEL_PATH"])
            if os.environ.get("PROVELUME_WHISPER_MODEL_PATH")
            else None
        )
        self.binary_path = binary
        self.model_path = model
        self.declared_version = declared_version or os.environ.get("PROVELUME_WHISPER_CPP_VERSION")

    def capability(self) -> dict[str, Any]:
        base = {
            "adapter_id": "whisper.cpp-cli",
            "component": "asr.whisper-cpp",
            "version": self.declared_version,
            "model_id": WHISPER_MODEL_ID,
            "model_sha256": None,
            "binary_sha256": None,
            "device": "cpu",
            "quantization": "q5_1",
            "qualified": False,
            "network_used": False,
            "runtime_downloads": False,
        }
        if self.binary_path is None or self.model_path is None or self.declared_version is None:
            return {**base, "state": "unavailable", "reason": "component_missing"}
        if self.declared_version != WHISPER_CPP_VERSION:
            return {**base, "state": "incompatible", "reason": "version_mismatch"}
        try:
            binary_sha, _binary_size = _file_sha256(self.binary_path, maximum=512 * 1024 * 1024)
            model_sha, model_size = _file_sha256(self.model_path, maximum=256 * 1024 * 1024)
        except AudioContractError:
            return {**base, "state": "unavailable", "reason": "component_missing"}
        if model_sha != WHISPER_MODEL_SHA256 or model_size != WHISPER_MODEL_SIZE:
            return {
                **base,
                "state": "incompatible",
                "reason": "model_identity_mismatch",
                "binary_sha256": binary_sha,
                "model_sha256": model_sha,
            }
        return {
            **base,
            "state": "ready",
            "reason": None,
            "binary_sha256": binary_sha,
            "model_sha256": model_sha,
            "qualified": True,
        }

    def transcribe(self, wav: bytes, *, language: str, threads: int) -> dict[str, Any]:
        capability = self.capability()
        if capability["state"] == "unavailable":
            raise AudioContractError("audio_asr_unavailable", "local ASR is unavailable")
        if capability["state"] != "ready":
            raise AudioContractError("audio_asr_incompatible", "local ASR identity is incompatible")
        assert self.binary_path is not None and self.model_path is not None
        with tempfile.TemporaryDirectory(prefix="provelume-audio-") as temporary:
            root = Path(temporary)
            source = root / "input.wav"
            output = root / "transcript"
            error_path = root / "stderr.txt"
            source.write_bytes(wav)
            command = [
                str(self.binary_path),
                "--model",
                str(self.model_path),
                "--file",
                str(source),
                "--output-json-full",
                "--output-file",
                str(output),
                "--language",
                language,
                "--threads",
                str(threads),
                "--temperature",
                "0",
                "--no-gpu",
                "--no-prints",
            ]
            try:
                with error_path.open("wb") as error_handle:
                    completed = subprocess.run(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=error_handle,
                        timeout=MAX_ASR_SECONDS,
                        check=False,
                        env={"LC_ALL": "C", "LANG": "C", "PATH": os.environ.get("PATH", "")},
                    )
                if error_path.stat().st_size > MAX_ASR_STDERR_BYTES or completed.returncode != 0:
                    raise AudioContractError(
                        "audio_asr_failed", "local ASR exited outside its contract"
                    )
                result_path = output.with_suffix(".json")
                if not result_path.is_file() or result_path.stat().st_size > 32 * 1024 * 1024:
                    raise AudioContractError("audio_asr_failed", "local ASR output is unavailable")
                return json.loads(result_path.read_text(encoding="utf-8"))
            except AudioContractError:
                raise
            except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as exc:
                raise AudioContractError("audio_asr_failed", "local ASR failed safely") from exc


def _validate_settings(language: str, threads: int) -> dict[str, Any]:
    if _LANGUAGE.fullmatch(language) is None or language not in {"auto", "en", "it"}:
        raise AudioContractError("audio_contract_violation", "audio language is unsupported")
    if type(threads) is not int or threads < 1 or threads > 32:
        raise AudioContractError("audio_contract_violation", "ASR thread count is invalid")
    return {"language": language, "threads": threads, "device": "cpu", "quantization": "q5_1"}


def validate_audio_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AudioContractError("audio_contract_violation", "audio record is invalid")
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
        "tracks",
        "chapters",
        "codec",
        "sample_rate_hz",
        "channels",
        "bits_per_sample",
        "sample_count",
        "duration_ms",
        "metadata_records",
        "decode_state",
        "warnings",
        "waveform",
        "transcript",
        "time_map",
        "corrections",
        "invariants",
    }
    if (
        set(record) != required
        or record.get("schema_version") != AUDIO_SCHEMA_VERSION
        or record.get("kind") != "audio-profile"
        or record.get("profile_id") != AUDIO_PROFILE_ID
    ):
        raise AudioContractError("audio_contract_violation", "audio record fields are invalid")
    if (
        not isinstance(record["version_id"], str)
        or _IDENTIFIER.fullmatch(record["version_id"]) is None
        or not isinstance(record["original_sha256"], str)
        or _SHA256.fullmatch(record["original_sha256"]) is None
    ):
        raise AudioContractError("audio_contract_violation", "audio identity is invalid")
    if (
        record["format"] not in AUDIO_FORMATS
        or record["media_type"] != AUDIO_MEDIA_TYPES[record["format"]]
    ):
        raise AudioContractError("audio_contract_violation", "audio format is invalid")
    if type(record["byte_length"]) is not int or not 1 <= record["byte_length"] <= MAX_INPUT_BYTES:
        raise AudioContractError("audio_contract_violation", "audio byte length is invalid")
    if (
        not isinstance(record["tracks"], list)
        or not record["tracks"]
        or len(record["tracks"]) > MAX_CHANNELS
    ):
        raise AudioContractError("audio_contract_violation", "audio tracks are invalid")
    _duration(record["duration_ms"])
    _channels(record["channels"])
    if record["decode_state"] not in {"qualified", "unavailable"} or not isinstance(
        record["warnings"], list
    ):
        raise AudioContractError("audio_contract_violation", "audio decode state is invalid")
    waveform = record["waveform"]
    if (
        not isinstance(waveform, Mapping)
        or set(waveform) != {"state", "recipe", "point_count", "peak_ppm", "rms_ppm"}
        or waveform["state"] not in {"available", "unavailable"}
    ):
        raise AudioContractError("audio_contract_violation", "audio waveform is invalid")
    if (
        type(waveform["point_count"]) is not int
        or not 0 <= waveform["point_count"] <= MAX_WAVEFORM_POINTS
    ):
        raise AudioContractError(
            "audio_contract_violation", "audio waveform point count is invalid"
        )
    transcript = record["transcript"]
    if (
        not isinstance(transcript, Mapping)
        or set(transcript)
        != {
            "state",
            "reason",
            "language",
            "engine",
            "model",
            "settings",
            "segments",
            "speaker_identity",
            "uncertainty_preserved",
        }
        or transcript["state"] not in {"available", "unavailable"}
        or transcript["speaker_identity"] is not None
        or transcript["uncertainty_preserved"] is not True
    ):
        raise AudioContractError("audio_contract_violation", "audio transcript is invalid")
    segments = transcript["segments"]
    if not isinstance(segments, list) or len(segments) > MAX_SEGMENTS:
        raise AudioContractError(
            "audio_contract_violation", "audio transcript segments are invalid"
        )
    if transcript["state"] == "unavailable" and (
        segments or not isinstance(transcript["reason"], str)
    ):
        raise AudioContractError("audio_contract_violation", "unavailable transcript is invalid")
    if transcript["state"] == "available" and (
        transcript["reason"] is not None
        or not isinstance(transcript["engine"], Mapping)
        or not isinstance(transcript["model"], Mapping)
    ):
        raise AudioContractError("audio_contract_violation", "available transcript is invalid")
    previous_end = 0
    word_count = 0
    for segment in segments:
        if (
            not isinstance(segment, Mapping)
            or set(segment)
            != {
                "id",
                "start_ms",
                "end_ms",
                "text",
                "confidence",
                "warning_codes",
                "words",
                "speaker_identity",
            }
            or segment["speaker_identity"] is not None
        ):
            raise AudioContractError("audio_contract_violation", "audio segment is invalid")
        if (
            type(segment["start_ms"]) is not int
            or type(segment["end_ms"]) is not int
            or segment["start_ms"] < previous_end
            or segment["end_ms"] < segment["start_ms"]
        ):
            raise AudioContractError("audio_contract_violation", "audio segment time is invalid")
        if (
            not isinstance(segment["text"], str)
            or "\x00" in segment["text"]
            or not isinstance(segment["words"], list)
        ):
            raise AudioContractError("audio_contract_violation", "audio segment content is invalid")
        word_count += len(segment["words"])
        previous_end = segment["end_ms"]
    if word_count > MAX_WORDS:
        raise AudioContractError("audio_contract_violation", "audio word count is invalid")
    time_map = record["time_map"]
    if (
        not isinstance(time_map, Mapping)
        or set(time_map) != {"anchor_count", "segment_anchors", "word_anchors", "reopen_original"}
        or time_map["reopen_original"] is not True
        or time_map["anchor_count"] != time_map["segment_anchors"] + time_map["word_anchors"]
    ):
        raise AudioContractError("audio_contract_violation", "audio time map is invalid")
    invariants = record["invariants"]
    expected = {
        "derived": True,
        "original_immutable": True,
        "canonical_records_immutable": True,
        "network_used": False,
        "runtime_downloads": False,
        "remote_asr": False,
        "speaker_identity": False,
        "summary_or_classification": False,
        "source_writeback": False,
    }
    if invariants != expected or record["corrections"] != {
        "contract": "lectio-transcript-corrections-v1",
        "source_text_mutated": False,
    }:
        raise AudioContractError("audio_contract_violation", "audio invariants are invalid")
    return record


class AudioProfileManager:
    """Explicit bounded audio jobs and universal derived-profile lifecycle."""

    def __init__(self, store: InstanceStore, *, asr_adapter: Any | None = None):
        self.store = store
        self.bundles = RepresentationBundleManager(store)
        self.asr_adapter = asr_adapter or WhisperCppAdapter()
        self.root = store.paths.state / "audio"
        self.jobs = self.root / "jobs"

    def capability(self) -> dict[str, Any]:
        asr = self.asr_adapter.capability()
        return {
            "schema_version": 1,
            "profile_id": AUDIO_PROFILE_ID,
            "candidate_formats": list(AUDIO_FORMATS),
            "matrix": [
                {
                    "format": name,
                    "inspect": "available",
                    "waveform": "available" if name == "WAV" else "unavailable",
                    "asr": "optional" if name == "WAV" else "unavailable",
                }
                for name in AUDIO_FORMATS
            ],
            "decode_baseline": "wav-pcm16le-mono-or-stereo",
            "asr": asr,
            "network_used": False,
            "runtime_downloads": False,
            "mutated": False,
        }

    def _source(self, version_id: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        version = self.store.read_canonical("versions", version_id)
        if version is None:
            raise AudioContractError("audio_not_found", "audio DocumentVersion was not found")
        original = self.store.read_canonical("originals", str(version.get("original_id", "")))
        if original is None:
            raise AudioContractError("audio_not_found", "audio Original was not found")
        data = self.store.original_bytes(str(original["id"]))
        digest = _sha256(data)
        if (
            digest != original.get("sha256")
            or digest != version.get("content_hash")
            or len(data) != original.get("size_bytes")
            or len(data) != version.get("size_bytes")
        ):
            raise AudioContractError(
                "audio_contract_violation", "audio Original identity verification failed"
            )
        return version, original, data

    def _record_for_bundle(self, bundle: Mapping[str, Any]) -> dict[str, Any] | None:
        if bundle.get("recipe", {}).get("id") != AUDIO_RECIPE_ID:
            return None
        output = next(
            (item for item in bundle["outputs"] if Path(item["storage_ref"]).name == "audio.json"),
            None,
        )
        if output is None:
            return None
        try:
            path = safe_instance_path(self.store.paths.root, str(output["storage_ref"]))
            return validate_audio_record(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _derive(
        self,
        version_id: str,
        *,
        language: str = "auto",
        threads: int = 1,
        frozen_settings: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, tuple[str, bytes]], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        _version, original, data = self._source(version_id)
        settings_input = _validate_settings(language, threads)
        inspected = _inspect_internal(data)
        pcm = inspected.pop("_pcm")
        normalised_wav: bytes | None = None
        points: list[dict[str, int]] = []
        if pcm is not None:
            normalised_wav, points = _pcm16_mono_16khz(data, {**inspected, "_pcm": pcm})
        asr = self.asr_adapter.capability()
        transcript: dict[str, Any]
        if frozen_settings is not None:
            frozen_asr = dict(frozen_settings.get("asr_identity", {}))
            if frozen_asr != asr:
                raise AudioContractError(
                    "audio_asr_unavailable", "audio rebuild components no longer match"
                )
            settings_input = dict(frozen_settings.get("asr_settings", {}))
        if normalised_wav is not None and asr.get("state") == "ready":
            raw = self.asr_adapter.transcribe(
                normalised_wav,
                language=str(settings_input["language"]),
                threads=int(settings_input["threads"]),
            )
            selected = _normalise_transcript(raw, duration_ms=int(inspected["duration_ms"] or 0))
            transcript = {
                "state": "available",
                "reason": None,
                "language": selected["language"],
                "engine": {
                    "id": asr["adapter_id"],
                    "version": asr["version"],
                    "binary_sha256": asr["binary_sha256"],
                },
                "model": {
                    "id": asr["model_id"],
                    "sha256": asr["model_sha256"],
                    "quantization": asr["quantization"],
                },
                "settings": settings_input,
                "segments": selected["segments"],
                "speaker_identity": None,
                "uncertainty_preserved": True,
            }
        else:
            reason = (
                "codec_unqualified"
                if normalised_wav is None
                else str(asr.get("reason") or "component_missing")
            )
            transcript = {
                "state": "unavailable",
                "reason": reason,
                "language": settings_input["language"],
                "engine": None,
                "model": None,
                "settings": settings_input,
                "segments": [],
                "speaker_identity": None,
                "uncertainty_preserved": True,
            }
        segment_count = len(transcript["segments"])
        word_count = sum(len(item["words"]) for item in transcript["segments"])
        anchors = [
            {"kind": "time", "start_ms": item["start_ms"], "end_ms": item["end_ms"]}
            for segment in transcript["segments"]
            for item in [segment, *segment["words"]]
        ]
        peak = max((item["peak_ppm"] for item in points), default=0)
        rms = math.isqrt(sum(item["rms_ppm"] ** 2 for item in points) // max(1, len(points)))
        waveform = {
            "schema_version": 1,
            "version_id": version_id,
            "original_sha256": original["sha256"],
            "recipe": "pcm16le-channel-aggregate-window-v1",
            "points": points,
        }
        time_map = {
            "schema_version": 1,
            "version_id": version_id,
            "original_sha256": original["sha256"],
            "segments": [
                {
                    "segment_id": segment["id"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "words": [
                        {
                            "word_id": word["id"],
                            "start_ms": word["start_ms"],
                            "end_ms": word["end_ms"],
                        }
                        for word in segment["words"]
                    ],
                }
                for segment in transcript["segments"]
            ],
            "reopen": {"authority": "exact-original", "version_id": version_id},
        }
        record = validate_audio_record(
            {
                "schema_version": AUDIO_SCHEMA_VERSION,
                "kind": "audio-profile",
                "profile_id": AUDIO_PROFILE_ID,
                "version_id": version_id,
                "original_sha256": str(original["sha256"]),
                **inspected,
                "waveform": {
                    "state": "available" if points else "unavailable",
                    "recipe": waveform["recipe"] if points else None,
                    "point_count": len(points),
                    "peak_ppm": peak,
                    "rms_ppm": rms,
                },
                "transcript": transcript,
                "time_map": {
                    "anchor_count": len(anchors),
                    "segment_anchors": segment_count,
                    "word_anchors": word_count,
                    "reopen_original": True,
                },
                "corrections": {
                    "contract": "lectio-transcript-corrections-v1",
                    "source_text_mutated": False,
                },
                "invariants": {
                    "derived": True,
                    "original_immutable": True,
                    "canonical_records_immutable": True,
                    "network_used": False,
                    "runtime_downloads": False,
                    "remote_asr": False,
                    "speaker_identity": False,
                    "summary_or_classification": False,
                    "source_writeback": False,
                },
            }
        )
        recipe_settings = {
            "format": inspected["format"],
            "decode_recipe": "pcm16le-mono-16000-linear-v1" if normalised_wav is not None else None,
            "decoded_sha256": _sha256(normalised_wav) if normalised_wav is not None else None,
            "waveform_recipe": waveform["recipe"] if points else None,
            "asr_identity": asr,
            "asr_settings": settings_input,
            "max_duration_ms": MAX_DURATION_MS,
            "max_channels": MAX_CHANNELS,
        }
        payloads = {
            "audio.json": ("application/json", canonical_json_bytes(record)),
            "time-map.json": ("application/json", canonical_json_bytes(time_map)),
            "waveform.json": ("application/json", canonical_json_bytes(waveform)),
        }
        if transcript["state"] == "available":
            payloads["transcript.json"] = (
                "application/json",
                canonical_json_bytes(
                    {
                        "schema_version": 1,
                        "language": transcript["language"],
                        "segments": transcript["segments"],
                    }
                ),
            )
            payloads["transcript.txt"] = (
                "text/plain",
                ("\n".join(segment["text"] for segment in transcript["segments"]) + "\n").encode(
                    "utf-8"
                ),
            )
        return payloads, recipe_settings, anchors, asr

    def create(
        self, version_id: str, *, language: str = "auto", threads: int = 1
    ) -> dict[str, Any]:
        payloads, settings, anchors, asr = self._derive(
            version_id, language=language, threads=threads
        )
        available = asr.get("state") == "ready" and "transcript.json" in payloads
        try:
            return self.bundles.materialize(
                version_id,
                recipe_id=AUDIO_RECIPE_ID,
                recipe_version=AUDIO_RECIPE_VERSION,
                recipe_settings=settings,
                output_payloads=payloads,
                implementation={
                    "component": "provelume.core",
                    "component_version": "0.9.0",
                    "adapter": "perceptio-audio-profile",
                    "adapter_version": "1",
                    "settings": {
                        "mode": "offline",
                        "asr": "whisper.cpp",
                        "speaker_identity": False,
                    },
                },
                warnings=() if available else ("local_asr_unavailable",),
                anchor_targets=anchors,
                availability_state="available" if available else "degraded",
                availability_reason=None if available else "component_missing",
                missing_component=None if available else "asr.whisper-cpp",
            )
        except RepresentationContractError as exc:
            raise AudioContractError("audio_contract_violation", str(exc)) from exc

    def queue(self, version_id: str, *, language: str = "auto", threads: int = 1) -> dict[str, Any]:
        self._source(version_id)
        settings = _validate_settings(language, threads)
        processing_identity = {"asr": self.asr_adapter.capability(), "settings": settings}
        identity = _sha256(
            canonical_json_bytes(
                {
                    "version_id": version_id,
                    "recipe": AUDIO_RECIPE_ID,
                    "version": AUDIO_RECIPE_VERSION,
                    "processing_identity": processing_identity,
                }
            )
        )
        job_id = f"audio_{identity}"
        self.jobs.mkdir(parents=True, exist_ok=True)
        target = self.jobs / f"{job_id}.json"
        if target.exists():
            return {"scheduled": False, "job": self.get_job(job_id)}
        job = {
            "schema_version": AUDIO_JOB_SCHEMA_VERSION,
            "id": job_id,
            "kind": "audio.profile",
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
        if re.fullmatch(r"audio_[0-9a-f]{64}", job_id) is None:
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
        for path in sorted(self.jobs.glob("audio_*.json"), reverse=True):
            value = self.get_job(path.stem)
            if value is not None:
                result.append(value)
            if len(result) >= min(max(limit, 1), 500):
                break
        return result

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise AudioContractError("audio_not_found", "audio job was not found")
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            raise AudioContractError(
                "audio_job_state_invalid", "completed audio job cannot be cancelled"
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
            raise AudioContractError("audio_not_found", "audio job was not found")
        if job["status"] not in {"failed", "cancelled"}:
            raise AudioContractError("audio_job_state_invalid", "audio job is not retryable")
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
            raise AudioContractError("audio_not_found", "audio job was not found")
        if job["status"] == "succeeded":
            return job
        if job["status"] != "queued":
            raise AudioContractError("audio_job_state_invalid", "audio job state is invalid")
        if job["cancel_requested"]:
            job.update(
                {
                    "status": "cancelled",
                    "completed_at": utc_now(),
                    "checkpoint": {
                        "phase": "cancelled",
                        "sequence": int(job["checkpoint"]["sequence"]) + 1,
                    },
                }
            )
            self.store._atomic_json(self.jobs / f"{job_id}.json", job)
            return job
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
        settings = job["processing_identity"]["settings"]
        try:
            bundle = self.create(
                str(job["version_id"]),
                language=str(settings["language"]),
                threads=int(settings["threads"]),
            )
        except AudioContractError as exc:
            job.update(
                {
                    "status": "failed",
                    "completed_at": utc_now(),
                    "error_code": exc.code,
                    "checkpoint": {
                        "phase": "failed",
                        "sequence": int(job["checkpoint"]["sequence"]) + 1,
                    },
                }
            )
            self.store._atomic_json(self.jobs / f"{job_id}.json", job)
            return job
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
        for bundle in self.bundles.list(recipe_id=AUDIO_RECIPE_ID, limit=500):
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
            "profile_id": AUDIO_PROFILE_ID,
            "support": self.capability(),
            "profiles": profiles,
            "jobs": self.list_jobs(limit=limit),
            "privacy": {"local_only": True, "speaker_identity": False, "source_writeback": False},
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
        if bundle is None or bundle.get("recipe", {}).get("id") != AUDIO_RECIPE_ID:
            raise AudioContractError("audio_not_found", "audio representation was not found")
        try:
            return self.bundles.remove(representation_id)
        except RepresentationContractError as exc:
            raise AudioContractError("audio_not_found", str(exc)) from exc

    def rebuild(self, representation_id: str) -> dict[str, Any]:
        receipt_path = self.bundles.history / f"{representation_id}.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            bundle = receipt["bundle"]
            if bundle["recipe"]["id"] != AUDIO_RECIPE_ID:
                raise KeyError("wrong recipe")
            version_id = str(bundle["version"]["id"])
            settings = dict(bundle["recipe"]["settings"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AudioContractError(
                "audio_not_found", "audio removal history was not found"
            ) from exc
        payloads, _settings, _anchors, _asr = self._derive(
            version_id,
            language=str(settings["asr_settings"]["language"]),
            threads=int(settings["asr_settings"]["threads"]),
            frozen_settings=settings,
        )
        raw = {name: value[1] for name, value in payloads.items()}
        expected = {Path(item["storage_ref"]).name for item in bundle["outputs"]}
        if set(raw) != expected:
            raise AudioContractError(
                "audio_asr_unavailable", "audio rebuild outputs no longer match"
            )
        try:
            return self.bundles.rebuild(representation_id, raw)
        except RepresentationContractError as exc:
            raise AudioContractError("audio_contract_violation", str(exc)) from exc


__all__ = [
    "AUDIO_ERROR_CODES",
    "AUDIO_FORMATS",
    "AUDIO_PROFILE_ID",
    "AudioContractError",
    "AudioProfileManager",
    "WhisperCppAdapter",
    "inspect_audio_bytes",
    "validate_audio_record",
]
