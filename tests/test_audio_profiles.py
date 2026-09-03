from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.audio_profiles import (
    AudioContractError,
    AudioProfileManager,
    WhisperCppAdapter,
    inspect_audio_bytes,
    validate_audio_record,
)
from provelume.instance_backup import create_backup, extract_backup, verify_backup
from provelume.instance_validation import inspect_instance
from provelume.representations import canonical_json_bytes
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore
from provelume.web import create_app


def _wav(
    *,
    seconds: float = 0.1,
    channels: int = 1,
    rate: int = 16_000,
    fixture: str = "music",
) -> bytes:
    frames = int(seconds * rate)
    payload = io.BytesIO()
    with wave.open(payload, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = []
        noise_state = 1
        for frame in range(frames):
            if fixture == "silence":
                value = 0
            elif fixture == "noise":
                noise_state = (1_103_515_245 * noise_state + 12_345) & 0x7FFFFFFF
                value = (noise_state % 4_001) - 2_000
            elif fixture == "speech-like":
                envelope = (frame % max(1, rate // 8)) / max(1, rate // 8)
                value = int(
                    700
                    * envelope
                    * (
                        math.sin(2 * math.pi * 120 * frame / rate)
                        + math.sin(2 * math.pi * 720 * frame / rate) / 2
                    )
                )
            else:
                value = int(1_000 * math.sin(2 * math.pi * 440 * frame / rate))
            samples.extend([value] * channels)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return payload.getvalue()


def _flac() -> bytes:
    streaminfo = bytearray(34)
    streaminfo[:4] = b"\x00\x10\x00\x10"
    packed = (48_000 << 44) | (1 << 41) | (15 << 36) | 48_000
    streaminfo[10:18] = packed.to_bytes(8, "big")
    return b"fLaC\x80\x00\x00\x22" + bytes(streaminfo)


def _mp3() -> bytes:
    return b"\xff\xfb\x90\x64" + b"\x00" * 4_096


def _adts() -> bytes:
    frame_length = 7
    profile = 1
    frequency_index = 4
    channels = 2
    return bytes(
        [
            0xFF,
            0xF1,
            (profile << 6) | (frequency_index << 2) | (channels >> 2),
            ((channels & 3) << 6) | (frame_length >> 11),
            (frame_length >> 3) & 0xFF,
            ((frame_length & 7) << 5) | 0x1F,
            0xFC,
        ]
    )


def _ogg_opus() -> bytes:
    payload = (
        b"OpusHead"
        + bytes([1, 1])
        + (312).to_bytes(2, "little")
        + (48_000).to_bytes(4, "little")
        + b"\x00\x00\x00"
    )
    header = bytearray(
        b"OggS\x00\x06"
        + (48_312).to_bytes(8, "little")
        + (1).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + b"\x00\x00\x00\x00"
        + b"\x01"
        + bytes([len(payload)])
        + payload
    )
    crc = 0
    for byte in header:
        crc ^= byte << 24
        for _bit in range(8):
            crc = (
                ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
                if crc & 0x80000000
                else (crc << 1) & 0xFFFFFFFF
            )
    header[22:26] = crc.to_bytes(4, "little")
    return bytes(header)


def _m4a(*, audio_track: bool = True) -> bytes:
    def atom(kind: bytes, payload: bytes) -> bytes:
        return (len(payload) + 8).to_bytes(4, "big") + kind + payload

    ftyp = atom(b"ftyp", b"M4A \x00\x00\x00\x00")
    mvhd = (
        b"\x00\x00\x00\x00" + b"\x00" * 8 + (1_000).to_bytes(4, "big") + (1_500).to_bytes(4, "big")
    )
    if audio_track:
        handler = atom(b"hdlr", b"\x00" * 8 + b"soun" + b"\x00" * 8)
        sample_description = atom(b"stsd", b"\x00" * 8 + b"mp4a")
        track = atom(b"trak", atom(b"mdia", handler + atom(b"minf", sample_description)))
    else:
        track = atom(b"trak", b"")
    moov = atom(b"moov", atom(b"mvhd", mvhd) + track)
    return ftyp + moov


class FakeAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return {
            "state": "ready",
            "qualified": True,
            "adapter_id": "fixture-whisper-cpp",
            "version": "1.9.2",
            "binary_sha256": "a" * 64,
            "device": "cpu",
            "model_id": "fixture-ggml",
            "model_sha256": "b" * 64,
            "quantization": "q5_1",
        }

    @staticmethod
    def transcribe(_wav_bytes: bytes, *, language: str, threads: int) -> dict[str, object]:
        assert language in {"auto", "en", "it"}
        assert 1 <= threads <= 16
        return {
            "language": "it",
            "segments": [
                {
                    "start_ms": 0,
                    "end_ms": 80,
                    "text": "ciao",
                    "confidence": 0.9,
                    "words": [
                        {
                            "start_ms": 0,
                            "end_ms": 80,
                            "text": "ciao",
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
            "warnings": [],
        }


class MissingAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return {
            "state": "unavailable",
            "reason": "component_missing",
            "qualified": False,
            "adapter_id": "whisper.cpp-cli",
            "version": None,
            "binary_sha256": None,
            "device": "cpu",
            "model_id": "ggml-tiny-q5_1",
            "model_sha256": None,
            "quantization": "q5_1",
            "network_used": False,
            "runtime_downloads": False,
        }


class LowConfidenceAdapter(FakeAdapter):
    @staticmethod
    def transcribe(wav_bytes: bytes, *, language: str, threads: int) -> dict[str, object]:
        result = FakeAdapter.transcribe(wav_bytes, language=language, threads=threads)
        segments = result["segments"]
        assert isinstance(segments, list)
        segments[0]["confidence"] = 0.2
        segments[0]["words"][0]["confidence"] = 0.2
        return result


class SpecialTokenAdapter(FakeAdapter):
    @staticmethod
    def transcribe(wav_bytes: bytes, *, language: str, threads: int) -> dict[str, object]:
        result = FakeAdapter.transcribe(wav_bytes, language=language, threads=threads)
        segments = result["segments"]
        assert isinstance(segments, list)
        segments[0]["words"].insert(0, {"text": "<|0.00|>"})
        return result


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, str]:
    source = tmp_path / "source"
    source.mkdir()
    # Intake remains extension-agnostic here; S04 identifies audio from the exact bytes.
    (source / "voice.wav").write_bytes(_wav())
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    version_id = str(instance.store.list_canonical("documents")[0]["current_version_id"])
    return instance, version_id


def test_pcm16_wav_inspection_is_bounded_and_qualified() -> None:
    record = inspect_audio_bytes(_wav(channels=2, rate=48_000))
    assert record["format"] == "WAV"
    assert record["codec"] == "pcm"
    assert record["channels"] == 2
    assert record["sample_rate_hz"] == 48_000
    assert record["decode_state"] == "qualified"
    assert 90 <= record["duration_ms"] <= 100


@pytest.mark.parametrize("fixture", ["silence", "music", "noise", "speech-like"])
def test_representative_pcm_fixtures_have_deterministic_bounded_waveforms(
    tmp_path: Path, fixture: str
) -> None:
    source = tmp_path / fixture
    source.mkdir()
    (source / "fixture.wav").write_bytes(_wav(seconds=0.2, fixture=fixture))
    instance = ProvelumeInstance.initialise(tmp_path / f"instance-{fixture}")
    instance.ingest(source)
    version_id = str(instance.store.list_canonical("documents")[0]["current_version_id"])
    manager = AudioProfileManager(instance.store, asr_adapter=MissingAdapter())
    first = manager.create(version_id)
    second = manager.create(version_id)
    assert first["representation_id"] == second["representation_id"]
    selected = manager.get(str(first["representation_id"]))
    assert selected is not None
    assert 1 <= selected["record"]["waveform"]["point_count"] <= 2_000
    assert selected["record"]["transcript"]["state"] == "unavailable"
    if fixture == "silence":
        assert selected["record"]["waveform"]["peak_ppm"] == 0
        assert selected["record"]["waveform"]["rms_ppm"] == 0


def test_empty_limit_duration_and_channel_boundaries_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = inspect_audio_bytes(_wav(seconds=0))
    assert empty["sample_count"] == 0
    assert empty["duration_ms"] == 0

    monkeypatch.setattr("provelume.audio_profiles.MAX_INPUT_BYTES", 64)
    with pytest.raises(AudioContractError) as oversized:
        inspect_audio_bytes(_wav())
    assert oversized.value.code == "audio_input_limit_exceeded"
    monkeypatch.setattr("provelume.audio_profiles.MAX_INPUT_BYTES", 256 * 1024 * 1024)
    monkeypatch.setattr("provelume.audio_profiles.MAX_DURATION_MS", 1)
    with pytest.raises(AudioContractError) as duration:
        inspect_audio_bytes(_wav())
    assert duration.value.code == "audio_duration_limit_exceeded"
    monkeypatch.setattr("provelume.audio_profiles.MAX_DURATION_MS", 2 * 60 * 60 * 1_000)
    with pytest.raises(AudioContractError) as channels:
        inspect_audio_bytes(_wav(channels=9))
    assert channels.value.code == "audio_channel_limit_exceeded"


@pytest.mark.parametrize(
    ("payload", "format_name", "codec"),
    [
        (_flac(), "FLAC", "flac"),
        (_mp3(), "MP3", "mp3"),
        (_adts(), "AAC", "aac"),
        (_ogg_opus(), "OGG", "opus"),
        (_m4a(), "M4A", "aac"),
    ],
)
def test_candidate_containers_are_inspected_but_not_silently_decoded(
    payload: bytes, format_name: str, codec: str
) -> None:
    record = inspect_audio_bytes(payload)
    assert record["format"] == format_name
    assert record["codec"] == codec
    assert record["decode_state"] == "unavailable"
    assert "codec_unqualified" in record["warnings"]


def test_m4a_without_an_audio_handler_is_rejected() -> None:
    with pytest.raises(AudioContractError) as failure:
        inspect_audio_bytes(_m4a(audio_track=False))
    assert failure.value.code == "audio_unsupported_format"


def test_ogg_checksum_is_verified() -> None:
    payload = bytearray(_ogg_opus())
    payload[-1] ^= 1
    with pytest.raises(AudioContractError) as caught:
        inspect_audio_bytes(bytes(payload))
    assert caught.value.code == "audio_invalid_container"


def test_malformed_and_unqualified_audio_fail_closed() -> None:
    with pytest.raises(AudioContractError) as missing:
        inspect_audio_bytes(b"not audio")
    assert missing.value.code == "audio_unsupported_format"
    truncated = _wav()[:-3]
    with pytest.raises(AudioContractError) as invalid:
        inspect_audio_bytes(truncated)
    assert invalid.value.code == "audio_invalid_container"

    appended = _wav() + b"untrusted-trailer"
    with pytest.raises(AudioContractError) as trailer:
        inspect_audio_bytes(appended)
    assert trailer.value.code == "audio_invalid_container"


def test_whisper_adapter_requires_exact_binary_and_model_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "whisper-cli"
    model = tmp_path / "ggml-tiny-q5_1.bin"
    binary.write_bytes(b"qualified-binary-fixture")
    model.write_bytes(b"qualified-model-fixture")
    monkeypatch.setattr("provelume.audio_profiles.WHISPER_MODEL_SIZE", model.stat().st_size)
    monkeypatch.setattr(
        "provelume.audio_profiles.WHISPER_MODEL_SHA256",
        hashlib.sha256(model.read_bytes()).hexdigest(),
    )
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    ready = WhisperCppAdapter(
        binary_path=binary,
        model_path=model,
        declared_version="1.9.2",
        expected_binary_sha256=binary_sha,
    ).capability()
    assert ready["state"] == "ready"
    assert ready["binary_sha256"] == binary_sha

    incompatible = WhisperCppAdapter(
        binary_path=binary,
        model_path=model,
        declared_version="1.9.2",
        expected_binary_sha256="0" * 64,
    ).capability()
    assert incompatible["state"] == "incompatible"
    assert incompatible["reason"] == "binary_identity_mismatch"


def test_audio_job_creates_citable_bundle_without_mutating_original(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    before = instance.store.original_bytes(
        str(instance.store.read_canonical("versions", version_id)["original_id"])
    )
    manager = AudioProfileManager(instance.store, asr_adapter=FakeAdapter())
    queued = manager.queue(version_id, language="it", threads=2)
    completed = manager.run(str(queued["job"]["id"]))
    assert completed["status"] == "succeeded"
    profile = manager.get(str(completed["representation_id"]))
    assert profile is not None
    assert profile["record"]["transcript"]["segments"][0]["text"] == "ciao"
    assert profile["record"]["time_map"]["anchor_count"] == 2
    bundle = manager.bundles.get(str(completed["representation_id"]))
    assert bundle is not None
    assert len(bundle["anchors"]) == 2
    assert all(anchor["version_id"] == version_id for anchor in bundle["anchors"])
    assert bundle["anchors"][0]["target"] == {"start_ms": 0, "end_ms": 80}
    assert validate_audio_record(profile["record"])["invariants"]["network_used"] is False
    assert (
        instance.store.original_bytes(
            str(instance.store.read_canonical("versions", version_id)["original_id"])
        )
        == before
    )

    malformed = dict(profile["record"])
    malformed["time_map"] = {**malformed["time_map"], "word_anchors": 0}
    with pytest.raises(AudioContractError):
        validate_audio_record(malformed)

    leaked = dict(profile["record"])
    leaked["transcript"] = {**leaked["transcript"], "speaker_identity": "speaker-1"}
    with pytest.raises(AudioContractError):
        validate_audio_record(leaked)


def test_cancel_retry_remove_and_rebuild_are_durable(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = AudioProfileManager(instance.store, asr_adapter=FakeAdapter())
    job_id = str(manager.queue(version_id)["job"]["id"])
    assert manager.cancel(job_id)["status"] == "cancelled"
    assert manager.retry(job_id)["status"] == "queued"
    completed = manager.run(job_id)
    representation_id = str(completed["representation_id"])
    assert manager.remove(representation_id)["original_mutated"] is False
    assert manager.rebuild(representation_id)["representation_id"] == representation_id


def test_audio_settings_have_distinct_derived_identities(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = AudioProfileManager(instance.store, asr_adapter=FakeAdapter())
    english = manager.create(version_id, language="en", threads=1)
    italian = manager.create(version_id, language="it", threads=2)
    assert english["representation_id"] != italian["representation_id"]
    assert english["recipe"]["settings"] != italian["recipe"]["settings"]


def test_low_confidence_is_preserved_as_uncertain_evidence(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = AudioProfileManager(instance.store, asr_adapter=LowConfidenceAdapter())
    selected = manager.create(version_id)
    profile = manager.get(str(selected["representation_id"]))
    assert profile is not None
    segment = profile["record"]["transcript"]["segments"][0]
    assert segment["confidence"] == 0.2
    assert segment["warning_codes"] == ["low_confidence"]
    assert profile["record"]["transcript"]["uncertainty_preserved"] is True


def test_special_tokens_preserve_the_v1_raw_word_ordinal(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = AudioProfileManager(instance.store, asr_adapter=SpecialTokenAdapter())
    selected = manager.create(version_id)
    profile = manager.get(str(selected["representation_id"]))
    assert profile is not None
    word = profile["record"]["transcript"]["segments"][0]["words"][0]
    expected = (
        "aword_"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "segment": 0,
                    "word": 1,
                    "start_ms": 0,
                    "end_ms": 80,
                    "text": "ciao",
                }
            )
        ).hexdigest()
    )
    assert word["id"] == expected
    assert validate_audio_record(profile["record"])["version_id"] == version_id


def test_audio_api_and_browser_are_read_only_by_default(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    client = TestClient(create_app(instance.root))
    support = client.get("/api/v1/audio/support")
    assert support.status_code == 200
    assert support.json()["network_used"] is False
    assert client.get("/audio").status_code == 200
    assert client.post(f"/api/v1/audio/jobs/{version_id}").status_code == 404
    assert client.delete("/api/v1/audio/repr_missing").status_code == 405
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/audio/jobs/{version_id}" not in paths
    assert set(paths["/api/v1/audio/{representation_id}"]) == {"get"}


def test_browser_renders_an_existing_flat_audio_record(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = AudioProfileManager(instance.store, asr_adapter=FakeAdapter())
    job_id = str(manager.queue(version_id)["job"]["id"])
    assert manager.run(job_id)["status"] == "succeeded"
    response = TestClient(create_app(instance.root)).get("/audio")
    assert response.status_code == 200
    assert "WAV/pcm" in response.text


def test_run_rejects_asr_identity_drift(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = AudioProfileManager(instance.store, asr_adapter=FakeAdapter())
    job_id = str(manager.queue(version_id)["job"]["id"])
    manager.asr_adapter.capability = lambda: {**FakeAdapter.capability(), "version": "changed"}
    failed = manager.run(job_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "audio_asr_unavailable"


def test_backup_transfer_and_support_registry_preserve_audio_profile(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    manager = AudioProfileManager(instance.store, asr_adapter=FakeAdapter())
    selected_id = str(manager.create(version_id)["representation_id"])
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    backup = create_backup(instance.store, destination=tmp_path / "backups", reason="audio")
    assert verify_backup(backup["archive"])["status"] == "valid"
    restored_root = tmp_path / "restored"
    extract_backup(backup["archive"], restored_root)
    assert (
        AudioProfileManager(InstanceStore(restored_root), asr_adapter=FakeAdapter()).get(
            selected_id
        )
        is not None
    )

    portable = tmp_path / "portable.zip"
    instance.export_portable(portable)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(portable)
    assert target.get_audio(selected_id) is not None

    support = instance.representation_support(profile_id="perceptio-audio-v1")
    records = {item["operation"]: item for item in support["records"]}
    assert records["inspect"]["effective_state"] == "available"
    assert records["extract"]["declared_state"] == "optional"
    assert records["extract"]["missing_component"] == "asr.whisper-cpp"
    assert records["ai_enrich"]["reason"] == "not_implemented"
