"""Bounded Capture request identity primitives; these do not accept a submission.

The transport adapter must authenticate the device, authorize proposal references,
verify the actual payload type and commit its durable journal before acknowledging.
This module performs no filesystem, network, acquisition or authority operation.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from .ingest import DEFAULT_MAX_FILE_BYTES

CAPTURE_REQUEST_SCHEMA = 1
CAPTURE_MODES = frozenset(
    {"file", "photo", "scan", "screenshot", "pdf", "url", "text", "audio", "voice_note"}
)
CAPTURE_CHANNELS = frozenset({"local_browser", "paired_pwa"})
_REQUIRED = frozenset({"schema_version", "client_submission_id", "captured_at", "mode", "channel"})
_OPTIONAL = frozenset({"note", "area_id", "project_id", "filename", "declared_mime"})
_REFERENCE = re.compile(r"(?:area|project)_[0-9a-f]{32}\Z")
_DEVICE = re.compile(r"dev_[0-9a-f]{32}\Z")
_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*\Z")


class CaptureRequestError(ValueError):
    """A client envelope cannot supply an authenticated or accepted receipt."""


def _text(value: Any, *, limit: int, multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise CaptureRequestError("Capture metadata must use bounded text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise CaptureRequestError("Capture metadata must be valid UTF-8") from exc
    if size > limit or any(
        (ord(char) < 32 and not (multiline and char in "\n\t")) or 127 <= ord(char) < 160
        for char in value
    ):
        raise CaptureRequestError("Capture metadata exceeds its text boundary")
    return value


def validate_capture_metadata(value: Any, *, transport_channel: str) -> dict[str, Any]:
    """Validate declared metadata only; never infer type support or authorization."""
    if not isinstance(value, dict) or not value.keys() >= _REQUIRED:
        raise CaptureRequestError("Capture metadata is incomplete")
    if value.keys() - (_REQUIRED | _OPTIONAL):
        raise CaptureRequestError("Capture metadata contains unsupported fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise CaptureRequestError("Unsupported Capture request schema")
    selected = dict(value)
    identity = _text(value["client_submission_id"], limit=36)
    try:
        parsed = UUID(identity)
    except ValueError as exc:
        raise CaptureRequestError("Capture identity must be a canonical UUID4") from exc
    if parsed.version != 4 or str(parsed) != identity:
        raise CaptureRequestError("Capture identity must be a canonical UUID4")
    captured_at = _text(value["captured_at"], limit=40)
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaptureRequestError("Capture time must include an explicit offset") from exc
    if "T" not in captured_at or captured.tzinfo is None:
        raise CaptureRequestError("Capture time must include an explicit offset")
    if not isinstance(value["mode"], str) or value["mode"] not in CAPTURE_MODES:
        raise CaptureRequestError("Unsupported Capture mode")
    if not isinstance(value["channel"], str) or value["channel"] not in CAPTURE_CHANNELS:
        raise CaptureRequestError("Unsupported Capture channel")
    if transport_channel not in CAPTURE_CHANNELS or value["channel"] != transport_channel:
        raise CaptureRequestError("Capture channel must match its authenticated transport")
    for field in ("area_id", "project_id"):
        if field in value and (
            not isinstance(value[field], str)
            or not _REFERENCE.fullmatch(value[field])
            or not value[field].startswith(field.removesuffix("_id") + "_")
        ):
            raise CaptureRequestError("Invalid Capture proposal reference")
    if "note" in value:
        _text(value["note"], limit=4096, multiline=True)
    if "filename" in value:
        name = _text(value["filename"], limit=255)
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise CaptureRequestError("Capture filename must be a display basename")
    if "declared_mime" in value:
        mime = _text(value["declared_mime"], limit=127)
        if not _MIME.fullmatch(mime):
            raise CaptureRequestError("Invalid declared Capture media type")
    return selected


def capture_scope_key(authenticated_device_id: str, client_submission_id: str) -> str:
    """Scope an occurrence to a server-authenticated device, never a client field."""
    if not isinstance(authenticated_device_id, str) or not _DEVICE.fullmatch(
        authenticated_device_id
    ):
        raise CaptureRequestError("Invalid authenticated Capture device identity")
    if not isinstance(client_submission_id, str):
        raise CaptureRequestError("Invalid Capture occurrence identity")
    try:
        parsed = UUID(client_submission_id)
    except ValueError as exc:
        raise CaptureRequestError("Invalid Capture occurrence identity") from exc
    if parsed.version != 4 or str(parsed) != client_submission_id:
        raise CaptureRequestError("Invalid Capture occurrence identity")
    key = f"{authenticated_device_id}\0{client_submission_id}".encode("ascii")
    return "capture_" + hashlib.sha256(key).hexdigest()


def capture_payload_fingerprint(payload: bytes, metadata: Any, *, transport_channel: str) -> str:
    """Bind exact submitted bytes and declared metadata for later conflict checking.

    A fingerprint is neither a malware scan nor a committed submission receipt.
    Different occurrences of identical content remain separate scope keys.
    """
    if not isinstance(payload, bytes) or len(payload) > DEFAULT_MAX_FILE_BYTES:
        raise CaptureRequestError("Capture payload exceeds its bounded identity input")
    selected = validate_capture_metadata(metadata, transport_channel=transport_channel)
    canonical = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = canonical.encode("utf-8")
    digest = hashlib.sha256()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    digest.update(payload)
    return digest.hexdigest()
