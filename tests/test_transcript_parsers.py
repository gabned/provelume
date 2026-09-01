from __future__ import annotations

import hashlib

import pytest

from provelume.transcript_bundle import build_transcript_bundle
from provelume.transcript_contract import (
    TranscriptContractError,
    TranscriptLimits,
)
from provelume.transcript_parsers import BoundedTranscriptParser

SRT = (
    b"1\r\n00:00:00,000 --> 00:00:01,250\r\nHello <script>alert(1)</script>\r\n\r\n"
    b"2\r\n00:00:01,250 --> 00:00:02,000\r\nhttps://example.invalid/x\r\n"
)
VTT = (
    b"WEBVTT\n\ncue-a\n00:00.000 --> 00:01.000 align:start\n"
    b"<v Synthetic Speaker>Hello &lt;b&gt;world&lt;/b&gt;\n\n"
    b"cue-b\n00:01.000 --> 00:02.000\njavascript:alert(1)\n"
)


def test_srt_utf8_crlf_is_strict_bounded_and_exact_bytes_remain_authoritative() -> None:
    parsed = BoundedTranscriptParser().parse(SRT, profile="srt-v1")
    assert parsed.original_sha256 == hashlib.sha256(SRT).hexdigest()
    assert parsed.original_size_bytes == len(SRT)
    assert parsed.encoding == "utf-8"
    assert parsed.source_line_endings == "crlf"
    assert "line_endings_normalised" in parsed.warning_codes
    assert "speaker_label_absent" in parsed.warning_codes
    assert [cue.ordinal for cue in parsed.cues] == [1, 2]
    assert parsed.cues[0].text == "Hello <script>alert(1)</script>"


def test_webvtt_voice_label_is_an_unverified_observation_and_payload_is_inert() -> None:
    parsed = BoundedTranscriptParser().parse(VTT, profile="webvtt-v1")
    assert parsed.cues[0].speaker_label == "Synthetic Speaker"
    assert parsed.cues[0].settings == "align:start"
    assert parsed.cues[1].speaker_label is None
    assert "javascript:alert(1)" in parsed.cues[1].text
    assert parsed.warning_codes == ()


def test_utf8_bom_is_explicitly_derived_and_preserved_in_original_checksum() -> None:
    data = b"\xef\xbb\xbf" + VTT
    parsed = BoundedTranscriptParser().parse(data, profile="webvtt-v1")
    assert parsed.bom == "utf-8-bom"
    assert parsed.original_sha256 == hashlib.sha256(data).hexdigest()
    assert "utf8_bom_removed" in parsed.warning_codes


def test_mixed_crlf_and_lf_are_reported_before_normalisation() -> None:
    data = (
        b"1\r\n00:00:00,000 --> 00:00:01,000\r\nfirst\r\n\r\n"
        b"2\n00:00:01,000 --> 00:00:02,000\nsecond\n"
    )
    parsed = BoundedTranscriptParser().parse(data, profile="srt-v1")
    assert parsed.source_line_endings == "mixed"
    assert "line_endings_normalised" in parsed.warning_codes


@pytest.mark.parametrize("data", [b"\xff\xfe1\x00", b"WEBVTT\n\n\xff", b"1\x00\n"])
def test_unsupported_encoding_or_nul_fails_without_fallback(data: bytes) -> None:
    with pytest.raises(TranscriptContractError) as caught:
        BoundedTranscriptParser().parse(data, profile="srt-v1")
    assert caught.value.code == "transcript_encoding_unsupported"


@pytest.mark.parametrize(
    ("profile", "data", "code"),
    [
        ("srt-v1", b"1\nnot-time\ntext\n", "transcript_cue_malformed"),
        (
            "srt-v1",
            b"1\n00:00:61,000 --> 00:00:02,000\ntext\n",
            "transcript_timestamp_invalid",
        ),
        (
            "srt-v1",
            b"1\n00:00:02,000 --> 00:00:01,000\ntext\n",
            "transcript_timestamp_invalid",
        ),
        (
            "webvtt-v1",
            b"WEBVTT\n\nSTYLE\n::cue { color:red }\n",
            "transcript_active_block_unsupported",
        ),
        ("webvtt-v1", b"WEBVTT\n00:00.000 --> 00:01.000\ntext\n", "transcript_cue_malformed"),
        ("plain-text-v1", b"plain", "transcript_profile_unsupported"),
    ],
)
def test_malformed_ambiguous_or_unsupported_input_fails_visibly(
    profile: str, data: bytes, code: str
) -> None:
    with pytest.raises(TranscriptContractError) as caught:
        BoundedTranscriptParser().parse(data, profile=profile)
    assert caught.value.code == code


def test_duplicate_overlap_out_of_order_and_ambiguous_speaker_are_deterministic() -> None:
    data = (
        b"WEBVTT\n\nid\n00:02.000 --> 00:04.000\n<v A><v B>one\n\n"
        b"id\n00:01.000 --> 00:03.000\n<v A><v B>one\n\n"
        b"other\n00:01.000 --> 00:03.000\n<v A><v B>one\n"
    )
    parsed = BoundedTranscriptParser().parse(data, profile="webvtt-v1")
    warnings = [code for cue in parsed.cues for code in cue.warning_codes]
    assert "speaker_label_ambiguous" in warnings
    assert "cue_identifier_duplicate" in warnings
    assert "cue_out_of_order" in warnings
    assert "cue_overlap" in warnings
    assert "cue_duplicate" in warnings
    assert all(cue.speaker_label is None for cue in parsed.cues)


def test_non_adjacent_overlap_and_voice_class_are_not_silently_promoted() -> None:
    data = (
        b"WEBVTT\n\nfirst\n00:00.000 --> 00:10.000\none\n\n"
        b"second\n00:01.000 --> 00:02.000\ntwo\n\n"
        b"third\n00:03.000 --> 00:04.000\n<v.class Person>three\n"
    )
    parsed = BoundedTranscriptParser().parse(data, profile="webvtt-v1")
    assert "cue_overlap" in parsed.cues[2].warning_codes
    assert "speaker_label_ambiguous" in parsed.cues[2].warning_codes
    assert parsed.cues[2].speaker_label is None


def test_duration_line_cue_text_and_cue_explosion_limits_fail_closed() -> None:
    parser = BoundedTranscriptParser()
    with pytest.raises(TranscriptContractError) as duration:
        parser.parse(
            b"1\n00:00:00,000 --> 00:00:02,000\nx\n",
            profile="srt-v1",
            limits=TranscriptLimits(max_cue_duration_ms=1_000),
        )
    assert duration.value.code == "transcript_duration_limit_exceeded"

    with pytest.raises(TranscriptContractError) as line:
        parser.parse(
            b"1\n00:00:00,000 --> 00:00:01,000\n12345\n",
            profile="srt-v1",
            limits=TranscriptLimits(max_line_characters=4),
        )
    assert line.value.code == "transcript_line_limit_exceeded"

    with pytest.raises(TranscriptContractError) as cues:
        parser.parse(
            b"1\n00:00:00,000 --> 00:00:01,000\na\n\n"
            b"2\n00:00:01,000 --> 00:00:02,000\nb\n",
            profile="srt-v1",
            limits=TranscriptLimits(max_cues_per_file=1),
        )
    assert cues.value.code == "transcript_cue_limit_exceeded"


def test_output_amplification_is_bounded_before_a_bundle_can_be_complete() -> None:
    parsed = BoundedTranscriptParser().parse(SRT, profile="srt-v1")
    with pytest.raises(TranscriptContractError) as caught:
        build_transcript_bundle(
            parsed=parsed,
            limits=TranscriptLimits(max_derived_bytes_per_file=100),
            settings_sha256="0" * 64,
            job_id="job_" + "0" * 32,
            source_id="src_" + "0" * 32,
            connector_instance_id="connector_instance_" + "0" * 32,
            locator_sha256="1" * 64,
            filesystem_identity_sha256="2" * 64,
            filesystem_mtime_ns=1,
            acquisition_id="acq_" + "0" * 32,
            document_id="doc_" + "0" * 32,
            version_id="ver_" + "0" * 32,
            original_id="sha256_" + "3" * 64,
            acquired_at="2026-01-01T00:00:00+00:00",
        )
    assert caught.value.code == "transcript_output_limit_exceeded"


def test_parser_deadline_fails_closed_before_output() -> None:
    with pytest.raises(TranscriptContractError) as caught:
        BoundedTranscriptParser(monotonic=lambda: 2.0).parse(
            SRT,
            profile="srt-v1",
            deadline=1.0,
        )
    assert caught.value.code == "transcript_timeout"


def test_note_is_ignored_with_a_sanitised_warning_not_promoted_to_a_cue() -> None:
    parsed = BoundedTranscriptParser().parse(
        b"WEBVTT\n\nNOTE synthetic metadata\nprivate-looking note\n\n"
        b"00:00.000 --> 00:01.000\ntext\n",
        profile="webvtt-v1",
    )
    assert len(parsed.cues) == 1
    assert "webvtt_note_ignored" in parsed.warning_codes
    assert "private-looking" not in json_for(parsed.warning_codes)


def json_for(value: object) -> str:
    import json

    return json.dumps(value, sort_keys=True)
