from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

OCR_CONTRACT_SCHEMA_VERSION = 1
OCR_ENGINE_ID = "tesseract-cli"
OCR_MODES = ("disabled", "automatic", "forced", "selected-page")
OCR_LANGUAGE_DETECTION_MODES = ("disabled", "bounded")
OCR_CAPABILITY_STATES = (
    "disabled",
    "adapter-unavailable",
    "engine-unavailable",
    "language-pack-missing",
    "ready",
)
OCR_TEXT_STATUSES = ("machine-unverified", "needs-review")
OCR_OBSERVATION_KINDS = ("layout", "table", "barcode", "qr-code")
OCR_ERROR_CODES = (
    "ocr_disabled",
    "ocr_adapter_unavailable",
    "ocr_engine_unavailable",
    "ocr_language_pack_missing",
    "ocr_unsupported_input",
    "ocr_corrupt_input",
    "ocr_input_too_large",
    "ocr_page_limit_exceeded",
    "ocr_pixel_limit_exceeded",
    "ocr_decompression_limit_exceeded",
    "ocr_temporary_space_exceeded",
    "ocr_deadline_exceeded",
    "ocr_invalid_selection",
    "ocr_contract_violation",
    "ocr_adapter_failure",
    "ocr_cancelled",
)

OCR_SUPPORTED_INPUTS = {
    "application/pdf": (".pdf",),
    "image/tiff": (".tif", ".tiff"),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/bmp": (".bmp",),
}
OCR_STAGED_PAGE_INPUTS = tuple(
    media_type for media_type in OCR_SUPPORTED_INPUTS if media_type != "application/pdf"
)

OCR_ERROR_MESSAGES = {
    "ocr_disabled": {
        "en": "OCR is disabled in this Instance.",
        "it": "L'OCR è disabilitato in questa Istanza.",
    },
    "ocr_adapter_unavailable": {
        "en": "No OCR execution adapter is installed; this build exposes the contract only.",
        "it": (
            "Nessun adapter di esecuzione OCR è installato; "
            "questa build espone solo il contratto."
        ),
    },
    "ocr_engine_unavailable": {
        "en": "The configured local OCR engine is not installed or cannot be executed.",
        "it": "Il motore OCR locale configurato non è installato o non può essere eseguito.",
    },
    "ocr_language_pack_missing": {
        "en": "One or more explicitly selected OCR language packs are not installed.",
        "it": "Uno o più pacchetti lingua OCR selezionati non sono installati.",
    },
    "ocr_unsupported_input": {
        "en": "The input media type, extension or signature is not supported for OCR.",
        "it": "Il tipo, l'estensione o la firma dell'input non è supportato per l'OCR.",
    },
    "ocr_corrupt_input": {
        "en": "The OCR input is corrupt or cannot be decoded safely.",
        "it": "L'input OCR è corrotto o non può essere decodificato in sicurezza.",
    },
    "ocr_input_too_large": {
        "en": "The OCR input exceeds the configured byte limit.",
        "it": "L'input OCR supera il limite di byte configurato.",
    },
    "ocr_page_limit_exceeded": {
        "en": "The OCR input or selection exceeds the configured page limit.",
        "it": "L'input o la selezione OCR supera il limite di pagine configurato.",
    },
    "ocr_pixel_limit_exceeded": {
        "en": "The OCR input exceeds a per-page or total pixel limit.",
        "it": "L'input OCR supera un limite di pixel per pagina o complessivo.",
    },
    "ocr_decompression_limit_exceeded": {
        "en": "The decoded image would exceed a byte or decompression-ratio limit.",
        "it": "L'immagine decodificata supererebbe un limite di byte o di decompressione.",
    },
    "ocr_temporary_space_exceeded": {
        "en": "The OCR job cannot stay within its temporary-storage allowance.",
        "it": "Il job OCR non può rispettare il limite di spazio temporaneo.",
    },
    "ocr_deadline_exceeded": {
        "en": "The OCR page or job exceeded its configured deadline.",
        "it": "La pagina o il job OCR ha superato il tempo massimo configurato.",
    },
    "ocr_invalid_selection": {
        "en": "The selected-page request is empty, duplicated or outside the document.",
        "it": "La selezione pagine è vuota, duplicata o esterna al documento.",
    },
    "ocr_contract_violation": {
        "en": "The OCR request or result does not satisfy the public contract.",
        "it": "La richiesta o il risultato OCR non rispetta il contratto pubblico.",
    },
    "ocr_adapter_failure": {
        "en": "The local OCR adapter failed without producing a valid result.",
        "it": "L'adapter OCR locale non ha prodotto un risultato valido.",
    },
    "ocr_cancelled": {
        "en": "The OCR job was cancelled without changing canonical knowledge.",
        "it": "Il job OCR è stato annullato senza modificare la conoscenza canonica.",
    },
}

_LANGUAGE = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
_COMPONENT_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,79}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RECORD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")

_MIB = 1024 * 1024
OCR_LIMIT_CEILINGS = {
    "max_input_bytes": 256 * _MIB,
    "max_pages": 200,
    "max_page_pixels": 80_000_000,
    "max_total_pixels": 500_000_000,
    "max_decompressed_page_bytes": 320 * _MIB,
    "max_decompression_ratio": 100,
    "max_temp_bytes": 1024 * _MIB,
    "max_seconds_per_page": 60,
    "max_total_seconds": 900,
    "max_output_chars_per_page": 500_000,
}


class OcrContractError(ValueError):
    """A closed OCR contract failure safe to expose without source content."""

    def __init__(self, code: str, message: str):
        if code not in OCR_ERROR_CODES:
            raise ValueError("OCR error code is outside the closed registry")
        super().__init__(message)
        self.code = code


class OcrUnavailableError(RuntimeError):
    """Raised when an explicitly requested OCR capability cannot execute."""

    def __init__(self, code: str, messages: Mapping[str, str]):
        if code not in OCR_ERROR_CODES or set(messages) != {"en", "it"}:
            raise ValueError("invalid OCR availability error")
        super().__init__(messages["en"])
        self.code = code
        self.messages = dict(messages)


def _closed_integer(value: Any, name: str, *, ceiling: int) -> int:
    if type(value) is not int or value < 1 or value > ceiling:
        raise OcrContractError(
            "ocr_contract_violation",
            f"{name} must be an integer between 1 and {ceiling}",
        )
    return value


def _closed_ratio(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OcrContractError("ocr_contract_violation", f"{name} must be a number")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0 or selected > 1.0:
        raise OcrContractError(
            "ocr_contract_violation", f"{name} must be between 0 and 1"
        )
    return selected


def _closed_identifier(value: Any, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise OcrContractError("ocr_contract_violation", f"{name} is invalid")
    return value


def _languages(value: Any, name: str = "languages") -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or len(value) > 8
        or any(not isinstance(item, str) or _LANGUAGE.fullmatch(item) is None for item in value)
    ):
        raise OcrContractError(
            "ocr_contract_violation",
            f"{name} must contain one to eight explicit language-pack identifiers",
        )
    selected = tuple(value)
    if selected != tuple(sorted(set(selected))):
        raise OcrContractError(
            "ocr_contract_violation", f"{name} must be unique and sorted"
        )
    return selected


@dataclass(frozen=True, slots=True)
class OcrLimits:
    max_input_bytes: int = OCR_LIMIT_CEILINGS["max_input_bytes"]
    max_pages: int = OCR_LIMIT_CEILINGS["max_pages"]
    max_page_pixels: int = OCR_LIMIT_CEILINGS["max_page_pixels"]
    max_total_pixels: int = OCR_LIMIT_CEILINGS["max_total_pixels"]
    max_decompressed_page_bytes: int = OCR_LIMIT_CEILINGS[
        "max_decompressed_page_bytes"
    ]
    max_decompression_ratio: int = OCR_LIMIT_CEILINGS["max_decompression_ratio"]
    max_temp_bytes: int = OCR_LIMIT_CEILINGS["max_temp_bytes"]
    max_seconds_per_page: int = OCR_LIMIT_CEILINGS["max_seconds_per_page"]
    max_total_seconds: int = OCR_LIMIT_CEILINGS["max_total_seconds"]
    max_output_chars_per_page: int = OCR_LIMIT_CEILINGS[
        "max_output_chars_per_page"
    ]

    def __post_init__(self) -> None:
        for name, ceiling in OCR_LIMIT_CEILINGS.items():
            _closed_integer(getattr(self, name), name, ceiling=ceiling)
        if self.max_total_pixels < self.max_page_pixels:
            raise OcrContractError(
                "ocr_contract_violation",
                "max_total_pixels cannot be lower than max_page_pixels",
            )
        if self.max_total_seconds < self.max_seconds_per_page:
            raise OcrContractError(
                "ocr_contract_violation",
                "max_total_seconds cannot be lower than max_seconds_per_page",
            )

    @classmethod
    def from_mapping(cls, value: Any) -> OcrLimits:
        if not isinstance(value, Mapping) or set(value) != set(OCR_LIMIT_CEILINGS):
            raise OcrContractError(
                "ocr_contract_violation", "OCR limit fields are incomplete or unsupported"
            )
        return cls(**{name: value[name] for name in OCR_LIMIT_CEILINGS})

    def as_record(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OcrAutomaticPolicy:
    min_reliable_characters: int = 32
    min_printable_ratio: float = 0.85

    def __post_init__(self) -> None:
        _closed_integer(
            self.min_reliable_characters,
            "min_reliable_characters",
            ceiling=10_000,
        )
        object.__setattr__(
            self,
            "min_printable_ratio",
            _closed_ratio(self.min_printable_ratio, "min_printable_ratio"),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> OcrAutomaticPolicy:
        expected = {"min_reliable_characters", "min_printable_ratio"}
        if not isinstance(value, Mapping) or set(value) != expected:
            raise OcrContractError(
                "ocr_contract_violation",
                "automatic OCR policy fields are incomplete or unsupported",
            )
        return cls(
            min_reliable_characters=value["min_reliable_characters"],
            min_printable_ratio=value["min_printable_ratio"],
        )

    def as_record(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OcrLanguageDetection:
    mode: str = "disabled"
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in OCR_LANGUAGE_DETECTION_MODES:
            raise OcrContractError(
                "ocr_contract_violation", "unsupported OCR language-detection mode"
            )
        if self.mode == "disabled" and self.candidates:
            raise OcrContractError(
                "ocr_contract_violation",
                "disabled language detection cannot contain candidates",
            )
        if self.mode == "bounded":
            selected = _languages(self.candidates, "language detection candidates")
            if len(selected) > 4:
                raise OcrContractError(
                    "ocr_contract_violation",
                    "bounded language detection supports at most four candidates",
                )

    @classmethod
    def from_mapping(cls, value: Any) -> OcrLanguageDetection:
        if not isinstance(value, Mapping) or set(value) != {"mode", "candidates"}:
            raise OcrContractError(
                "ocr_contract_violation",
                "language-detection fields are incomplete or unsupported",
            )
        candidates = value["candidates"]
        if not isinstance(candidates, list):
            raise OcrContractError(
                "ocr_contract_violation", "language-detection candidates must be a list"
            )
        return cls(mode=value["mode"], candidates=tuple(candidates))

    def as_record(self) -> dict[str, Any]:
        return {"mode": self.mode, "candidates": list(self.candidates)}


@dataclass(frozen=True, slots=True)
class OcrSettings:
    schema_version: int = OCR_CONTRACT_SCHEMA_VERSION
    mode: str = "disabled"
    engine: str = OCR_ENGINE_ID
    languages: tuple[str, ...] = ("eng",)
    language_detection: OcrLanguageDetection = OcrLanguageDetection()
    automatic: OcrAutomaticPolicy = OcrAutomaticPolicy()
    limits: OcrLimits = OcrLimits()

    def __post_init__(self) -> None:
        if self.schema_version != OCR_CONTRACT_SCHEMA_VERSION:
            raise OcrContractError(
                "ocr_contract_violation", "unsupported OCR settings schema version"
            )
        if self.mode not in OCR_MODES:
            raise OcrContractError("ocr_contract_violation", "unsupported OCR mode")
        _closed_identifier(self.engine, "OCR engine", _COMPONENT_ID)
        selected = _languages(self.languages)
        object.__setattr__(self, "languages", selected)
        if self.language_detection.mode == "bounded" and not set(
            self.language_detection.candidates
        ).issubset(selected):
            raise OcrContractError(
                "ocr_contract_violation",
                "language-detection candidates must be selected language packs",
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "engine": self.engine,
            "languages": list(self.languages),
            "language_detection": self.language_detection.as_record(),
            "automatic": self.automatic.as_record(),
            "limits": self.limits.as_record(),
        }


def default_ocr_config() -> dict[str, Any]:
    """Return a new disabled-by-default, local-only OCR configuration."""

    return OcrSettings().as_record()


def ocr_settings_from_config(config: Any) -> OcrSettings:
    """Read the optional OCR section without mutating an existing Instance."""

    if not isinstance(config, Mapping):
        raise OcrContractError("ocr_contract_violation", "Instance configuration is invalid")
    value = config.get("ocr")
    if value is None:
        return OcrSettings()
    expected = {
        "schema_version",
        "mode",
        "engine",
        "languages",
        "language_detection",
        "automatic",
        "limits",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise OcrContractError(
            "ocr_contract_violation", "OCR settings fields are incomplete or unsupported"
        )
    languages = value["languages"]
    if not isinstance(languages, list):
        raise OcrContractError("ocr_contract_violation", "OCR languages must be a list")
    return OcrSettings(
        schema_version=value["schema_version"],
        mode=value["mode"],
        engine=value["engine"],
        languages=tuple(languages),
        language_detection=OcrLanguageDetection.from_mapping(value["language_detection"]),
        automatic=OcrAutomaticPolicy.from_mapping(value["automatic"]),
        limits=OcrLimits.from_mapping(value["limits"]),
    )


def settings_fingerprint(settings: OcrSettings) -> str:
    payload = json.dumps(
        settings.as_record(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def should_schedule_ocr(
    settings: OcrSettings,
    *,
    reliable_text_characters: int = 0,
    printable_ratio: float = 0.0,
    selected_pages: Sequence[int] = (),
    document_page_count: int | None = None,
) -> bool:
    """Resolve mode policy only; this function never discovers or invokes an engine."""

    if type(reliable_text_characters) is not int or reliable_text_characters < 0:
        raise OcrContractError(
            "ocr_contract_violation", "reliable text character count is invalid"
        )
    ratio = _closed_ratio(printable_ratio, "printable_ratio")
    if settings.mode == "disabled":
        return False
    if settings.mode == "forced":
        return True
    if settings.mode == "automatic":
        return (
            reliable_text_characters < settings.automatic.min_reliable_characters
            or ratio < settings.automatic.min_printable_ratio
        )
    validate_page_selection(
        selected_pages,
        page_count=document_page_count,
        max_pages=settings.limits.max_pages,
    )
    return True


def validate_page_selection(
    pages: Sequence[int], *, page_count: int | None, max_pages: int
) -> tuple[int, ...]:
    if (
        isinstance(pages, (str, bytes))
        or not pages
        or len(pages) > max_pages
        or any(type(page) is not int or page < 1 for page in pages)
    ):
        raise OcrContractError(
            "ocr_invalid_selection", "selected pages must be a nonempty bounded list"
        )
    selected = tuple(pages)
    if selected != tuple(sorted(set(selected))):
        raise OcrContractError(
            "ocr_invalid_selection", "selected pages must be unique and sorted"
        )
    if page_count is not None and (
        type(page_count) is not int or page_count < 1 or selected[-1] > page_count
    ):
        raise OcrContractError(
            "ocr_invalid_selection", "selected pages exceed the source document"
        )
    return selected


def _signature_matches(media_type: str, signature: bytes) -> bool:
    if media_type == "application/pdf":
        return signature.startswith(b"%PDF-")
    if media_type == "image/tiff":
        return signature.startswith((b"II*\x00", b"MM\x00*"))
    if media_type == "image/png":
        return signature.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return signature.startswith(b"\xff\xd8\xff")
    if media_type == "image/bmp":
        return signature.startswith(b"BM")
    return False


@dataclass(frozen=True, slots=True)
class OcrInputDescriptor:
    media_type: str
    suffix: str
    signature: bytes
    input_bytes: int
    page_count: int
    max_page_pixels: int
    total_pixels: int
    max_decompressed_page_bytes: int
    max_decompression_ratio: int

    def validate(self, limits: OcrLimits) -> dict[str, Any]:
        suffix = self.suffix.casefold()
        allowed_suffixes = OCR_SUPPORTED_INPUTS.get(self.media_type)
        if allowed_suffixes is None or suffix not in allowed_suffixes:
            raise OcrContractError(
                "ocr_unsupported_input", "OCR media type and extension are not supported"
            )
        if not isinstance(self.signature, bytes) or not _signature_matches(
            self.media_type, self.signature
        ):
            raise OcrContractError(
                "ocr_unsupported_input", "OCR input signature does not match its media type"
            )
        for name in (
            "input_bytes",
            "page_count",
            "max_page_pixels",
            "total_pixels",
            "max_decompressed_page_bytes",
            "max_decompression_ratio",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise OcrContractError(
                    "ocr_corrupt_input", f"OCR input descriptor {name} is invalid"
                )
        if self.input_bytes > limits.max_input_bytes:
            raise OcrContractError("ocr_input_too_large", "OCR input byte limit exceeded")
        if self.page_count > limits.max_pages:
            raise OcrContractError(
                "ocr_page_limit_exceeded", "OCR page limit exceeded"
            )
        if (
            self.max_page_pixels > limits.max_page_pixels
            or self.total_pixels > limits.max_total_pixels
        ):
            raise OcrContractError(
                "ocr_pixel_limit_exceeded", "OCR pixel limit exceeded"
            )
        if self.total_pixels < self.max_page_pixels:
            raise OcrContractError(
                "ocr_corrupt_input",
                "OCR total pixels cannot be lower than the largest page",
            )
        if (
            self.max_decompressed_page_bytes > limits.max_decompressed_page_bytes
            or self.max_decompression_ratio > limits.max_decompression_ratio
        ):
            raise OcrContractError(
                "ocr_decompression_limit_exceeded",
                "OCR decompression limit exceeded",
            )
        return {
            "media_type": self.media_type,
            "suffix": suffix,
            "input_bytes": self.input_bytes,
            "page_count": self.page_count,
            "max_page_pixels": self.max_page_pixels,
            "total_pixels": self.total_pixels,
            "max_decompressed_page_bytes": self.max_decompressed_page_bytes,
            "max_decompression_ratio": self.max_decompression_ratio,
        }


@dataclass(frozen=True, slots=True)
class OcrSourcePageIdentity:
    original_sha256: str
    version_id: str
    page_number: int
    page_image_sha256: str
    source_media_type: str

    def __post_init__(self) -> None:
        _closed_identifier(self.original_sha256, "Original SHA-256", _SHA256)
        _closed_identifier(self.page_image_sha256, "page image SHA-256", _SHA256)
        _closed_identifier(self.version_id, "Version ID", _RECORD_ID)
        _closed_integer(self.page_number, "page_number", ceiling=1_000_000)
        if self.source_media_type not in OCR_SUPPORTED_INPUTS:
            raise OcrContractError(
                "ocr_contract_violation", "source page media type is unsupported"
            )

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OcrAdapterCapability:
    adapter_id: str
    adapter_version: str
    engine_id: str
    engine_version: str | None
    engine_available: bool
    installed_languages: tuple[str, ...]
    input_media_types: tuple[str, ...]
    emits_coordinates: bool
    emits_confidence: bool
    emits_layout: bool = False
    emits_tables: bool = False
    emits_barcodes: bool = False
    emits_qr_codes: bool = False

    def __post_init__(self) -> None:
        _closed_identifier(self.adapter_id, "adapter ID", _COMPONENT_ID)
        _closed_identifier(self.adapter_version, "adapter version", _VERSION)
        _closed_identifier(self.engine_id, "engine ID", _COMPONENT_ID)
        if self.engine_version is not None:
            _closed_identifier(self.engine_version, "engine version", _VERSION)
        if type(self.engine_available) is not bool:
            raise OcrContractError(
                "ocr_contract_violation", "engine availability must be boolean"
            )
        if self.engine_available and self.engine_version is None:
            raise OcrContractError(
                "ocr_contract_violation", "an available engine requires an exact version"
            )
        if self.installed_languages:
            selected = _languages(self.installed_languages, "installed languages")
            object.__setattr__(self, "installed_languages", selected)
        if (
            not self.input_media_types
            or tuple(sorted(set(self.input_media_types))) != self.input_media_types
            or any(item not in OCR_SUPPORTED_INPUTS for item in self.input_media_types)
        ):
            raise OcrContractError(
                "ocr_contract_violation", "adapter input media types are invalid"
            )
        for name in (
            "emits_coordinates",
            "emits_confidence",
            "emits_layout",
            "emits_tables",
            "emits_barcodes",
            "emits_qr_codes",
        ):
            if type(getattr(self, name)) is not bool:
                raise OcrContractError(
                    "ocr_contract_violation", f"{name} must be boolean"
                )


class OcrEngineAdapter(Protocol):
    """Replaceable local-only S02 seam; S01 intentionally ships no implementation."""

    def capability(self) -> OcrAdapterCapability: ...

    def recognise_page(
        self, request: OcrPageRequest, staged_page_path: Path
    ) -> OcrPageResult: ...


def ocr_capability_report(
    settings: OcrSettings,
    adapter: OcrEngineAdapter | None = None,
) -> dict[str, Any]:
    """Report capability without implicit discovery, execution, download or fallback."""

    capability: OcrAdapterCapability | None = None
    missing_languages: tuple[str, ...] = ()
    code: str | None
    if settings.mode == "disabled":
        state = "disabled"
        code = "ocr_disabled"
    elif adapter is None:
        state = "adapter-unavailable"
        code = "ocr_adapter_unavailable"
    else:
        capability = adapter.capability()
        if capability.engine_id != settings.engine or not capability.engine_available:
            state = "engine-unavailable"
            code = "ocr_engine_unavailable"
        elif not set(settings.languages).issubset(capability.installed_languages):
            state = "language-pack-missing"
            code = "ocr_language_pack_missing"
            missing_languages = tuple(
                sorted(set(settings.languages) - set(capability.installed_languages))
            )
        else:
            state = "ready"
            code = None
    return {
        "schema_version": OCR_CONTRACT_SCHEMA_VERSION,
        "state": state,
        "available": state == "ready",
        "mode": settings.mode,
        "configured_engine": settings.engine,
        "configured_languages": list(settings.languages),
        "missing_languages": list(missing_languages),
        "adapter": None
        if capability is None
        else {
            "id": capability.adapter_id,
            "version": capability.adapter_version,
            "engine_id": capability.engine_id,
            "engine_version": capability.engine_version,
            "installed_languages": list(capability.installed_languages),
            "input_media_types": list(capability.input_media_types),
            "outputs": {
                "coordinates": capability.emits_coordinates,
                "confidence": capability.emits_confidence,
                "layout": capability.emits_layout,
                "tables": capability.emits_tables,
                "barcodes": capability.emits_barcodes,
                "qr_codes": capability.emits_qr_codes,
            },
        },
        "error": None
        if code is None
        else {"code": code, "messages": dict(OCR_ERROR_MESSAGES[code])},
        "network_required": False,
        "runtime_downloads": False,
        "remote_fallback": False,
        "original_mutation": False,
        "canonical_mutation": False,
    }


def require_ocr_available(report: Mapping[str, Any]) -> None:
    if report.get("state") == "ready" and report.get("available") is True:
        return
    error = report.get("error")
    if not isinstance(error, Mapping):
        raise OcrUnavailableError(
            "ocr_contract_violation", OCR_ERROR_MESSAGES["ocr_contract_violation"]
        )
    code = error.get("code")
    messages = error.get("messages")
    if not isinstance(code, str) or not isinstance(messages, Mapping):
        raise OcrUnavailableError(
            "ocr_contract_violation", OCR_ERROR_MESSAGES["ocr_contract_violation"]
        )
    raise OcrUnavailableError(code, messages)


@dataclass(frozen=True, slots=True)
class OcrPageRequest:
    source_page: OcrSourcePageIdentity
    staged_media_type: str
    settings_sha256: str
    languages: tuple[str, ...]
    deadline_seconds: int
    max_output_chars: int

    def __post_init__(self) -> None:
        if self.staged_media_type not in OCR_STAGED_PAGE_INPUTS:
            raise OcrContractError(
                "ocr_contract_violation",
                "staged OCR pages must use an explicitly supported raster media type",
            )
        _closed_identifier(self.settings_sha256, "settings SHA-256", _SHA256)
        object.__setattr__(self, "languages", _languages(self.languages))
        _closed_integer(self.deadline_seconds, "deadline_seconds", ceiling=900)
        _closed_integer(self.max_output_chars, "max_output_chars", ceiling=500_000)

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": OCR_CONTRACT_SCHEMA_VERSION,
            "source_page": self.source_page.as_record(),
            "staged_media_type": self.staged_media_type,
            "settings_sha256": self.settings_sha256,
            "languages": list(self.languages),
            "deadline_seconds": self.deadline_seconds,
            "max_output_chars": self.max_output_chars,
        }


@dataclass(frozen=True, slots=True)
class OcrBoundingBox:
    left: int
    top: int
    width: int
    height: int
    page_width: int
    page_height: int
    coordinate_space: str = "source-pixels"

    def __post_init__(self) -> None:
        if self.coordinate_space != "source-pixels":
            raise OcrContractError(
                "ocr_contract_violation", "unsupported OCR coordinate space"
            )
        for name in ("left", "top"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise OcrContractError(
                    "ocr_contract_violation", f"bounding box {name} is invalid"
                )
        for name in ("width", "height", "page_width", "page_height"):
            _closed_integer(getattr(self, name), f"bounding box {name}", ceiling=1_000_000)
        if self.left + self.width > self.page_width or self.top + self.height > self.page_height:
            raise OcrContractError(
                "ocr_contract_violation", "OCR bounding box exceeds its source page"
            )


@dataclass(frozen=True, slots=True)
class OcrTextSpan:
    text: str
    status: str
    confidence: float | None = None
    box: OcrBoundingBox | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text or len(self.text) > 100_000:
            raise OcrContractError("ocr_contract_violation", "OCR text span is invalid")
        if self.status not in OCR_TEXT_STATUSES:
            raise OcrContractError(
                "ocr_contract_violation", "OCR text cannot be marked as verified"
            )
        if self.confidence is not None:
            object.__setattr__(
                self, "confidence", _closed_ratio(self.confidence, "OCR confidence")
            )


@dataclass(frozen=True, slots=True)
class OcrPageWarning:
    code: str
    message: str

    def __post_init__(self) -> None:
        _closed_identifier(self.code, "OCR warning code", _COMPONENT_ID)
        if not isinstance(self.message, str) or not self.message.strip() or len(self.message) > 500:
            raise OcrContractError("ocr_contract_violation", "OCR warning message is invalid")


@dataclass(frozen=True, slots=True)
class OcrObservation:
    kind: str
    adapter_id: str
    adapter_version: str
    schema_id: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.kind not in OCR_OBSERVATION_KINDS:
            raise OcrContractError(
                "ocr_contract_violation", "unsupported OCR observation kind"
            )
        _closed_identifier(self.adapter_id, "observation adapter ID", _COMPONENT_ID)
        _closed_identifier(self.adapter_version, "observation adapter version", _VERSION)
        _closed_identifier(self.schema_id, "observation schema ID", _COMPONENT_ID)
        if not isinstance(self.payload, Mapping):
            raise OcrContractError(
                "ocr_contract_violation", "OCR observation payload must be an object"
            )
        try:
            encoded = json.dumps(self.payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise OcrContractError(
                "ocr_contract_violation", "OCR observation payload is not JSON-safe"
            ) from exc
        if len(encoded.encode("utf-8")) > _MIB:
            raise OcrContractError(
                "ocr_contract_violation", "OCR observation payload exceeds 1 MiB"
            )


@dataclass(frozen=True, slots=True)
class OcrProvenance:
    engine_id: str
    engine_version: str
    adapter_id: str
    adapter_version: str
    languages: tuple[str, ...]
    settings_sha256: str
    source_page: OcrSourcePageIdentity

    def __post_init__(self) -> None:
        _closed_identifier(self.engine_id, "engine ID", _COMPONENT_ID)
        _closed_identifier(self.engine_version, "engine version", _VERSION)
        _closed_identifier(self.adapter_id, "adapter ID", _COMPONENT_ID)
        _closed_identifier(self.adapter_version, "adapter version", _VERSION)
        object.__setattr__(self, "languages", _languages(self.languages))
        _closed_identifier(self.settings_sha256, "settings SHA-256", _SHA256)

    def as_record(self) -> dict[str, Any]:
        value = asdict(self)
        value["languages"] = list(self.languages)
        return value


@dataclass(frozen=True, slots=True)
class OcrPageResult:
    source_page: OcrSourcePageIdentity
    text: str
    text_status: str
    spans: tuple[OcrTextSpan, ...]
    warnings: tuple[OcrPageWarning, ...]
    observations: tuple[OcrObservation, ...]
    provenance: OcrProvenance

    def __post_init__(self) -> None:
        if self.text_status not in OCR_TEXT_STATUSES:
            raise OcrContractError(
                "ocr_contract_violation", "OCR page text cannot be marked as verified"
            )
        if not isinstance(self.text, str) or len(self.text) > 500_000:
            raise OcrContractError("ocr_contract_violation", "OCR page text is invalid")
        if (
            len(self.spans) > 100_000
            or len(self.warnings) > 1_000
            or len(self.observations) > 10_000
        ):
            raise OcrContractError(
                "ocr_contract_violation", "OCR page result collection limit exceeded"
            )
        if self.provenance.source_page != self.source_page:
            raise OcrContractError(
                "ocr_contract_violation", "OCR result provenance identifies another page"
            )

    def as_record(self) -> dict[str, Any]:
        grouped = {kind: [] for kind in OCR_OBSERVATION_KINDS}
        for observation in self.observations:
            grouped[observation.kind].append(
                {
                    "adapter_id": observation.adapter_id,
                    "adapter_version": observation.adapter_version,
                    "schema_id": observation.schema_id,
                    "payload": dict(observation.payload),
                }
            )
        return {
            "schema_version": OCR_CONTRACT_SCHEMA_VERSION,
            "source_page": self.source_page.as_record(),
            "text": self.text,
            "text_status": self.text_status,
            "spans": [
                {
                    "text": span.text,
                    "status": span.status,
                    "confidence": span.confidence,
                    "box": None if span.box is None else asdict(span.box),
                }
                for span in self.spans
            ],
            "warnings": [asdict(warning) for warning in self.warnings],
            "observations": grouped,
            "provenance": self.provenance.as_record(),
            "authoritative": False,
            "derived": True,
            "removable": True,
            "rebuildable": True,
        }


def validate_ocr_page_result(
    request: OcrPageRequest,
    result: OcrPageResult,
    capability: OcrAdapterCapability,
) -> None:
    """Validate an adapter result against the exact request and reported component identity."""

    if result.source_page != request.source_page:
        raise OcrContractError(
            "ocr_contract_violation", "OCR result identifies another source page"
        )
    if len(result.text) > request.max_output_chars:
        raise OcrContractError(
            "ocr_contract_violation", "OCR result exceeds the requested text limit"
        )
    provenance = result.provenance
    if (
        provenance.settings_sha256 != request.settings_sha256
        or provenance.languages != request.languages
        or provenance.engine_id != capability.engine_id
        or provenance.engine_version != capability.engine_version
        or provenance.adapter_id != capability.adapter_id
        or provenance.adapter_version != capability.adapter_version
    ):
        raise OcrContractError(
            "ocr_contract_violation",
            "OCR result provenance does not match the request and adapter capability",
        )


def ocr_derivation_key(
    source_page: OcrSourcePageIdentity,
    settings: OcrSettings,
    capability: OcrAdapterCapability,
) -> str:
    if not capability.engine_available or capability.engine_version is None:
        raise OcrContractError(
            "ocr_engine_unavailable", "cannot identify a derivation without an engine version"
        )
    payload = {
        "contract_schema_version": OCR_CONTRACT_SCHEMA_VERSION,
        "source_page": source_page.as_record(),
        "settings_sha256": settings_fingerprint(settings),
        "adapter": {"id": capability.adapter_id, "version": capability.adapter_version},
        "engine": {"id": capability.engine_id, "version": capability.engine_version},
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"ocr_{digest}"


def ocr_checkpoint_record(
    derivation_key: str, committed_pages: Sequence[int], *, total_pages: int
) -> dict[str, Any]:
    if (
        not isinstance(derivation_key, str)
        or re.fullmatch(r"ocr_[0-9a-f]{64}", derivation_key) is None
    ):
        raise OcrContractError("ocr_contract_violation", "OCR derivation key is invalid")
    selected = validate_page_selection(
        committed_pages, page_count=total_pages, max_pages=total_pages
    )
    next_page = next((page for page in range(1, total_pages + 1) if page not in selected), None)
    return {
        "schema_version": OCR_CONTRACT_SCHEMA_VERSION,
        "derivation_key": derivation_key,
        "phase": "ocr.page.committed",
        "sequence": len(selected),
        "committed_pages": list(selected),
        "next_page": next_page,
        "terminal": next_page is None,
    }


@contextmanager
def isolated_ocr_temp_directory(base: Path) -> Iterator[Path]:
    """Create a private, per-job temporary directory and always remove it."""

    selected = Path(base)
    selected.mkdir(parents=True, exist_ok=True)
    if selected.is_symlink() or not selected.is_dir():
        raise OcrContractError(
            "ocr_contract_violation", "OCR temporary root must be a real directory"
        )
    with tempfile.TemporaryDirectory(prefix="ocr-job-", dir=selected) as directory:
        path = Path(directory)
        os.chmod(path, 0o700)
        yield path
