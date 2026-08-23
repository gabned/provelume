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
XLSX_MAX_MEMBERS = 3_000
XLSX_MAX_SHEETS = 100
XLSX_MAX_XML_BYTES = 20 * 1024 * 1024
XLSX_MAX_ROWS = 20_000
XLSX_MAX_CELLS = 100_000


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


class XlsxTextExtractor:
    extensions = {".xlsx"}
    spreadsheet_namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    def _shared_strings(self, archive: ZipFile) -> list[str]:
        try:
            info = archive.getinfo("xl/sharedStrings.xml")
        except KeyError:
            return []
        if info.file_size > XLSX_MAX_XML_BYTES:
            raise ExtractionError(
                f"XLSX shared strings exceed the {XLSX_MAX_XML_BYTES}-byte safety limit"
            )
        root = ElementTree.fromstring(archive.read(info))
        item_tag = f"{{{self.spreadsheet_namespace}}}si"
        text_tag = f"{{{self.spreadsheet_namespace}}}t"
        return [
            "".join(node.text or "" for node in item.iter(text_tag))
            for item in root.iter(item_tag)
        ]

    def extract(self, data: bytes) -> ExtractionResult:
        try:
            with ZipFile(BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) > XLSX_MAX_MEMBERS:
                    raise ExtractionError(
                        f"XLSX exceeds the {XLSX_MAX_MEMBERS}-member safety limit"
                    )
                worksheet_infos = sorted(
                    (
                        info
                        for info in members
                        if info.filename.startswith("xl/worksheets/")
                        and info.filename.endswith(".xml")
                    ),
                    key=lambda info: info.filename,
                )
                if not worksheet_infos:
                    raise ExtractionError("XLSX contains no worksheets")
                if len(worksheet_infos) > XLSX_MAX_SHEETS:
                    raise ExtractionError(
                        f"XLSX exceeds the {XLSX_MAX_SHEETS}-worksheet safety limit"
                    )
                shared_strings = self._shared_strings(archive)
                output: list[str] = []
                total_rows = 0
                total_cells = 0
                row_tag = f"{{{self.spreadsheet_namespace}}}row"
                cell_tag = f"{{{self.spreadsheet_namespace}}}c"
                value_tag = f"{{{self.spreadsheet_namespace}}}v"
                text_tag = f"{{{self.spreadsheet_namespace}}}t"

                for info in worksheet_infos:
                    if info.file_size > XLSX_MAX_XML_BYTES:
                        raise ExtractionError(
                            f"XLSX worksheet exceeds the {XLSX_MAX_XML_BYTES}-byte safety limit"
                        )
                    root = ElementTree.fromstring(archive.read(info))
                    output.append(f"Sheet: {Path(info.filename).stem}")
                    for row in root.iter(row_tag):
                        total_rows += 1
                        if total_rows > XLSX_MAX_ROWS:
                            raise ExtractionError(
                                f"XLSX exceeds the {XLSX_MAX_ROWS}-row safety limit"
                            )
                        values: list[str] = []
                        for cell in row.findall(cell_tag):
                            total_cells += 1
                            if total_cells > XLSX_MAX_CELLS:
                                raise ExtractionError(
                                    f"XLSX exceeds the {XLSX_MAX_CELLS}-cell safety limit"
                                )
                            cell_type = cell.get("t") or ""
                            if cell_type == "inlineStr":
                                value = "".join(
                                    node.text or "" for node in cell.iter(text_tag)
                                )
                            else:
                                value_node = cell.find(value_tag)
                                value = value_node.text if value_node is not None else ""
                                if cell_type == "s" and value:
                                    try:
                                        value = shared_strings[int(value)]
                                    except (ValueError, IndexError) as exc:
                                        raise ExtractionError(
                                            "XLSX contains an invalid shared-string reference"
                                        ) from exc
                                elif cell_type == "b" and value:
                                    value = "TRUE" if value == "1" else "FALSE"
                            values.append(value or "")
                        if any(value for value in values):
                            output.append(" | ".join(values))
        except ExtractionError:
            raise
        except (BadZipFile, ElementTree.ParseError, OSError, RuntimeError) as exc:
            raise ExtractionError(f"XLSX extraction failed: {exc}") from exc

        return ExtractionResult(
            text=_bounded_text("\n".join(output), "XLSX"),
            generator="provelume.xlsx-ooxml",
            generator_version="1",
        )


class ImageMetadataExtractor:
    extensions = {".png", ".jpg", ".jpeg"}
    jpeg_sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions

    @staticmethod
    def _png_dimensions(data: bytes) -> tuple[int, int]:
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ExtractionError("PNG signature or header is invalid")
        if data[12:16] != b"IHDR":
            raise ExtractionError("PNG is missing the leading IHDR chunk")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if width <= 0 or height <= 0:
            raise ExtractionError("PNG dimensions are invalid")
        return width, height

    @classmethod
    def _jpeg_dimensions(cls, data: bytes) -> tuple[int, int]:
        if len(data) < 4 or data[:2] != b"\xff\xd8":
            raise ExtractionError("JPEG signature is invalid")
        position = 2
        while position < len(data):
            while position < len(data) and data[position] == 0xFF:
                position += 1
            if position >= len(data):
                break
            marker = data[position]
            position += 1
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if position + 2 > len(data):
                break
            segment_length = int.from_bytes(data[position : position + 2], "big")
            if segment_length < 2 or position + segment_length > len(data):
                raise ExtractionError("JPEG segment length is invalid")
            if marker in cls.jpeg_sof_markers:
                if segment_length < 7:
                    raise ExtractionError("JPEG frame header is invalid")
                height = int.from_bytes(data[position + 3 : position + 5], "big")
                width = int.from_bytes(data[position + 5 : position + 7], "big")
                if width <= 0 or height <= 0:
                    raise ExtractionError("JPEG dimensions are invalid")
                return width, height
            if marker == 0xDA:
                break
            position += segment_length
        raise ExtractionError("JPEG frame dimensions were not found")

    def extract(self, data: bytes) -> ExtractionResult:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            image_format = "PNG"
            width, height = self._png_dimensions(data)
        elif data.startswith(b"\xff\xd8"):
            image_format = "JPEG"
            width, height = self._jpeg_dimensions(data)
        else:
            raise ExtractionError("image format does not match PNG or JPEG")
        text = (
            f"Image format: {image_format}\n"
            f"Width: {width}\n"
            f"Height: {height}\n"
            f"Pixels: {width * height}"
        )
        return ExtractionResult(
            text=text,
            generator="provelume.image-metadata",
            generator_version="1",
        )


EXTRACTORS: tuple[Extractor, ...] = (
    PlainTextExtractor(),
    PdfTextExtractor(),
    DocxTextExtractor(),
    CsvTextExtractor(),
    EmlTextExtractor(),
    XlsxTextExtractor(),
    ImageMetadataExtractor(),
)


def extractor_for(path: Path) -> Extractor | None:
    for extractor in EXTRACTORS:
        if extractor.supports(path.suffix):
            return extractor
    return None
