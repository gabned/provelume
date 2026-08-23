from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader


class ExtractionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    text: str
    generator: str
    generator_version: str


class Extractor(Protocol):
    def supports(self, suffix: str) -> bool: ...

    def extract(self, data: bytes) -> ExtractionResult: ...


class PlainTextExtractor:
    extensions = {".txt", ".md", ".markdown"}

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    def extract(self, data: bytes) -> ExtractionResult:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExtractionError("text file is not valid UTF-8") from exc
        return ExtractionResult(text=text, generator="provelume.text", generator_version="1")


class PdfTextExtractor:
    extensions = {".pdf"}

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    def extract(self, data: bytes) -> ExtractionResult:
        try:
            reader = PdfReader(BytesIO(data))
            if len(reader.pages) > 500:
                raise ExtractionError("PDF exceeds the 500-page safety limit")
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"PDF extraction failed: {exc}") from exc
        return ExtractionResult(text=text, generator="pypdf", generator_version="5+")


EXTRACTORS: tuple[Extractor, ...] = (PlainTextExtractor(), PdfTextExtractor())


def extractor_for(path: Path) -> Extractor | None:
    for extractor in EXTRACTORS:
        if extractor.supports(path.suffix):
            return extractor
    return None
