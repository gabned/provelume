from __future__ import annotations

import os
from pathlib import Path

import pytest

from provelume.service import ProvelumeInstance
from provelume.video_profiles import FFmpegAdapter, VideoProfileManager


@pytest.mark.skipif(
    os.environ.get("PROVELUME_REAL_VIDEO") != "1",
    reason="real FFmpeg video qualification is opt-in",
)
def test_exact_ffmpeg_pair_runs_offline_on_real_short_video(tmp_path: Path) -> None:
    fixture_root = Path(os.environ["PROVELUME_REAL_VIDEO_FIXTURE_ROOT"])
    assert fixture_root.is_absolute() and fixture_root.is_dir()
    capability = FFmpegAdapter().capability()
    assert capability["state"] == "ready"
    assert capability["qualified"] is True
    assert capability["network_used"] is False
    assert capability["runtime_downloads"] is False

    source = tmp_path / "source"
    source.mkdir()
    for suffix in ("mp4", "mov", "mkv", "webm", "avi"):
        source_path = fixture_root / f"bounded.{suffix}"
        assert source_path.is_file()
        (source / source_path.name).write_bytes(source_path.read_bytes())
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    manager = VideoProfileManager(instance.store)
    records = {}
    for document in instance.store.list_canonical("documents"):
        version_id = str(document["current_version_id"])
        bundle = manager.create(version_id, timestamps_ms=[500])
        selected = manager.get(str(bundle["representation_id"]))
        assert selected is not None
        records[selected["record"]["format"]] = selected["record"]

    assert set(records) == {"MP4", "MOV", "MKV", "WEBM", "AVI"}
    for format_name in ("MP4", "MOV", "MKV", "WEBM", "AVI"):
        record = records[format_name]
        assert any(
            stream["kind"] == "video" and stream["qualified"]
            for stream in record["streams"]
        )
        assert record["scenes"]
        assert len(record["scenes"]) == len(record["keyframes"])
        assert record["frame_ocr"][0]["timestamp_ms"] == 500
        assert record["invariants"]["network_used"] is False
    assert records["MP4"]["subtitles"][0]["cues"]
    assert records["MOV"]["subtitles"][0]["cues"]
    assert records["MKV"]["subtitles"][0]["cues"]
