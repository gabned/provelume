"""Closed effective Capture input matrix; Original storage is never execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from pypdf import PdfReader

from .audio_profiles import AudioContractError, inspect_audio_bytes
from .capture_requests import CaptureRequestError
from .extractors import MAX_EXTRACTED_CHARS, ExtractionError, ExtractionResult, PdfTextExtractor
from .photo_profiles import PhotoContractError, PillowPhotoDecoder, inspect_photo_bytes

MAX_TEXT_BYTES = 512 * 1024
MAX_URL_BYTES = 8192
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PHOTO_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024
SUPPORTED_MODES = (
    "text",
    "url",
    "pdf",
    "file",
    "photo",
    "scan",
    "screenshot",
    "audio",
    "voice_note",
)


@dataclass(frozen=True)
class CapturePayload:
    filename: str
    media_type: str
    text: str | None


def capture_capabilities() -> dict:
    return {
        "schema_version": 1,
        "channel": "local_browser",
        "paired_transport": "explicit_https_configuration_required",
        "maximum_items": 1,
        "modes": {
            "text": {"maximum_bytes": MAX_TEXT_BYTES, "types": ["text/plain"]},
            "url": {"maximum_bytes": MAX_URL_BYTES, "types": ["text/uri-list"], "fetch": False},
            "pdf": {"maximum_bytes": MAX_PDF_BYTES, "types": ["application/pdf"]},
            "file": {
                "types": [
                    "text/plain",
                    "text/markdown",
                    "application/pdf",
                    "image/png",
                    "image/jpeg",
                    "audio/wav",
                ],
                "extensions": [".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".wav"],
                "maximum_text_bytes": MAX_TEXT_BYTES,
                "maximum_pdf_bytes": MAX_PDF_BYTES,
                "maximum_photo_bytes": MAX_PHOTO_BYTES,
                "maximum_audio_bytes": MAX_AUDIO_BYTES,
            },
            **{
                mode: {
                    "maximum_bytes": MAX_PHOTO_BYTES,
                    "types": ["image/png", "image/jpeg"],
                    "maximum_pixels": 20_000_000,
                    "maximum_expansion_ratio": 100,
                }
                for mode in ("photo", "scan", "screenshot")
            },
            **{
                mode: {
                    "maximum_bytes": MAX_AUDIO_BYTES,
                    "types": ["audio/wav"],
                    "maximum_duration_seconds": 120,
                    "codec": "PCM16",
                    "maximum_channels": 2,
                }
                for mode in ("audio", "voice_note")
            },
        },
        "unavailable_modes": []
        if PillowPhotoDecoder().capability()["state"] == "ready"
        else ["photo", "scan", "screenshot"],
        "processing": {
            "photo": "Original only; OCR separate",
            "audio": "Original only; transcription separate",
        },
        "handling": (
            "Untrusted Original bytes; explicit attachment download only; no antivirus claim."
        ),
    }


def validate_capture_payload(payload: bytes, metadata: dict) -> CapturePayload:
    if not isinstance(payload, bytes) or not payload:
        raise CaptureRequestError("Capture requires nonempty bytes")
    mode = metadata["mode"]
    if mode not in SUPPORTED_MODES:
        raise CaptureRequestError("Capture mode is not currently supported")
    filename = metadata.get(
        "filename",
        {
            "pdf": "capture.pdf",
            "url": "capture.txt",
            "photo": "capture.png",
            "scan": "capture.png",
            "screenshot": "capture.png",
            "audio": "capture.wav",
            "voice_note": "capture.wav",
        }.get(mode, "capture.txt"),
    )
    suffix = PurePosixPath(filename).suffix.lower()
    if mode == "file" and suffix not in {".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".wav"}:
        raise CaptureRequestError("Capture file type is not currently supported")
    pdf = mode == "pdf" or (mode == "file" and suffix == ".pdf")
    photo = mode in {"photo", "scan", "screenshot"} or (
        mode == "file" and suffix in {".png", ".jpg", ".jpeg"}
    )
    audio = mode in {"audio", "voice_note"} or (mode == "file" and suffix == ".wav")
    if photo:
        try:
            if len(payload) > MAX_PHOTO_BYTES or suffix not in {".png", ".jpg", ".jpeg"}:
                raise ValueError()
            inspected = inspect_photo_bytes(payload)
            if inspected["dimensions"]["pixels"] > 20_000_000 or inspected["format"] != (
                "PNG" if suffix == ".png" else "JPEG"
            ):
                raise ValueError()
            # Use the already-qualified decoder, never trust only a magic prefix.
            PillowPhotoDecoder().decode(payload, inspected["format"])
            result = CapturePayload(filename, inspected["media_type"], None)
        except (PhotoContractError, ValueError) as exc:
            raise CaptureRequestError(
                "Capture photo is malformed, oversized or unsupported"
            ) from exc
    elif audio:
        try:
            if len(payload) > MAX_AUDIO_BYTES or suffix != ".wav":
                raise ValueError()
            inspected = inspect_audio_bytes(payload)
            if (
                inspected["container"] != "wav"
                or inspected["decode_state"] != "qualified"
                or inspected["duration_ms"] > 120_000
            ):
                raise ValueError()
            result = CapturePayload(filename, "audio/wav", None)
        except (AudioContractError, ValueError) as exc:
            raise CaptureRequestError("Capture audio requires bounded valid PCM16 WAV") from exc
    elif pdf:
        if (
            suffix != ".pdf"
            or len(payload) > MAX_PDF_BYTES
            or not re.match(rb"%PDF-[12]\.[0-9]", payload)
            or b"%%EOF" not in payload[-1024:]
        ):
            raise CaptureRequestError("Invalid or oversized Capture PDF")
        try:
            reader = PdfReader(BytesIO(payload), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 500:
                raise ValueError()
        except Exception as exc:
            raise CaptureRequestError("Malformed, encrypted or unsupported Capture PDF") from exc
        result = CapturePayload(filename, "application/pdf", None)
    else:
        maximum = MAX_URL_BYTES if mode == "url" else MAX_TEXT_BYTES
        if len(payload) > maximum or suffix not in {".txt", ".md"}:
            raise CaptureRequestError("Invalid Capture text name or byte limit")
        try:
            text = payload.decode("utf-8")
        except UnicodeError as exc:
            raise CaptureRequestError("Capture text must be UTF-8") from exc
        if len(text) > MAX_EXTRACTED_CHARS or any(
            (ord(c) < 32 and c not in "\n\r\t") or 127 <= ord(c) < 160 for c in text
        ):
            raise CaptureRequestError("Capture text exceeds its content boundary")
        if mode == "url":
            try:
                url = urlsplit(text)
                if (
                    url.scheme not in {"http", "https"}
                    or not url.hostname
                    or url.username is not None
                    or url.password is not None
                    or any(c.isspace() for c in text)
                    or "\\" in text
                ):
                    raise ValueError()
                _ = url.port
            except ValueError as exc:
                raise CaptureRequestError(
                    "Capture URL must be a single HTTP(S) link without credentials"
                ) from exc
        media = (
            "text/uri-list"
            if mode == "url"
            else "text/markdown"
            if suffix == ".md"
            else "text/plain"
        )
        result = CapturePayload(filename, media, text)
    if metadata.get("declared_mime", result.media_type) != result.media_type:
        raise CaptureRequestError("Declared Capture type does not match submitted bytes/name")
    return result


def extract_capture_payload(payload: bytes, selected: CapturePayload) -> ExtractionResult:
    if selected.text is not None:
        return ExtractionResult(selected.text, "provelume.text", "1")
    if selected.media_type != "application/pdf":
        raise ExtractionError(
            "Original preserved; OCR/transcription requires separate explicit work"
        )
    try:
        return PdfTextExtractor().extract(payload)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("Capture PDF text extraction unavailable") from exc
