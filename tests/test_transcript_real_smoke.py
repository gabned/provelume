from __future__ import annotations

import os
import platform
import socket
import struct
from pathlib import Path

import pytest

from provelume.service import ProvelumeInstance
from provelume.transcript_contract import (
    TRANSCRIPT_PARSER_ID,
    TRANSCRIPT_PARSER_VERSION,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("PROVELUME_TRANSCRIPT_CONFORMANCE_SMOKE") != "1",
    reason="local transcript conformance smoke is opt-in",
)

SRT = (
    b"\xef\xbb\xbf1\r\n00:00:00,000 --> 00:00:01,000\r\n"
    b"synthetic-srt-smoke <script>inert</script>\r\n"
)
VTT = (
    b"WEBVTT\n\nsmoke-cue\n00:00.000 --> 00:01.000\n"
    b"<v Synthetic Label>synthetic-webvtt-smoke https://remote.invalid\n"
)


def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("local transcript smoke attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "gethostbyname", forbidden)


@pytest.mark.parametrize(
    ("profile", "suffix", "data", "token"),
    [
        ("srt-v1", ".srt", SRT, "synthetic-srt-smoke"),
        ("webvtt-v1", ".vtt", VTT, "synthetic-webvtt-smoke"),
    ],
)
def test_permanent_exact_byte_profile_smoke_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    suffix: str,
    data: bytes,
    token: str,
) -> None:
    assert platform.python_implementation() == "CPython"
    assert platform.python_version_tuple()[:2] == ("3", "12")
    assert struct.calcsize("P") * 8 == 64
    source_file = tmp_path / f"synthetic{suffix}"
    source_file.write_bytes(data)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    capability = instance.transcript_capability()
    selected = next(item for item in capability["profiles"] if item["id"] == profile)
    assert selected["parser"]["id"] == TRANSCRIPT_PARSER_ID
    assert selected["parser"]["version"] == TRANSCRIPT_PARSER_VERSION
    assert selected["conformance"] == "deterministic-synthetic"
    assert capability["network_access"] == "none"

    source = instance.create_transcript_source(
        name="Synthetic conformance Source",
        path=source_file,
        profile=profile,
        selection_kind="file",
    )
    assert source["state"] == "disabled"
    instance.set_transcript_source_state(str(source["id"]), "enabled")
    _deny_network(monkeypatch)
    queued = instance.queue_transcript_intake(str(source["id"]))
    result = instance.run_transcript_job(str(queued["job"]["id"]))
    assert result is not None and result["status"] == "succeeded"
    assert result["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    revision = instance.list_transcript_revisions()[0]
    assert instance.get_transcript_original(str(revision["id"]))[1] == data
    detail = instance.get_transcript_revision(str(revision["id"]), include_content=True)
    assert detail is not None and token in detail["text"]
    assert detail["manifest"]["network_used"] is False
    assert detail["manifest"]["active_content_executed"] is False
    assert instance.validate_instance(deep=True)["status"] == "valid"
