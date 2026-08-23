from __future__ import annotations

import csv
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from io import BytesIO, StringIO
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

MAX_EXTRACTED_CHARS = 500_000
DOCX_MAX_XML_BYTES = 10 * 1024 * 1024
DOCX_MAX_MEMBERS = 2_000
CSV_MAX_ROWS = 5_000
CSV_MAX_COLUMNS = 200
EML_MAX_PARTS = 500


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


def _bounded_text(text: str, label: str) -> str:
    if len(text) > MAX_EXTRACTED_CHARS:
        raise ExtractionError(
            f"{label} extracted text exceeds the {MAX_EXTRACTED_CHARS}-character safety limit"
        )
    return text


class PlainTextExtractor:
    extensions = {".txt", ".md", ".markdown"}

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    def extract(self, data: bytes) -> ExtractionResult:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExtractionError("text file is not valid UTF-8") from exc
        return ExtractionResult(
            text=_bounded_text(text, "text file"),
            generator="provelume.text",
            generator_version="1",
        )


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
        return ExtractionResult(
            text=_bounded_text(text, "PDF"),
            generator="pypdf",
            generator_version="5+",
        )


class DocxTextExtractor:
    extensions = {".docx"}
    word_namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    def extract(self, data: bytes) -> ExtractionResult:
        try:
            with ZipFile(BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) > DOCX_MAX_MEMBERS:
                    raise ExtractionError(
                        f"DOCX exceeds the {DOCX_MAX_MEMBERS}-member safety limit"
                    )
                try:
                    document = archive.getinfo("word/document.xml")
                except KeyError as exc:
                    raise ExtractionError("DOCX is missing word/document.xml") from exc
                if document.file_size > DOCX_MAX_XML_BYTES:
                    raise ExtractionError(
                        f"DOCX document XML exceeds the {DOCX_MAX_XML_BYTES}-byte safety limit"
                    )
                xml_bytes = archive.read(document)
            root = ElementTree.fromstring(xml_bytes)
        except ExtractionError:
            raise
        except (BadZipFile, ElementTree.ParseError, OSError, RuntimeError) as exc:
            raise ExtractionError(f"DOCX extraction failed: {exc}") from exc

        paragraph_tag = f"{{{self.word_namespace}}}p"
        text_tag = f"{{{self.word_namespace}}}t"
        tab_tag = f"{{{self.word_namespace}}}tab"
        break_tags = {
            f"{{{self.word_namespace}}}br",
            f"{{{self.word_namespace}}}cr",
        }
        paragraphs: list[str] = []
        for paragraph in root.iter(paragraph_tag):
            parts: list[str] = []
            for node in paragraph.iter():
                if node.tag == text_tag and node.text:
                    parts.append(node.text)
                elif node.tag == tab_tag:
                    parts.append("\t")
                elif node.tag in break_tags:
                    parts.append("\n")
            value = "".join(parts).strip()
            if value:
                paragraphs.append(value)
        text = "\n\n".join(paragraphs)
        return ExtractionResult(
            text=_bounded_text(text, "DOCX"),
            generator="provelume.docx-ooxml",
            generator_version="1",
        )


class CsvTextExtractor:
    extensions = {".csv"}

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    def extract(self, data: bytes) -> ExtractionResult:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExtractionError("CSV is not valid UTF-8") from exc
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|") if sample else csv.excel
        except csv.Error:
            dialect = csv.excel
        rows: list[str] = []
        try:
            reader = csv.reader(StringIO(text, newline=""), dialect)
            for row_number, row in enumerate(reader, start=1):
                if row_number > CSV_MAX_ROWS:
                    raise ExtractionError(
                        f"CSV exceeds the {CSV_MAX_ROWS}-row safety limit"
                    )
                if len(row) > CSV_MAX_COLUMNS:
                    raise ExtractionError(
                        f"CSV row {row_number} exceeds the {CSV_MAX_COLUMNS}-column safety limit"
                    )
                rows.append(" | ".join(cell.strip() for cell in row))
        except ExtractionError:
            raise
        except csv.Error as exc:
            raise ExtractionError(f"CSV extraction failed: {exc}") from exc
        return ExtractionResult(
            text=_bounded_text("\n".join(rows), "CSV"),
            generator="python.csv",
            generator_version="stdlib-3.12",
        )


class _ReadableHtml(HTMLParser):
    block_tags = {
        "article",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "tr",
    }
    skipped_tags = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag in self.skipped_tags:
            self.skip_depth += 1
        elif tag in self.block_tags and not self.skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.skipped_tags and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.block_tags and not self.skip_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(
            line.strip() for line in "".join(self.parts).splitlines() if line.strip()
        )


def _html_to_text(value: str) -> str:
    parser = _ReadableHtml()
    parser.feed(value)
    parser.close()
    return parser.text()


class EmlTextExtractor:
    extensions = {".eml"}

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    def extract(self, data: bytes) -> ExtractionResult:
        try:
            message = BytesParser(policy=policy.default).parsebytes(data)
            parts = list(message.walk())
            if len(parts) > EML_MAX_PARTS:
                raise ExtractionError(
                    f"EML exceeds the {EML_MAX_PARTS}-part safety limit"
                )
            plain_parts: list[str] = []
            html_parts: list[str] = []
            for part in parts:
                if part.is_multipart() or part.get_content_disposition() == "attachment":
                    continue
                if part.get_content_maintype() != "text":
                    continue
                content = part.get_content()
                if not isinstance(content, str):
                    continue
                if part.get_content_subtype() == "plain":
                    plain_parts.append(content)
                elif part.get_content_subtype() == "html":
                    html_parts.append(_html_to_text(content))
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"EML extraction failed: {exc}") from exc

        headers = [
            f"{label}: {message.get(name)}"
            for label, name in (
                ("Subject", "subject"),
                ("From", "from"),
                ("To", "to"),
                ("Date", "date"),
            )
            if message.get(name)
        ]
        body_parts = plain_parts if plain_parts else html_parts
        chunks = [*headers, "\n\n".join(part.strip() for part in body_parts if part.strip())]
        text = "\n".join(chunk for chunk in chunks if chunk).strip()
        if not text:
            raise ExtractionError("EML contains no searchable headers or body text")
        return ExtractionResult(
            text=_bounded_text(text, "EML"),
            generator="python.email",
            generator_version="stdlib-3.12",
        )


EXTRACTORS: tuple[Extractor, ...] = (
    PlainTextExtractor(),
    PdfTextExtractor(),
    DocxTextExtractor(),
    CsvTextExtractor(),
    EmlTextExtractor(),
)


def extractor_for(path: Path) -> Extractor | None:
    for extractor in EXTRACTORS:
        if extractor.supports(path.suffix):
            return extractor
    return None
