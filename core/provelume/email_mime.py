from __future__ import annotations

import base64
import binascii
import hashlib
import quopri
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Any

from .email_contract import (
    EMAIL_CONTRACT_SCHEMA_VERSION,
    EMAIL_PARSER_ID,
    EMAIL_PARSER_PROTOCOL_VERSION,
    EMAIL_PARSER_VERSION,
    BodySelection,
    DecodedAttachment,
    EmailContractError,
    EmailLimits,
    EmailWarning,
    ParsedAddress,
    ParsedAddressGroup,
    ParsedEmail,
    ParsedHeader,
    ParsedPart,
    ensure_unique_warnings,
)

_SUPPORTED_CHARSETS = {
    "ascii": "ascii",
    "cp1252": "cp1252",
    "iso-8859-1": "iso-8859-1",
    "latin-1": "iso-8859-1",
    "us-ascii": "ascii",
    "utf-8": "utf-8",
    "windows-1252": "cp1252",
}
_ADDRESS_HEADERS = {
    "bcc",
    "cc",
    "from",
    "reply-to",
    "resent-bcc",
    "resent-cc",
    "resent-from",
    "resent-sender",
    "resent-to",
    "sender",
    "to",
}
_MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s@]+>\Z", re.ASCII)
_MESSAGE_ID_TOKEN = re.compile(r"<[^<>\s]+>", re.ASCII)
_HEADER_NAME = re.compile(rb"[!-9;-~]+\Z")
_BASE64_ALPHABET = re.compile(rb"[A-Za-z0-9+/]*={0,2}\Z")
_HEX = frozenset(b"0123456789abcdefABCDEF")
_LINE_BREAKS = (b"\r\n", b"\n", b"\r")


@dataclass(frozen=True, slots=True)
class _RawHeader:
    name: str
    occurrence: int
    raw_field: bytes
    raw_value: bytes
    unfolded_value: bytes
    malformed: bool = False


@dataclass(slots=True)
class _ParseState:
    data: bytes
    limits: EmailLimits
    deadline: float
    message_sha256: str
    headers_seen: int = 0
    header_bytes_seen: int = 0
    parts_seen: int = 0
    decoded_bytes: int = 0
    attachment_bytes: int = 0
    warnings: list[EmailWarning] = field(default_factory=list)
    parts: list[ParsedPart] = field(default_factory=list)
    attachments: list[DecodedAttachment] = field(default_factory=list)
    body_candidates: list[tuple[str, str, bytes, str]] = field(default_factory=list)
    html_body_seen: bool = False

    def check_deadline(self) -> None:
        if time.monotonic() > self.deadline:
            raise EmailContractError(
                "email_timeout", "email message parsing deadline was exceeded"
            )

    def warn(
        self,
        code: str,
        *,
        part_id: str | None = None,
        header_name: str | None = None,
        occurrence: int | None = None,
    ) -> None:
        self.warnings.append(
            EmailWarning(
                code=code,
                part_id=part_id,
                header_name=header_name,
                occurrence=occurrence,
            )
        )
        if len(self.warnings) > self.limits.max_warnings_per_message:
            raise EmailContractError(
                "email_mime_limit_exceeded", "email warning limit was exceeded"
            )


def _part_id(message_sha256: str, part_path: str) -> str:
    return "epart_" + hashlib.sha256(
        f"{message_sha256}\0{part_path}".encode("ascii")
    ).hexdigest()


def _split_header_body(data: bytes) -> tuple[bytes, bytes]:
    position = 0
    for line in data.splitlines(keepends=True):
        next_position = position + len(line)
        if line in _LINE_BREAKS:
            return data[:position], data[next_position:]
        position = next_position
    return data, b""


def _line_content(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith((b"\n", b"\r")):
        return line[:-1]
    return line


def _unfold(value: bytes) -> bytes:
    return re.sub(rb"(?:\r\n|\n|\r)[ \t]+", b" ", value).strip(b" \t")


def _raw_headers(
    header_data: bytes,
    *,
    state: _ParseState,
    part_id: str,
) -> tuple[_RawHeader, ...]:
    lines = header_data.splitlines(keepends=True)
    fields: list[tuple[bytes, bool]] = []
    current = bytearray()
    current_malformed = False
    for line in lines:
        state.check_deadline()
        if len(_line_content(line)) > state.limits.max_header_line_bytes:
            raise EmailContractError(
                "email_header_limit_exceeded", "email header line limit was exceeded"
            )
        if line.startswith((b" ", b"\t")):
            if not current:
                current_malformed = True
                current.extend(line)
            else:
                current.extend(line)
            continue
        if current:
            fields.append((bytes(current), current_malformed))
        current = bytearray(line)
        current_malformed = False
    if current:
        fields.append((bytes(current), current_malformed))

    state.headers_seen += len(fields)
    state.header_bytes_seen += len(header_data)
    if state.headers_seen > state.limits.max_headers_per_message:
        raise EmailContractError(
            "email_header_limit_exceeded", "email header count limit was exceeded"
        )
    if state.header_bytes_seen > state.limits.max_header_bytes_per_message:
        raise EmailContractError(
            "email_header_limit_exceeded", "email header byte limit was exceeded"
        )

    occurrences: Counter[str] = Counter()
    result: list[_RawHeader] = []
    for raw_field, inherited_malformed in fields:
        first_line = _line_content(raw_field.splitlines(keepends=True)[0])
        name_bytes, separator, first_value = first_line.partition(b":")
        malformed = (
            inherited_malformed
            or not separator
            or _HEADER_NAME.fullmatch(name_bytes) is None
            or any(byte > 127 for byte in name_bytes)
        )
        if malformed:
            state.warn("header_malformed", part_id=part_id)
            continue
        name = name_bytes.decode("ascii").casefold()
        occurrences[name] += 1
        first_line_length = len(raw_field.splitlines(keepends=True)[0])
        remainder = raw_field[first_line_length:]
        raw_value = first_value + remainder
        result.append(
            _RawHeader(
                name=name,
                occurrence=occurrences[name],
                raw_field=raw_field,
                raw_value=raw_value,
                unfolded_value=_unfold(raw_value),
            )
        )
    return tuple(result)


def _header_message(header_data: bytes) -> Any:
    try:
        return BytesParser(policy=policy.default).parsebytes(header_data + b"\r\n\r\n")
    except (IndexError, KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise EmailContractError(
            "email_message_malformed", "email headers could not be parsed"
        ) from exc


def _safe_text(value: str) -> str:
    return value.encode("utf-8", "replace").decode("utf-8")


def _decode_header(raw: bytes) -> tuple[str | None, tuple[str, ...]]:
    text = raw.decode("ascii", "surrogateescape")
    if "=?" not in text:
        try:
            return raw.decode("ascii"), ()
        except UnicodeDecodeError:
            return None, ("encoded_word_invalid",)
    try:
        chunks = decode_header(text)
    except (LookupError, UnicodeError, ValueError):
        return None, ("encoded_word_invalid",)
    decoded: list[str] = []
    for chunk, charset in chunks:
        if isinstance(chunk, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in chunk):
                return None, ("encoded_word_invalid",)
            decoded.append(chunk)
            continue
        selected = "ascii" if charset is None else charset.casefold()
        codec = _SUPPORTED_CHARSETS.get(selected)
        if codec is None:
            return None, ("encoded_word_invalid",)
        try:
            decoded.append(chunk.decode(codec, "strict"))
        except (LookupError, UnicodeDecodeError):
            return None, ("encoded_word_invalid",)
    return "".join(decoded), ()


def _parsed_headers(
    raw_headers: tuple[_RawHeader, ...], state: _ParseState
) -> tuple[ParsedHeader, ...]:
    counts = Counter(item.name for item in raw_headers)
    result: list[ParsedHeader] = []
    for item in raw_headers:
        decoded, decode_warnings = _decode_header(item.unfolded_value)
        warning_codes = list(decode_warnings)
        if counts[item.name] > 1:
            warning_codes.append("header_repeated")
        for code in warning_codes:
            state.warn(
                code,
                header_name=item.name,
                occurrence=item.occurrence,
            )
        result.append(
            ParsedHeader(
                name=item.name,
                occurrence=item.occurrence,
                raw_value=item.raw_value.decode("latin-1"),
                raw_sha256=hashlib.sha256(item.raw_value).hexdigest(),
                decoded_value=None if decoded is None else _safe_text(decoded),
                state="warning" if warning_codes else "valid",
                warning_codes=tuple(dict.fromkeys(warning_codes)),
            )
        )
    return tuple(result)


def _selected_headers(
    raw_headers: tuple[_RawHeader, ...], name: str
) -> tuple[_RawHeader, ...]:
    return tuple(item for item in raw_headers if item.name == name)


def _message_ids(
    raw_headers: tuple[_RawHeader, ...], state: _ParseState
) -> tuple[str, ...]:
    selected = _selected_headers(raw_headers, "message-id")
    if not selected:
        state.warn("declared_message_id_absent", header_name="message-id")
        return ()
    values: list[str] = []
    for item in selected:
        try:
            value = item.unfolded_value.decode("ascii")
        except UnicodeDecodeError:
            value = ""
        if _MESSAGE_ID.fullmatch(value) is None:
            state.warn(
                "declared_message_id_malformed",
                header_name="message-id",
                occurrence=item.occurrence,
            )
            continue
        values.append(value)
    if len(selected) > 1 or len(values) > 1:
        state.warn("declared_message_id_repeated", header_name="message-id")
    return tuple(values)


def _reference_tokens(
    raw_headers: tuple[_RawHeader, ...], name: str, state: _ParseState
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _selected_headers(raw_headers, name):
        try:
            value = item.unfolded_value.decode("ascii")
        except UnicodeDecodeError:
            state.warn("reference_malformed", header_name=name, occurrence=item.occurrence)
            continue
        tokens = _MESSAGE_ID_TOKEN.findall(value)
        remainder = _MESSAGE_ID_TOKEN.sub("", value)
        if any(not character.isspace() for character in remainder) or any(
            _MESSAGE_ID.fullmatch(token) is None for token in tokens
        ):
            state.warn("reference_malformed", header_name=name, occurrence=item.occurrence)
        for token in tokens:
            if len(result) >= state.limits.max_reference_tokens:
                raise EmailContractError(
                    "email_header_limit_exceeded",
                    "email reference token limit was exceeded",
                )
            if token in seen:
                state.warn("reference_repeated", header_name=name, occurrence=item.occurrence)
                continue
            seen.add(token)
            result.append(token)
    return tuple(result)


def _declared_dates(
    raw_headers: tuple[_RawHeader, ...], state: _ParseState
) -> tuple[str, ...]:
    result: list[str] = []
    for item in _selected_headers(raw_headers, "date"):
        try:
            value = item.unfolded_value.decode("ascii")
            parsed = parsedate_to_datetime(value)
            if parsed is None or parsed.tzinfo is None:
                raise ValueError("date lacks a timezone")
            result.append(parsed.isoformat())
        except (TypeError, UnicodeError, ValueError):
            state.warn(
                "declared_date_invalid",
                header_name="date",
                occurrence=item.occurrence,
            )
    return tuple(result)


def _address_groups(header_message: Any, state: _ParseState) -> tuple[ParsedAddressGroup, ...]:
    result: list[ParsedAddressGroup] = []
    for name in sorted(_ADDRESS_HEADERS):
        values = header_message.get_all(name, [])
        for occurrence, value in enumerate(values, 1):
            defects = tuple(getattr(value, "defects", ()))
            if defects:
                state.warn("header_malformed", header_name=name, occurrence=occurrence)
            try:
                groups = tuple(value.groups)
            except (AttributeError, TypeError, ValueError):
                state.warn("header_malformed", header_name=name, occurrence=occurrence)
                continue
            for group in groups:
                addresses: list[ParsedAddress] = []
                for address in group.addresses:
                    addresses.append(
                        ParsedAddress(
                            display_name=_safe_text(address.display_name or ""),
                            username=_safe_text(address.username or ""),
                            domain=_safe_text(address.domain or ""),
                        )
                    )
                result.append(
                    ParsedAddressGroup(
                        header_name=name,
                        occurrence=occurrence,
                        display_name=(
                            None
                            if group.display_name is None
                            else _safe_text(group.display_name)
                        ),
                        addresses=tuple(addresses),
                    )
                )
    return tuple(result)


def _strict_base64(payload: bytes, state: _ParseState) -> bytes:
    compact = bytes(byte for byte in payload if byte not in b" \t\r\n")
    if len(compact) % 4 or _BASE64_ALPHABET.fullmatch(compact) is None:
        raise EmailContractError(
            "email_transfer_invalid", "email Base64 transfer encoding is invalid"
        )
    if b"=" in compact[:-2] or compact.count(b"=") > 2:
        raise EmailContractError(
            "email_transfer_invalid", "email Base64 padding is invalid"
        )
    estimated = (len(compact) // 4) * 3 - len(compact) + len(compact.rstrip(b"="))
    if estimated > state.limits.max_decoded_bytes_per_message - state.decoded_bytes:
        raise EmailContractError(
            "email_decoded_limit_exceeded", "email decoded byte limit was exceeded"
        )
    try:
        return base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EmailContractError(
            "email_transfer_invalid", "email Base64 transfer encoding is invalid"
        ) from exc


def _strict_quoted_printable(payload: bytes) -> bytes:
    offset = 0
    while True:
        marker = payload.find(b"=", offset)
        if marker < 0:
            break
        following = payload[marker + 1 : marker + 3]
        if payload[marker + 1 : marker + 3] == b"\r\n":
            offset = marker + 3
        elif payload[marker + 1 : marker + 2] == b"\n":
            offset = marker + 2
        elif len(following) == 2 and all(byte in _HEX for byte in following):
            offset = marker + 3
        else:
            raise EmailContractError(
                "email_transfer_invalid",
                "email quoted-printable transfer encoding is invalid",
            )
    return quopri.decodestring(payload)


def _decode_transfer(payload: bytes, encoding: str, state: _ParseState) -> bytes:
    state.check_deadline()
    selected = encoding.casefold().strip() or "7bit"
    if selected == "base64":
        decoded = _strict_base64(payload, state)
    elif selected == "quoted-printable":
        decoded = _strict_quoted_printable(payload)
    elif selected == "7bit":
        if any(byte > 127 for byte in payload):
            raise EmailContractError(
                "email_transfer_invalid", "email 7bit payload contains non-ASCII bytes"
            )
        decoded = payload
    elif selected in {"8bit", "binary"}:
        decoded = payload
    else:
        raise EmailContractError(
            "email_transfer_invalid", "email transfer encoding is unsupported"
        )
    if len(decoded) > state.limits.max_decoded_bytes_per_message - state.decoded_bytes:
        raise EmailContractError(
            "email_decoded_limit_exceeded", "email decoded byte limit was exceeded"
        )
    state.decoded_bytes += len(decoded)
    return decoded


def _remove_boundary_line_break(data: bytes) -> bytes:
    if data.endswith(b"\r\n"):
        return data[:-2]
    if data.endswith((b"\n", b"\r")):
        return data[:-1]
    return data


def _multipart_children(body: bytes, boundary: str) -> tuple[bytes, ...]:
    try:
        boundary_bytes = boundary.encode("ascii")
    except UnicodeEncodeError as exc:
        raise EmailContractError(
            "email_mime_malformed", "email MIME boundary is invalid"
        ) from exc
    if not boundary_bytes or len(boundary_bytes) > 70 or any(
        byte < 33 or byte > 126 for byte in boundary_bytes
    ):
        raise EmailContractError(
            "email_mime_malformed", "email MIME boundary is invalid"
        )
    delimiter = b"--" + boundary_bytes
    children: list[bytes] = []
    child_start: int | None = None
    position = 0
    closed = False
    for line in body.splitlines(keepends=True):
        content = _line_content(line)
        suffix = content[len(delimiter) :] if content.startswith(delimiter) else None
        is_open = suffix is not None and suffix.strip(b" \t") == b""
        is_close = suffix is not None and suffix.startswith(b"--") and (
            suffix[2:].strip(b" \t") == b""
        )
        if is_open or is_close:
            if child_start is not None:
                children.append(_remove_boundary_line_break(body[child_start:position]))
            if is_close:
                closed = True
                child_start = None
                break
            child_start = position + len(line)
        position += len(line)
    if child_start is not None and not closed:
        raise EmailContractError(
            "email_mime_malformed", "email multipart closing boundary is missing"
        )
    if not closed or not children:
        raise EmailContractError(
            "email_mime_malformed", "email multipart boundaries are incomplete"
        )
    return tuple(children)


def _parameter(header_message: Any, name: str, parameter: str) -> str | None:
    try:
        value = header_message.get_param(parameter, header=name)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None
    if not isinstance(value, str):
        return None
    return _safe_text(value)


def _filename(header_message: Any) -> str | None:
    try:
        value = header_message.get_filename()
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None
    if not isinstance(value, str):
        return None
    return _safe_text(value)


def _walk_entity(
    data: bytes,
    *,
    state: _ParseState,
    part_path: str,
    parent_part_id: str | None,
    depth: int,
    nested_depth: int,
    body_eligible: bool,
) -> None:
    state.check_deadline()
    if depth > state.limits.max_mime_depth:
        raise EmailContractError(
            "email_mime_limit_exceeded", "email MIME depth limit was exceeded"
        )
    state.parts_seen += 1
    if state.parts_seen > state.limits.max_mime_parts:
        raise EmailContractError(
            "email_mime_limit_exceeded", "email MIME part limit was exceeded"
        )

    selected_part_id = _part_id(state.message_sha256, part_path)
    header_data, body = _split_header_body(data)
    _raw_headers(header_data, state=state, part_id=selected_part_id)
    header_message = _header_message(header_data)
    for defect in getattr(header_message, "defects", ()):
        del defect
        state.warn("mime_defect", part_id=selected_part_id)

    try:
        media_type = header_message.get_content_type().casefold()
    except (AttributeError, TypeError, ValueError):
        media_type = "text/plain"
        state.warn("mime_defect", part_id=selected_part_id)
    try:
        disposition = header_message.get_content_disposition()
    except (AttributeError, TypeError, ValueError):
        disposition = None
        state.warn("mime_defect", part_id=selected_part_id)
    transfer = str(header_message.get("Content-Transfer-Encoding", "7bit")).strip().casefold()
    content_id_value = header_message.get("Content-ID")
    content_id = None if content_id_value is None else _safe_text(str(content_id_value).strip())
    filename = _filename(header_message)
    part_warnings: list[str] = []

    if media_type.startswith("multipart/"):
        if transfer not in {"", "7bit", "8bit", "binary"}:
            raise EmailContractError(
                "email_transfer_invalid", "multipart transfer encoding is unsupported"
            )
        boundary = _parameter(header_message, "content-type", "boundary")
        if boundary is None:
            raise EmailContractError(
                "email_mime_malformed", "email multipart boundary is missing"
            )
        children = _multipart_children(body, boundary)
        child_ids = tuple(
            _part_id(state.message_sha256, f"{part_path}.{index}")
            for index in range(len(children))
        )
        if media_type == "multipart/signed":
            part_warnings.append("unsupported_signed_part")
            state.warn("unsupported_signed_part", part_id=selected_part_id)
        if media_type == "multipart/encrypted":
            part_warnings.append("unsupported_encrypted_part")
            state.warn("unsupported_encrypted_part", part_id=selected_part_id)
        state.parts.append(
            ParsedPart(
                part_id=selected_part_id,
                part_path=part_path,
                parent_part_id=parent_part_id,
                media_type=media_type,
                disposition=disposition,
                transfer_encoding=transfer or "7bit",
                content_id=content_id,
                filename=filename,
                is_multipart=True,
                child_part_ids=child_ids,
                decoded_status="container",
                decoded_sha256=None,
                decoded_size_bytes=None,
                warning_codes=tuple(part_warnings),
            )
        )
        for index, child in enumerate(children):
            _walk_entity(
                child,
                state=state,
                part_path=f"{part_path}.{index}",
                parent_part_id=selected_part_id,
                depth=depth + 1,
                nested_depth=nested_depth,
                body_eligible=(
                    body_eligible
                    and disposition != "attachment"
                    and filename is None
                ),
            )
        return

    decoded = _decode_transfer(body, transfer, state)
    nested = media_type == "message/rfc822"
    child_ids: tuple[str, ...] = ()
    if nested:
        if nested_depth >= state.limits.max_nested_message_depth:
            raise EmailContractError(
                "email_mime_limit_exceeded", "nested email message depth was exceeded"
            )
        nested_child_id = _part_id(state.message_sha256, f"{part_path}.0")
        child_ids = (nested_child_id,)
        part_warnings.append("nested_message_preserved")
        state.warn("nested_message_preserved", part_id=selected_part_id)

    is_attachment = (
        disposition == "attachment"
        or filename is not None
        or disposition == "inline"
        or nested
    )
    if is_attachment:
        if len(state.attachments) >= state.limits.max_attachments_per_message:
            raise EmailContractError(
                "email_attachment_limit_exceeded", "email attachment count limit was exceeded"
            )
        if len(decoded) > state.limits.max_attachment_bytes:
            raise EmailContractError(
                "email_attachment_limit_exceeded", "email attachment byte limit was exceeded"
            )
        if (
            len(decoded)
            > state.limits.max_total_attachment_bytes_per_message - state.attachment_bytes
        ):
            raise EmailContractError(
                "email_attachment_limit_exceeded",
                "email total attachment byte limit was exceeded",
            )
        state.attachment_bytes += len(decoded)
        state.attachments.append(
            DecodedAttachment(
                attachment_index=len(state.attachments),
                part_id=selected_part_id,
                part_path=part_path,
                media_type=media_type,
                disposition=disposition,
                transfer_encoding=transfer or "7bit",
                content_id=content_id,
                filename=filename,
                sha256=hashlib.sha256(decoded).hexdigest(),
                size_bytes=len(decoded),
                data=decoded,
            )
        )
    elif media_type == "text/plain" and body_eligible:
        charset = _parameter(header_message, "content-type", "charset")
        if charset is None:
            state.warn("charset_absent", part_id=selected_part_id)
            charset = "us-ascii"
        state.body_candidates.append((part_path, selected_part_id, decoded, charset))
    elif media_type == "text/html" and body_eligible:
        if _parameter(header_message, "content-type", "charset") is None:
            state.warn("charset_absent", part_id=selected_part_id)
        state.html_body_seen = True

    decoded_status = "nested-message" if nested else "decoded"
    state.parts.append(
        ParsedPart(
            part_id=selected_part_id,
            part_path=part_path,
            parent_part_id=parent_part_id,
            media_type=media_type,
            disposition=disposition,
            transfer_encoding=transfer or "7bit",
            content_id=content_id,
            filename=filename,
            is_multipart=False,
            child_part_ids=child_ids,
            decoded_status=decoded_status,
            decoded_sha256=hashlib.sha256(decoded).hexdigest(),
            decoded_size_bytes=len(decoded),
            warning_codes=tuple(part_warnings),
        )
    )
    if nested:
        _walk_entity(
            decoded,
            state=state,
            part_path=f"{part_path}.0",
            parent_part_id=selected_part_id,
            depth=depth + 1,
            nested_depth=nested_depth + 1,
            body_eligible=False,
        )


def _body(state: _ParseState) -> BodySelection:
    for _path, part_id, data, charset in state.body_candidates:
        selected_charset = charset.casefold()
        codec = _SUPPORTED_CHARSETS.get(selected_charset)
        if codec is None:
            state.warn("charset_unsupported", part_id=part_id)
            continue
        try:
            text = data.decode(codec, "strict")
        except UnicodeDecodeError:
            state.warn("charset_invalid", part_id=part_id)
            continue
        if len(text) > state.limits.max_body_characters:
            raise EmailContractError(
                "email_decoded_limit_exceeded", "email body character limit was exceeded"
            )
        encoded = text.encode("utf-8")
        return BodySelection(
            status="available",
            selection_rule="first-safe-text-plain-depth-first",
            part_id=part_id,
            media_type="text/plain",
            charset=selected_charset,
            sha256=hashlib.sha256(encoded).hexdigest(),
            character_count=len(text),
            text=text,
        )
    if state.html_body_seen:
        state.warn("html_body_unavailable")
    state.warn("body_text_unavailable")
    return BodySelection(
        status="unavailable",
        selection_rule="no-safe-text-plain-no-html-fallback",
        part_id=None,
        media_type=None,
        charset=None,
        sha256=None,
        character_count=0,
        text=None,
    )


class StdlibEmailParser:
    """Bounded MIME parser behind Provelume's replaceable parser protocol.

    CPython's ``email`` package parses header syntax and parameters. MIME boundary
    delimitation and transfer decoding remain explicit here so accepted attachment
    bytes are exact, decoder behavior is strict, and all cumulative limits are
    enforced by this public seam.
    """

    parser_id = EMAIL_PARSER_ID
    parser_version = EMAIL_PARSER_VERSION

    def parse(
        self,
        data: bytes,
        *,
        limits: EmailLimits | None = None,
        deadline: float | None = None,
    ) -> ParsedEmail:
        if not isinstance(data, bytes):
            raise EmailContractError(
                "email_message_malformed", "email message input must be immutable bytes"
            )
        selected = limits or EmailLimits()
        if len(data) > selected.max_message_bytes:
            raise EmailContractError(
                "email_message_limit_exceeded", "email message byte limit was exceeded"
            )
        if not data:
            raise EmailContractError(
                "email_message_malformed", "email message is empty"
            )
        started = time.monotonic()
        bounded_deadline = started + selected.max_seconds_per_message
        if deadline is not None:
            bounded_deadline = min(bounded_deadline, deadline)
        if bounded_deadline <= started:
            raise EmailContractError(
                "email_timeout", "email message parsing deadline was exceeded"
            )
        digest = hashlib.sha256(data).hexdigest()
        state = _ParseState(
            data=data,
            limits=selected,
            deadline=bounded_deadline,
            message_sha256=digest,
        )
        top_header_data, _body_data = _split_header_body(data)
        top_part_id = _part_id(digest, "0")
        top_raw_headers = _raw_headers(
            top_header_data,
            state=state,
            part_id=top_part_id,
        )
        # The walk accounts for the same top-level headers. Reset those counters;
        # parsed envelope fields below continue to use the already captured bytes.
        state.headers_seen = 0
        state.header_bytes_seen = 0
        top_message = _header_message(top_header_data)
        parsed_headers = _parsed_headers(top_raw_headers, state)
        declared_ids = _message_ids(top_raw_headers, state)
        references = _reference_tokens(top_raw_headers, "references", state)
        in_reply_to = _reference_tokens(top_raw_headers, "in-reply-to", state)
        declared_dates = _declared_dates(top_raw_headers, state)
        addresses = _address_groups(top_message, state)

        try:
            _walk_entity(
                data,
                state=state,
                part_path="0",
                parent_part_id=None,
                depth=0,
                nested_depth=0,
                body_eligible=True,
            )
        except RecursionError as exc:
            raise EmailContractError(
                "email_mime_limit_exceeded", "email MIME recursion limit was exceeded"
            ) from exc
        selected_body = _body(state)
        warnings = ensure_unique_warnings(state.warnings, selected)
        return ParsedEmail(
            schema_version=EMAIL_CONTRACT_SCHEMA_VERSION,
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            parser_protocol_version=EMAIL_PARSER_PROTOCOL_VERSION,
            message_sha256=digest,
            message_size_bytes=len(data),
            headers=parsed_headers,
            address_groups=addresses,
            declared_message_ids=declared_ids,
            references=references,
            in_reply_to=in_reply_to,
            declared_dates=declared_dates,
            parts=tuple(state.parts),
            body=selected_body,
            attachments=tuple(state.attachments),
            total_decoded_bytes=state.decoded_bytes,
            warnings=warnings,
            limits=selected,
        )


def parse_email(
    data: bytes,
    *,
    limits: EmailLimits | None = None,
    deadline: float | None = None,
) -> ParsedEmail:
    return StdlibEmailParser().parse(data, limits=limits, deadline=deadline)


__all__ = ["StdlibEmailParser", "parse_email"]
