from __future__ import annotations

import csv
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from .ocr_contract import (
    OCR_ENGINE_ID,
    OCR_SUPPORTED_INPUTS,
    OcrAdapterCapability,
    OcrBoundingBox,
    OcrContractError,
    OcrPageRequest,
    OcrPageResult,
    OcrPageWarning,
    OcrProvenance,
    OcrRendererCapability,
    OcrSettings,
    OcrTextSpan,
    validate_ocr_page_result,
)
from .ocr_process import minimal_child_environment, run_bounded_process

TESSERACT_ADAPTER_ID = "provelume.tesseract-cli"
TESSERACT_ADAPTER_VERSION = "1"
_VERSION = re.compile(r"(?im)^tesseract\s+([0-9]+(?:\.[0-9]+){1,3})\b")
_LANGUAGE = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
_TSV_HEADER = (
    "level",
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
)


def _compatible(value: str) -> bool:
    try:
        numbers = tuple(int(item) for item in value.split("."))
    except ValueError:
        return False
    return numbers >= (5, 3) and numbers < (6,)


class TesseractCliAdapter:
    """Replaceable, local-only Tesseract process adapter."""

    def __init__(
        self,
        settings: OcrSettings,
        renderer: OcrRendererCapability,
        temporary_root: Path,
        *,
        cancelled: Callable[[], bool] | None = None,
    ):
        self.settings = settings
        self.renderer = renderer
        self.temporary_root = Path(temporary_root)
        self.cancelled = cancelled
        self._capability: OcrAdapterCapability | None = None

    def _resolve_executable(self) -> str | None:
        configured = self.settings.engine_executable
        has_separator = any(separator in configured for separator in ("/", "\\"))
        candidate = configured if has_separator else shutil.which(configured)
        if not candidate:
            return None
        path = Path(candidate).expanduser().resolve()
        if not path.is_file() or path.is_symlink():
            return None
        if os.name == "posix" and not os.access(path, os.X_OK):
            return None
        return str(path)

    def _environment(self, work_directory: Path) -> dict[str, str]:
        extra = {}
        if self.settings.tessdata_path is not None:
            extra["TESSDATA_PREFIX"] = str(
                Path(self.settings.tessdata_path).expanduser().resolve()
            )
        return minimal_child_environment(work_directory, extra=extra)

    def capability(self) -> OcrAdapterCapability:
        if self._capability is not None:
            return self._capability
        executable = self._resolve_executable()
        unavailable = OcrAdapterCapability(
            adapter_id=TESSERACT_ADAPTER_ID,
            adapter_version=TESSERACT_ADAPTER_VERSION,
            engine_id=OCR_ENGINE_ID,
            engine_version=None,
            engine_available=False,
            engine_executable=None,
            version_compatible=False,
            tessdata_path=None,
            installed_languages=(),
            input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
            emits_coordinates=True,
            emits_confidence=True,
        )
        if executable is None:
            self._capability = unavailable
            return unavailable
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        try:
            version_result = run_bounded_process(
                [executable, "--version"],
                temporary_directory=self.temporary_root,
                timeout_seconds=min(10, self.settings.limits.max_seconds_per_page),
                stdout_limit=64 * 1024,
                stderr_limit=64 * 1024,
                environment=self._environment(self.temporary_root),
            )
            version_output = (version_result.stdout + b"\n" + version_result.stderr).decode(
                "utf-8", errors="replace"
            )
            match = _VERSION.search(version_output)
            if version_result.returncode != 0 or match is None:
                self._capability = unavailable
                return unavailable
            version = match.group(1)
            language_result = run_bounded_process(
                [executable, "--list-langs"],
                temporary_directory=self.temporary_root,
                timeout_seconds=min(10, self.settings.limits.max_seconds_per_page),
                stdout_limit=256 * 1024,
                stderr_limit=64 * 1024,
                environment=self._environment(self.temporary_root),
            )
            if language_result.returncode != 0:
                self._capability = unavailable
                return unavailable
            decoded = language_result.stdout.decode("utf-8", errors="strict")
            languages = tuple(
                sorted(
                    {
                        line.strip()
                        for line in decoded.splitlines()[1:]
                        if _LANGUAGE.fullmatch(line.strip()) is not None
                    }
                )
            )
            tessdata_path = self.settings.tessdata_path
            path_match = re.search(r'"([^"]+)"', decoded.splitlines()[0] if decoded else "")
            if tessdata_path is None and path_match is not None:
                tessdata_path = str(Path(path_match.group(1)).resolve())
            elif tessdata_path is not None:
                tessdata_path = str(Path(tessdata_path).expanduser().resolve())
            self._capability = OcrAdapterCapability(
                adapter_id=TESSERACT_ADAPTER_ID,
                adapter_version=TESSERACT_ADAPTER_VERSION,
                engine_id=OCR_ENGINE_ID,
                engine_version=version,
                engine_available=True,
                engine_executable=executable,
                version_compatible=_compatible(version),
                tessdata_path=tessdata_path,
                installed_languages=languages,
                input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
                emits_coordinates=True,
                emits_confidence=True,
            )
        except (OcrContractError, OSError, UnicodeError):
            self._capability = unavailable
        return self._capability

    @staticmethod
    def _integer(value: str, label: str, *, minimum: int = 0) -> int:
        try:
            selected = int(value)
        except ValueError as exc:
            raise OcrContractError(
                "ocr_engine_output_invalid", f"Tesseract TSV {label} is invalid"
            ) from exc
        if selected < minimum:
            raise OcrContractError(
                "ocr_engine_output_invalid", f"Tesseract TSV {label} is invalid"
            )
        return selected

    def _parse_tsv(
        self,
        data: bytes,
        request: OcrPageRequest,
        capability: OcrAdapterCapability,
    ) -> OcrPageResult:
        try:
            decoded = data.decode("utf-8", errors="strict")
            rows = csv.DictReader(decoded.splitlines(), dialect="excel-tab")
        except (UnicodeError, csv.Error) as exc:
            raise OcrContractError(
                "ocr_engine_output_invalid", "Tesseract TSV is not valid UTF-8 TSV"
            ) from exc
        if tuple(rows.fieldnames or ()) != _TSV_HEADER:
            raise OcrContractError(
                "ocr_engine_output_invalid", "Tesseract TSV header is invalid"
            )
        words: list[tuple[tuple[int, int, int], str]] = []
        spans: list[OcrTextSpan] = []
        low_confidence = 0
        try:
            for row_number, row in enumerate(rows, start=1):
                if (
                    row_number > 100_000
                    or None in row
                    or set(row) != set(_TSV_HEADER)
                    or any(value is None for value in row.values())
                ):
                    raise OcrContractError(
                        "ocr_engine_output_invalid", "Tesseract TSV row limit or shape is invalid"
                    )
                level = self._integer(row["level"], "level", minimum=1)
                if level != 5 or not row["text"].strip():
                    continue
                if self._integer(row["page_num"], "page number", minimum=1) != 1:
                    raise OcrContractError(
                        "ocr_engine_output_invalid", "Tesseract TSV page identity is invalid"
                    )
                left = self._integer(row["left"], "left")
                top = self._integer(row["top"], "top")
                width = self._integer(row["width"], "width", minimum=1)
                height = self._integer(row["height"], "height", minimum=1)
                try:
                    raw_confidence = float(row["conf"])
                except ValueError as exc:
                    raise OcrContractError(
                        "ocr_engine_output_invalid", "Tesseract TSV confidence is invalid"
                    ) from exc
                if raw_confidence < 0 or raw_confidence > 100:
                    raise OcrContractError(
                        "ocr_engine_output_invalid", "Tesseract TSV confidence is invalid"
                    )
                confidence = raw_confidence / 100.0
                low_confidence += int(confidence < 0.5)
                text = row["text"].strip()
                line_key = (
                    self._integer(row["block_num"], "block number"),
                    self._integer(row["par_num"], "paragraph number"),
                    self._integer(row["line_num"], "line number"),
                )
                words.append((line_key, text))
                spans.append(
                    OcrTextSpan(
                        text=text,
                        status=("needs-review" if confidence < 0.5 else "machine-unverified"),
                        confidence=confidence,
                        box=OcrBoundingBox(
                            left=left,
                            top=top,
                            width=width,
                            height=height,
                            page_width=request.page_width,
                            page_height=request.page_height,
                        ),
                    )
                )
        except csv.Error as exc:
            raise OcrContractError(
                "ocr_engine_output_invalid", "Tesseract TSV is malformed"
            ) from exc
        lines: list[str] = []
        current_key: tuple[int, int, int] | None = None
        current_words: list[str] = []
        for line_key, word in words:
            if current_key is not None and line_key != current_key:
                lines.append(" ".join(current_words))
                current_words = []
            current_key = line_key
            current_words.append(word)
        if current_words:
            lines.append(" ".join(current_words))
        text = "\n".join(lines)
        if len(text) > request.max_output_chars:
            raise OcrContractError(
                "ocr_output_limit_exceeded", "Tesseract text exceeds the page limit"
            )
        warnings = []
        if not text:
            warnings.append(
                OcrPageWarning(code="empty-text", message="No OCR text was produced.")
            )
        if low_confidence:
            warnings.append(
                OcrPageWarning(
                    code="low-confidence",
                    message=f"{low_confidence} word spans require review.",
                )
            )
        if capability.engine_version is None or capability.engine_executable is None:
            raise OcrContractError(
                "ocr_engine_unavailable", "Tesseract identity is incomplete"
            )
        if (
            self.renderer.renderer_version is None
            or self.renderer.decoder_version is None
            or self.renderer.resolved_path is None
        ):
            raise OcrContractError(
                "ocr_renderer_unavailable", "Renderer identity is incomplete"
            )
        provenance = OcrProvenance(
            engine_id=capability.engine_id,
            engine_version=capability.engine_version,
            engine_executable=capability.engine_executable,
            adapter_id=capability.adapter_id,
            adapter_version=capability.adapter_version,
            tessdata_path=capability.tessdata_path,
            renderer_id=self.renderer.renderer_id,
            renderer_version=self.renderer.renderer_version,
            renderer_adapter_id=self.renderer.adapter_id,
            renderer_adapter_version=self.renderer.adapter_version,
            renderer_resolved_path=self.renderer.resolved_path,
            decoder_id=self.renderer.decoder_id,
            decoder_version=self.renderer.decoder_version,
            render_dpi=self.settings.render_dpi,
            languages=request.languages,
            settings_sha256=request.settings_sha256,
            source_page=request.source_page,
        )
        result = OcrPageResult(
            source_page=request.source_page,
            text=text,
            text_status=("needs-review" if low_confidence else "machine-unverified"),
            spans=tuple(spans),
            warnings=tuple(warnings),
            observations=(),
            provenance=provenance,
        )
        validate_ocr_page_result(request, result, capability, self.renderer)
        return result

    def recognise_page(
        self, request: OcrPageRequest, staged_page_path: Path
    ) -> OcrPageResult:
        capability = self.capability()
        if not capability.engine_available or capability.engine_executable is None:
            raise OcrContractError(
                "ocr_engine_unavailable", "Tesseract is not available"
            )
        if not capability.version_compatible:
            raise OcrContractError(
                "ocr_version_incompatible", "Tesseract version is incompatible"
            )
        missing = set(request.languages) - set(capability.installed_languages)
        if missing:
            raise OcrContractError(
                "ocr_language_pack_missing", "Selected Tesseract language pack is absent"
            )
        work_directory = Path(staged_page_path).resolve().parent
        output_base = work_directory / "tesseract-output"
        output_path = output_base.with_suffix(".tsv")
        output_path.unlink(missing_ok=True)
        remaining_temp_bytes = (
            self.settings.limits.max_temp_bytes
            - staged_page_path.stat().st_size
            - (320 * 1024)
        )
        if remaining_temp_bytes < 1:
            raise OcrContractError(
                "ocr_temporary_space_exceeded",
                "Tesseract has no remaining temporary-storage allowance",
            )
        max_tsv_bytes = min(
            self.settings.limits.max_temp_bytes,
            max(1024 * 1024, request.max_output_chars * 64),
            remaining_temp_bytes,
        )
        result = run_bounded_process(
            [
                capability.engine_executable,
                str(Path(staged_page_path).resolve()),
                str(output_base.resolve()),
                "-l",
                "+".join(request.languages),
                "--psm",
                "3",
                "tsv",
            ],
            temporary_directory=work_directory,
            timeout_seconds=request.deadline_seconds,
            stdout_limit=64 * 1024,
            stderr_limit=256 * 1024,
            cancelled=self.cancelled,
            environment=self._environment(work_directory),
            produced_file_limits={output_path: max_tsv_bytes},
        )
        if result.returncode != 0:
            raise OcrContractError(
                "ocr_adapter_failure", "Tesseract exited without a successful result"
            )
        if not output_path.is_file() or output_path.is_symlink():
            raise OcrContractError(
                "ocr_engine_output_invalid", "Tesseract TSV output is missing"
            )
        if output_path.stat().st_size > max_tsv_bytes:
            raise OcrContractError(
                "ocr_output_limit_exceeded", "Tesseract TSV output exceeds its byte limit"
            )
        return self._parse_tsv(output_path.read_bytes(), request, capability)


__all__ = [
    "TESSERACT_ADAPTER_ID",
    "TESSERACT_ADAPTER_VERSION",
    "TesseractCliAdapter",
]
