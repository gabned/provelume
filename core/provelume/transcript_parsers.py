from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

from .transcript_contract import (
    TRANSCRIPT_PARSER_ID,
    TRANSCRIPT_PARSER_PROTOCOL_VERSION,
    TRANSCRIPT_PARSER_VERSION,
    TRANSCRIPT_PROFILES,
    ParsedTranscript,
    TranscriptContractError,
    TranscriptCue,
    TranscriptLimits,
    profile_format,
)

_SRT_TIMESTAMP = re.compile(r"([0-9]{2,}):([0-5][0-9]):([0-5][0-9]),([0-9]{3})\Z")
_VTT_TIMESTAMP = re.compile(
    r"(?:(?:([0-9]{2,}):)?([0-5][0-9]):([0-5][0-9])\.([0-9]{3}))\Z"
)
_SRT_TIMING = re.compile(r"(\S+) --> (\S+)\Z")
_VTT_TIMING = re.compile(r"(\S+) --> (\S+)(?: ([^\r\n]+))?\Z")
_VOICE_TAG = re.compile(r"<v[ \t]+([^>]*)>", re.IGNORECASE)
_VOICE_LIKE = re.compile(r"<v(?:[ .\t>])", re.IGNORECASE)


class TranscriptParser(Protocol):
    """Replaceable parser seam; implementations return provider-neutral cue observations."""

    parser_id: str
    parser_version: str
    parser_protocol_version: int
    supported_profiles: tuple[str, ...]

    def parse(
        self,
        data: bytes,
        *,
        profile: str,
        limits: TranscriptLimits | None = None,
        deadline: float | None = None,
    ) -> ParsedTranscript: ...


class BoundedTranscriptParser:
    """Strict, deterministic SRT/WebVTT parser with no active-content surface."""

    parser_id = TRANSCRIPT_PARSER_ID
    parser_version = TRANSCRIPT_PARSER_VERSION
    parser_protocol_version = TRANSCRIPT_PARSER_PROTOCOL_VERSION
    supported_profiles = TRANSCRIPT_PROFILES

    def __init__(self, monotonic: Callable[[], float] = time.monotonic):
        self._monotonic = monotonic

    def _deadline(self, deadline: float) -> None:
        if self._monotonic() > deadline:
            raise TranscriptContractError(
                "transcript_timeout", "transcript parser deadline was exceeded"
            )

    @staticmethod
    def _decode(data: bytes) -> tuple[str, str | None, str, list[str]]:
        bom = None
        payload = data
        warnings: list[str] = []
        if data.startswith(b"\xef\xbb\xbf"):
            bom = "utf-8-bom"
            payload = data[3:]
            warnings.append("utf8_bom_removed")
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise TranscriptContractError(
                "transcript_encoding_unsupported",
                "transcript encoding is not supported; exact bytes were preserved",
            ) from exc
        if "\x00" in text:
            raise TranscriptContractError(
                "transcript_encoding_unsupported",
                "transcript contains an unsupported NUL character",
            )
        has_crlf = "\r\n" in text
        remainder = text.replace("\r\n", "")
        has_cr = "\r" in remainder
        has_lf = "\n" in remainder
        styles = sum((has_crlf, has_cr, has_lf))
        if styles > 1:
            source_line_endings = "mixed"
        elif has_crlf:
            source_line_endings = "crlf"
        elif has_cr:
            source_line_endings = "cr"
        elif has_lf:
            source_line_endings = "lf"
        else:
            source_line_endings = "none"
        if has_crlf or has_cr:
            warnings.append("line_endings_normalised")
        return text.replace("\r\n", "\n").replace("\r", "\n"), bom, source_line_endings, warnings

    @staticmethod
    def _blocks(lines: Sequence[str]) -> list[list[str]]:
        result: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            if line == "":
                if current:
                    result.append(current)
                    current = []
            else:
                current.append(line)
        if current:
            result.append(current)
        return result

    @staticmethod
    def _milliseconds(match: re.Match[str]) -> int:
        hours, minutes, seconds, milliseconds = match.groups()
        return (
            ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000
            + int(milliseconds)
        )

    def _timestamp(self, value: str, *, profile: str) -> int:
        match = (_SRT_TIMESTAMP if profile == "srt-v1" else _VTT_TIMESTAMP).fullmatch(value)
        if match is None:
            raise TranscriptContractError(
                "transcript_timestamp_invalid", "transcript cue timestamp is invalid"
            )
        return self._milliseconds(match)

    def _timing(self, value: str, *, profile: str) -> tuple[int, int, str | None]:
        match = (_SRT_TIMING if profile == "srt-v1" else _VTT_TIMING).fullmatch(value)
        if match is None:
            raise TranscriptContractError(
                "transcript_cue_malformed", "transcript cue timing line is malformed"
            )
        start_text, end_text, *settings = match.groups()
        return (
            self._timestamp(start_text, profile=profile),
            self._timestamp(end_text, profile=profile),
            settings[0] if settings else None,
        )

    @staticmethod
    def _speaker(text: str) -> tuple[str | None, bool]:
        matches = _VOICE_TAG.findall(text)
        voice_like = _VOICE_LIKE.findall(text)
        if not voice_like:
            return None, False
        if (
            len(matches) != 1
            or len(voice_like) != 1
            or _VOICE_TAG.match(text) is None
        ):
            return None, True
        selected = " ".join(matches[0].strip().split())
        if (
            not selected
            or len(selected) > 200
            or any(ord(char) < 32 for char in selected)
            or any(char in "<>" for char in selected)
        ):
            return None, True
        return selected, False

    def _srt_cues(
        self,
        lines: Sequence[str],
        *,
        limits: TranscriptLimits,
        deadline: float,
    ) -> list[TranscriptCue]:
        blocks = self._blocks(lines)
        cues: list[TranscriptCue] = []
        for block in blocks:
            self._deadline(deadline)
            if len(block) < 3 or re.fullmatch(r"[0-9]+", block[0]) is None:
                raise TranscriptContractError(
                    "transcript_cue_malformed", "SRT cue structure is malformed"
                )
            start, end, settings = self._timing(block[1], profile="srt-v1")
            if settings is not None:
                raise TranscriptContractError(
                    "transcript_cue_malformed", "SRT cue settings are unsupported"
                )
            text = "\n".join(block[2:])
            cues.append(
                TranscriptCue(
                    ordinal=len(cues) + 1,
                    identifier=block[0],
                    start_ms=start,
                    end_ms=end,
                    text=text,
                )
            )
            if len(cues) > limits.max_cues_per_file:
                raise TranscriptContractError(
                    "transcript_cue_limit_exceeded", "transcript cue limit was exceeded"
                )
        return cues

    def _webvtt_cues(
        self,
        lines: Sequence[str],
        *,
        limits: TranscriptLimits,
        deadline: float,
        warnings: list[str],
    ) -> list[TranscriptCue]:
        if (
            not lines
            or not (lines[0] == "WEBVTT" or lines[0].startswith(("WEBVTT ", "WEBVTT\t")))
            or "-->" in lines[0]
        ):
            raise TranscriptContractError(
                "transcript_cue_malformed", "WebVTT signature is missing"
            )
        try:
            body_start = lines.index("") + 1
        except ValueError as exc:
            raise TranscriptContractError(
                "transcript_cue_malformed", "WebVTT header is not terminated"
            ) from exc
        blocks = self._blocks(lines[body_start:])
        cues: list[TranscriptCue] = []
        for block in blocks:
            self._deadline(deadline)
            head = block[0]
            if head == "NOTE" or head.startswith(("NOTE ", "NOTE\t")):
                warnings.append("webvtt_note_ignored")
                continue
            if head in {"STYLE", "REGION"} or head.startswith(("STYLE ", "REGION ")):
                raise TranscriptContractError(
                    "transcript_active_block_unsupported",
                    "WebVTT STYLE and REGION blocks are not interpreted",
                )
            if " --> " in head:
                identifier = None
                timing_index = 0
            elif len(block) >= 2 and " --> " in block[1]:
                identifier = head
                timing_index = 1
            else:
                raise TranscriptContractError(
                    "transcript_cue_malformed", "WebVTT cue structure is malformed"
                )
            if len(block) <= timing_index + 1:
                raise TranscriptContractError(
                    "transcript_cue_malformed", "WebVTT cue text is missing"
                )
            start, end, settings = self._timing(block[timing_index], profile="webvtt-v1")
            text = "\n".join(block[timing_index + 1 :])
            speaker, ambiguous = self._speaker(text)
            cue_warnings = ("speaker_label_ambiguous",) if ambiguous else ()
            cues.append(
                TranscriptCue(
                    ordinal=len(cues) + 1,
                    identifier=identifier,
                    start_ms=start,
                    end_ms=end,
                    text=text,
                    speaker_label=speaker,
                    settings=settings,
                    warning_codes=cue_warnings,
                )
            )
            if len(cues) > limits.max_cues_per_file:
                raise TranscriptContractError(
                    "transcript_cue_limit_exceeded", "transcript cue limit was exceeded"
                )
        return cues

    @staticmethod
    def _append_warning(values: list[str], code: str, limits: TranscriptLimits) -> None:
        values.append(code)
        if len(values) > limits.max_warnings_per_file:
            raise TranscriptContractError(
                "transcript_cue_limit_exceeded", "transcript warning limit was exceeded"
            )

    def _validate_cues(
        self,
        cues: Sequence[TranscriptCue],
        *,
        limits: TranscriptLimits,
        warnings: list[str],
    ) -> tuple[TranscriptCue, ...]:
        identifiers: set[str] = set()
        signatures: set[tuple[int, int, str]] = set()
        result: list[TranscriptCue] = []
        prior_starts: list[int] = []
        prior_intervals: list[tuple[int, int]] = []
        any_speaker = False
        for cue in cues:
            cue_warnings = list(cue.warning_codes)
            if cue.end_ms <= cue.start_ms:
                raise TranscriptContractError(
                    "transcript_timestamp_invalid", "transcript cue interval is invalid"
                )
            if cue.end_ms - cue.start_ms > limits.max_cue_duration_ms:
                raise TranscriptContractError(
                    "transcript_duration_limit_exceeded",
                    "transcript cue duration limit was exceeded",
                )
            if cue.end_ms > limits.max_timeline_ms:
                raise TranscriptContractError(
                    "transcript_duration_limit_exceeded", "transcript timeline limit was exceeded"
                )
            if len(cue.text) > limits.max_cue_characters:
                raise TranscriptContractError(
                    "transcript_text_limit_exceeded", "transcript cue text limit was exceeded"
                )
            if cue.identifier is not None:
                if cue.identifier in identifiers:
                    cue_warnings.append("cue_identifier_duplicate")
                identifiers.add(cue.identifier)
            signature = (cue.start_ms, cue.end_ms, hashlib.sha256(cue.text.encode()).hexdigest())
            if signature in signatures:
                cue_warnings.append("cue_duplicate")
            signatures.add(signature)
            if prior_starts and cue.start_ms < max(prior_starts):
                cue_warnings.append("cue_out_of_order")
            if any(
                cue.start_ms < prior_end and cue.end_ms > prior_start
                for prior_start, prior_end in prior_intervals
            ):
                cue_warnings.append("cue_overlap")
            if cue.speaker_label is not None:
                any_speaker = True
            for code in cue_warnings:
                self._append_warning(warnings, code, limits)
            result.append(replace(cue, warning_codes=tuple(sorted(set(cue_warnings)))))
            prior_starts.append(cue.start_ms)
            prior_intervals.append((cue.start_ms, cue.end_ms))
        if not any_speaker:
            self._append_warning(warnings, "speaker_label_absent", limits)
        return tuple(result)

    def parse(
        self,
        data: bytes,
        *,
        profile: str,
        limits: TranscriptLimits | None = None,
        deadline: float | None = None,
    ) -> ParsedTranscript:
        selected = limits or TranscriptLimits()
        if len(data) > selected.max_file_bytes:
            raise TranscriptContractError(
                "transcript_file_limit_exceeded", "transcript file limit was exceeded"
            )
        selected_deadline = (
            self._monotonic() + selected.max_seconds_per_file if deadline is None else deadline
        )
        format_name = profile_format(profile)
        text, bom, line_endings, warnings = self._decode(data)
        lines = text.split("\n")
        if any(len(line) > selected.max_line_characters for line in lines):
            raise TranscriptContractError(
                "transcript_line_limit_exceeded", "transcript line limit was exceeded"
            )
        if len(text) > selected.max_text_characters_per_file:
            raise TranscriptContractError(
                "transcript_text_limit_exceeded", "transcript text limit was exceeded"
            )
        self._deadline(selected_deadline)
        if profile == "srt-v1":
            cues = self._srt_cues(lines, limits=selected, deadline=selected_deadline)
        elif profile == "webvtt-v1":
            cues = self._webvtt_cues(
                lines,
                limits=selected,
                deadline=selected_deadline,
                warnings=warnings,
            )
        else:  # profile_format already rejects this; retained as a fail-closed guard.
            raise TranscriptContractError(
                "transcript_profile_unsupported", "transcript profile is unsupported"
            )
        if not cues:
            raise TranscriptContractError(
                "transcript_cue_malformed", "transcript contains no supported cues"
            )
        validated = self._validate_cues(cues, limits=selected, warnings=warnings)
        self._deadline(selected_deadline)
        return ParsedTranscript(
            profile=profile,
            format=format_name,
            original_sha256=hashlib.sha256(data).hexdigest(),
            original_size_bytes=len(data),
            encoding="utf-8",
            bom=bom,
            source_line_endings=line_endings,
            cues=validated,
            warning_codes=tuple(sorted(set(warnings))),
            text_character_count=sum(len(cue.text) for cue in validated),
        )


__all__ = ["BoundedTranscriptParser", "TranscriptParser"]
