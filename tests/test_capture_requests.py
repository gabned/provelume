"""Client metadata cannot manufacture acceptance, device authority or replay identity."""

from copy import deepcopy

import pytest

from provelume.capture_requests import (
    CaptureRequestError,
    capture_scope_key,
)
from provelume.capture_requests import (
    capture_payload_fingerprint as payload_fingerprint,
)
from provelume.capture_requests import (
    validate_capture_metadata as parse_metadata,
)
from provelume.ingest import DEFAULT_MAX_FILE_BYTES

CLIENT_ID = "b5f127f9-1d95-4f6e-8c08-4c0729c775fa"
OTHER_ID = "b5f127f9-1d95-4f6e-8c08-4c0729c775fb"
DEVICE = "dev_" + "a" * 32


def validate_capture_metadata(value):
    return parse_metadata(value, transport_channel="paired_pwa")


def capture_payload_fingerprint(payload, metadata):
    return payload_fingerprint(payload, metadata, transport_channel="paired_pwa")


@pytest.fixture
def metadata():
    return {
        "schema_version": 1,
        "client_submission_id": CLIENT_ID,
        "captured_at": "2026-09-26T12:34:56.123456+02:00",
        "mode": "text",
        "channel": "paired_pwa",
        "note": "Una nota\ncon provenienza",
        "area_id": "area_" + "a" * 32,
        "project_id": "project_" + "b" * 32,
    }


def test_exact_capture_time_and_optional_proposals_are_retained_without_mutation(metadata):
    before = deepcopy(metadata)
    selected = validate_capture_metadata(metadata)
    assert selected == before
    assert selected is not metadata
    assert "received_at" not in selected
    assert "acquisition_id" not in selected
    selected["note"] = "another note"
    assert metadata == before


def test_device_scoped_occurrences_remain_distinct_for_the_same_content(metadata):
    assert capture_scope_key(DEVICE, CLIENT_ID) != capture_scope_key(DEVICE, OTHER_ID)
    assert capture_scope_key(DEVICE, CLIENT_ID) != capture_scope_key("dev_" + "b" * 32, CLIENT_ID)
    # Changed bytes/metadata do not choose a new occurrence key: the journal must
    # detect conflicting reuse instead of accepting a second occurrence.
    scope = capture_scope_key(DEVICE, CLIENT_ID)
    before = capture_payload_fingerprint(b"exact\x00original\xff", metadata)
    assert before == capture_payload_fingerprint(
        b"exact\x00original\xff", dict(reversed(list(metadata.items())))
    )
    assert before != capture_payload_fingerprint(b"exact\x00original\xfe", metadata)
    assert before != capture_payload_fingerprint(
        b"exact\x00original\xff", {**metadata, "note": "new"}
    )
    assert capture_scope_key(DEVICE, CLIENT_ID) == scope


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("client_submission_id", CLIENT_ID.upper()),
        ("client_submission_id", "../submission"),
        ("captured_at", "2026-09-26T12:00:00"),
        ("captured_at", "yesterday"),
        ("mode", {"file": True}),
        ("mode", "calendar_event"),
        ("channel", "owner_admin"),
        ("channel", None),
        ("area_id", "collection_" + "a" * 32),
        ("project_id", "area_" + "a" * 32),
        ("note", "x\x00y"),
        ("note", "\ud800"),
        ("note", "😀" * 1025),
        ("filename", "../original.pdf"),
        ("filename", "C:\\original.pdf"),
        ("declared_mime", "text/plain; charset=utf-8"),
    ],
)
def test_hostile_or_unsupported_metadata_is_rejected(metadata, field, value):
    with pytest.raises(CaptureRequestError):
        validate_capture_metadata({**metadata, field: value})


@pytest.mark.parametrize("field", ["device_id", "credential", "received_at", "accepted"])
def test_client_cannot_supply_server_authority_or_receipt_fields(metadata, field):
    with pytest.raises(CaptureRequestError, match="unsupported fields"):
        validate_capture_metadata({**metadata, field: "client value"})


def test_text_bound_is_measured_in_utf8_bytes(metadata):
    selected = validate_capture_metadata({**metadata, "note": "😀" * 1024})
    assert len(selected["note"].encode("utf-8")) == 4096


def test_channel_is_bound_to_an_independent_server_transport(metadata):
    with pytest.raises(CaptureRequestError, match="authenticated transport"):
        parse_metadata({**metadata, "channel": "local_browser"}, transport_channel="paired_pwa")
    with pytest.raises(CaptureRequestError, match="authenticated transport"):
        parse_metadata(metadata, transport_channel="owner_admin")


def test_identity_input_bound_precedes_hashing_without_claiming_payload_support(metadata):
    with pytest.raises(CaptureRequestError, match="bounded identity"):
        capture_payload_fingerprint(b"x" * (DEFAULT_MAX_FILE_BYTES + 1), metadata)
    with pytest.raises(CaptureRequestError):
        capture_payload_fingerprint(bytearray(b"original"), metadata)
    with pytest.raises(CaptureRequestError, match="authenticated"):
        capture_scope_key("src_" + "a" * 32, CLIENT_ID)


def test_required_metadata_cannot_be_omitted(metadata):
    for field in ("schema_version", "client_submission_id", "captured_at", "mode", "channel"):
        with pytest.raises(CaptureRequestError, match="incomplete"):
            validate_capture_metadata(
                {key: value for key, value in metadata.items() if key != field}
            )
