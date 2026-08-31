from __future__ import annotations

import base64
import socket
import time
from dataclasses import replace

import pytest

from provelume.email_contract import EmailContractError, EmailLimits
from provelume.email_mime import StdlibEmailParser

PARSER = StdlibEmailParser()


def _email(headers: bytes, body: bytes = b"body") -> bytes:
    return headers + b"\r\n\r\n" + body


def _warning_codes(parsed: object) -> set[str]:
    return {item.code for item in parsed.warnings}  # type: ignore[attr-defined]


def test_headers_dates_encoded_words_ids_and_groups_are_observations() -> None:
    data = _email(
        b"From: =?utf-8?q?Synthetic_Sender?= <sender@example.invalid>\r\n"
        b"To: Team: One <one@example.invalid>, Two <two@example.invalid>;\r\n"
        b"Subject: =?utf-8?b?U3ludGhldGljIOKckw==?=\r\n"
        b"Subject: repeated\r\n"
        b"Date: Tue, 04 Feb 2025 10:11:12 +0100\r\n"
        b"Message-ID: <one@example.invalid>\r\n"
        b"Message-ID: malformed\r\n"
        b"References: <missing@example.invalid> <missing@example.invalid>\r\n"
        b"In-Reply-To: <parent@example.invalid>\r\n"
        b"Content-Type: text/plain; charset=utf-8"
    )
    parsed = PARSER.parse(data)
    assert parsed.message_size_bytes == len(data)
    assert parsed.declared_message_ids == ("<one@example.invalid>",)
    assert parsed.references == ("<missing@example.invalid>",)
    assert parsed.in_reply_to == ("<parent@example.invalid>",)
    assert parsed.declared_dates == ("2025-02-04T10:11:12+01:00",)
    assert any(header.decoded_value == "Synthetic ✓" for header in parsed.headers)
    team = next(group for group in parsed.address_groups if group.display_name == "Team")
    assert [(item.username, item.domain) for item in team.addresses] == [
        ("one", "example.invalid"),
        ("two", "example.invalid"),
    ]
    assert {
        "header_repeated",
        "declared_message_id_malformed",
        "declared_message_id_repeated",
        "reference_repeated",
    }.issubset(_warning_codes(parsed))


@pytest.mark.parametrize(
    ("message_id", "warning"),
    (
        (b"", "declared_message_id_absent"),
        (b"Message-ID: malformed\r\n", "declared_message_id_malformed"),
    ),
)
def test_missing_or_malformed_message_id_remains_importable(
    message_id: bytes,
    warning: str,
) -> None:
    parsed = PARSER.parse(
        _email(message_id + b"Content-Type: text/plain; charset=us-ascii")
    )
    assert parsed.body.text == "body"
    assert parsed.declared_message_ids == ()
    assert warning in _warning_codes(parsed)


def test_multipart_mixed_alternative_related_selects_first_safe_plain_text() -> None:
    data = _email(
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=outer",
        b"--outer\r\n"
        b"Content-Type: multipart/alternative; boundary=alternative\r\n\r\n"
        b"--alternative\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"selected plain\r\n"
        b"--alternative\r\n"
        b"Content-Type: multipart/related; boundary=related\r\n\r\n"
        b"--related\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<script>never()</script><img src=https://tracker.invalid/pixel>\r\n"
        b"--related--\r\n"
        b"--alternative--\r\n"
        b"--outer--\r\n",
    )
    parsed = PARSER.parse(data)
    assert parsed.body.text == "selected plain"
    assert parsed.body.selection_rule == "first-safe-text-plain-depth-first"
    assert parsed.active_content_executed is False
    assert parsed.remote_fetch is False
    assert parsed.network_used is False


def test_html_only_never_renders_converts_or_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("email parsing attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    html = (
        b"<script>alert(1)</script><style>@import url(https://remote.invalid)</style>"
        b"<form action=https://remote.invalid><img src=cid:missing>"
        b"<img src=https://remote.invalid/pixel>"
    )
    parsed = PARSER.parse(
        _email(b"Content-Type: text/html; charset=utf-8", html)
    )
    assert parsed.body.status == "unavailable"
    assert parsed.body.text is None
    assert {"html_body_unavailable", "body_text_unavailable"}.issubset(
        _warning_codes(parsed)
    )
    assert parsed.active_content_executed is parsed.remote_fetch is False


@pytest.mark.parametrize(
    ("charset", "payload", "warning"),
    (
        (b"x-unknown", b"plain", "charset_unsupported"),
        (b"utf-8", b"\xff", "charset_invalid"),
    ),
)
def test_unknown_or_invalid_charset_fails_body_selection_with_warning(
    charset: bytes,
    payload: bytes,
    warning: str,
) -> None:
    parsed = PARSER.parse(
        _email(
            b"Content-Type: text/plain; charset="
            + charset
            + b"\r\nContent-Transfer-Encoding: 8bit",
            payload,
        )
    )
    assert parsed.body.status == "unavailable"
    assert warning in _warning_codes(parsed)


@pytest.mark.parametrize(
    ("encoding", "payload"),
    (
        (b"base64", b"YWJ"),
        (b"base64", b"YW=J"),
        (b"quoted-printable", b"truncated="),
        (b"quoted-printable", b"invalid=QZ"),
        (b"x-provider-magic", b"opaque"),
    ),
)
def test_invalid_or_unsupported_transfer_encoding_fails_closed(
    encoding: bytes,
    payload: bytes,
) -> None:
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(
            _email(
                b"Content-Type: application/octet-stream\r\n"
                b"Content-Disposition: attachment\r\n"
                b"Content-Transfer-Encoding: "
                + encoding,
                payload,
            )
        )
    assert caught.value.code == "email_transfer_invalid"


def test_valid_transfer_decoding_preserves_exact_attachment_bytes() -> None:
    binary = b"\x00synthetic\xffbytes"
    for encoding, payload in (
        (b"base64", base64.b64encode(binary)),
        (b"quoted-printable", b"=00synthetic=FFbytes"),
    ):
        parsed = PARSER.parse(
            _email(
                b"Content-Type: application/octet-stream\r\n"
                b"Content-Disposition: attachment\r\n"
                b"Content-Transfer-Encoding: "
                + encoding,
                payload,
            )
        )
        assert parsed.attachments[0].data == binary
        assert parsed.total_decoded_bytes == len(binary)


def test_nested_message_is_preserved_and_recursed_only_within_budget() -> None:
    nested = _email(
        b"Message-ID: <nested@example.invalid>\r\n"
        b"Content-Type: text/plain; charset=us-ascii",
        b"nested body",
    )
    parsed = PARSER.parse(
        _email(
            b"Content-Type: message/rfc822\r\n"
            b"Content-Disposition: attachment",
            nested,
        )
    )
    assert parsed.attachments[0].data == nested
    assert any(part.decoded_status == "nested-message" for part in parsed.parts)
    assert "nested_message_preserved" in _warning_codes(parsed)

    doubly_nested = _email(
        b"Content-Type: message/rfc822\r\nContent-Disposition: attachment",
        nested,
    )
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(
            _email(
                b"Content-Type: message/rfc822\r\n"
                b"Content-Disposition: attachment",
                doubly_nested,
            ),
            limits=replace(EmailLimits(), max_nested_message_depth=1),
        )
    assert caught.value.code == "email_mime_limit_exceeded"


def test_archives_are_preserved_as_one_attachment_and_never_expanded() -> None:
    archive = b"PK\x03\x04synthetic-not-opened"
    parsed = PARSER.parse(
        _email(
            b"Content-Type: application/zip; name=archive.zip\r\n"
            b"Content-Disposition: attachment; filename=archive.zip\r\n"
            b"Content-Transfer-Encoding: base64",
            base64.b64encode(archive),
        )
    )
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].data == archive
    assert len(parsed.parts) == 1


def test_header_part_attachment_decoded_body_and_deadline_limits_are_closed() -> None:
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(
            _email(b"X-One: 1\r\nX-Two: 2"),
            limits=replace(EmailLimits(), max_headers_per_message=1),
        )
    assert caught.value.code == "email_header_limit_exceeded"

    attachment = _email(
        b"Content-Type: application/octet-stream\r\n"
        b"Content-Disposition: attachment",
        b"12345",
    )
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(attachment, limits=replace(EmailLimits(), max_attachment_bytes=4))
    assert caught.value.code == "email_attachment_limit_exceeded"

    body = _email(b"Content-Type: text/plain; charset=us-ascii", b"12345")
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(body, limits=replace(EmailLimits(), max_body_characters=4))
    assert caught.value.code == "email_decoded_limit_exceeded"

    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(body, deadline=time.monotonic() - 1)
    assert caught.value.code == "email_timeout"


def test_header_byte_line_and_warning_budgets_fail_before_unbounded_parsing() -> None:
    data = _email(
        b"X-Synthetic: 1234567890\r\nContent-Type: text/plain",
    )
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(data, limits=replace(EmailLimits(), max_header_line_bytes=8))
    assert caught.value.code == "email_header_limit_exceeded"

    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(
            data,
            limits=replace(EmailLimits(), max_header_bytes_per_message=12),
        )
    assert caught.value.code == "email_header_limit_exceeded"

    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(
            _email(b"Content-Type: text/plain"),
            limits=replace(EmailLimits(), max_warnings_per_message=1),
        )
    assert caught.value.code == "email_mime_limit_exceeded"


def test_cumulative_part_depth_attachment_and_decoded_budgets_fail_closed() -> None:
    two_parts = _email(
        b"Content-Type: multipart/mixed; boundary=x",
        b"--x\r\nContent-Type: text/plain\r\n\r\none\r\n"
        b"--x\r\nContent-Type: text/plain\r\n\r\ntwo\r\n--x--\r\n",
    )
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(two_parts, limits=replace(EmailLimits(), max_mime_parts=2))
    assert caught.value.code == "email_mime_limit_exceeded"

    nested = _email(
        b"Content-Type: multipart/mixed; boundary=outer",
        b"--outer\r\nContent-Type: multipart/mixed; boundary=inner\r\n\r\n"
        b"--inner\r\nContent-Type: text/plain\r\n\r\ndeep\r\n"
        b"--inner--\r\n--outer--\r\n",
    )
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(nested, limits=replace(EmailLimits(), max_mime_depth=1))
    assert caught.value.code == "email_mime_limit_exceeded"

    attachments = _email(
        b"Content-Type: multipart/mixed; boundary=a",
        b"--a\r\nContent-Disposition: attachment\r\n\r\n123\r\n"
        b"--a\r\nContent-Disposition: attachment\r\n\r\n456\r\n--a--\r\n",
    )
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(
            attachments,
            limits=replace(EmailLimits(), max_attachments_per_message=1),
        )
    assert caught.value.code == "email_attachment_limit_exceeded"
    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(
            attachments,
            limits=replace(
                EmailLimits(),
                max_attachment_bytes=4,
                max_total_attachment_bytes_per_message=5,
            ),
        )
    assert caught.value.code == "email_attachment_limit_exceeded"

    with pytest.raises(EmailContractError) as caught:
        PARSER.parse(
            _email(
                b"Content-Type: application/octet-stream\r\n"
                b"Content-Disposition: attachment\r\n"
                b"Content-Transfer-Encoding: base64",
                base64.b64encode(b"12345"),
            ),
            limits=replace(
                EmailLimits(),
                max_attachment_bytes=4,
                max_total_attachment_bytes_per_message=4,
                max_decoded_bytes_per_message=4,
            ),
        )
    assert caught.value.code == "email_decoded_limit_exceeded"


def test_raw_utf8_header_is_retained_as_an_explicit_nonsemantic_warning() -> None:
    parsed = PARSER.parse(
        _email(
            b"Subject: Synthetic \xe2\x9c\x93\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Transfer-Encoding: 8bit",
            "UTF-8 body \u2713".encode(),
        )
    )
    subject = next(item for item in parsed.headers if item.name == "subject")
    assert subject.raw_value.encode("latin-1") == b" Synthetic \xe2\x9c\x93"
    assert subject.decoded_value is None
    assert "encoded_word_invalid" in subject.warning_codes
    assert parsed.body.text == "UTF-8 body \u2713"
