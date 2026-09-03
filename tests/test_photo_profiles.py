from __future__ import annotations

import base64
import copy
import hashlib
import importlib.metadata
import json
import socket
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.instance_backup import create_backup, extract_backup, verify_backup
from provelume.instance_validation import inspect_instance
from provelume.photo_profiles import (
    MAX_METADATA_BYTES,
    MAX_PIXELS,
    PhotoContractError,
    PhotoDecodeResult,
    PhotoProfileManager,
    PillowPhotoDecoder,
    inspect_photo_bytes,
    validate_photo_record,
)
from provelume.representations import RepresentationBundleManager
from provelume.service import ProvelumeInstance
from provelume.storage import CANONICAL_KINDS, InstanceStore
from provelume.web import create_app

_PREVIEW = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return len(payload).to_bytes(4, "big") + kind + payload + checksum.to_bytes(4, "big")


def _png(width: int = 4, height: int = 3, *, marker: bytes = b"") -> bytes:
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    raw = (b"\x00" + b"\x10\x20\x30" * width) * height
    chunks = [_png_chunk(b"IHDR", header)]
    if marker:
        chunks.append(_png_chunk(b"tEXt", b"fixture\x00" + marker))
    chunks.extend((_png_chunk(b"IDAT", zlib.compress(raw)), _png_chunk(b"IEND", b"")))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def _tiff(width: int = 4, height: int = 3) -> bytes:
    entries = b"".join(
        (
            (256).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + (1).to_bytes(4, "little")
            + width.to_bytes(4, "little"),
            (257).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + (1).to_bytes(4, "little")
            + height.to_bytes(4, "little"),
        )
    )
    return (
        b"II*\x00"
        + (8).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + entries
        + b"\x00\x00\x00\x00"
    )


def _jpeg_with_private_metadata(width: int = 4, height: int = 3) -> bytes:
    capture = b"2026:09:03 07:00:00\x00"
    root_offset = 8
    gps_offset = root_offset + 2 + 3 * 12 + 4
    capture_offset = gps_offset + 2 + 2 * 12 + 4
    root_entries = b"".join(
        (
            (274).to_bytes(2, "little")
            + (3).to_bytes(2, "little")
            + (1).to_bytes(4, "little")
            + (6).to_bytes(2, "little")
            + b"\x00\x00",
            (306).to_bytes(2, "little")
            + (2).to_bytes(2, "little")
            + len(capture).to_bytes(4, "little")
            + capture_offset.to_bytes(4, "little"),
            (34853).to_bytes(2, "little")
            + (4).to_bytes(2, "little")
            + (1).to_bytes(4, "little")
            + gps_offset.to_bytes(4, "little"),
        )
    )
    gps_entries = b"".join(
        (
            (2).to_bytes(2, "little")
            + (1).to_bytes(2, "little")
            + (1).to_bytes(4, "little")
            + b"\x01\x00\x00\x00",
            (4).to_bytes(2, "little")
            + (1).to_bytes(2, "little")
            + (1).to_bytes(4, "little")
            + b"\x01\x00\x00\x00",
        )
    )
    tiff = (
        b"II*\x00"
        + root_offset.to_bytes(4, "little")
        + (3).to_bytes(2, "little")
        + root_entries
        + b"\x00\x00\x00\x00"
        + (2).to_bytes(2, "little")
        + gps_entries
        + b"\x00\x00\x00\x00"
        + capture
    )
    exif = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif
    xmp = b"http://ns.adobe.com/xap/1.0/\x00<private/>"
    app1_xmp = b"\xff\xe1" + (len(xmp) + 2).to_bytes(2, "big") + xmp
    sof = (
        bytes([8])
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + bytes([3, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0])
    )
    return (
        b"\xff\xd8"
        + app1
        + app1_xmp
        + b"\xff\xc0"
        + (len(sof) + 2).to_bytes(2, "big")
        + sof
        + b"\xff\xd9"
    )


def _bmp(width: int = 4, height: int = 3) -> bytes:
    stride = ((width * 3 + 3) // 4) * 4
    pixels = b"\x00" * (stride * height)
    size = 54 + len(pixels)
    return (
        b"BM"
        + size.to_bytes(4, "little")
        + b"\x00\x00\x00\x00"
        + (54).to_bytes(4, "little")
        + (40).to_bytes(4, "little")
        + width.to_bytes(4, "little", signed=True)
        + height.to_bytes(4, "little", signed=True)
        + (1).to_bytes(2, "little")
        + (24).to_bytes(2, "little")
        + b"\x00" * 24
        + pixels
    )


class FakeDecoder:
    def __init__(self, hashes: dict[str, str] | None = None):
        self.hashes = hashes or {}

    @staticmethod
    def capability() -> dict[str, object]:
        return {
            "state": "ready",
            "component": "codec.pillow",
            "version": "12.3.0",
            "qualified": True,
        }

    def decode(self, data: bytes, expected_format: str) -> PhotoDecodeResult:
        assert expected_format in {"JPEG", "PNG", "TIFF", "BMP"}
        digest = hashlib.sha256(data).hexdigest()
        return PhotoDecodeResult(
            preview_png=_PREVIEW,
            perceptual_hash=self.hashes.get(digest, digest[:16]),
            decoder_version="12.3.0",
            source_frames=1,
        )


class FakeCodeAdapter:
    @staticmethod
    def capability() -> dict[str, object]:
        return {
            "state": "ready",
            "qualified": True,
            "adapter_id": "fixture-zxing",
            "version": "2.3.0",
        }

    @staticmethod
    def observe(_data: bytes) -> list[dict[str, object]]:
        return [
            {
                "kind": "qr-code",
                "symbology": "QR_CODE",
                "payload": b"https://private.invalid/",
                "region": {"x": 1, "y": 1, "width": 2, "height": 2},
            }
        ]


class UnavailableDecoder:
    @staticmethod
    def capability() -> dict[str, object]:
        return {
            "state": "unavailable",
            "component": "codec.pillow",
            "version": None,
            "qualified": False,
        }


def _seed(tmp_path: Path, files: dict[str, bytes]) -> tuple[ProvelumeInstance, dict[str, str]]:
    source = tmp_path / "source"
    source.mkdir()
    for name, payload in files.items():
        (source / name).write_bytes(payload)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    versions = {}
    for document in instance.store.list_canonical("documents"):
        versions[Path(str(document["locator"])).name] = str(document["current_version_id"])
    return instance, versions


def _snapshot(instance: ProvelumeInstance) -> tuple[dict[str, list[dict]], dict[str, bytes]]:
    canonical = {kind: instance.store.list_canonical(kind) for kind in CANONICAL_KINDS}
    originals = {
        str(item["id"]): instance.store.original_bytes(str(item["id"]))
        for item in instance.store.list_canonical("originals")
    }
    return canonical, originals


def test_baseline_signatures_orientation_color_and_gps_default_redaction() -> None:
    records = {
        "PNG": inspect_photo_bytes(_png()),
        "JPEG": inspect_photo_bytes(_jpeg_with_private_metadata()),
        "TIFF": inspect_photo_bytes(_tiff()),
        "BMP": inspect_photo_bytes(_bmp()),
    }
    assert set(records) == {record["format"] for record in records.values()}
    assert records["PNG"]["color"]["model"] == "rgb"
    assert records["BMP"]["color"]["bit_depth"] == 24
    jpeg = records["JPEG"]
    assert jpeg["orientation"] == {"exif_value": 6, "label": "rotate-90"}
    assert jpeg["dimensions"]["display_width"] == 3
    assert jpeg["capture_time"]["value"] == "2026:09:03 07:00:00"
    assert jpeg["gps"] == {
        "present": True,
        "source_precision": "exact",
        "coordinates": None,
        "redacted": True,
        "default_export": "excluded",
    }
    assert jpeg["metadata"]["xmp"]["raw_values_exported"] is False


def test_malformed_metadata_pixel_decompression_and_metadata_limits_fail_closed() -> None:
    with pytest.raises(PhotoContractError, match="signature"):
        inspect_photo_bytes(b"<svg onload=alert(1)>")
    with pytest.raises(PhotoContractError, match="chunk"):
        inspect_photo_bytes(_png()[:-12])
    malformed_ihdr = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", (1).to_bytes(4, "big") * 2)
        + _png_chunk(b"IEND", b"")
    )
    with pytest.raises(PhotoContractError, match="IHDR"):
        inspect_photo_bytes(malformed_ihdr)
    with pytest.raises(PhotoContractError) as pixels:
        inspect_photo_bytes(_png(MAX_PIXELS + 1, 1))
    assert pixels.value.code == "photo_pixel_limit_exceeded"
    oversized = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", (1).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0]))
        + (MAX_METADATA_BYTES + 1).to_bytes(4, "big")
        + b"iTXt"
        + b"x"
    )
    with pytest.raises(PhotoContractError) as metadata:
        inspect_photo_bytes(oversized)
    assert metadata.value.code == "photo_invalid_metadata"


def test_only_exact_qualified_pillow_version_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decoder = PillowPhotoDecoder()
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "12.4.0")
    assert decoder.capability()["state"] == "incompatible"
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "12.3.0")
    assert decoder.capability()["state"] == "ready"


def test_malformed_png_job_fails_closed_and_remains_retryable(tmp_path: Path) -> None:
    malformed = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", (1).to_bytes(4, "big") * 2)
        + _png_chunk(b"IEND", b"")
    )
    instance, versions = _seed(tmp_path, {"malformed.png": malformed})
    manager = PhotoProfileManager(instance.store, decoder=FakeDecoder())
    queued = manager.queue(versions["malformed.png"])

    first = manager.run(queued["job"]["id"])
    second = manager.run(queued["job"]["id"])

    assert first["status"] == second["status"] == "failed"
    assert first["error_code"] == second["error_code"] == "photo_invalid_metadata"


def test_job_profile_preview_qr_ocr_anchor_and_remove_rebuild_are_derived(
    tmp_path: Path,
) -> None:
    instance, versions = _seed(tmp_path, {"camera.jpg": _jpeg_with_private_metadata()})
    version_id = versions["camera.jpg"]
    ocr = instance.root / "state" / "derived" / "ocr-bundles" / "job_fixture" / ("ocr_" + "1" * 64)
    ocr.mkdir(parents=True)
    (ocr / "manifest.json").write_text(
        json.dumps(
            {
                "version_id": version_id,
                "derivation_key": "ocr_" + "1" * 64,
                "pages": [{"page_number": 1}],
            }
        ),
        encoding="utf-8",
    )
    before = _snapshot(instance)
    manager = PhotoProfileManager(
        instance.store, decoder=FakeDecoder(), code_adapter=FakeCodeAdapter()
    )
    queued = manager.queue(version_id)
    completed = manager.run(queued["job"]["id"])
    assert completed["status"] == "succeeded"
    selected = manager.get(completed["representation_id"])
    assert selected is not None
    record = selected["record"]
    assert validate_photo_record(record) == record
    assert record["preview"]["active_content"] is False
    assert record["metadata"]["device_fields_redacted"] is True
    assert record["ocr_reuse"]["page_anchors"] == [1]
    universal = manager.bundles.get(completed["representation_id"])
    assert universal is not None
    assert {anchor["kind"] for anchor in universal["anchors"]} == {"page"}
    observation = record["codes"]["observations"][0]
    assert observation["kind"] == "qr-code"
    assert observation["payload_redacted"] is True
    assert "private.invalid" not in json.dumps(record)
    assert _snapshot(instance) == before

    receipt = manager.remove(completed["representation_id"])
    assert receipt["original_mutated"] is False
    rebuilt = manager.rebuild(completed["representation_id"])
    assert rebuilt["representation_id"] == completed["representation_id"]
    assert _snapshot(instance) == before


def test_exact_and_perceptual_proposals_are_separate_review_only(
    tmp_path: Path,
) -> None:
    first = _png(marker=b"first")
    exact = first
    similar = _png(marker=b"similar")
    far = _png(marker=b"far")
    hashes = {
        hashlib.sha256(first).hexdigest(): "0000000000000000",
        hashlib.sha256(similar).hexdigest(): "0000000000000001",
        hashlib.sha256(far).hexdigest(): "ffffffffffffffff",
    }
    instance, versions = _seed(
        tmp_path,
        {"a.png": first, "b.png": exact, "c.png": similar, "d.png": far},
    )
    manager = PhotoProfileManager(instance.store, decoder=FakeDecoder(hashes))
    manager.create(versions["a.png"])
    exact_record = manager.get(manager.create(versions["b.png"])["representation_id"])["record"]
    similar_record = manager.get(manager.create(versions["c.png"])["representation_id"])["record"]
    far_record = manager.get(manager.create(versions["d.png"])["representation_id"])["record"]

    assert {item["kind"] for item in exact_record["duplicates"]["proposals"]} == {"exact"}
    assert {item["kind"] for item in similar_record["duplicates"]["proposals"]} == {"perceptual"}
    assert far_record["duplicates"]["proposals"] == []
    assert all(
        item["advisory"] is True and item["action"] == "review"
        for record in (exact_record, similar_record)
        for item in record["duplicates"]["proposals"]
    )
    assert exact_record["duplicates"]["automatic_action"] == "none"


def test_closed_record_rejects_gps_or_automatic_action_relaxation(tmp_path: Path) -> None:
    instance, versions = _seed(tmp_path, {"photo.png": _png()})
    manager = PhotoProfileManager(instance.store, decoder=FakeDecoder())
    record = manager.get(manager.create(versions["photo.png"])["representation_id"])["record"]

    leaked = copy.deepcopy(record)
    leaked["gps"]["coordinates"] = {"latitude": 1.0, "longitude": 2.0}
    leaked["gps"]["redacted"] = False
    with pytest.raises(PhotoContractError, match="GPS"):
        validate_photo_record(leaked)

    automatic = copy.deepcopy(record)
    automatic["duplicates"]["automatic_action"] = "delete"
    with pytest.raises(PhotoContractError, match="duplicate"):
        validate_photo_record(automatic)


def test_remove_rejects_an_unrelated_universal_representation(tmp_path: Path) -> None:
    instance, versions = _seed(tmp_path, {"photo.png": _png()})
    version_id = versions["photo.png"]
    universal = RepresentationBundleManager(instance.store)
    unrelated = universal.materialize(
        version_id,
        recipe_id="provelume.unrelated-fixture",
        recipe_version="1",
        recipe_settings={},
        output_payloads={"fixture.txt": ("text/plain", b"unrelated\n")},
        implementation={
            "component": "provelume.core",
            "component_version": "0.9.0",
            "adapter": "fixture",
            "adapter_version": "1",
            "settings": {"mode": "offline"},
        },
    )
    manager = PhotoProfileManager(instance.store, decoder=FakeDecoder())

    with pytest.raises(PhotoContractError) as caught:
        manager.remove(unrelated["representation_id"])

    assert caught.value.code == "photo_not_found"
    assert universal.get(unrelated["representation_id"]) == unrelated


def test_recipe_filter_and_direct_get_are_not_consumed_by_other_bundles(
    tmp_path: Path,
) -> None:
    instance, versions = _seed(tmp_path, {"photo.png": _png()})
    version_id = versions["photo.png"]
    universal = RepresentationBundleManager(instance.store)
    for index in range(3):
        universal.materialize(
            version_id,
            recipe_id=f"provelume.unrelated-{index}",
            recipe_version="1",
            recipe_settings={},
            output_payloads={f"fixture-{index}.txt": ("text/plain", str(index).encode())},
            implementation={
                "component": "provelume.core",
                "component_version": "0.9.0",
                "adapter": "fixture",
                "adapter_version": "1",
                "settings": {"mode": "offline"},
            },
        )
    manager = PhotoProfileManager(instance.store, decoder=FakeDecoder())
    photo = manager.create(version_id)

    filtered = universal.list(recipe_id="provelume.photo-profile", limit=1)
    assert [item["representation_id"] for item in filtered] == [photo["representation_id"]]
    assert manager.get(photo["representation_id"]) is not None


def test_job_identity_changes_when_optional_processing_capability_changes(
    tmp_path: Path,
) -> None:
    instance, versions = _seed(tmp_path, {"photo.png": _png()})
    version_id = versions["photo.png"]
    unavailable = PhotoProfileManager(instance.store, decoder=UnavailableDecoder())
    ready = PhotoProfileManager(instance.store, decoder=FakeDecoder())

    first = unavailable.queue(version_id)
    second = ready.queue(version_id)

    assert first["scheduled"] is True
    assert second["scheduled"] is True
    assert first["job"]["id"] != second["job"]["id"]
    assert first["job"]["processing_identity"]["decoder"]["state"] == "unavailable"
    assert second["job"]["processing_identity"]["decoder"]["state"] == "ready"


def test_service_cli_api_browser_and_preview_headers_share_safe_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, versions = _seed(tmp_path, {"photo.png": _png()})
    manager = PhotoProfileManager(instance.store, decoder=FakeDecoder())
    created = manager.create(versions["photo.png"])
    selected_id = created["representation_id"]

    # Default surfaces truthfully show the missing optional decoder but retain the same record.
    expected = instance.photo_read_model()
    assert main(["photos", str(instance.root)]) == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli == expected
    client = TestClient(create_app(instance.root))
    api = client.get("/api/v1/photos")
    browser_en = client.get("/photos?lang=en")
    browser_it = client.get("/photos?lang=it")
    detail = client.get(f"/api/v1/photos/{selected_id}")

    assert api.status_code == 200 and api.json() == expected
    assert detail.status_code == 200
    assert browser_en.status_code == browser_it.status_code == 200
    assert "Photo profiles" in browser_en.text
    assert "Profili foto" in browser_it.text
    assert "private.invalid" not in browser_en.text + browser_it.text

    # A surface backed by the qualified manager serves only the sanitized PNG.
    instance.photos = manager
    guarded = TestClient(create_app(instance.root))
    with guarded:
        monkeypatch.setattr(
            socket,
            "create_connection",
            lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")),
        )
        response = guarded.get(f"/api/v1/photos/{selected_id}/preview")
    assert response.status_code == 200 and response.content == _PREVIEW
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'none'" in response.headers["content-security-policy"]
    assert "object-src 'none'" in response.headers["content-security-policy"]


def test_backup_transfer_and_deep_validation_preserve_photo_profile(tmp_path: Path) -> None:
    instance, versions = _seed(tmp_path, {"photo.png": _png()})
    manager = PhotoProfileManager(instance.store, decoder=FakeDecoder())
    selected_id = manager.create(versions["photo.png"])["representation_id"]
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    backup = create_backup(instance.store, destination=tmp_path / "backups", reason="photo-profile")
    assert verify_backup(backup["archive"])["status"] == "valid"
    restored_root = tmp_path / "restored"
    extract_backup(backup["archive"], restored_root)
    assert PhotoProfileManager(InstanceStore(restored_root)).get(selected_id) is not None

    portable = tmp_path / "portable.zip"
    instance.export_portable(portable)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(portable)
    assert target.get_photo(selected_id) is not None


def test_support_registry_keeps_core_inspection_and_optional_preview_distinct(
    tmp_path: Path,
) -> None:
    instance, _versions = _seed(tmp_path, {"photo.png": _png()})
    support = instance.representation_support(profile_id="perceptio-photo-v1")
    records = {item["operation"]: item for item in support["records"]}
    assert records["inspect"]["effective_state"] == "available"
    assert records["extract"]["effective_state"] == "available"
    assert records["preview"]["declared_state"] == "optional"
    assert records["preview"]["effective_state"] == "unavailable"
    assert records["preview"]["missing_component"] == "codec.pillow"
    assert records["ai_enrich"]["reason"] == "not_implemented"
