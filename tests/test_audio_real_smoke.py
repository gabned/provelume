from __future__ import annotations

import io
import math
import os
import struct
import wave
from pathlib import Path

import pytest

from provelume.audio_profiles import AudioProfileManager, WhisperCppAdapter
from provelume.service import ProvelumeInstance


def _speechless_wav(seconds: float = 10.0, rate: int = 16_000) -> bytes:
    frames = int(seconds * rate)
    payload = io.BytesIO()
    with wave.open(payload, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = [int(400 * math.sin(2 * math.pi * 220 * index / rate)) for index in range(frames)]
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return payload.getvalue()


@pytest.mark.skipif(
    os.environ.get("PROVELUME_REAL_AUDIO") != "1",
    reason="real whisper.cpp qualification is opt-in",
)
def test_exact_whisper_cpp_and_model_run_offline(tmp_path: Path) -> None:
    capability = WhisperCppAdapter().capability()
    assert capability["state"] == "ready"
    assert capability["qualified"] is True
    assert capability["network_used"] is False
    assert capability["runtime_downloads"] is False

    source = tmp_path / "source"
    source.mkdir()
    (source / "bounded.wav").write_bytes(_speechless_wav())
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    version_id = str(instance.store.list_canonical("documents")[0]["current_version_id"])
    manager = AudioProfileManager(instance.store)
    bundle = manager.create(version_id, language="en", threads=1)
    selected = manager.get(str(bundle["representation_id"]))
    assert selected is not None
    assert selected["record"]["transcript"]["state"] == "available"
    assert selected["record"]["invariants"]["network_used"] is False
    assert selected["record"]["invariants"]["speaker_identity"] is False
