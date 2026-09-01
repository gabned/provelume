from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from provelume.service import ProvelumeInstance
from provelume.transcript_contract import TranscriptContractError, TranscriptLimits
from provelume.transcript_files import LocalTranscriptAdapter


def _srt(path: Path, text: str = "synthetic") -> bytes:
    data = f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def test_source_is_a_separate_disabled_connector_instance_without_hidden_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "selected" / "one.srt"
    before = _srt(selected)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("transcript Source configuration attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    created = instance.create_transcript_source(
        name="Private meeting title",
        path=selected,
        profile="srt-v1",
        selection_kind="file",
    )
    assert created["state"] == "disabled"
    assert created["path"] == str(selected)
    assert selected.read_bytes() == before
    assert instance.list_transcript_jobs() == []

    public = instance.get_transcript_source(created["id"], local=False)
    assert public is not None
    encoded = json.dumps(public, sort_keys=True)
    assert "Private meeting title" not in encoded
    assert str(tmp_path) not in encoded
    connector = instance.get_connector_instance(created["connector_instance_id"])
    assert connector is not None
    assert connector["configured_enabled"] is False
    assert connector["network_mode"] == "disabled"
    assert connector["allowed_origins"] == []
    assert connector["definition"]["network_access"] == "none"
    assert len(connector["sources"]) == 1
    assert connector["sources"][0]["id"] == created["id"]
    assert connector["sources"][0]["configured_enabled"] is False
    network = instance.network_status()
    component = next(
        item
        for item in network["components"]
        if item["id"] == f"connector.{created['connector_instance_id']}"
    )
    assert component["network_capability"] == "local_only"
    assert component["declared_network_access"] == "none"
    assert component["enabled"] is False
    assert connector["definition"]["capabilities"] == [
        "manual_read",
        "scheduled_read",
        "source_selection",
        "transcript_read",
    ]


def test_state_schedule_reconfigure_resync_and_tombstone_are_explicit(tmp_path: Path) -> None:
    first = tmp_path / "one.srt"
    second = tmp_path / "two.vtt"
    _srt(first)
    second.write_bytes(b"WEBVTT\n\n00:00.000 --> 00:01.000\nsynthetic\n")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_transcript_source(
        name="One", path=first, profile="srt-v1", selection_kind="file"
    )
    source_id = str(source["id"])
    assert instance.set_transcript_source_state(source_id, "enabled")["state"] == "enabled"
    with pytest.raises(TranscriptContractError) as active:
        instance.reconfigure_transcript_source(
            source_id, path=second, profile="webvtt-v1", selection_kind="file"
        )
    assert active.value.code == "transcript_disabled"
    instance.set_transcript_source_state(source_id, "disabled")
    configured = instance.reconfigure_transcript_source(
        source_id, path=second, profile="webvtt-v1", selection_kind="file"
    )
    assert configured["config_revision"] == 2
    assert configured["path"] == str(second)
    assert instance.transcript_source_checkpoint(source_id)["resync_required"] is True
    scheduled = instance.configure_transcript_source_schedule(
        source_id, mode="interval", interval_seconds=300
    )
    assert scheduled["schedule"]["interval_seconds"] == 300
    removed = instance.remove_transcript_source(source_id)
    assert removed["state"] == "disabled"
    assert removed["lifecycle_state"] == "removed"
    connector = instance.get_connector_instance(str(removed["connector_instance_id"]))
    assert connector is not None and connector["lifecycle_state"] == "removed"


def test_profile_mismatch_missing_path_symlink_and_folder_entries_fail_visibly(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    wrong = tmp_path / "wrong.vtt"
    wrong.write_bytes(b"WEBVTT\n")
    with pytest.raises(TranscriptContractError) as mismatch:
        instance.create_transcript_source(
            name="Wrong", path=wrong, profile="srt-v1", selection_kind="file"
        )
    assert mismatch.value.code == "transcript_profile_mismatch"
    with pytest.raises(TranscriptContractError) as missing:
        instance.create_transcript_source(
            name="Missing",
            path=tmp_path / "missing.srt",
            profile="srt-v1",
            selection_kind="file",
        )
    assert missing.value.code == "transcript_source_missing"
    with pytest.raises(TranscriptContractError) as network_path:
        instance.create_transcript_source(
            name="Network selector",
            path="//server.invalid/share/private.srt",
            profile="srt-v1",
            selection_kind="file",
        )
    assert network_path.value.code == "transcript_source_unsafe"
    if hasattr(os, "symlink"):
        target = tmp_path / "target.srt"
        _srt(target)
        link = tmp_path / "link.srt"
        try:
            link.symlink_to(target)
        except OSError:
            pass
        else:
            with pytest.raises(TranscriptContractError) as linked:
                instance.create_transcript_source(
                    name="Link", path=link, profile="srt-v1", selection_kind="file"
                )
            assert linked.value.code == "transcript_source_unsafe"
    if hasattr(os, "link"):
        target = tmp_path / "hard-target.srt"
        _srt(target)
        hard_link = tmp_path / "hard-link.srt"
        try:
            os.link(target, hard_link)
        except OSError:
            pass
        else:
            with pytest.raises(TranscriptContractError) as linked_twice:
                instance.create_transcript_source(
                    name="Hard link",
                    path=hard_link,
                    profile="srt-v1",
                    selection_kind="file",
                )
            assert linked_twice.value.code == "transcript_source_unsafe"

    folder = tmp_path / "folder"
    _srt(folder / "valid.srt")
    (folder / "nested").mkdir()
    source = instance.create_transcript_source(
        name="Folder", path=folder, profile="srt-v1", selection_kind="folder"
    )
    instance.set_transcript_source_state(str(source["id"]), "enabled")
    with pytest.raises(TranscriptContractError) as non_regular:
        instance.queue_transcript_intake(str(source["id"]))
    assert non_regular.value.code == "transcript_input_non_regular"


def test_folder_enumeration_and_file_count_are_closed_and_non_recursive(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    _srt(folder / "one.srt")
    _srt(folder / "two.srt")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_transcript_source(
        name="Folder", path=folder, profile="srt-v1", selection_kind="folder"
    )
    instance.set_transcript_source_state(str(source["id"]), "enabled")
    queued = instance.queue_transcript_intake(str(source["id"]))
    assert queued["request"]["file_count"] == 2
    assert queued["request"]["selection_kind"] == "folder"
    request_path = instance.transcripts.requests / f"{queued['job']['id']}.json"
    request_text = request_path.read_text(encoding="utf-8")
    assert "one.srt" not in request_text
    assert "two.srt" not in request_text
    assert str(tmp_path) not in request_text


def test_enumeration_file_size_count_and_total_read_limits_fail_closed(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "bounded"
    _srt(folder / "one.srt", "a")
    _srt(folder / "two.srt", "b")
    _srt(folder / "three.srt", "c")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = instance.create_transcript_source(
        name="Bounded", path=folder, profile="srt-v1", selection_kind="folder"
    )
    instance.set_transcript_source_state(str(source["id"]), "enabled")
    config = instance.transcript_sources.source_config(
        str(source["id"]), require_enabled=True
    )
    adapter = LocalTranscriptAdapter(config)

    with pytest.raises(TranscriptContractError) as enumerated:
        adapter.snapshot(
            limits=TranscriptLimits(
                max_files_per_job=2,
                max_enumerated_entries=2,
            )
        )
    assert enumerated.value.code == "transcript_enumeration_limit_exceeded"

    with pytest.raises(TranscriptContractError) as file_count:
        adapter.snapshot(
            limits=TranscriptLimits(
                max_files_per_job=1,
                max_enumerated_entries=10,
            )
        )
    assert file_count.value.code == "transcript_enumeration_limit_exceeded"

    single = tmp_path / "large.srt"
    single.write_bytes(b"x" * 9)
    single_source = instance.create_transcript_source(
        name="Size", path=single, profile="srt-v1", selection_kind="file"
    )
    instance.set_transcript_source_state(str(single_source["id"]), "enabled")
    single_config = instance.transcript_sources.source_config(
        str(single_source["id"]), require_enabled=True
    )
    with pytest.raises(TranscriptContractError) as file_size:
        LocalTranscriptAdapter(single_config).snapshot(
            limits=TranscriptLimits(
                max_file_bytes=8,
                max_total_read_bytes=8,
                max_temp_bytes_per_job=8,
            )
        )
    assert file_size.value.code == "transcript_file_limit_exceeded"

    total_folder = tmp_path / "total"
    (total_folder / "one.srt").parent.mkdir()
    (total_folder / "one.srt").write_bytes(b"x" * 6)
    (total_folder / "two.srt").write_bytes(b"y" * 6)
    total_source = instance.create_transcript_source(
        name="Total", path=total_folder, profile="srt-v1", selection_kind="folder"
    )
    instance.set_transcript_source_state(str(total_source["id"]), "enabled")
    total_config = instance.transcript_sources.source_config(
        str(total_source["id"]), require_enabled=True
    )
    with pytest.raises(TranscriptContractError) as total_read:
        LocalTranscriptAdapter(total_config).snapshot(
            limits=TranscriptLimits(
                max_file_bytes=8,
                max_total_read_bytes=8,
                max_temp_bytes_per_job=8,
            )
        )
    assert total_read.value.code == "transcript_total_read_limit_exceeded"
