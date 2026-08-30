from __future__ import annotations

import hashlib
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ocr_contract import (
    OCR_SUPPORTED_INPUTS,
    OcrContractError,
    OcrInputDescriptor,
    OcrRendererCapability,
    OcrSettings,
    isolated_ocr_temp_directory,
)
from .ocr_process import minimal_child_environment, run_bounded_process

RENDERER_ADAPTER_ID = "provelume.pdfium-pillow"
RENDERER_ADAPTER_VERSION = "1"
RENDERER_ID = "pdfium-pillow"
DECODER_ID = "pillow"
_WORKER = Path(__file__).with_name("ocr_render_worker.py")


@dataclass(frozen=True, slots=True)
class OcrPlannedPage:
    number: int
    width: int
    height: int

    @property
    def pixels(self) -> int:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class OcrDocumentPlan:
    media_type: str
    suffix: str
    input_bytes: int
    pages: tuple[OcrPlannedPage, ...]

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass(frozen=True, slots=True)
class RenderedOcrPage:
    number: int
    path: Path
    width: int
    height: int
    sha256: str
    size_bytes: int


def _major(value: str | None) -> int | None:
    try:
        return int(str(value).split(".", 1)[0])
    except (TypeError, ValueError):
        return None


class PdfiumPillowRenderer:
    """Bounded local PDF renderer and image decoder executed out of process."""

    def __init__(
        self,
        settings: OcrSettings,
        temporary_root: Path,
        *,
        worker_path: Path = _WORKER,
        python_executable: str = sys.executable,
    ):
        self.settings = settings
        self.temporary_root = Path(temporary_root)
        self.worker_path = Path(worker_path).resolve()
        self.python_executable = str(Path(python_executable).resolve())
        self._capability: OcrRendererCapability | None = None

    def _run(
        self,
        arguments: list[str],
        *,
        work_directory: Path,
        timeout: int,
        stdout_limit: int = 256 * 1024,
        cancelled: Callable[[], bool] | None = None,
        produced_file: Path | None = None,
        produced_file_limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            result = run_bounded_process(
                [self.python_executable, "-I", str(self.worker_path), *arguments],
                temporary_directory=work_directory,
                timeout_seconds=timeout,
                stdout_limit=stdout_limit,
                stderr_limit=16 * 1024,
                cancelled=cancelled,
                environment=minimal_child_environment(work_directory),
                produced_file_limits=(
                    None
                    if produced_file is None or produced_file_limit is None
                    else {produced_file: produced_file_limit}
                ),
            )
        except OcrContractError as exc:
            if exc.code == "ocr_engine_unavailable":
                raise OcrContractError(
                    "ocr_renderer_unavailable", "OCR renderer process could not start"
                ) from exc
            raise
        if result.returncode != 0:
            raise OcrContractError(
                "ocr_corrupt_input",
                "OCR renderer rejected the input without producing page content",
            )
        try:
            value = json.loads(result.stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OcrContractError(
                "ocr_engine_output_invalid", "OCR renderer returned invalid metadata"
            ) from exc
        if not isinstance(value, dict):
            raise OcrContractError(
                "ocr_engine_output_invalid", "OCR renderer metadata is not an object"
            )
        return value

    def capability(self) -> OcrRendererCapability:
        if self._capability is not None:
            return self._capability
        unavailable = OcrRendererCapability(
            adapter_id=RENDERER_ADAPTER_ID,
            adapter_version=RENDERER_ADAPTER_VERSION,
            renderer_id=RENDERER_ID,
            renderer_version=None,
            renderer_available=False,
            version_compatible=False,
            resolved_path=None,
            decoder_id=DECODER_ID,
            decoder_version=None,
            component_versions=(),
            input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
        )
        try:
            with isolated_ocr_temp_directory(self.temporary_root) as temporary:
                value = self._run(
                    ["probe"],
                    work_directory=temporary,
                    timeout=min(10, self.settings.limits.max_seconds_per_page),
                )
            renderer_version = str(value["pypdfium2"])
            decoder_version = str(value["pillow"])
            pdfium_version = str(value["pdfium"])
            raw_path = value["pdfium_library"]
            if not isinstance(raw_path, str) or not raw_path:
                raise ValueError("PDFium library path is unavailable")
            resolved_path = str(Path(raw_path).resolve())
            if not Path(resolved_path).is_file():
                raise ValueError("PDFium library path is unavailable")
            components = {
                "pdfium": pdfium_version,
                "pillow": decoder_version,
                "pypdfium2": renderer_version,
            }
            codecs = value.get("pillow_codecs", {})
            if isinstance(codecs, dict):
                components.update(
                    {
                        f"pillow-{name}": str(version)
                        for name, version in codecs.items()
                    }
                )
            compatible = _major(renderer_version) == 5 and _major(decoder_version) == 12
            self._capability = OcrRendererCapability(
                adapter_id=RENDERER_ADAPTER_ID,
                adapter_version=RENDERER_ADAPTER_VERSION,
                renderer_id=RENDERER_ID,
                renderer_version=renderer_version,
                renderer_available=True,
                version_compatible=compatible,
                resolved_path=resolved_path,
                decoder_id=DECODER_ID,
                decoder_version=decoder_version,
                component_versions=tuple(sorted(components.items())),
                input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
            )
        except (KeyError, OSError, TypeError, ValueError, OcrContractError):
            self._capability = unavailable
        return self._capability

    def inspect(
        self,
        original_path: Path,
        *,
        media_type: str,
        suffix: str,
        signature: bytes,
        input_bytes: int,
        work_directory: Path,
        deadline_seconds: int | None = None,
    ) -> OcrDocumentPlan:
        if media_type not in OCR_SUPPORTED_INPUTS:
            raise OcrContractError(
                "ocr_unsupported_input", "OCR media type is not supported"
            )
        value = self._run(
            [
                "inspect",
                "--input",
                str(Path(original_path).resolve()),
                "--media-type",
                media_type,
                "--dpi",
                str(self.settings.render_dpi),
                "--max-page-pixels",
                str(self.settings.limits.max_page_pixels),
            ],
            work_directory=work_directory,
            timeout=(
                min(60, self.settings.limits.max_total_seconds)
                if deadline_seconds is None
                else deadline_seconds
            ),
        )
        raw_pages = value.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise OcrContractError("ocr_corrupt_input", "OCR input has no pages")
        pages: list[OcrPlannedPage] = []
        try:
            for expected, item in enumerate(raw_pages, start=1):
                if not isinstance(item, dict) or set(item) != {
                    "number",
                    "width",
                    "height",
                }:
                    raise ValueError
                page = OcrPlannedPage(
                    number=int(item["number"]),
                    width=int(item["width"]),
                    height=int(item["height"]),
                )
                if page.number != expected or page.width < 1 or page.height < 1:
                    raise ValueError
                pages.append(page)
        except (TypeError, ValueError) as exc:
            raise OcrContractError(
                "ocr_engine_output_invalid", "OCR renderer page plan is invalid"
            ) from exc
        pixels = [page.pixels for page in pages]
        max_decoded = max(pixels) * 4
        descriptor = OcrInputDescriptor(
            media_type=media_type,
            suffix=suffix,
            signature=signature,
            input_bytes=input_bytes,
            page_count=len(pages),
            max_page_pixels=max(pixels),
            total_pixels=sum(pixels),
            max_decompressed_page_bytes=max_decoded,
            max_decompression_ratio=max(1, math.ceil(max_decoded / input_bytes)),
        )
        descriptor.validate(self.settings.limits)
        return OcrDocumentPlan(
            media_type=media_type,
            suffix=suffix.casefold(),
            input_bytes=input_bytes,
            pages=tuple(pages),
        )

    def render(
        self,
        original_path: Path,
        plan: OcrDocumentPlan,
        page_number: int,
        *,
        work_directory: Path,
        cancelled: Callable[[], bool] | None = None,
        deadline_seconds: int | None = None,
    ) -> RenderedOcrPage:
        if page_number < 1 or page_number > plan.page_count:
            raise OcrContractError(
                "ocr_invalid_selection", "OCR renderer page is outside the document"
            )
        output = work_directory / f"page-{page_number:06d}.png"
        output.unlink(missing_ok=True)
        produced_file_limit = self.settings.limits.max_temp_bytes - (272 * 1024)
        if produced_file_limit < 1:
            raise OcrContractError(
                "ocr_temporary_space_exceeded",
                "OCR renderer has no remaining temporary-storage allowance",
            )
        value = self._run(
            [
                "render",
                "--input",
                str(Path(original_path).resolve()),
                "--output",
                str(output.resolve()),
                "--media-type",
                plan.media_type,
                "--page",
                str(page_number),
                "--dpi",
                str(self.settings.render_dpi),
                "--max-page-pixels",
                str(self.settings.limits.max_page_pixels),
            ],
            work_directory=work_directory,
            timeout=(
                self.settings.limits.max_seconds_per_page
                if deadline_seconds is None
                else deadline_seconds
            ),
            cancelled=cancelled,
            produced_file=output,
            produced_file_limit=produced_file_limit,
        )
        expected = plan.pages[page_number - 1]
        try:
            width = int(value["width"])
            height = int(value["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OcrContractError(
                "ocr_engine_output_invalid", "OCR renderer dimensions are invalid"
            ) from exc
        valid_widths = (
            {expected.width - 1, expected.width}
            if plan.media_type == "application/pdf"
            else {expected.width}
        )
        valid_heights = (
            {expected.height - 1, expected.height}
            if plan.media_type == "application/pdf"
            else {expected.height}
        )
        if (
            int(value.get("page", 0)) != page_number
            or width not in valid_widths
            or height not in valid_heights
            or not output.is_file()
            or output.is_symlink()
        ):
            raise OcrContractError(
                "ocr_engine_output_invalid", "OCR renderer output is incomplete"
            )
        data = output.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise OcrContractError(
                "ocr_engine_output_invalid", "OCR renderer output is not PNG"
            )
        if len(data) > self.settings.limits.max_temp_bytes:
            raise OcrContractError(
                "ocr_temporary_space_exceeded", "rendered OCR page exceeds temporary limit"
            )
        return RenderedOcrPage(
            number=page_number,
            path=output,
            width=width,
            height=height,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )


__all__ = [
    "DECODER_ID",
    "PdfiumPillowRenderer",
    "OcrDocumentPlan",
    "OcrPlannedPage",
    "RENDERER_ADAPTER_ID",
    "RENDERER_ADAPTER_VERSION",
    "RENDERER_ID",
    "RenderedOcrPage",
]
