from __future__ import annotations

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
    inspect_audio_bytes,
    validate_audio_record,
)
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _wav(*, seconds: float = 0.1, channels: int = 1, rate: int = 16_000) -> bytes:
    frames = int(seconds * rate)
    payload = io.BytesIO()
    with wave.open(payload, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = []
        for frame in range(frames):
            value = int(1_000 * math.sin(2 * math.pi * 440 * frame / rate))
            samples.extend([value] * channels)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return payload.getvalue()


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


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, str]:
    source = tmp_path / "source"
    source.mkdir()
    # Intake remains extension-agnostic here; S04 identifies audio from the exact bytes.
    (source / "voice.txt").write_bytes(_wav())
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


def test_malformed_and_unqualified_audio_fail_closed() -> None:
    with pytest.raises(AudioContractError) as missing:
        inspect_audio_bytes(b"not audio")
    assert missing.value.code == "audio_unsupported_format"
    truncated = _wav()[:-3]
    with pytest.raises(AudioContractError) as invalid:
        inspect_audio_bytes(truncated)
    assert invalid.value.code == "audio_invalid_container"


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
    assert validate_audio_record(profile["record"])["invariants"]["network_used"] is False
    assert instance.store.original_bytes(
        str(instance.store.read_canonical("versions", version_id)["original_id"])
    ) == before


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


def test_audio_api_and_browser_are_read_only_by_default(tmp_path: Path) -> None:
    instance, version_id = _seed(tmp_path)
    client = TestClient(create_app(instance.root))
    support = client.get("/api/v1/audio/support")
    assert support.status_code == 200
    assert support.json()["network_used"] is False
    assert client.get("/audio").status_code == 200
    queued = client.post(f"/api/v1/audio/jobs/{version_id}")
    assert queued.status_code == 202
