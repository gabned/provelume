"""Closed effective Capture input matrix; Original storage is never execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from pypdf import PdfReader

from .capture_requests import CaptureRequestError
from .extractors import MAX_EXTRACTED_CHARS, ExtractionError, ExtractionResult, PdfTextExtractor

MAX_TEXT_BYTES = 512 * 1024
MAX_URL_BYTES = 8192
MAX_PDF_BYTES = 25 * 1024 * 1024
SUPPORTED_MODES = ("text", "url", "pdf", "file")


@dataclass(frozen=True)
class CapturePayload:
    filename: str
    media_type: str
    text: str | None


def capture_capabilities() -> dict:
    return {
        "schema_version": 1,
        "channel": "local_browser",
        "paired_transport": "unavailable",
        "maximum_items": 1,
        "modes": {
            "text": {"maximum_bytes": MAX_TEXT_BYTES, "types": ["text/plain"]},
            "url": {"maximum_bytes": MAX_URL_BYTES, "types": ["text/uri-list"], "fetch": False},
            "pdf": {"maximum_bytes": MAX_PDF_BYTES, "types": ["application/pdf"]},
            "file": {
                "types": ["text/plain", "text/markdown", "application/pdf"],
                "extensions": [".txt", ".md", ".pdf"],
                "maximum_text_bytes": MAX_TEXT_BYTES,
                "maximum_pdf_bytes": MAX_PDF_BYTES,
            },
        },
        "unavailable_modes": ["photo", "scan", "screenshot", "audio", "voice_note"],
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
        "filename", {"pdf": "capture.pdf", "url": "capture.txt"}.get(mode, "capture.txt")
    )
    suffix = PurePosixPath(filename).suffix.lower()
    if mode == "file" and suffix not in {".txt", ".md", ".pdf"}:
        raise CaptureRequestError("Capture file type is not currently supported")
    pdf = mode == "pdf" or (mode == "file" and suffix == ".pdf")
    if pdf:
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
    try:
        return PdfTextExtractor().extract(payload)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("Capture PDF text extraction unavailable") from exc
