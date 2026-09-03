from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .extractors import ExtractionError, ImageMetadataExtractor
from .paths import safe_instance_path
from .representations import (
    RepresentationBundleManager,
    RepresentationContractError,
    canonical_json_bytes,
)
from .storage import InstanceStore, utc_now

PHOTO_SCHEMA_VERSION = 1
PHOTO_PROFILE_ID = "perceptio-photo-v1"
PHOTO_RECIPE_ID = "provelume.photo-profile"
PHOTO_RECIPE_VERSION = "1"
PHOTO_JOB_SCHEMA_VERSION = 1

PHOTO_FORMATS = ("JPEG", "PNG", "TIFF", "BMP")
PHOTO_MEDIA_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "BMP": "image/bmp",
}
PHOTO_ERROR_CODES = (
    "photo_not_found",
    "photo_unsupported_format",
    "photo_invalid_metadata",
    "photo_input_limit_exceeded",
    "photo_pixel_limit_exceeded",
    "photo_decompression_limit_exceeded",
    "photo_decoder_unavailable",
    "photo_decoder_incompatible",
    "photo_decode_failed",
    "photo_contract_violation",
    "photo_job_state_invalid",
)

MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_PIXELS = 80_000_000
MAX_DECOMPRESSED_BYTES = 320 * 1024 * 1024
MAX_DECOMPRESSION_RATIO = 100
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_METADATA_RECORDS = 4_096
MAX_PREVIEW_EDGE = 1_600
MAX_PREVIEW_BYTES = 32 * 1024 * 1024
MAX_DUPLICATE_CANDIDATES = 1_000
MAX_CODE_OBSERVATIONS = 100
PERCEPTUAL_DISTANCE_THRESHOLD = 6

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_CAPTURE_TIME = re.compile(r"\d{4}[:\-]\d{2}[:\-]\d{2}[ T]\d{2}:\d{2}:\d{2}\Z")


class PhotoContractError(ValueError):
    """Closed, content-free failure for photo profiling."""

    def __init__(self, code: str, message: str):
        if code not in PHOTO_ERROR_CODES:
            raise ValueError("photo error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _exact_object(value: Any, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise PhotoContractError(
            "photo_contract_violation", f"{name} fields are incomplete or unsupported"
        )
    return dict(value)


def _bounded_text(value: Any, name: str, maximum: int = 500) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or len(value) > maximum
    ):
        raise PhotoContractError("photo_contract_violation", f"{name} is invalid")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PhotoContractError("photo_contract_violation", f"{name} is invalid")
    return value


def _identify(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"):
        return "JPEG"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "TIFF"
    if data.startswith(b"BM"):
        return "BMP"
    raise PhotoContractError(
        "photo_unsupported_format", "photo signature is outside the qualified baseline"
    )


def _dimensions(data: bytes, selected_format: str) -> tuple[int, int]:
    extractor = ImageMetadataExtractor()
    try:
        if selected_format == "JPEG":
            return extractor._jpeg_dimensions(data)
        if selected_format == "PNG":
            return extractor._png_dimensions(data)
        if selected_format == "TIFF":
            return extractor._tiff_dimensions(data)
        return extractor._bmp_dimensions(data)
    except ExtractionError as exc:
        raise PhotoContractError(
            "photo_invalid_metadata", "photo dimensions cannot be read safely"
        ) from exc


def _check_limits(data: bytes, width: int, height: int) -> None:
    if not data or len(data) > MAX_INPUT_BYTES:
        raise PhotoContractError(
            "photo_input_limit_exceeded", "photo input exceeds its closed byte limit"
        )
    pixels = width * height
    if pixels < 1 or pixels > MAX_PIXELS:
        raise PhotoContractError(
            "photo_pixel_limit_exceeded", "photo dimensions exceed the closed pixel limit"
        )
    expanded = pixels * 4
    if expanded > MAX_DECOMPRESSED_BYTES:
        raise PhotoContractError(
            "photo_decompression_limit_exceeded",
            "photo decoded size exceeds the closed byte limit",
        )
    if len(data) and math.ceil(expanded / len(data)) > MAX_DECOMPRESSION_RATIO:
        raise PhotoContractError(
            "photo_decompression_limit_exceeded",
            "photo expansion ratio exceeds the closed limit",
        )


def _jpeg_segments(data: bytes) -> list[tuple[int, bytes]]:
    position = 2
    result: list[tuple[int, bytes]] = []
    while position < len(data) and len(result) < MAX_METADATA_RECORDS:
        if data[position] != 0xFF:
            raise PhotoContractError("photo_invalid_metadata", "JPEG marker stream is invalid")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(data):
            raise PhotoContractError("photo_invalid_metadata", "JPEG segment is truncated")
        length = int.from_bytes(data[position : position + 2], "big")
        if length < 2 or position + length > len(data):
            raise PhotoContractError("photo_invalid_metadata", "JPEG segment length is invalid")
        payload = data[position + 2 : position + length]
        result.append((marker, payload))
        position += length
        if marker == 0xDA:
            break
    if len(result) >= MAX_METADATA_RECORDS:
        raise PhotoContractError(
            "photo_invalid_metadata", "JPEG metadata record limit was exceeded"
        )
    return result


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    position = 8
    result: list[tuple[bytes, bytes]] = []
    while position + 12 <= len(data) and len(result) < MAX_METADATA_RECORDS:
        length = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        end = position + 12 + length
        if length > MAX_METADATA_BYTES or end > len(data):
            raise PhotoContractError("photo_invalid_metadata", "PNG chunk length is invalid")
        result.append((kind, data[position + 8 : position + 8 + length]))
        position = end
        if kind == b"IEND":
            break
    if not result or result[0][0] != b"IHDR" or result[-1][0] != b"IEND":
        raise PhotoContractError("photo_invalid_metadata", "PNG chunk stream is incomplete")
    if len(result) >= MAX_METADATA_RECORDS:
        raise PhotoContractError("photo_invalid_metadata", "PNG chunk limit was exceeded")
    return result


class _TiffView:
    _TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}

    def __init__(self, data: bytes):
        if len(data) < 8 or data[:4] not in {b"II*\x00", b"MM\x00*"}:
            raise PhotoContractError("photo_invalid_metadata", "TIFF header is invalid")
        self.data = data
        self.order = "little" if data[:2] == b"II" else "big"
        self.root_offset = int.from_bytes(data[4:8], self.order)

    def entries(self, offset: int) -> dict[int, tuple[int, int, bytes]]:
        if offset < 8 or offset + 2 > len(self.data):
            raise PhotoContractError("photo_invalid_metadata", "TIFF IFD offset is invalid")
        count = int.from_bytes(self.data[offset : offset + 2], self.order)
        if count > 512 or offset + 2 + count * 12 + 4 > len(self.data):
            raise PhotoContractError("photo_invalid_metadata", "TIFF IFD limit is invalid")
        result: dict[int, tuple[int, int, bytes]] = {}
        for index in range(count):
            start = offset + 2 + index * 12
            tag = int.from_bytes(self.data[start : start + 2], self.order)
            field_type = int.from_bytes(self.data[start + 2 : start + 4], self.order)
            values = int.from_bytes(self.data[start + 4 : start + 8], self.order)
            unit = self._TYPE_SIZE.get(field_type)
            if unit is None or values > MAX_METADATA_RECORDS:
                continue
            size = unit * values
            if size > MAX_METADATA_BYTES:
                raise PhotoContractError("photo_invalid_metadata", "TIFF metadata is oversized")
            if size <= 4:
                raw = self.data[start + 8 : start + 8 + size]
            else:
                value_offset = int.from_bytes(self.data[start + 8 : start + 12], self.order)
                if value_offset < 8 or value_offset + size > len(self.data):
                    raise PhotoContractError(
                        "photo_invalid_metadata", "TIFF metadata offset is invalid"
                    )
                raw = self.data[value_offset : value_offset + size]
            result[tag] = (field_type, values, raw)
        return result

    def scalar(self, entry: tuple[int, int, bytes] | None) -> int | None:
        if entry is None or entry[1] != 1 or entry[0] not in {1, 3, 4, 9}:
            return None
        size = self._TYPE_SIZE[entry[0]]
        return int.from_bytes(entry[2][:size], self.order, signed=entry[0] == 9)

    @staticmethod
    def ascii(entry: tuple[int, int, bytes] | None) -> str | None:
        if entry is None or entry[0] != 2:
            return None
        try:
            value = entry[2].rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            return None
        return value if _CAPTURE_TIME.fullmatch(value) else None


def _family_evidence(payloads: Sequence[bytes]) -> dict[str, Any]:
    total = sum(len(item) for item in payloads)
    if total > MAX_METADATA_BYTES:
        raise PhotoContractError("photo_invalid_metadata", "photo metadata limit was exceeded")
    joined = b"".join(payloads)
    return {
        "present": bool(payloads),
        "bytes": total,
        "sha256": _sha256(joined) if payloads else None,
        "raw_values_exported": False,
    }


def _metadata_evidence(data: bytes, selected_format: str) -> dict[str, Any]:
    exif_payloads: list[bytes] = []
    iptc_payloads: list[bytes] = []
    xmp_payloads: list[bytes] = []
    icc_payloads: list[bytes] = []
    orientation: int | None = None
    capture_time: str | None = None
    gps_present = False
    gps_precision = "none"
    color_model = "unknown"
    bit_depth: int | None = None

    tiff_data: bytes | None = None
    if selected_format == "JPEG":
        segments = _jpeg_segments(data)
        for marker, payload in segments:
            if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
                exif_payloads.append(payload)
                tiff_data = payload[6:]
            elif marker == 0xE1 and payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00"):
                xmp_payloads.append(payload)
            elif marker == 0xED:
                iptc_payloads.append(payload)
            elif marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"):
                icc_payloads.append(payload)
            elif marker in ImageMetadataExtractor.jpeg_sof_markers and len(payload) >= 6:
                bit_depth = payload[0]
                components = payload[5]
                color_model = {1: "grayscale", 3: "ycbcr", 4: "cmyk"}.get(components, "unknown")
    elif selected_format == "PNG":
        chunks = _png_chunks(data)
        header = chunks[0][1]
        bit_depth = header[8]
        color_model = {
            0: "grayscale",
            2: "rgb",
            3: "indexed",
            4: "grayscale-alpha",
            6: "rgba",
        }.get(header[9], "unknown")
        for kind, payload in chunks:
            if kind == b"eXIf":
                exif_payloads.append(payload)
                tiff_data = payload
            elif kind in {b"iTXt", b"tEXt", b"zTXt"} and b"XML:com.adobe.xmp" in payload:
                xmp_payloads.append(payload)
            elif kind == b"iCCP":
                icc_payloads.append(payload)
    elif selected_format == "TIFF":
        tiff_data = data
        exif_payloads.append(data[: min(len(data), MAX_METADATA_BYTES)])
    else:
        if len(data) < 30:
            raise PhotoContractError("photo_invalid_metadata", "BMP header is truncated")
        bit_depth = int.from_bytes(data[28:30], "little")
        color_model = "rgba" if bit_depth == 32 else "rgb" if bit_depth >= 24 else "indexed"

    if tiff_data is not None:
        view = _TiffView(tiff_data)
        root = view.entries(view.root_offset)
        orientation = view.scalar(root.get(274))
        exif_offset = view.scalar(root.get(34665))
        gps_offset = view.scalar(root.get(34853))
        capture_time = view.ascii(root.get(306))
        if root.get(700):
            xmp_payloads.append(root[700][2])
        if root.get(33723):
            iptc_payloads.append(root[33723][2])
        if root.get(34675):
            icc_payloads.append(root[34675][2])
        if exif_offset is not None:
            nested = view.entries(exif_offset)
            capture_time = view.ascii(nested.get(36867)) or capture_time
        if gps_offset is not None:
            gps = view.entries(gps_offset)
            gps_present = bool(gps)
            gps_precision = "exact" if {2, 4}.issubset(gps) else "unknown"

    if orientation not in set(range(1, 9)):
        orientation = None
    return {
        "orientation": {
            "exif_value": orientation,
            "label": {
                1: "normal",
                2: "mirror-horizontal",
                3: "rotate-180",
                4: "mirror-vertical",
                5: "mirror-horizontal-rotate-270",
                6: "rotate-90",
                7: "mirror-horizontal-rotate-90",
                8: "rotate-270",
            }.get(orientation, "unknown"),
        },
        "color": {
            "model": color_model,
            "bit_depth": bit_depth,
            "icc_profile_present": bool(icc_payloads),
            "icc_profile_sha256": _sha256(b"".join(icc_payloads)) if icc_payloads else None,
        },
        "metadata": {
            "exif": _family_evidence(exif_payloads),
            "iptc": _family_evidence(iptc_payloads),
            "xmp": _family_evidence(xmp_payloads),
            "device_fields_redacted": True,
        },
        "capture_time": {
            "present": capture_time is not None,
            "value": capture_time,
            "source": "exif" if capture_time else None,
            "verified": False,
        },
        "gps": {
            "present": gps_present,
            "source_precision": gps_precision,
            "coordinates": None,
            "redacted": True,
            "default_export": "excluded",
        },
    }


def inspect_photo_bytes(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_INPUT_BYTES:
        raise PhotoContractError(
            "photo_input_limit_exceeded", "photo input exceeds its closed byte limit"
        )
    selected_format = _identify(data)
    width, height = _dimensions(data, selected_format)
    _check_limits(data, width, height)
    evidence = _metadata_evidence(data, selected_format)
    orientation = evidence["orientation"]["exif_value"]
    display_width, display_height = (
        (height, width)
        if orientation in {5, 6, 7, 8}
        else (
            width,
            height,
        )
    )
    return {
        "format": selected_format,
        "media_type": PHOTO_MEDIA_TYPES[selected_format],
        "dimensions": {
            "encoded_width": width,
            "encoded_height": height,
            "display_width": display_width,
            "display_height": display_height,
            "pixels": width * height,
        },
        **evidence,
    }


@dataclass(frozen=True, slots=True)
class PhotoDecodeResult:
    preview_png: bytes
    perceptual_hash: str
    decoder_version: str
    source_frames: int


class PillowPhotoDecoder:
    """Optional pinned decoder used only when it is explicitly installed locally."""

    def capability(self) -> dict[str, Any]:
        try:
            version = importlib.metadata.version("Pillow")
        except importlib.metadata.PackageNotFoundError:
            return {
                "state": "unavailable",
                "component": "codec.pillow",
                "version": None,
                "qualified": False,
            }
        try:
            major = int(version.split(".", 1)[0])
        except ValueError:
            major = 0
        state = "ready" if major == 12 else "incompatible"
        return {
            "state": state,
            "component": "codec.pillow",
            "version": version,
            "qualified": state == "ready",
        }

    def decode(self, data: bytes, expected_format: str) -> PhotoDecodeResult:
        capability = self.capability()
        if capability["state"] == "unavailable":
            raise PhotoContractError(
                "photo_decoder_unavailable", "the optional local photo decoder is unavailable"
            )
        if capability["state"] != "ready":
            raise PhotoContractError(
                "photo_decoder_incompatible", "the installed photo decoder is incompatible"
            )
        try:
            from PIL import Image, ImageOps

            Image.MAX_IMAGE_PIXELS = MAX_PIXELS
            with Image.open(io.BytesIO(data)) as source:
                if str(source.format).upper() != expected_format:
                    raise PhotoContractError(
                        "photo_decode_failed", "decoded format does not match the signature"
                    )
                source_frames = int(getattr(source, "n_frames", 1))
                source.seek(0)
                source.load()
                if source.width * source.height > MAX_PIXELS:
                    raise PhotoContractError(
                        "photo_pixel_limit_exceeded", "decoded image exceeds the pixel limit"
                    )
                transposed = ImageOps.exif_transpose(source)
                grayscale = transposed.convert("L").resize((9, 8))
                samples = list(grayscale.getdata())
                bits = [
                    samples[row * 9 + column] > samples[row * 9 + column + 1]
                    for row in range(8)
                    for column in range(8)
                ]
                value = sum((1 << index) for index, bit in enumerate(bits) if bit)
                perceptual_hash = f"{value:016x}"
                preview = transposed.convert("RGB")
                preview.thumbnail((MAX_PREVIEW_EDGE, MAX_PREVIEW_EDGE))
                output = io.BytesIO()
                preview.save(output, format="PNG", optimize=False, compress_level=9)
                payload = output.getvalue()
                if not payload or len(payload) > MAX_PREVIEW_BYTES:
                    raise PhotoContractError(
                        "photo_decode_failed", "sanitized preview exceeds its byte limit"
                    )
                return PhotoDecodeResult(
                    preview_png=payload,
                    perceptual_hash=perceptual_hash,
                    decoder_version=str(capability["version"]),
                    source_frames=source_frames,
                )
        except PhotoContractError:
            raise
        except Exception as exc:
            raise PhotoContractError(
                "photo_decode_failed", "the local decoder rejected the photo safely"
            ) from exc


def _validate_family(value: Any, name: str) -> dict[str, Any]:
    family = _exact_object(value, name, {"present", "bytes", "sha256", "raw_values_exported"})
    if (
        type(family["present"]) is not bool
        or type(family["bytes"]) is not int
        or family["bytes"] < 0
        or family["bytes"] > MAX_METADATA_BYTES
        or family["raw_values_exported"] is not False
    ):
        raise PhotoContractError("photo_contract_violation", f"{name} is invalid")
    if family["present"]:
        _digest(family["sha256"], f"{name} digest")
    elif family["sha256"] is not None or family["bytes"] != 0:
        raise PhotoContractError("photo_contract_violation", f"{name} absence is invalid")
    return family


def validate_photo_record(value: Any) -> dict[str, Any]:
    record = _exact_object(
        value,
        "photo record",
        {
            "schema_version",
            "kind",
            "profile_id",
            "version_id",
            "original_sha256",
            "format",
            "media_type",
            "dimensions",
            "orientation",
            "color",
            "metadata",
            "capture_time",
            "gps",
            "preview",
            "duplicates",
            "ocr_reuse",
            "codes",
            "invariants",
        },
    )
    if (
        record["schema_version"] != PHOTO_SCHEMA_VERSION
        or record["kind"] != "photo-profile"
        or record["profile_id"] != PHOTO_PROFILE_ID
        or record["format"] not in PHOTO_FORMATS
        or record["media_type"] != PHOTO_MEDIA_TYPES[record["format"]]
    ):
        raise PhotoContractError("photo_contract_violation", "photo identity is invalid")
    _bounded_text(record["version_id"], "photo version id", 200)
    _digest(record["original_sha256"], "photo original digest")
    dimensions = _exact_object(
        record["dimensions"],
        "photo dimensions",
        {"encoded_width", "encoded_height", "display_width", "display_height", "pixels"},
    )
    if any(type(dimensions[key]) is not int or dimensions[key] < 1 for key in dimensions):
        raise PhotoContractError("photo_contract_violation", "photo dimensions are invalid")
    if dimensions["pixels"] != dimensions["encoded_width"] * dimensions["encoded_height"]:
        raise PhotoContractError("photo_contract_violation", "photo pixel count is invalid")
    orientation = _exact_object(record["orientation"], "orientation", {"exif_value", "label"})
    if orientation["exif_value"] is not None and orientation["exif_value"] not in range(1, 9):
        raise PhotoContractError("photo_contract_violation", "photo orientation is invalid")
    _bounded_text(orientation["label"], "orientation label")
    color = _exact_object(
        record["color"],
        "color evidence",
        {"model", "bit_depth", "icc_profile_present", "icc_profile_sha256"},
    )
    _bounded_text(color["model"], "color model")
    if color["bit_depth"] is not None and (
        type(color["bit_depth"]) is not int or color["bit_depth"] < 1 or color["bit_depth"] > 128
    ):
        raise PhotoContractError("photo_contract_violation", "photo bit depth is invalid")
    if color["icc_profile_present"]:
        _digest(color["icc_profile_sha256"], "ICC digest")
    elif color["icc_profile_sha256"] is not None:
        raise PhotoContractError("photo_contract_violation", "ICC absence is invalid")
    metadata = _exact_object(
        record["metadata"], "metadata", {"exif", "iptc", "xmp", "device_fields_redacted"}
    )
    for family in ("exif", "iptc", "xmp"):
        _validate_family(metadata[family], family)
    if metadata["device_fields_redacted"] is not True:
        raise PhotoContractError("photo_contract_violation", "device metadata must be redacted")
    capture = _exact_object(
        record["capture_time"], "capture time", {"present", "value", "source", "verified"}
    )
    if capture["verified"] is not False or type(capture["present"]) is not bool:
        raise PhotoContractError("photo_contract_violation", "capture-time state is invalid")
    if capture["present"]:
        _bounded_text(capture["value"], "capture time")
        _bounded_text(capture["source"], "capture source")
    elif capture["value"] is not None or capture["source"] is not None:
        raise PhotoContractError("photo_contract_violation", "capture-time absence is invalid")
    gps = _exact_object(
        record["gps"],
        "GPS evidence",
        {"present", "source_precision", "coordinates", "redacted", "default_export"},
    )
    if (
        type(gps["present"]) is not bool
        or gps["source_precision"] not in {"none", "unknown", "exact", "coarse"}
        or gps["coordinates"] is not None
        or gps["redacted"] is not True
        or gps["default_export"] != "excluded"
    ):
        raise PhotoContractError("photo_contract_violation", "GPS privacy state is invalid")
    preview = _exact_object(
        record["preview"],
        "preview",
        {"state", "media_type", "metadata_stripped", "active_content", "decoder", "source_frames"},
    )
    if (
        preview["state"] not in {"available", "unavailable"}
        or preview["active_content"] is not False
    ):
        raise PhotoContractError("photo_contract_violation", "photo preview state is invalid")
    if preview["state"] == "available":
        if preview["media_type"] != "image/png" or preview["metadata_stripped"] is not True:
            raise PhotoContractError(
                "photo_contract_violation", "photo preview contract is invalid"
            )
        _bounded_text(preview["decoder"], "photo decoder")
    elif any(preview[key] is not None for key in ("media_type", "decoder", "source_frames")):
        raise PhotoContractError("photo_contract_violation", "unavailable preview is invalid")
    duplicates = _exact_object(
        record["duplicates"],
        "duplicate evidence",
        {
            "exact_algorithm",
            "perceptual_algorithm",
            "threshold",
            "perceptual_hash",
            "proposals",
            "automatic_action",
        },
    )
    if (
        duplicates["exact_algorithm"] != "sha256"
        or duplicates["perceptual_algorithm"] != "dhash-64-v1"
        or duplicates["threshold"] != PERCEPTUAL_DISTANCE_THRESHOLD
        or duplicates["automatic_action"] != "none"
        or not isinstance(duplicates["proposals"], list)
        or len(duplicates["proposals"]) > MAX_DUPLICATE_CANDIDATES
    ):
        raise PhotoContractError("photo_contract_violation", "duplicate contract is invalid")
    if duplicates["perceptual_hash"] is not None and not re.fullmatch(
        r"[0-9a-f]{16}", duplicates["perceptual_hash"]
    ):
        raise PhotoContractError("photo_contract_violation", "perceptual hash is invalid")
    seen: set[tuple[str, str]] = set()
    for proposal in duplicates["proposals"]:
        item = _exact_object(
            proposal,
            "duplicate proposal",
            {
                "kind",
                "candidate_version_id",
                "candidate_representation_id",
                "distance",
                "threshold",
                "advisory",
                "action",
            },
        )
        if (
            item["kind"] not in {"exact", "perceptual"}
            or item["advisory"] is not True
            or item["action"] != "review"
            or (item["kind"], item["candidate_representation_id"]) in seen
        ):
            raise PhotoContractError("photo_contract_violation", "duplicate proposal is invalid")
        seen.add((item["kind"], item["candidate_representation_id"]))
        _bounded_text(item["candidate_version_id"], "candidate version id", 200)
        _bounded_text(item["candidate_representation_id"], "candidate representation id", 200)
        if item["kind"] == "exact" and item["distance"] != 0:
            raise PhotoContractError(
                "photo_contract_violation", "exact duplicate distance is invalid"
            )
        if item["kind"] == "perceptual" and (
            type(item["distance"]) is not int
            or item["distance"] < 0
            or item["distance"] > item["threshold"]
        ):
            raise PhotoContractError("photo_contract_violation", "perceptual distance is invalid")
    ocr = _exact_object(
        record["ocr_reuse"],
        "OCR reuse",
        {"bundle_ids", "page_anchors", "region_anchors", "source_unchanged"},
    )
    if (
        not isinstance(ocr["bundle_ids"], list)
        or not isinstance(ocr["page_anchors"], list)
        or not isinstance(ocr["region_anchors"], list)
        or ocr["source_unchanged"] is not True
    ):
        raise PhotoContractError("photo_contract_violation", "OCR reuse contract is invalid")
    codes = _exact_object(
        record["codes"],
        "code observations",
        {"state", "adapter", "observations", "payloads_redacted"},
    )
    if (
        codes["state"] not in {"unavailable", "available"}
        or codes["payloads_redacted"] is not True
        or not isinstance(codes["observations"], list)
        or len(codes["observations"]) > MAX_CODE_OBSERVATIONS
    ):
        raise PhotoContractError("photo_contract_violation", "code observation contract is invalid")
    if codes["state"] == "available":
        _bounded_text(codes["adapter"], "code adapter")
    elif codes["adapter"] is not None or codes["observations"]:
        raise PhotoContractError("photo_contract_violation", "unavailable code adapter is invalid")
    for observation in codes["observations"]:
        item = _exact_object(
            observation,
            "code observation",
            {"kind", "symbology", "payload_sha256", "payload_redacted", "region"},
        )
        if item["kind"] not in {"qr-code", "barcode"} or item["payload_redacted"] is not True:
            raise PhotoContractError("photo_contract_violation", "code observation is invalid")
        _bounded_text(item["symbology"], "code symbology")
        _digest(item["payload_sha256"], "code payload digest")
    invariants = _exact_object(
        record["invariants"],
        "photo invariants",
        {
            "derived",
            "original_immutable",
            "canonical_records_immutable",
            "network_used",
            "ai_used",
            "metadata_writeback",
            "automatic_duplicate_action",
        },
    )
    if invariants != {
        "derived": True,
        "original_immutable": True,
        "canonical_records_immutable": True,
        "network_used": False,
        "ai_used": False,
        "metadata_writeback": False,
        "automatic_duplicate_action": False,
    }:
        raise PhotoContractError("photo_contract_violation", "photo invariants are invalid")
    return record


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


class PhotoProfileManager:
    """Explicit local photo jobs and universal derived-profile lifecycle."""

    def __init__(
        self, store: InstanceStore, *, decoder: Any | None = None, code_adapter: Any = None
    ):
        self.store = store
        self.bundles = RepresentationBundleManager(store)
        self.decoder = decoder or PillowPhotoDecoder()
        self.code_adapter = code_adapter
        self.root = store.paths.state / "photo"
        self.jobs = self.root / "jobs"

    def capability(self) -> dict[str, Any]:
        decoder = self.decoder.capability()
        return {
            "schema_version": 1,
            "profile_id": PHOTO_PROFILE_ID,
            "baseline_formats": list(PHOTO_FORMATS),
            "preserve_inspect_only": ["AVIF", "DNG", "HEIC", "HEIF", "RAW", "WEBP"],
            "decoder": decoder,
            "metadata": {"state": "available", "component": "provelume.core"},
            "preview": {
                "state": "available" if decoder.get("state") == "ready" else "unavailable",
                "missing_component": None if decoder.get("state") == "ready" else "codec.pillow",
            },
            "barcode_qr": {
                "state": "available" if self._code_capability() is not None else "unavailable",
                "automatic": False,
            },
            "network_used": False,
            "runtime_downloads": False,
            "mutated": False,
        }

    def _source(self, version_id: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        version = self.store.read_canonical("versions", version_id)
        if version is None:
            raise PhotoContractError("photo_not_found", "photo DocumentVersion was not found")
        original = self.store.read_canonical("originals", str(version.get("original_id", "")))
        if original is None:
            raise PhotoContractError("photo_not_found", "photo Original was not found")
        data = self.store.original_bytes(str(original["id"]))
        digest = _sha256(data)
        if (
            digest != original.get("sha256")
            or digest != version.get("content_hash")
            or len(data) != original.get("size_bytes")
            or len(data) != version.get("size_bytes")
        ):
            raise PhotoContractError(
                "photo_contract_violation", "photo Original identity verification failed"
            )
        return version, original, data

    def _active_records(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        result: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for bundle in self.bundles.list(limit=500):
            if bundle.get("recipe", {}).get("id") != PHOTO_RECIPE_ID:
                continue
            output = next(
                (
                    item
                    for item in bundle["outputs"]
                    if Path(item["storage_ref"]).name == "metadata.json"
                ),
                None,
            )
            if output is None:
                continue
            try:
                path = safe_instance_path(self.store.paths.root, str(output["storage_ref"]))
                record = validate_photo_record(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            result.append((bundle, record))
        return result

    def _duplicate_proposals(
        self, version_id: str, original_sha256: str, perceptual_hash: str | None
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for bundle, record in self._active_records():
            candidate_version = str(record["version_id"])
            if candidate_version == version_id:
                continue
            exact = record["original_sha256"] == original_sha256
            candidate_hash = record["duplicates"]["perceptual_hash"]
            if exact:
                kind, distance = "exact", 0
            elif perceptual_hash is not None and candidate_hash is not None:
                distance = _hamming(perceptual_hash, candidate_hash)
                if distance > PERCEPTUAL_DISTANCE_THRESHOLD:
                    continue
                kind = "perceptual"
            else:
                continue
            result.append(
                {
                    "kind": kind,
                    "candidate_version_id": candidate_version,
                    "candidate_representation_id": bundle["representation_id"],
                    "distance": distance,
                    "threshold": 0 if kind == "exact" else PERCEPTUAL_DISTANCE_THRESHOLD,
                    "advisory": True,
                    "action": "review",
                }
            )
            if len(result) >= MAX_DUPLICATE_CANDIDATES:
                break
        return sorted(result, key=lambda item: (item["kind"], item["candidate_representation_id"]))

    def _ocr_reuse(self, version_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        bundle_ids: list[str] = []
        pages: set[int] = set()
        root = self.store.paths.state / "derived" / "ocr-bundles"
        if root.exists() and not root.is_symlink():
            for path in sorted(root.glob("*/*/manifest.json"))[:500]:
                try:
                    if path.is_symlink() or path.stat().st_size > MAX_METADATA_BYTES:
                        continue
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(value, Mapping) or value.get("version_id") != version_id:
                    continue
                identifier = value.get("derivation_key")
                rows = value.get("pages")
                if not isinstance(identifier, str) or not isinstance(rows, list):
                    continue
                bundle_ids.append(identifier)
                for row in rows[:200]:
                    if isinstance(row, Mapping) and type(row.get("page_number")) is int:
                        pages.add(int(row["page_number"]))
        anchors = [{"kind": "page", "page": page} for page in sorted(pages)]
        return (
            {
                "bundle_ids": sorted(set(bundle_ids)),
                "page_anchors": sorted(pages),
                "region_anchors": [],
                "source_unchanged": True,
            },
            anchors,
        )

    def _code_capability(self) -> dict[str, Any] | None:
        if self.code_adapter is None:
            return None
        try:
            value = self.code_adapter.capability()
        except Exception:
            return None
        if (
            not isinstance(value, Mapping)
            or value.get("state") != "ready"
            or value.get("qualified") is not True
            or not isinstance(value.get("adapter_id"), str)
            or not isinstance(value.get("version"), str)
        ):
            return None
        return dict(value)

    def _code_observations(self, data: bytes) -> dict[str, Any]:
        capability = self._code_capability()
        if capability is None:
            return {
                "state": "unavailable",
                "adapter": None,
                "observations": [],
                "payloads_redacted": True,
            }
        try:
            raw = self.code_adapter.observe(data)
        except Exception as exc:
            raise PhotoContractError(
                "photo_decode_failed", "qualified code adapter failed safely"
            ) from exc
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise PhotoContractError("photo_contract_violation", "code observations are invalid")
        observations: list[dict[str, Any]] = []
        for value in raw[:MAX_CODE_OBSERVATIONS]:
            if not isinstance(value, Mapping):
                raise PhotoContractError("photo_contract_violation", "code observation is invalid")
            kind = str(value.get("kind", ""))
            symbology = str(value.get("symbology", ""))
            payload = value.get("payload")
            region = value.get("region")
            if (
                kind not in {"qr-code", "barcode"}
                or not symbology
                or not isinstance(payload, bytes)
            ):
                raise PhotoContractError("photo_contract_violation", "code observation is invalid")
            observations.append(
                {
                    "kind": kind,
                    "symbology": symbology,
                    "payload_sha256": _sha256(payload),
                    "payload_redacted": True,
                    "region": region if isinstance(region, Mapping) else None,
                }
            )
        return {
            "state": "available",
            "adapter": f"{capability['adapter_id']}@{capability['version']}",
            "observations": observations,
            "payloads_redacted": True,
        }

    def _derive(
        self,
        version_id: str,
        *,
        frozen_settings: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, tuple[str, bytes]], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        _version, original, data = self._source(version_id)
        inspected = inspect_photo_bytes(data)
        capability = self.decoder.capability()
        decoded: PhotoDecodeResult | None = None
        if capability.get("state") == "ready":
            decoded = self.decoder.decode(data, inspected["format"])
        perceptual_hash = decoded.perceptual_hash if decoded is not None else None
        if frozen_settings is None:
            proposals = self._duplicate_proposals(
                version_id, str(original["sha256"]), perceptual_hash
            )
            ocr_reuse, anchors = self._ocr_reuse(version_id)
            codes = self._code_observations(data)
        else:
            proposals = list(frozen_settings.get("duplicate_proposals", []))
            ocr_reuse = dict(frozen_settings.get("ocr_reuse", {}))
            anchors = [{"kind": "page", "page": page} for page in ocr_reuse.get("page_anchors", [])]
            codes = dict(frozen_settings.get("codes", {}))
        preview = {
            "state": "available" if decoded is not None else "unavailable",
            "media_type": "image/png" if decoded is not None else None,
            "metadata_stripped": decoded is not None,
            "active_content": False,
            "decoder": f"Pillow@{decoded.decoder_version}" if decoded is not None else None,
            "source_frames": decoded.source_frames if decoded is not None else None,
        }
        record = validate_photo_record(
            {
                "schema_version": PHOTO_SCHEMA_VERSION,
                "kind": "photo-profile",
                "profile_id": PHOTO_PROFILE_ID,
                "version_id": version_id,
                "original_sha256": str(original["sha256"]),
                **inspected,
                "preview": preview,
                "duplicates": {
                    "exact_algorithm": "sha256",
                    "perceptual_algorithm": "dhash-64-v1",
                    "threshold": PERCEPTUAL_DISTANCE_THRESHOLD,
                    "perceptual_hash": perceptual_hash,
                    "proposals": proposals,
                    "automatic_action": "none",
                },
                "ocr_reuse": ocr_reuse,
                "codes": codes,
                "invariants": {
                    "derived": True,
                    "original_immutable": True,
                    "canonical_records_immutable": True,
                    "network_used": False,
                    "ai_used": False,
                    "metadata_writeback": False,
                    "automatic_duplicate_action": False,
                },
            }
        )
        settings = {
            "privacy": "gps-and-device-redacted-v1",
            "format": inspected["format"],
            "max_pixels": MAX_PIXELS,
            "max_metadata_bytes": MAX_METADATA_BYTES,
            "max_decompression_ratio": MAX_DECOMPRESSION_RATIO,
            "decoder_component": capability.get("component", "codec.pillow"),
            "decoder_version": capability.get("version"),
            "duplicate_proposals": proposals,
            "ocr_reuse": ocr_reuse,
            "codes": codes,
        }
        payloads = {"metadata.json": ("application/json", canonical_json_bytes(record))}
        if decoded is not None:
            payloads["preview.png"] = ("image/png", decoded.preview_png)
        return payloads, settings, anchors, capability

    def create(self, version_id: str) -> dict[str, Any]:
        payloads, settings, anchors, capability = self._derive(version_id)
        available = capability.get("state") == "ready"
        try:
            return self.bundles.materialize(
                version_id,
                recipe_id=PHOTO_RECIPE_ID,
                recipe_version=PHOTO_RECIPE_VERSION,
                recipe_settings=settings,
                output_payloads=payloads,
                implementation={
                    "component": "provelume.core",
                    "component_version": "0.9.0",
                    "adapter": "perceptio-photo-profile",
                    "adapter_version": "1",
                    "settings": {"mode": "offline", "privacy": "redacted"},
                },
                warnings=("preview_component_unavailable",) if not available else (),
                anchor_targets=anchors,
                availability_state="available" if available else "degraded",
                availability_reason=None if available else "component_missing",
                missing_component=None if available else "codec.pillow",
            )
        except RepresentationContractError as exc:
            raise PhotoContractError("photo_contract_violation", str(exc)) from exc

    def queue(self, version_id: str) -> dict[str, Any]:
        self._source(version_id)
        identity = _sha256(
            canonical_json_bytes(
                {
                    "version_id": version_id,
                    "recipe": PHOTO_RECIPE_ID,
                    "version": PHOTO_RECIPE_VERSION,
                }
            )
        )
        job_id = f"photo_{identity}"
        self.jobs.mkdir(parents=True, exist_ok=True)
        target = self.jobs / f"{job_id}.json"
        if target.exists():
            return {"scheduled": False, "job": self.get_job(job_id)}
        job = {
            "schema_version": PHOTO_JOB_SCHEMA_VERSION,
            "id": job_id,
            "kind": "photo.profile",
            "version_id": version_id,
            "status": "queued",
            "requested_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "representation_id": None,
            "error_code": None,
        }
        self.store._atomic_json(target, job)
        return {"scheduled": True, "job": job}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"photo_[0-9a-f]{64}", job_id):
            return None
        try:
            value = self.store._read_json(self.jobs / f"{job_id}.json")
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return value if value.get("id") == job_id else None

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.jobs.exists():
            return []
        result = []
        for path in sorted(self.jobs.glob("photo_*.json"), reverse=True):
            value = self.get_job(path.stem)
            if value is not None:
                result.append(value)
            if len(result) >= min(max(limit, 1), 500):
                break
        return result

    def run(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise PhotoContractError("photo_not_found", "photo job was not found")
        if job.get("status") == "succeeded":
            return job
        if job.get("status") not in {"queued", "failed"}:
            raise PhotoContractError("photo_job_state_invalid", "photo job state is invalid")
        job.update({"status": "running", "started_at": utc_now(), "error_code": None})
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        try:
            bundle = self.create(str(job["version_id"]))
        except PhotoContractError as exc:
            job.update({"status": "failed", "completed_at": utc_now(), "error_code": exc.code})
            self.store._atomic_json(self.jobs / f"{job_id}.json", job)
            return job
        job.update(
            {
                "status": "succeeded",
                "completed_at": utc_now(),
                "representation_id": bundle["representation_id"],
            }
        )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        return job

    def read_model(self, *, version_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        profiles = []
        for bundle, record in self._active_records():
            if version_id is not None and record["version_id"] != version_id:
                continue
            profiles.append(
                {
                    "representation_id": bundle["representation_id"],
                    "availability": bundle["availability"],
                    "record": record,
                    "outputs": bundle["outputs"],
                }
            )
            if len(profiles) >= min(max(limit, 1), 500):
                break
        return {
            "schema_version": 1,
            "profile_id": PHOTO_PROFILE_ID,
            "support": self.capability(),
            "profiles": profiles,
            "jobs": self.list_jobs(limit=limit),
            "privacy": {
                "gps_default_export": "excluded",
                "device_metadata_exported": False,
                "source_writeback": False,
            },
            "network_used": False,
        }

    def get(self, representation_id: str) -> dict[str, Any] | None:
        for item in self.read_model(limit=500)["profiles"]:
            if item["representation_id"] == representation_id:
                return item
        return None

    def remove(self, representation_id: str) -> dict[str, Any]:
        try:
            return self.bundles.remove(representation_id)
        except RepresentationContractError as exc:
            raise PhotoContractError("photo_not_found", str(exc)) from exc

    def rebuild(self, representation_id: str) -> dict[str, Any]:
        receipt_path = self.bundles.history / f"{representation_id}.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            bundle = receipt["bundle"]
            if bundle["recipe"]["id"] != PHOTO_RECIPE_ID:
                raise KeyError("wrong recipe")
            version_id = str(bundle["version"]["id"])
            settings = dict(bundle["recipe"]["settings"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PhotoContractError(
                "photo_not_found", "photo removal history was not found"
            ) from exc
        payloads, _settings, _anchors, _capability = self._derive(
            version_id, frozen_settings=settings
        )
        raw = {name: value[1] for name, value in payloads.items()}
        expected_names = {Path(item["storage_ref"]).name for item in bundle["outputs"]}
        if set(raw) != expected_names:
            raise PhotoContractError(
                "photo_decoder_unavailable", "photo rebuild components no longer match"
            )
        try:
            return self.bundles.rebuild(representation_id, raw)
        except RepresentationContractError as exc:
            raise PhotoContractError("photo_contract_violation", str(exc)) from exc


__all__ = [
    "MAX_DECOMPRESSION_RATIO",
    "MAX_METADATA_BYTES",
    "MAX_PIXELS",
    "PERCEPTUAL_DISTANCE_THRESHOLD",
    "PHOTO_ERROR_CODES",
    "PHOTO_FORMATS",
    "PHOTO_PROFILE_ID",
    "PhotoContractError",
    "PhotoDecodeResult",
    "PhotoProfileManager",
    "PillowPhotoDecoder",
    "inspect_photo_bytes",
    "validate_photo_record",
]
