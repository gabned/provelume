from __future__ import annotations

import base64
import hashlib
import io
import os
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.instance_backup import create_backup, extract_backup, verify_backup
from provelume.instance_validation import inspect_instance
from provelume.ocr_contract import OcrContractError
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore
from provelume.video_profiles import (
    FFMPEG_SOURCE_SHA256,
    FFMPEG_SOURCE_SIZE,
    FFmpegAdapter,
    VideoContractError,
    VideoProfileManager,
    _normalise_probe,
    _ppm_to_png,
    identify_video_bytes,
    validate_video_record,
)
from provelume.web import create_app


def _atom(kind: bytes, payload: bytes = b"") -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


def _mp4(*, brand: bytes = b"isom") -> bytes:
    return _atom(b"ftyp", brand + b"\x00\x00\x00\x00" + brand) + _atom(b"moov")


def _wav() -> bytes:
    payload = io.BytesIO()
    with wave.open(payload, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 1_600)
    return payload.getvalue()


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _capability(*, state: str = "ready", reason: str | None = None) -> dict[str, object]:
    return {
        "adapter_id": "ffmpeg-cli-pair",
        "component": "codec.ffmpeg",
        "version": "9.0.1",
        "ffmpeg_sha256": "a" * 64 if state == "ready" else None,
        "ffprobe_sha256": "b" * 64 if state == "ready" else None,
        "qualified_platform": "ubuntu-24.04-x86_64",
        "source_sha256": FFMPEG_SOURCE_SHA256,
        "source_size_bytes": FFMPEG_SOURCE_SIZE,
        "network_used": False,
        "runtime_downloads": False,
        "qualified": state == "ready",
        "state": state,
        "reason": reason,
    }


def _stream(index: int, kind: str, codec: str, *, qualified: bool) -> dict[str, object]:
    video = kind == "video"
    audio = kind == "audio"
    attachment = kind == "attachment"
    return {
        "index": index,
        "kind": kind,
        "codec": codec,
        "language": "en" if kind == "subtitle" else "und",
        "duration_ms": 2_000 if kind in {"video", "audio", "subtitle"} else None,
        "width": 640 if video else None,
        "height": 360 if video else None,
        "frame_rate": 29.97 if video else None,
        "variable_frame_rate": True if video else None,
        "profile": "High" if video else None,
        "level": "40" if video else None,
        "pixel_format": "yuv420p" if video else None,
        "rotation_degrees": 90 if video else None,
        "color_range": "tv" if video else None,
        "color_space": "bt2020nc" if video else None,
        "color_transfer": "smpte2084" if video else None,
        "color_primaries": "bt2020" if video else None,
        "hdr": True if video else None,
        "channels": 1 if audio else None,
        "sample_rate_hz": 16_000 if audio else None,
        "attachment_name": "font.ttf" if attachment else None,
        "attachment_media_type": "application/x-truetype-font" if attachment else None,
        "default": index == 0,
        "qualified": qualified,
    }


class FakeVideoAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return _capability()

    @staticmethod
    def inspect(_data: bytes, *, format_name: str) -> dict[str, object]:
        assert format_name == "MP4"
        return {
            "container": "mp4",
            "duration_ms": 2_000,
            "streams": [
                _stream(0, "video", "h264", qualified=True),
                _stream(1, "audio", "aac", qualified=True),
                _stream(2, "subtitle", "mov_text", qualified=True),
                _stream(3, "attachment", "ttf", qualified=False),
            ],
            "chapters": [{"id": "chapter-1", "start_ms": 0, "end_ms": 2_000}],
            "encrypted": False,
        }

    @staticmethod
    def gray_samples(
        _data: bytes, *, stream_index: int, duration_ms: int
    ) -> list[tuple[int, bytes]]:
        assert stream_index == 0 and duration_ms == 2_000
        size = 64 * 36
        return [(0, b"\x00" * size), (1_000, b"\xff" * size), (2_000, b"\xff" * size)]

    @staticmethod
    def frame(_data: bytes, *, stream_index: int, timestamp_ms: int) -> bytes:
        assert stream_index == 0 and 0 <= timestamp_ms <= 2_000
        return PNG

    @staticmethod
    def subtitle(_data: bytes, *, stream_index: int) -> bytes:
        assert stream_index == 2
        return b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello exact frame\n"

    @staticmethod
    def audio(_data: bytes, *, stream_index: int) -> bytes:
        assert stream_index == 1
        return _wav()


class MissingVideoAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return _capability(state="unavailable", reason="component_missing")


class FakeAsrAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return {
            "state": "ready",
            "qualified": True,
            "adapter_id": "fixture-whisper",
            "version": "1.9.2",
            "binary_sha256": "c" * 64,
            "device": "cpu",
            "model_id": "fixture-model",
            "model_sha256": "d" * 64,
            "quantization": "q5_1",
            "network_used": False,
            "runtime_downloads": False,
        }

    @staticmethod
    def transcribe(_wav_bytes: bytes, *, language: str, threads: int) -> dict[str, object]:
        assert language in {"auto", "en", "it"} and threads == 1
        return {
            "language": "en",
            "segments": [
                {
                    "start_ms": 0,
                    "end_ms": 800,
                    "text": "spoken evidence",
                    "confidence": 0.9,
                    "words": [
                        {
                            "start_ms": 0,
                            "end_ms": 300,
                            "text": "spoken",
                            "confidence": 0.9,
                        },
                        {
                            "start_ms": 310,
                            "end_ms": 800,
                            "text": "evidence",
                            "confidence": 0.9,
                        },
                    ],
                }
            ],
            "warnings": [],
        }


class MissingAsrAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return {
            "state": "unavailable",
            "reason": "component_missing",
            "adapter_id": "whisper.cpp-cli",
            "version": None,
            "binary_sha256": None,
            "model_id": "ggml-tiny-q5_1",
            "model_sha256": None,
            "quantization": "q5_1",
            "qualified": False,
            "network_used": False,
            "runtime_downloads": False,
        }


class FakeOcrAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return {
            "state": "ready",
            "reason": None,
            "settings_sha256": "e" * 64,
            "engine": {"id": "fixture-tesseract"},
            "contract": "lectio-ocr-region-v1",
        }

    @staticmethod
    def recognise(
        frame: bytes, *, version_id: str, original_sha256: str, ordinal: int
    ) -> dict[str, object]:
        assert frame == PNG and version_id and len(original_sha256) == 64 and ordinal >= 1
        return {
            "spans": [
                {
                    "text": f"frame {ordinal}",
                    "status": "machine-unverified",
                    "confidence": 0.95,
                    "box": {
                        "left": 0,
                        "top": 0,
                        "width": 1,
                        "height": 1,
                        "page_width": 1,
                        "page_height": 1,
                        "coordinate_space": "source-pixels",
                    },
                }
            ]
        }


class MissingOcrAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return {"state": "unavailable", "reason": "component_missing"}


class FailingOcrAdapter(FakeOcrAdapter):
    @staticmethod
    def recognise(
        frame: bytes, *, version_id: str, original_sha256: str, ordinal: int
    ) -> dict[str, object]:
        raise OcrContractError("ocr_deadline_exceeded", "bounded OCR deadline")


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, str]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "clip.mp4").write_bytes(_mp4())
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    version_id = str(instance.store.list_canonical("documents")[0]["current_version_id"])
    return instance, version_id


def _manager(instance: ProvelumeInstance) -> VideoProfileManager:
    return VideoProfileManager(
        instance.store,
        video_adapter=FakeVideoAdapter(),
        asr_adapter=FakeAsrAdapter(),
        ocr_adapter=FakeOcrAdapter(),
    )


def test_candidate_signatures_are_structurally_bounded() -> None:
    assert identify_video_bytes(_mp4()) == "MP4"
    assert identify_video_bytes(_mp4(brand=b"qt  ")) == "MOV"
    avi_payload = b"AVI " + b"data"
    avi = b"RIFF" + len(avi_payload).to_bytes(4, "little") + avi_payload
    assert identify_video_bytes(avi) == "AVI"
    assert identify_video_bytes(b"\x1aE\xdf\xa3\x00webm\x00") == "WEBM"
    assert identify_video_bytes(b"\x1aE\xdf\xa3\x00matroska\x00") == "MKV"

    with pytest.raises(VideoContractError) as truncated_mp4:
        identify_video_bytes(_atom(b"ftyp", b"isom")[:-1])
    assert truncated_mp4.value.code == "video_invalid_container"
    with pytest.raises(VideoContractError) as truncated_avi:
        identify_video_bytes(b"RIFF\x08\x00\x00\x00AVI ")
    assert truncated_avi.value.code == "video_invalid_container"
    with pytest.raises(VideoContractError) as generic_ebml:
        identify_video_bytes(b"\x1aE\xdf\xa3unknown")
    assert generic_ebml.value.code == "video_invalid_container"


def test_first_party_ppm_to_png_is_deterministic_and_bounded() -> None:
    ppm = b"P6\n2 1\n255\n" + b"\xff\x00\x00\x00\xff\x00"
    first = _ppm_to_png(ppm)
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert first == _ppm_to_png(ppm)
    with pytest.raises(VideoContractError):
        _ppm_to_png(ppm[:-1])


def test_probe_normalises_profile_vfr_rotation_hdr_and_attachments() -> None:
    raw = {
        "format": {"duration": "2.0"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "profile": "High",
                "level": 40,
                "width": 640,
                "height": 360,
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30/1",
                "pix_fmt": "yuv420p10le",
                "color_range": "tv",
                "color_space": "bt2020nc",
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
                "side_data_list": [{"rotation": 90}],
                "duration": "2.0",
            },
            {
                "index": 1,
                "codec_type": "attachment",
                "codec_name": "ttf",
                "tags": {"filename": "font.ttf", "mimetype": "application/x-truetype-font"},
            },
        ],
        "chapters": [],
    }
    record = _normalise_probe(raw, format_name="MP4")
    video, attachment = record["streams"]
    assert video["profile"] == "High"
    assert video["variable_frame_rate"] is True
    assert video["rotation_degrees"] == 90
    assert video["hdr"] is True
    assert attachment["attachment_name"] == "font.ttf"
    assert attachment["qualified"] is False


def test_webm_matrix_qualifies_only_declared_streams() -> None:
    raw = {
        "format": {"duration": "2.0"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "vp9",
                "width": 640,
                "height": 360,
                "avg_frame_rate": "25/1",
            },
            {"index": 1, "codec_type": "audio", "codec_name": "opus"},
            {"index": 2, "codec_type": "subtitle", "codec_name": "webvtt"},
        ],
        "chapters": [],
    }
    assert [
        stream["qualified"] for stream in _normalise_probe(raw, format_name="WEBM")["streams"]
    ] == [True, True, True]


@pytest.mark.skipif(os.name != "posix", reason="executable fixture uses POSIX scripts")
def test_ffmpeg_pair_requires_hash_and_reported_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FFmpegAdapter, "_qualified_platform", staticmethod(lambda: True))
    ffmpeg = tmp_path / "ffmpeg"
    ffprobe = tmp_path / "ffprobe"
    ffmpeg.write_text("#!/bin/sh\nprintf 'ffmpeg version 9.0.1\\n'\n", encoding="utf-8")
    ffprobe.write_text("#!/bin/sh\nprintf 'ffprobe version 9.0.1\\n'\n", encoding="utf-8")
    ffmpeg.chmod(0o700)
    ffprobe.chmod(0o700)
    adapter = FFmpegAdapter(
        ffmpeg_path=ffmpeg.resolve(),
        ffprobe_path=ffprobe.resolve(),
        declared_version="9.0.1",
        expected_ffmpeg_sha256=hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
        expected_ffprobe_sha256=hashlib.sha256(ffprobe.read_bytes()).hexdigest(),
    )
    assert adapter.capability()["state"] == "ready"
    ffprobe.write_text("#!/bin/sh\nprintf 'ffprobe version 8.0\\n'\n", encoding="utf-8")
    ffprobe.chmod(0o700)
    drifted = FFmpegAdapter(
        ffmpeg_path=ffmpeg.resolve(),
        ffprobe_path=ffprobe.resolve(),
        declared_version="9.0.1",
        expected_ffmpeg_sha256=hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
        expected_ffprobe_sha256=hashlib.sha256(ffprobe.read_bytes()).hexdigest(),
    )
    assert drifted.capability()["reason"] == "version_mismatch"


def test_frame_extraction_bounds_both_portrait_axes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FFmpegAdapter()
    fake_binary = tmp_path / "ffmpeg"
    fake_binary.write_bytes(b"fixture")
    monkeypatch.setattr(adapter, "_require", lambda: (fake_binary, fake_binary))
    captured: list[list[str]] = []

    def fake_run(command, *, root, stdout_limit=0, produced=None):
        captured.append(list(command))
        assert produced is not None
        next(iter(produced)).write_bytes(b"P6\n1 1\n255\n\x00\x00\x00")
        return b""

    monkeypatch.setattr(adapter, "_run", fake_run)
    assert adapter.frame(b"source", stream_index=0, timestamp_ms=0).startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    filter_value = captured[0][captured[0].index("-vf") + 1]
    assert filter_value == (
        "scale=1600:1600:force_original_aspect_ratio=decrease:force_divisible_by=2"
    )


def test_profile_preserves_synchronised_citable_evidence_and_original(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = _manager(instance)
    original_id = str(instance.store.read_canonical("versions", version_id)["original_id"])
    before = instance.store.original_bytes(original_id)

    first = manager.create(version_id, timestamps_ms=[500, 1_250], transcript_language="en")
    second = manager.create(version_id, timestamps_ms=[500, 1_250], transcript_language="en")
    assert first["representation_id"] == second["representation_id"]
    selected = manager.get(str(first["representation_id"]))
    assert selected is not None
    record = validate_video_record(selected["record"])
    assert record["streams"][0]["profile"] == "High"
    assert record["subtitles"][0]["cues"][0]["text"] == "Hello exact frame"
    assert record["transcript"]["segments"][0]["text"] == "spoken evidence"
    assert [(scene["start_ms"], scene["end_ms"]) for scene in record["scenes"]] == [
        (0, 1_000),
        (1_000, 2_000),
    ]
    assert [item["timestamp_ms"] for item in record["keyframes"]] == [500, 1_500]
    assert [item["timestamp_ms"] for item in record["frame_ocr"]] == [500, 1_250]
    assert all(len(item["regions"]) == 1 for item in record["frame_ocr"])
    bundle = manager.bundles.get(str(first["representation_id"]))
    assert bundle is not None
    assert any(anchor["kind"] == "region" for anchor in bundle["anchors"])
    assert sum(anchor["kind"] == "time" for anchor in bundle["anchors"]) >= 9
    assert instance.store.original_bytes(original_id) == before


def test_missing_decoder_is_truthful_and_never_falls_back(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = VideoProfileManager(
        instance.store,
        video_adapter=MissingVideoAdapter(),
        asr_adapter=MissingAsrAdapter(),
        ocr_adapter=MissingOcrAdapter(),
    )
    bundle = manager.create(version_id)
    selected = manager.get(str(bundle["representation_id"]))
    assert selected is not None
    assert selected["availability"]["state"] == "degraded"
    assert selected["record"]["component"]["state"] == "unavailable"
    assert selected["record"]["scenes"] == []
    assert selected["record"]["invariants"]["network_used"] is False


def test_jobs_cancel_retry_remove_rebuild_and_identity_drift(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = _manager(instance)
    job_id = str(manager.queue(version_id, timestamps_ms=[500])["job"]["id"])
    assert manager.cancel(job_id)["status"] == "cancelled"
    assert manager.retry(job_id)["status"] == "queued"
    complete = manager.run(job_id)
    assert complete["status"] == "succeeded"
    representation_id = str(complete["representation_id"])
    assert manager.remove(representation_id)["original_mutated"] is False
    assert manager.rebuild(representation_id)["representation_id"] == representation_id

    other = _manager(instance)
    drift_job = str(other.queue(version_id, timestamps_ms=[1_000])["job"]["id"])
    other.video_adapter.capability = lambda: {**_capability(), "version": "changed"}
    failed = other.run(drift_job)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "video_decoder_unavailable"


def test_ocr_failure_leaves_job_recoverable(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = VideoProfileManager(
        instance.store,
        video_adapter=FakeVideoAdapter(),
        asr_adapter=FakeAsrAdapter(),
        ocr_adapter=FailingOcrAdapter(),
    )
    job_id = str(manager.queue(version_id, timestamps_ms=[500])["job"]["id"])
    failed = manager.run(job_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "video_process_failed"
    assert manager.retry(job_id)["status"] == "queued"


def test_hostile_probe_boundaries_fail_closed() -> None:
    base = {
        "format": {"duration": "2.0"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 360,
                "avg_frame_rate": "30/1",
                "duration": "2.0",
            }
        ],
        "chapters": [],
    }
    hostile = {**base, "streams": [{**base["streams"][0], "width": 100_000}]}
    with pytest.raises(VideoContractError) as dimensions:
        _normalise_probe(hostile, format_name="MP4")
    assert dimensions.value.code == "video_dimension_limit_exceeded"

    fast = {**base, "streams": [{**base["streams"][0], "avg_frame_rate": "121/1"}]}
    with pytest.raises(VideoContractError) as frame_rate:
        _normalise_probe(fast, format_name="MP4")
    assert frame_rate.value.code == "video_frame_rate_limit_exceeded"

    encrypted = {
        **base,
        "streams": [{**base["streams"][0], "codec_tag_string": "encv"}],
    }
    with pytest.raises(VideoContractError) as encryption:
        _normalise_probe(encrypted, format_name="MP4")
    assert encryption.value.code == "video_encrypted"


def test_video_api_and_browser_are_read_only(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = _manager(instance)
    selected = manager.create(version_id)
    client = TestClient(create_app(instance.root))
    assert client.get("/api/v1/video/support").status_code == 200
    assert client.get("/video?lang=it").status_code == 200
    assert client.post(f"/api/v1/video/jobs/{version_id}").status_code == 404
    assert client.delete(f"/api/v1/video/{selected['representation_id']}").status_code == 405
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/api/v1/video/{representation_id}"]) == {"get"}
    timeline = client.get(
        f"/api/v1/video/{selected['representation_id']}/outputs/timeline.json"
    )
    assert timeline.status_code == 200
    assert timeline.headers["cache-control"] == "no-store"
    assert client.get(
        f"/api/v1/video/{selected['representation_id']}/outputs/selected-frame-001.png"
    ).status_code == 404


def test_backup_transfer_and_support_registry_preserve_video_profile(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    selected_id = str(_manager(instance).create(version_id)["representation_id"])
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    backup = create_backup(instance.store, destination=tmp_path / "backups", reason="video")
    assert verify_backup(backup["archive"])["status"] == "valid"
    restored = tmp_path / "restored"
    extract_backup(backup["archive"], restored)
    restored_manager = VideoProfileManager(
        InstanceStore(restored),
        video_adapter=FakeVideoAdapter(),
        asr_adapter=FakeAsrAdapter(),
        ocr_adapter=FakeOcrAdapter(),
    )
    assert restored_manager.get(selected_id) is not None

    portable = tmp_path / "portable.zip"
    instance.export_portable(portable)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(portable)
    assert target.get_video(selected_id) is not None

    support = instance.representation_support(profile_id="perceptio-video-v1")
    records = {item["operation"]: item for item in support["records"]}
    assert records["preserve"]["effective_state"] == "available"
    assert records["inspect"]["effective_state"] == "available"
    assert records["extract"]["declared_state"] == "optional"
    assert records["extract"]["missing_component"] == "codec.ffmpeg"
    assert records["ai_enrich"]["reason"] == "not_implemented"
