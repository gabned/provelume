from __future__ import annotations

import csv
import decimal
import hashlib
import json
import posixpath
import re
import stat
import sys
import time
import unicodedata
import zlib
from collections.abc import Callable, Mapping
from contextlib import suppress
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from .paths import safe_instance_path
from .representations import (
    MAX_REPRESENTATION_ANCHORS,
    RepresentationBundleManager,
    RepresentationContractError,
    canonical_json_bytes,
)
from .storage import InstanceStore, utc_now

FILE_FAMILY_SCHEMA_VERSION = 1
FILE_FAMILY_JOB_SCHEMA_VERSION = 1
FILE_FAMILY_RECIPE_ID = "provelume.file-family-profile"
FILE_FAMILY_RECIPE_VERSION = "1"

CSV_PROFILE_ID = "perceptio-csv-cell-v1"
XLSX_PROFILE_ID = "perceptio-xlsx-sheet-cell-v1"
ZIP_PROFILE_ID = "perceptio-zip-member-v1"
FILE_FAMILY_PROFILE_IDS = (CSV_PROFILE_ID, XLSX_PROFILE_ID, ZIP_PROFILE_ID)
PROFILE_FORMATS = {
    CSV_PROFILE_ID: "CSV",
    XLSX_PROFILE_ID: "XLSX",
    ZIP_PROFILE_ID: "ZIP",
}
PROFILE_MEDIA_TYPES = {
    CSV_PROFILE_ID: "text/csv",
    XLSX_PROFILE_ID: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ZIP_PROFILE_ID: "application/zip",
}

PARSER_COMPONENT = "runtime.cpython"
PARSER_VERSION = "3.12"
PARSER_LICENSE = "PSF-2.0"

CSV_MAX_INPUT_BYTES = 16 * 1024 * 1024
CSV_MAX_ROWS = 5_000
CSV_MAX_COLUMNS = 200
CSV_MAX_CELLS = 100_000
CSV_MAX_FIELD_CHARS = 1_000_000
CSV_MAX_TEXT_CHARS = 2_000_000

XLSX_MAX_INPUT_BYTES = 64 * 1024 * 1024
XLSX_MAX_MEMBERS = 3_000
XLSX_MAX_TOTAL_UNCOMPRESSED = 128 * 1024 * 1024
XLSX_MAX_MEMBER_BYTES = 32 * 1024 * 1024
XLSX_MAX_XML_BYTES = 20 * 1024 * 1024
XLSX_MAX_XML_DEPTH = 64
XLSX_MAX_XML_ELEMENTS = 500_000
XLSX_MAX_XML_TEXT_CHARS = 4_000_000
XLSX_MAX_SHEETS = 100
XLSX_MAX_ROWS = 20_000
XLSX_MAX_CELLS = MAX_REPRESENTATION_ANCHORS - XLSX_MAX_SHEETS
XLSX_MAX_SHARED_STRINGS = 100_000
XLSX_MAX_CELL_CHARS = 1_000_000

ZIP_MAX_INPUT_BYTES = 64 * 1024 * 1024
ZIP_MAX_MEMBERS = 1_000
ZIP_MAX_TOTAL_UNCOMPRESSED = 50 * 1024 * 1024
ZIP_MAX_MEMBER_BYTES = 10 * 1024 * 1024
ZIP_MAX_COMPRESSION_RATIO = 200

MAX_ARCHIVE_PROCESS_SECONDS = 30.0
MAX_PATH_CHARS = 240
MAX_SEGMENT_CHARS = 120
MAX_CELL_COLUMN = 16_384
MAX_CELL_ROW = 1_048_576

FILE_FAMILY_ERROR_CODES = (
    "file_family_not_found",
    "file_family_profile_invalid",
    "file_family_input_limit_exceeded",
    "file_family_encoding_unsupported",
    "file_family_structure_invalid",
    "file_family_path_unsafe",
    "file_family_collision",
    "file_family_encrypted",
    "file_family_active_content",
    "file_family_external_relationship",
    "file_family_formula_value_unavailable",
    "file_family_member_limit_exceeded",
    "file_family_compression_unsafe",
    "file_family_processing_timeout",
    "file_family_cancelled",
    "file_family_contract_violation",
    "file_family_job_state_invalid",
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CELL = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})\Z")
_DRIVE = re.compile(r"[A-Za-z]:")
_WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
_WINDOWS_RESERVED = {
    "aux",
    "clock$",
    "con",
    "conin$",
    "conout$",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}

_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

_FIXED_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".zip": "application/zip",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
}


class FileFamilyContractError(ValueError):
    """Closed, content-free failure for bounded CSV, XLSX and ZIP profiles."""

    def __init__(self, code: str, message: str):
        if code not in FILE_FAMILY_ERROR_CODES:
            raise ValueError("file-family error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cancel_or_timeout(
    cancelled: Callable[[], bool] | None,
    started: float,
) -> None:
    if cancelled is not None and cancelled():
        raise FileFamilyContractError("file_family_cancelled", "file-family job was cancelled")
    if time.monotonic() - started > MAX_ARCHIVE_PROCESS_SECONDS:
        raise FileFamilyContractError(
            "file_family_processing_timeout", "file-family processing deadline expired"
        )


def _safe_member_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_CHARS:
        raise FileFamilyContractError("file_family_path_unsafe", "archive path is invalid")
    selected = value[:-1] if value.endswith("/") else value
    if (
        not selected
        or selected != unicodedata.normalize("NFC", selected)
        or selected.startswith("/")
        or "\\" in selected
        or _DRIVE.match(selected)
        or any(ord(character) < 32 for character in selected)
    ):
        raise FileFamilyContractError("file_family_path_unsafe", "archive path is unsafe")
    path = PurePosixPath(selected)
    if path.as_posix() != selected or any(part in {"", ".", ".."} for part in path.parts):
        raise FileFamilyContractError("file_family_path_unsafe", "archive path is unsafe")
    for part in path.parts:
        stem = part.rstrip(" .").split(".", 1)[0].casefold()
        if (
            len(part) > MAX_SEGMENT_CHARS
            or part != part.rstrip(" .")
            or any(character in _WINDOWS_FORBIDDEN for character in part)
            or stem in _WINDOWS_RESERVED
        ):
            raise FileFamilyContractError("file_family_path_unsafe", "archive path is not portable")
    return selected


def _is_symlink(info: ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


def _archive_infos(
    archive: ZipFile,
    *,
    max_members: int,
    max_total: int,
    max_member: int,
) -> list[tuple[str, ZipInfo]]:
    raw = archive.infolist()
    if len(raw) > max_members:
        raise FileFamilyContractError(
            "file_family_member_limit_exceeded", "archive member count exceeds its closed limit"
        )
    selected: list[tuple[str, ZipInfo]] = []
    identities: set[str] = set()
    total = 0
    for info in raw:
        path = _safe_member_path(info.filename)
        identity = path.casefold()
        if identity in identities:
            raise FileFamilyContractError("file_family_collision", "archive member paths collide")
        identities.add(identity)
        if _is_symlink(info):
            raise FileFamilyContractError("file_family_path_unsafe", "archive symlink is unsafe")
        if info.flag_bits & 0x1:
            raise FileFamilyContractError(
                "file_family_encrypted", "encrypted archive members are not inspected"
            )
        if info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
            raise FileFamilyContractError(
                "file_family_compression_unsafe", "archive compression method is unsupported"
            )
        if info.file_size > max_member:
            raise FileFamilyContractError(
                "file_family_member_limit_exceeded", "archive member exceeds its byte limit"
            )
        total += 0 if info.is_dir() else info.file_size
        if total > max_total:
            raise FileFamilyContractError(
                "file_family_member_limit_exceeded",
                "archive uncompressed bytes exceed their closed limit",
            )
        if info.file_size / max(info.compress_size, 1) > ZIP_MAX_COMPRESSION_RATIO:
            raise FileFamilyContractError(
                "file_family_compression_unsafe", "archive expansion ratio is unsafe"
            )
        selected.append((path, info))
    return selected


def _read_archive_member(archive: ZipFile, info: ZipInfo) -> bytes:
    try:
        payload = archive.read(info)
    except (BadZipFile, OSError, RuntimeError, NotImplementedError, zlib.error) as exc:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "archive member verification failed"
        ) from exc
    if len(payload) != info.file_size:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "archive member length is inconsistent"
        )
    return payload


def _column_name(column: int) -> str:
    if not 1 <= column <= MAX_CELL_COLUMN:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "cell column is outside its boundary"
        )
    result = ""
    selected = column
    while selected:
        selected, remainder = divmod(selected - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell_coordinates(value: Any) -> tuple[int, int, str]:
    if not isinstance(value, str):
        raise FileFamilyContractError("file_family_structure_invalid", "cell reference is missing")
    match = _CELL.fullmatch(value)
    if match is None:
        raise FileFamilyContractError("file_family_structure_invalid", "cell reference is invalid")
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - 64
    row = int(match.group(2))
    if column > MAX_CELL_COLUMN or row > MAX_CELL_ROW:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "cell reference is outside its boundary"
        )
    return row, column, value


def _parse_xml(payload: bytes, *, label: str) -> ElementTree.Element:
    if len(payload) > XLSX_MAX_XML_BYTES:
        raise FileFamilyContractError(
            "file_family_member_limit_exceeded", f"{label} exceeds the XML byte limit"
        )
    lowered = payload.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FileFamilyContractError(
            "file_family_active_content", f"{label} contains an active XML declaration"
        )
    depth = 0
    elements = 0
    text_characters = 0
    try:
        parser = ElementTree.iterparse(BytesIO(payload), events=("start", "end"))
        for event, element in parser:
            if event == "start":
                depth += 1
                elements += 1
                if depth > XLSX_MAX_XML_DEPTH or elements > XLSX_MAX_XML_ELEMENTS:
                    raise FileFamilyContractError(
                        "file_family_member_limit_exceeded", f"{label} exceeds XML structure limits"
                    )
            else:
                text_characters += len(element.text or "") + len(element.tail or "")
                if text_characters > XLSX_MAX_XML_TEXT_CHARS:
                    raise FileFamilyContractError(
                        "file_family_member_limit_exceeded", f"{label} exceeds the XML text limit"
                    )
                depth -= 1
        root = parser.root
    except FileFamilyContractError:
        raise
    except (ElementTree.ParseError, LookupError, ValueError) as exc:
        raise FileFamilyContractError(
            "file_family_structure_invalid", f"{label} XML is malformed"
        ) from exc
    if root is None or depth != 0:
        raise FileFamilyContractError("file_family_structure_invalid", f"{label} XML is incomplete")
    return root


def _parse_csv(
    data: bytes,
    *,
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if len(data) > CSV_MAX_INPUT_BYTES:
        raise FileFamilyContractError(
            "file_family_input_limit_exceeded", "CSV input exceeds its closed byte limit"
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileFamilyContractError(
            "file_family_encoding_unsupported", "CSV is not UTF-8 or UTF-8-BOM"
        ) from exc
    if "\x00" in text or len(text) > CSV_MAX_TEXT_CHARS:
        raise FileFamilyContractError(
            "file_family_input_limit_exceeded", "CSV text exceeds its closed character limit"
        )
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|") if sample else csv.excel
    except csv.Error:
        dialect = csv.excel
    if dialect.delimiter not in {",", ";", "\t", "|"}:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "CSV delimiter is outside the closed set"
        )
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    cells = 0
    prior_field_limit = csv.field_size_limit()
    csv.field_size_limit(CSV_MAX_FIELD_CHARS)
    try:
        reader = csv.reader(StringIO(text, newline=""), dialect)
        for row_number, raw_row in enumerate(reader, start=1):
            _cancel_or_timeout(cancelled, started)
            if row_number > CSV_MAX_ROWS:
                raise FileFamilyContractError(
                    "file_family_member_limit_exceeded", "CSV row count exceeds its closed limit"
                )
            if len(raw_row) > CSV_MAX_COLUMNS:
                raise FileFamilyContractError(
                    "file_family_member_limit_exceeded", "CSV column count exceeds its closed limit"
                )
            selected_cells = []
            for column, display in enumerate(raw_row, start=1):
                cells += 1
                if cells > CSV_MAX_CELLS or len(display) > CSV_MAX_FIELD_CHARS:
                    raise FileFamilyContractError(
                        "file_family_member_limit_exceeded", "CSV cell limits were exceeded"
                    )
                coordinate = f"{_column_name(column)}{row_number}"
                selected_cells.append(
                    {
                        "row": row_number,
                        "column": column,
                        "coordinate": coordinate,
                        "value_kind": "empty" if display == "" else "text",
                        "display_value": display,
                    }
                )
                anchors.append(
                    {
                        "kind": "cell",
                        "schema_version": 1,
                        "profile": "csv",
                        "row": row_number,
                        "column": column,
                        "coordinate": coordinate,
                    }
                )
            rows.append({"row": row_number, "cells": selected_cells})
    except csv.Error as exc:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "CSV quoting or field structure is invalid"
        ) from exc
    finally:
        csv.field_size_limit(prior_field_limit)
    profile = {
        "delimiter": dialect.delimiter,
        "quote_character": dialect.quotechar,
        "row_count": len(rows),
        "cell_count": cells,
        "rows": rows,
    }
    preview = {"tables": [{"name": "CSV", "rows": rows}], "members": []}
    return profile, anchors, preview


def _xlsx_payloads(
    data: bytes,
    *,
    cancelled: Callable[[], bool] | None,
) -> dict[str, bytes]:
    if len(data) > XLSX_MAX_INPUT_BYTES:
        raise FileFamilyContractError(
            "file_family_input_limit_exceeded", "XLSX input exceeds its closed byte limit"
        )
    started = time.monotonic()
    payloads: dict[str, bytes] = {}
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = _archive_infos(
                archive,
                max_members=XLSX_MAX_MEMBERS,
                max_total=XLSX_MAX_TOTAL_UNCOMPRESSED,
                max_member=XLSX_MAX_MEMBER_BYTES,
            )
            for path, info in infos:
                _cancel_or_timeout(cancelled, started)
                if info.is_dir():
                    continue
                payloads[path] = _read_archive_member(archive, info)
    except FileFamilyContractError:
        raise
    except (BadZipFile, OSError, RuntimeError, NotImplementedError, zlib.error) as exc:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "XLSX package is corrupt or truncated"
        ) from exc
    return payloads


def _relationship_map(payloads: Mapping[str, bytes]) -> dict[str, tuple[str, str]]:
    relationships: dict[str, tuple[str, str]] = {}
    for path, payload in sorted(payloads.items()):
        if not path.endswith(".rels"):
            continue
        root = _parse_xml(payload, label=path)
        if root.tag != f"{{{_PACKAGE_REL_NS}}}Relationships":
            raise FileFamilyContractError(
                "file_family_structure_invalid", "OOXML relationship root is invalid"
            )
        current: dict[str, tuple[str, str]] = {}
        for node in root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
            relation_id = node.get("Id")
            target = node.get("Target")
            relation_type = node.get("Type")
            if str(node.get("TargetMode", "Internal")).casefold() == "external":
                raise FileFamilyContractError(
                    "file_family_external_relationship", "external OOXML relationships are rejected"
                )
            if (
                not relation_id
                or relation_id in current
                or not target
                or not relation_type
                or target.startswith(("/", "\\"))
                or "\\" in target
                or PurePosixPath(target).as_posix() != target
            ):
                raise FileFamilyContractError(
                    "file_family_structure_invalid", "OOXML relationship is invalid"
                )
            source = (
                path[: -len("/_rels/.rels")]
                if path.endswith("/_rels/.rels")
                else posixpath.join(
                    posixpath.dirname(posixpath.dirname(path)),
                    PurePosixPath(path).stem,
                )
            )
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
            try:
                resolved = _safe_member_path(resolved)
            except FileFamilyContractError as exc:
                raise FileFamilyContractError(
                    "file_family_structure_invalid", "OOXML relationship escapes the package"
                ) from exc
            current[relation_id] = (resolved, relation_type)
        if path == "xl/_rels/workbook.xml.rels":
            relationships = current
    return relationships


def _shared_strings(payloads: Mapping[str, bytes]) -> list[str]:
    payload = payloads.get("xl/sharedStrings.xml")
    if payload is None:
        return []
    root = _parse_xml(payload, label="xl/sharedStrings.xml")
    if root.tag != f"{{{_SPREADSHEET_NS}}}sst":
        raise FileFamilyContractError(
            "file_family_structure_invalid", "XLSX shared-string root is invalid"
        )
    strings = []
    total = 0
    for item in root.iter(f"{{{_SPREADSHEET_NS}}}si"):
        value = "".join(node.text or "" for node in item.iter(f"{{{_SPREADSHEET_NS}}}t"))
        total += len(value)
        strings.append(value)
        if len(strings) > XLSX_MAX_SHARED_STRINGS or total > XLSX_MAX_XML_TEXT_CHARS:
            raise FileFamilyContractError(
                "file_family_member_limit_exceeded", "XLSX shared strings exceed their limits"
            )
    return strings


def _xlsx_display_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
) -> tuple[str, str, bool]:
    cell_type = cell.get("t") or "n"
    value_node = cell.find(f"{{{_SPREADSHEET_NS}}}v")
    formula_present = cell.find(f"{{{_SPREADSHEET_NS}}}f") is not None
    if formula_present and value_node is None:
        raise FileFamilyContractError(
            "file_family_formula_value_unavailable",
            "formula-only XLSX cells have no inert cached value",
        )
    if cell_type == "inlineStr":
        display = "".join(node.text or "" for node in cell.iter(f"{{{_SPREADSHEET_NS}}}t"))
        kind = "empty" if display == "" else "text"
    else:
        raw = "" if value_node is None or value_node.text is None else value_node.text
        if cell_type == "s":
            if (
                not raw.isascii()
                or not raw.isdigit()
                or len(raw) > len(str(XLSX_MAX_SHARED_STRINGS))
            ):
                raise FileFamilyContractError(
                    "file_family_structure_invalid", "XLSX shared-string reference is invalid"
                )
            try:
                display = shared_strings[int(raw)]
            except (IndexError, ValueError) as exc:
                raise FileFamilyContractError(
                    "file_family_structure_invalid", "XLSX shared-string reference is invalid"
                ) from exc
            kind = "empty" if display == "" else "text"
        elif cell_type == "b":
            if raw not in {"0", "1"}:
                raise FileFamilyContractError(
                    "file_family_structure_invalid", "XLSX Boolean cache is invalid"
                )
            display = "TRUE" if raw == "1" else "FALSE"
            kind = "boolean"
        elif cell_type in {"n", "str", "e", "d"}:
            display = raw
            kind = {
                "n": "empty" if raw == "" else "number",
                "str": "empty" if raw == "" else "text",
                "e": "error",
                "d": "date-string",
            }[cell_type]
            if cell_type == "n" and raw:
                try:
                    number = decimal.Decimal(raw)
                except decimal.InvalidOperation as exc:
                    raise FileFamilyContractError(
                        "file_family_structure_invalid", "XLSX numeric cache is invalid"
                    ) from exc
                if not number.is_finite():
                    raise FileFamilyContractError(
                        "file_family_structure_invalid", "XLSX numeric cache is not finite"
                    )
        else:
            raise FileFamilyContractError(
                "file_family_structure_invalid", "XLSX cell type is unsupported"
            )
    if len(display) > XLSX_MAX_CELL_CHARS:
        raise FileFamilyContractError(
            "file_family_member_limit_exceeded", "XLSX cell text exceeds its limit"
        )
    return display, kind, formula_present


def _parse_xlsx(
    data: bytes,
    *,
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    payloads = _xlsx_payloads(data, cancelled=cancelled)
    required = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
    if not required.issubset(payloads):
        raise FileFamilyContractError(
            "file_family_structure_invalid", "XLSX package is missing required parts"
        )
    active_names = (
        "vbaproject.bin",
        "activex",
        "embeddings",
        "externalLinks".casefold(),
        "oleobject",
    )
    lowered_names = [path.casefold() for path in payloads]
    content_types = payloads["[Content_Types].xml"].lower()
    if any(token.casefold() in path for path in lowered_names for token in active_names) or any(
        token in content_types for token in (b"macroenabled", b"vba", b"activex", b"oleobject")
    ):
        raise FileFamilyContractError(
            "file_family_active_content", "macro or embedded active OOXML content is rejected"
        )
    content_types_root = _parse_xml(
        payloads["[Content_Types].xml"], label="[Content_Types].xml"
    )
    if content_types_root.tag != f"{{{_CONTENT_TYPES_NS}}}Types":
        raise FileFamilyContractError(
            "file_family_structure_invalid", "XLSX content-type root is invalid"
        )
    relationships = _relationship_map(payloads)
    workbook = _parse_xml(payloads["xl/workbook.xml"], label="xl/workbook.xml")
    if workbook.tag != f"{{{_SPREADSHEET_NS}}}workbook":
        raise FileFamilyContractError(
            "file_family_structure_invalid", "XLSX workbook root is invalid"
        )
    sheets_node = workbook.find(f"{{{_SPREADSHEET_NS}}}sheets")
    if sheets_node is None:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "XLSX workbook contains no sheets"
        )
    declared = []
    sheet_names: set[str] = set()
    for node in sheets_node.findall(f"{{{_SPREADSHEET_NS}}}sheet"):
        name = node.get("name")
        relation_id = node.get(f"{{{_OFFICE_REL_NS}}}id")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 255
            or name != unicodedata.normalize("NFC", name)
            or any(ord(character) < 32 for character in name)
            or name.casefold() in sheet_names
            or relation_id not in relationships
        ):
            raise FileFamilyContractError(
                "file_family_structure_invalid", "XLSX sheet identity is invalid"
            )
        sheet_names.add(name.casefold())
        path, relation_type = relationships[relation_id]
        if not relation_type.endswith("/worksheet") or not path.startswith("xl/worksheets/"):
            raise FileFamilyContractError(
                "file_family_structure_invalid", "XLSX sheet relationship is invalid"
            )
        if path not in payloads:
            raise FileFamilyContractError(
                "file_family_structure_invalid", "XLSX worksheet part is missing"
            )
        declared.append((name, path))
    if not declared or len(declared) > XLSX_MAX_SHEETS:
        raise FileFamilyContractError(
            "file_family_member_limit_exceeded", "XLSX sheet count exceeds its boundary"
        )
    shared_strings = _shared_strings(payloads)
    anchors: list[dict[str, Any]] = []
    sheets = []
    total_rows = 0
    total_cells = 0
    started = time.monotonic()
    for sheet_index, (name, path) in enumerate(declared, start=1):
        _cancel_or_timeout(cancelled, started)
        anchors.append(
            {
                "kind": "sheet",
                "schema_version": 1,
                "sheet_index": sheet_index,
                "sheet_name": name,
            }
        )
        root = _parse_xml(payloads[path], label=path)
        if root.tag != f"{{{_SPREADSHEET_NS}}}worksheet":
            raise FileFamilyContractError(
                "file_family_structure_invalid", "XLSX worksheet root is invalid"
            )
        rows_by_number: dict[int, list[dict[str, Any]]] = {}
        seen_cells: set[str] = set()
        sheet_row_count = 0
        for row_node in root.iter(f"{{{_SPREADSHEET_NS}}}row"):
            _cancel_or_timeout(cancelled, started)
            total_rows += 1
            sheet_row_count += 1
            if total_rows > XLSX_MAX_ROWS:
                raise FileFamilyContractError(
                    "file_family_member_limit_exceeded", "XLSX row count exceeds its closed limit"
                )
            for cell in row_node.findall(f"{{{_SPREADSHEET_NS}}}c"):
                row, column, coordinate = _cell_coordinates(cell.get("r"))
                if coordinate in seen_cells:
                    raise FileFamilyContractError(
                        "file_family_collision", "XLSX cell coordinates collide"
                    )
                seen_cells.add(coordinate)
                declared_row = row_node.get("r")
                if declared_row is not None and (
                    not declared_row.isascii()
                    or not declared_row.isdigit()
                    or len(declared_row) > 7
                    or int(declared_row) != row
                ):
                    raise FileFamilyContractError(
                        "file_family_structure_invalid", "XLSX row and cell coordinates disagree"
                    )
                total_cells += 1
                if total_cells > XLSX_MAX_CELLS:
                    raise FileFamilyContractError(
                        "file_family_member_limit_exceeded",
                        "XLSX cell count exceeds its closed limit",
                    )
                display, value_kind, formula_present = _xlsx_display_value(cell, shared_strings)
                rows_by_number.setdefault(row, []).append(
                    {
                        "row": row,
                        "column": column,
                        "coordinate": coordinate,
                        "value_kind": value_kind,
                        "display_value": display,
                        "formula_present": formula_present,
                    }
                )
                anchors.append(
                    {
                        "kind": "cell",
                        "schema_version": 1,
                        "profile": "xlsx",
                        "sheet_index": sheet_index,
                        "sheet_name": name,
                        "row": row,
                        "column": column,
                        "coordinate": coordinate,
                    }
                )
        rows = [
            {"row": row, "cells": sorted(cells, key=lambda item: item["column"])}
            for row, cells in sorted(rows_by_number.items())
        ]
        sheets.append(
            {
                "sheet_index": sheet_index,
                "sheet_name": name,
                "row_count": sheet_row_count,
                "cell_count": sum(len(row["cells"]) for row in rows),
                "rows": rows,
            }
        )
    profile = {
        "sheet_count": len(sheets),
        "row_count": total_rows,
        "cell_count": total_cells,
        "shared_string_count": len(shared_strings),
        "sheets": sheets,
    }
    preview = {"tables": sheets, "members": []}
    return profile, anchors, preview


def _parse_zip(
    data: bytes,
    *,
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if len(data) > ZIP_MAX_INPUT_BYTES:
        raise FileFamilyContractError(
            "file_family_input_limit_exceeded", "ZIP input exceeds its closed byte limit"
        )
    started = time.monotonic()
    members = []
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = _archive_infos(
                archive,
                max_members=ZIP_MAX_MEMBERS,
                max_total=ZIP_MAX_TOTAL_UNCOMPRESSED,
                max_member=ZIP_MAX_MEMBER_BYTES,
            )
            for archive_index, (path, info) in enumerate(infos, start=1):
                _cancel_or_timeout(cancelled, started)
                if info.is_dir():
                    continue
                payload = _read_archive_member(archive, info)
                members.append(
                    {
                        "archive_index": archive_index,
                        "path": path,
                        "sha256": _sha256(payload),
                        "media_type": _FIXED_MEDIA_TYPES.get(
                            PurePosixPath(path).suffix.casefold(), "application/octet-stream"
                        ),
                        "compressed_size": info.compress_size,
                        "uncompressed_size": info.file_size,
                        "compression_ratio": round(info.file_size / max(info.compress_size, 1), 6),
                        "nested_archive": PurePosixPath(path).suffix.casefold() == ".zip",
                    }
                )
    except FileFamilyContractError:
        raise
    except (BadZipFile, OSError, RuntimeError, NotImplementedError, zlib.error) as exc:
        raise FileFamilyContractError(
            "file_family_structure_invalid", "ZIP package is corrupt or truncated"
        ) from exc
    members.sort(key=lambda item: item["path"])
    anchors = []
    for member_index, member in enumerate(members, start=1):
        member["member_index"] = member_index
        anchors.append(
            {
                "kind": "member",
                "schema_version": 1,
                "member_index": member_index,
                "path": member["path"],
                "sha256": member["sha256"],
            }
        )
    profile = {
        "member_count": len(members),
        "total_uncompressed_bytes": sum(item["uncompressed_size"] for item in members),
        "members": members,
        "host_extraction": False,
        "nested_expansion": False,
    }
    preview = {"tables": [], "members": members}
    return profile, anchors, preview


def _limits(profile_id: str) -> dict[str, Any]:
    if profile_id == CSV_PROFILE_ID:
        return {
            "max_input_bytes": CSV_MAX_INPUT_BYTES,
            "max_rows": CSV_MAX_ROWS,
            "max_columns": CSV_MAX_COLUMNS,
            "max_cells": CSV_MAX_CELLS,
            "max_field_characters": CSV_MAX_FIELD_CHARS,
        }
    if profile_id == XLSX_PROFILE_ID:
        return {
            "max_input_bytes": XLSX_MAX_INPUT_BYTES,
            "max_members": XLSX_MAX_MEMBERS,
            "max_total_uncompressed_bytes": XLSX_MAX_TOTAL_UNCOMPRESSED,
            "max_sheets": XLSX_MAX_SHEETS,
            "max_rows": XLSX_MAX_ROWS,
            "max_cells": XLSX_MAX_CELLS,
            "max_xml_depth": XLSX_MAX_XML_DEPTH,
        }
    if profile_id == ZIP_PROFILE_ID:
        return {
            "max_input_bytes": ZIP_MAX_INPUT_BYTES,
            "max_members": ZIP_MAX_MEMBERS,
            "max_total_uncompressed_bytes": ZIP_MAX_TOTAL_UNCOMPRESSED,
            "max_member_bytes": ZIP_MAX_MEMBER_BYTES,
            "max_compression_ratio": ZIP_MAX_COMPRESSION_RATIO,
            "max_processing_seconds": int(MAX_ARCHIVE_PROCESS_SECONDS),
        }
    raise FileFamilyContractError(
        "file_family_profile_invalid", "file-family profile is outside the closed set"
    )


def _invalid_profile(message: str) -> FileFamilyContractError:
    return FileFamilyContractError("file_family_contract_violation", message)


def _profile_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid_profile(f"{label} fields are invalid")
    return dict(value)


def _profile_integer(value: Any, *, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid_profile(f"{label} is outside its closed limit")
    return value


def _profile_cell(
    value: Any,
    *,
    expected_row: int,
    expected_column: int,
    xlsx: bool,
) -> dict[str, Any]:
    fields = {"row", "column", "coordinate", "value_kind", "display_value"}
    if xlsx:
        fields.add("formula_present")
    cell = _profile_object(value, fields, "file-family cell")
    row = _profile_integer(cell["row"], minimum=1, maximum=MAX_CELL_ROW, label="cell row")
    column = _profile_integer(
        cell["column"], minimum=1, maximum=MAX_CELL_COLUMN, label="cell column"
    )
    if row != expected_row or column != expected_column:
        raise _invalid_profile("file-family cell ordering is invalid")
    expected_coordinate = f"{_column_name(column)}{row}"
    if cell["coordinate"] != expected_coordinate:
        raise _invalid_profile("file-family cell coordinate is inconsistent")
    display = cell["display_value"]
    maximum = XLSX_MAX_CELL_CHARS if xlsx else CSV_MAX_FIELD_CHARS
    if not isinstance(display, str) or len(display) > maximum:
        raise _invalid_profile("file-family displayed value is invalid")
    kinds = {"empty", "text"}
    if xlsx:
        kinds.update({"boolean", "number", "error", "date-string"})
        if type(cell["formula_present"]) is not bool:
            raise _invalid_profile("XLSX formula-presence evidence is invalid")
    if cell["value_kind"] not in kinds or (cell["value_kind"] == "empty") != (display == ""):
        raise _invalid_profile("file-family displayed value type is invalid")
    if xlsx and cell["value_kind"] == "boolean" and display not in {"TRUE", "FALSE"}:
        raise _invalid_profile("XLSX Boolean display is invalid")
    if xlsx and cell["value_kind"] == "number":
        try:
            number = decimal.Decimal(display)
        except decimal.InvalidOperation as exc:
            raise _invalid_profile("XLSX numeric display is invalid") from exc
        if not number.is_finite():
            raise _invalid_profile("XLSX numeric display is not finite")
    return cell


def _validate_csv_profile(value: Any) -> None:
    profile = _profile_object(
        value,
        {"delimiter", "quote_character", "row_count", "cell_count", "rows"},
        "CSV profile",
    )
    if profile["delimiter"] not in {",", ";", "\t", "|"}:
        raise _invalid_profile("CSV delimiter is invalid")
    if not isinstance(profile["quote_character"], str) or len(profile["quote_character"]) != 1:
        raise _invalid_profile("CSV quote character is invalid")
    rows = profile["rows"]
    if not isinstance(rows, list):
        raise _invalid_profile("CSV rows are invalid")
    row_count = _profile_integer(
        profile["row_count"], minimum=0, maximum=CSV_MAX_ROWS, label="CSV row count"
    )
    if row_count != len(rows):
        raise _invalid_profile("CSV row count is inconsistent")
    cell_count = 0
    for expected_row, value_row in enumerate(rows, start=1):
        row = _profile_object(value_row, {"row", "cells"}, "CSV row")
        if row["row"] != expected_row or not isinstance(row["cells"], list):
            raise _invalid_profile("CSV row ordering is invalid")
        if len(row["cells"]) > CSV_MAX_COLUMNS:
            raise _invalid_profile("CSV column count exceeds its closed limit")
        for expected_column, cell in enumerate(row["cells"], start=1):
            _profile_cell(
                cell,
                expected_row=expected_row,
                expected_column=expected_column,
                xlsx=False,
            )
            cell_count += 1
    expected_cells = _profile_integer(
        profile["cell_count"], minimum=0, maximum=CSV_MAX_CELLS, label="CSV cell count"
    )
    if expected_cells != cell_count:
        raise _invalid_profile("CSV cell count is inconsistent")


def _validate_xlsx_profile(value: Any) -> None:
    profile = _profile_object(
        value,
        {"sheet_count", "row_count", "cell_count", "shared_string_count", "sheets"},
        "XLSX profile",
    )
    sheets = profile["sheets"]
    if not isinstance(sheets, list):
        raise _invalid_profile("XLSX sheets are invalid")
    sheet_count = _profile_integer(
        profile["sheet_count"], minimum=1, maximum=XLSX_MAX_SHEETS, label="XLSX sheet count"
    )
    if sheet_count != len(sheets):
        raise _invalid_profile("XLSX sheet count is inconsistent")
    _profile_integer(
        profile["shared_string_count"],
        minimum=0,
        maximum=XLSX_MAX_SHARED_STRINGS,
        label="XLSX shared-string count",
    )
    total_rows = 0
    total_cells = 0
    sheet_names: set[str] = set()
    for sheet_index, value_sheet in enumerate(sheets, start=1):
        sheet = _profile_object(
            value_sheet,
            {"sheet_index", "sheet_name", "row_count", "cell_count", "rows"},
            "XLSX sheet",
        )
        name = sheet["sheet_name"]
        if (
            sheet["sheet_index"] != sheet_index
            or not isinstance(name, str)
            or not 1 <= len(name) <= 255
            or name != unicodedata.normalize("NFC", name)
            or any(ord(character) < 32 for character in name)
            or name.casefold() in sheet_names
            or not isinstance(sheet["rows"], list)
        ):
            raise _invalid_profile("XLSX sheet identity is invalid")
        sheet_names.add(name.casefold())
        declared_rows = _profile_integer(
            sheet["row_count"], minimum=0, maximum=XLSX_MAX_ROWS, label="XLSX row count"
        )
        if declared_rows < len(sheet["rows"]):
            raise _invalid_profile("XLSX row count is inconsistent")
        total_rows += declared_rows
        prior_row = 0
        sheet_cells = 0
        for value_row in sheet["rows"]:
            row = _profile_object(value_row, {"row", "cells"}, "XLSX row")
            row_number = _profile_integer(
                row["row"], minimum=1, maximum=MAX_CELL_ROW, label="XLSX row number"
            )
            if row_number <= prior_row or not isinstance(row["cells"], list) or not row["cells"]:
                raise _invalid_profile("XLSX row ordering is invalid")
            prior_row = row_number
            prior_column = 0
            for value_cell in row["cells"]:
                if not isinstance(value_cell, Mapping):
                    raise _invalid_profile("XLSX cell is invalid")
                column = value_cell.get("column")
                if type(column) is not int or column <= prior_column:
                    raise _invalid_profile("XLSX cell ordering is invalid")
                _profile_cell(
                    value_cell,
                    expected_row=row_number,
                    expected_column=column,
                    xlsx=True,
                )
                prior_column = column
                sheet_cells += 1
        declared_cells = _profile_integer(
            sheet["cell_count"], minimum=0, maximum=XLSX_MAX_CELLS, label="XLSX cell count"
        )
        if declared_cells != sheet_cells:
            raise _invalid_profile("XLSX sheet cell count is inconsistent")
        total_cells += sheet_cells
    declared_total_rows = _profile_integer(
        profile["row_count"], minimum=0, maximum=XLSX_MAX_ROWS, label="XLSX total row count"
    )
    declared_total_cells = _profile_integer(
        profile["cell_count"], minimum=0, maximum=XLSX_MAX_CELLS, label="XLSX total cell count"
    )
    if declared_total_rows != total_rows or declared_total_cells != total_cells:
        raise _invalid_profile("XLSX aggregate counts are inconsistent")


def _validate_zip_profile(value: Any) -> None:
    profile = _profile_object(
        value,
        {
            "member_count",
            "total_uncompressed_bytes",
            "members",
            "host_extraction",
            "nested_expansion",
        },
        "ZIP profile",
    )
    members = profile["members"]
    if (
        not isinstance(members, list)
        or profile["host_extraction"] is not False
        or profile["nested_expansion"] is not False
    ):
        raise _invalid_profile("ZIP profile invariants are invalid")
    declared_count = _profile_integer(
        profile["member_count"], minimum=0, maximum=ZIP_MAX_MEMBERS, label="ZIP member count"
    )
    if declared_count != len(members):
        raise _invalid_profile("ZIP member count is inconsistent")
    prior_path = ""
    identities: set[str] = set()
    offsets: set[int] = set()
    total = 0
    for member_index, value_member in enumerate(members, start=1):
        member = _profile_object(
            value_member,
            {
                "archive_index",
                "path",
                "sha256",
                "media_type",
                "compressed_size",
                "uncompressed_size",
                "compression_ratio",
                "nested_archive",
                "member_index",
            },
            "ZIP member",
        )
        try:
            path = _safe_member_path(member["path"])
        except FileFamilyContractError as exc:
            raise _invalid_profile("ZIP member path is invalid") from exc
        identity = path.casefold()
        if (
            member["member_index"] != member_index
            or path <= prior_path
            or identity in identities
            or _SHA256.fullmatch(str(member["sha256"])) is None
            or member["media_type"]
            != _FIXED_MEDIA_TYPES.get(
                PurePosixPath(path).suffix.casefold(), "application/octet-stream"
            )
            or type(member["nested_archive"]) is not bool
            or member["nested_archive"] != (PurePosixPath(path).suffix.casefold() == ".zip")
        ):
            raise _invalid_profile("ZIP member identity is invalid")
        offset = _profile_integer(
            member["archive_index"],
            minimum=1,
            maximum=ZIP_MAX_MEMBERS,
            label="ZIP archive index",
        )
        compressed = _profile_integer(
            member["compressed_size"],
            minimum=0,
            maximum=ZIP_MAX_INPUT_BYTES,
            label="ZIP compressed size",
        )
        uncompressed = _profile_integer(
            member["uncompressed_size"],
            minimum=0,
            maximum=ZIP_MAX_MEMBER_BYTES,
            label="ZIP uncompressed size",
        )
        ratio = member["compression_ratio"]
        expected_ratio = round(uncompressed / max(compressed, 1), 6)
        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or ratio != expected_ratio
            or ratio > ZIP_MAX_COMPRESSION_RATIO
            or offset in offsets
        ):
            raise _invalid_profile("ZIP member size evidence is invalid")
        offsets.add(offset)
        identities.add(identity)
        prior_path = path
        total += uncompressed
    declared_total = _profile_integer(
        profile["total_uncompressed_bytes"],
        minimum=0,
        maximum=ZIP_MAX_TOTAL_UNCOMPRESSED,
        label="ZIP total bytes",
    )
    if declared_total != total:
        raise _invalid_profile("ZIP aggregate bytes are inconsistent")


def validate_file_family_record(value: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "kind",
        "profile_id",
        "version_id",
        "original_sha256",
        "format",
        "media_type",
        "byte_length",
        "parser",
        "limits",
        "profile",
        "invariants",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise FileFamilyContractError(
            "file_family_contract_violation", "file-family record fields are invalid"
        )
    record = dict(value)
    profile_id = record.get("profile_id")
    if (
        record.get("schema_version") != FILE_FAMILY_SCHEMA_VERSION
        or record.get("kind") != "file-family-profile"
        or profile_id not in FILE_FAMILY_PROFILE_IDS
        or not isinstance(record.get("version_id"), str)
        or _SHA256.fullmatch(str(record.get("original_sha256"))) is None
        or record.get("format") != PROFILE_FORMATS[profile_id]
        or record.get("media_type") != PROFILE_MEDIA_TYPES[profile_id]
        or type(record.get("byte_length")) is not int
        or not 0 <= record["byte_length"] <= _limits(profile_id)["max_input_bytes"]
        or record.get("limits") != _limits(profile_id)
        or not isinstance(record.get("profile"), Mapping)
    ):
        raise FileFamilyContractError(
            "file_family_contract_violation", "file-family record identity is invalid"
        )
    if record.get("parser") != {
        "component": PARSER_COMPONENT,
        "version": PARSER_VERSION,
        "license": PARSER_LICENSE,
        "adapter": f"bounded-{PROFILE_FORMATS[profile_id].casefold()}",
        "adapter_version": "1",
    }:
        raise FileFamilyContractError(
            "file_family_contract_violation", "file-family parser identity is invalid"
        )
    expected_invariants = {
        "derived": True,
        "original_immutable": True,
        "canonical_records_immutable": True,
        "network_used": False,
        "runtime_downloads": False,
        "active_content_executed": False,
        "formula_execution": False,
        "source_writeback": False,
        "host_archive_extraction": False,
    }
    if record.get("invariants") != expected_invariants:
        raise FileFamilyContractError(
            "file_family_contract_violation", "file-family invariants are invalid"
        )
    profile = record["profile"]
    if profile_id == CSV_PROFILE_ID:
        _validate_csv_profile(profile)
    elif profile_id == XLSX_PROFILE_ID:
        _validate_xlsx_profile(profile)
    else:
        _validate_zip_profile(profile)
    return record


class FileFamilyProfileManager:
    """Deterministic local jobs and lifecycle for exactly three bounded profiles."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.bundles = RepresentationBundleManager(store)
        self.root = store.paths.state / "file-families"
        self.jobs = self.root / "jobs"

    def capability(self) -> dict[str, Any]:
        runtime = f"{sys.version_info.major}.{sys.version_info.minor}"
        return {
            "schema_version": 1,
            "profile_ids": list(FILE_FAMILY_PROFILE_IDS),
            "profiles": [
                {
                    "profile_id": profile_id,
                    "format": PROFILE_FORMATS[profile_id],
                    "parser": {
                        "component": PARSER_COMPONENT,
                        "version": PARSER_VERSION,
                        "license": PARSER_LICENSE,
                    },
                    "limits": _limits(profile_id),
                    "state": "available" if runtime == PARSER_VERSION else "unavailable",
                    "reason": None if runtime == PARSER_VERSION else "unsupported_platform",
                }
                for profile_id in FILE_FAMILY_PROFILE_IDS
            ],
            "runtime": runtime,
            "network_used": False,
            "runtime_downloads": False,
            "mutated": False,
        }

    def _source(self, version_id: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        version = self.store.read_canonical("versions", version_id)
        if version is None:
            raise FileFamilyContractError(
                "file_family_not_found", "file-family DocumentVersion was not found"
            )
        original = self.store.read_canonical("originals", str(version.get("original_id", "")))
        if original is None:
            raise FileFamilyContractError(
                "file_family_not_found", "file-family Original was not found"
            )
        data = self.store.original_bytes(str(original["id"]))
        digest = _sha256(data)
        if (
            digest != original.get("sha256")
            or digest != version.get("content_hash")
            or len(data) != original.get("size_bytes")
            or len(data) != version.get("size_bytes")
        ):
            raise FileFamilyContractError(
                "file_family_contract_violation", "Original identity verification failed"
            )
        return version, original, data

    def _derive(
        self,
        version_id: str,
        profile_id: str,
        *,
        cancelled: Callable[[], bool] | None = None,
        frozen_settings: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, tuple[str, bytes]], dict[str, Any], list[dict[str, Any]]]:
        if profile_id not in FILE_FAMILY_PROFILE_IDS:
            raise FileFamilyContractError(
                "file_family_profile_invalid", "file-family profile is outside the closed set"
            )
        if f"{sys.version_info.major}.{sys.version_info.minor}" != PARSER_VERSION:
            raise FileFamilyContractError(
                "file_family_profile_invalid", "Python 3.12 parser identity is unavailable"
            )
        _version, original, data = self._source(version_id)
        if frozen_settings is not None and dict(frozen_settings) != {
            "profile_id": profile_id,
            "parser": {
                "component": PARSER_COMPONENT,
                "version": PARSER_VERSION,
                "license": PARSER_LICENSE,
            },
            "limits": _limits(profile_id),
        }:
            raise FileFamilyContractError(
                "file_family_contract_violation", "rebuild settings no longer match"
            )
        parser = {
            "component": PARSER_COMPONENT,
            "version": PARSER_VERSION,
            "license": PARSER_LICENSE,
            "adapter": f"bounded-{PROFILE_FORMATS[profile_id].casefold()}",
            "adapter_version": "1",
        }
        if profile_id == CSV_PROFILE_ID:
            profile, anchors, preview = _parse_csv(data, cancelled=cancelled)
        elif profile_id == XLSX_PROFILE_ID:
            profile, anchors, preview = _parse_xlsx(data, cancelled=cancelled)
        else:
            profile, anchors, preview = _parse_zip(data, cancelled=cancelled)
        if len(anchors) > MAX_REPRESENTATION_ANCHORS:
            raise FileFamilyContractError(
                "file_family_member_limit_exceeded", "file-family anchor count exceeds its limit"
            )
        record = validate_file_family_record(
            {
                "schema_version": FILE_FAMILY_SCHEMA_VERSION,
                "kind": "file-family-profile",
                "profile_id": profile_id,
                "version_id": version_id,
                "original_sha256": str(original["sha256"]),
                "format": PROFILE_FORMATS[profile_id],
                "media_type": PROFILE_MEDIA_TYPES[profile_id],
                "byte_length": len(data),
                "parser": parser,
                "limits": _limits(profile_id),
                "profile": profile,
                "invariants": {
                    "derived": True,
                    "original_immutable": True,
                    "canonical_records_immutable": True,
                    "network_used": False,
                    "runtime_downloads": False,
                    "active_content_executed": False,
                    "formula_execution": False,
                    "source_writeback": False,
                    "host_archive_extraction": False,
                },
            }
        )
        preview_record = {
            "schema_version": 1,
            "profile_id": profile_id,
            "version_id": version_id,
            "format": PROFILE_FORMATS[profile_id],
            **preview,
            "inert": True,
            "active_content_executed": False,
        }
        settings = {
            "profile_id": profile_id,
            "parser": {
                "component": PARSER_COMPONENT,
                "version": PARSER_VERSION,
                "license": PARSER_LICENSE,
            },
            "limits": _limits(profile_id),
        }
        return (
            {
                "profile.json": ("application/json", canonical_json_bytes(record)),
                "preview.json": ("application/json", canonical_json_bytes(preview_record)),
            },
            settings,
            anchors,
        )

    def create(
        self,
        version_id: str,
        profile_id: str,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        payloads, settings, anchors = self._derive(version_id, profile_id, cancelled=cancelled)
        expected = {
            name: {"media_type": media_type, "sha256": _sha256(payload), "size_bytes": len(payload)}
            for name, (media_type, payload) in payloads.items()
        }
        for existing in self.bundles.list(
            version_id=version_id, recipe_id=FILE_FAMILY_RECIPE_ID, limit=500
        ):
            actual = {
                Path(str(output["storage_ref"])).name: {
                    "media_type": output["media_type"],
                    "sha256": output["sha256"],
                    "size_bytes": output["size_bytes"],
                }
                for output in existing["outputs"]
            }
            if (
                existing["recipe"]["version"] == FILE_FAMILY_RECIPE_VERSION
                and existing["recipe"]["settings"] == settings
                and actual == expected
            ):
                return existing
        try:
            return self.bundles.materialize(
                version_id,
                recipe_id=FILE_FAMILY_RECIPE_ID,
                recipe_version=FILE_FAMILY_RECIPE_VERSION,
                recipe_settings=settings,
                output_payloads=payloads,
                implementation={
                    "component": "provelume.core",
                    "component_version": "0.9.0",
                    "adapter": "perceptio-file-family-profile",
                    "adapter_version": "1",
                    "settings": {"mode": "offline", "active_content": "never"},
                },
                anchor_targets=anchors,
            )
        except RepresentationContractError as exc:
            raise FileFamilyContractError("file_family_contract_violation", str(exc)) from exc

    def queue(self, version_id: str, profile_id: str) -> dict[str, Any]:
        self._source(version_id)
        if profile_id not in FILE_FAMILY_PROFILE_IDS:
            raise FileFamilyContractError(
                "file_family_profile_invalid", "file-family profile is outside the closed set"
            )
        processing_identity = {
            "profile_id": profile_id,
            "parser": {
                "component": PARSER_COMPONENT,
                "version": PARSER_VERSION,
                "license": PARSER_LICENSE,
            },
            "limits": _limits(profile_id),
        }
        identity = _sha256(
            canonical_json_bytes(
                {
                    "version_id": version_id,
                    "recipe": FILE_FAMILY_RECIPE_ID,
                    "version": FILE_FAMILY_RECIPE_VERSION,
                    "processing_identity": processing_identity,
                }
            )
        )
        job_id = f"file_family_{identity}"
        self.jobs.mkdir(parents=True, exist_ok=True)
        target = self.jobs / f"{job_id}.json"
        if target.exists():
            return {"scheduled": False, "job": self.get_job(job_id)}
        job = {
            "schema_version": FILE_FAMILY_JOB_SCHEMA_VERSION,
            "id": job_id,
            "kind": "file-family.profile",
            "version_id": version_id,
            "profile_id": profile_id,
            "processing_identity": processing_identity,
            "status": "queued",
            "checkpoint": {"phase": "queued", "sequence": 0},
            "requested_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "representation_id": None,
            "error_code": None,
            "cancel_requested": False,
            "retry_count": 0,
        }
        self.store._atomic_json(target, job)
        return {"scheduled": True, "job": job}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        if re.fullmatch(r"file_family_[0-9a-f]{64}", job_id) is None:
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
        for path in sorted(self.jobs.glob("file_family_*.json"), reverse=True):
            value = self.get_job(path.stem)
            if value is not None:
                result.append(value)
            if len(result) >= min(max(limit, 1), 500):
                break
        return result

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise FileFamilyContractError("file_family_not_found", "file-family job was not found")
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            raise FileFamilyContractError(
                "file_family_job_state_invalid", "completed file-family job cannot be cancelled"
            )
        job["cancel_requested"] = True
        if job["status"] == "queued":
            job.update(
                {
                    "status": "cancelled",
                    "completed_at": utc_now(),
                    "checkpoint": {"phase": "cancelled", "sequence": 1},
                }
            )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        return job

    def retry(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise FileFamilyContractError("file_family_not_found", "file-family job was not found")
        if job["status"] not in {"failed", "cancelled"}:
            raise FileFamilyContractError(
                "file_family_job_state_invalid", "file-family job is not retryable"
            )
        job.update(
            {
                "status": "queued",
                "checkpoint": {
                    "phase": "queued",
                    "sequence": int(job["checkpoint"]["sequence"]) + 1,
                },
                "started_at": None,
                "completed_at": None,
                "representation_id": None,
                "error_code": None,
                "cancel_requested": False,
                "retry_count": int(job["retry_count"]) + 1,
            }
        )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        return job

    def run(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise FileFamilyContractError("file_family_not_found", "file-family job was not found")
        if job["status"] == "succeeded":
            return job
        if job["status"] != "queued":
            raise FileFamilyContractError(
                "file_family_job_state_invalid", "file-family job state is invalid"
            )
        if job["cancel_requested"]:
            return self.cancel(job_id)
        job.update(
            {
                "status": "running",
                "started_at": utc_now(),
                "checkpoint": {
                    "phase": "deriving",
                    "sequence": int(job["checkpoint"]["sequence"]) + 1,
                },
                "error_code": None,
            }
        )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)

        def cancelled() -> bool:
            current = self.get_job(job_id)
            return current is not None and current.get("cancel_requested") is True

        try:
            if job["processing_identity"] != {
                "profile_id": job["profile_id"],
                "parser": {
                    "component": PARSER_COMPONENT,
                    "version": PARSER_VERSION,
                    "license": PARSER_LICENSE,
                },
                "limits": _limits(str(job["profile_id"])),
            }:
                raise FileFamilyContractError(
                    "file_family_contract_violation", "queued parser identity changed"
                )
            bundle = self.create(
                str(job["version_id"]), str(job["profile_id"]), cancelled=cancelled
            )
        except FileFamilyContractError as exc:
            job.update(
                {
                    "status": "cancelled" if exc.code == "file_family_cancelled" else "failed",
                    "completed_at": utc_now(),
                    "error_code": exc.code,
                    "checkpoint": {
                        "phase": "cancelled" if exc.code == "file_family_cancelled" else "failed",
                        "sequence": int(job["checkpoint"]["sequence"]) + 1,
                    },
                }
            )
            self.store._atomic_json(self.jobs / f"{job_id}.json", job)
            return job
        current = self.get_job(job_id)
        if current is not None and current.get("cancel_requested") is True:
            with suppress(RepresentationContractError):
                self.bundles.remove(str(bundle["representation_id"]))
            current.update(
                {
                    "status": "cancelled",
                    "completed_at": utc_now(),
                    "representation_id": None,
                    "checkpoint": {
                        "phase": "cancelled",
                        "sequence": int(current["checkpoint"]["sequence"]) + 1,
                    },
                }
            )
            self.store._atomic_json(self.jobs / f"{job_id}.json", current)
            return current
        job.update(
            {
                "status": "succeeded",
                "completed_at": utc_now(),
                "representation_id": bundle["representation_id"],
                "checkpoint": {
                    "phase": "published",
                    "sequence": int(job["checkpoint"]["sequence"]) + 1,
                },
            }
        )
        self.store._atomic_json(self.jobs / f"{job_id}.json", job)
        return job

    def _record_for_bundle(self, bundle: Mapping[str, Any]) -> dict[str, Any] | None:
        if bundle.get("recipe", {}).get("id") != FILE_FAMILY_RECIPE_ID:
            return None
        output = next(
            (
                item
                for item in bundle["outputs"]
                if Path(item["storage_ref"]).name == "profile.json"
            ),
            None,
        )
        if output is None:
            return None
        try:
            path = safe_instance_path(self.store.paths.root, str(output["storage_ref"]))
            return validate_file_family_record(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def read_model(
        self,
        *,
        profile_id: str | None = None,
        version_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        if profile_id is not None and profile_id not in FILE_FAMILY_PROFILE_IDS:
            raise FileFamilyContractError(
                "file_family_profile_invalid", "file-family profile is outside the closed set"
            )
        profiles = []
        for bundle in self.bundles.list(recipe_id=FILE_FAMILY_RECIPE_ID, limit=500):
            record = self._record_for_bundle(bundle)
            if (
                record is None
                or (profile_id is not None and record["profile_id"] != profile_id)
                or (version_id is not None and record["version_id"] != version_id)
            ):
                continue
            profiles.append(
                {
                    "representation_id": bundle["representation_id"],
                    "availability": bundle["availability"],
                    "record": record,
                    "anchors": bundle["anchors"],
                    "outputs": bundle["outputs"],
                }
            )
            if len(profiles) >= min(max(limit, 1), 500):
                break
        return {
            "schema_version": 1,
            "profile_ids": list(FILE_FAMILY_PROFILE_IDS),
            "support": self.capability(),
            "profiles": profiles,
            "jobs": self.list_jobs(limit=limit),
            "network_used": False,
            "source_writeback": False,
        }

    def get(self, representation_id: str) -> dict[str, Any] | None:
        bundle = self.bundles.get(representation_id, deep=True)
        if bundle is None:
            return None
        record = self._record_for_bundle(bundle)
        if record is None:
            return None
        return {
            "representation_id": bundle["representation_id"],
            "availability": bundle["availability"],
            "record": record,
            "anchors": bundle["anchors"],
            "outputs": bundle["outputs"],
        }

    def remove(self, representation_id: str) -> dict[str, Any]:
        bundle = self.bundles.get(representation_id, deep=True)
        if bundle is None or bundle.get("recipe", {}).get("id") != FILE_FAMILY_RECIPE_ID:
            raise FileFamilyContractError(
                "file_family_not_found", "file-family representation was not found"
            )
        try:
            return self.bundles.remove(representation_id)
        except RepresentationContractError as exc:
            raise FileFamilyContractError("file_family_not_found", str(exc)) from exc

    def rebuild(self, representation_id: str) -> dict[str, Any]:
        receipt_path = self.bundles.history / f"{representation_id}.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            bundle = receipt["bundle"]
            if bundle["recipe"]["id"] != FILE_FAMILY_RECIPE_ID:
                raise KeyError("wrong recipe")
            version_id = str(bundle["version"]["id"])
            settings = dict(bundle["recipe"]["settings"])
            profile_id = str(settings["profile_id"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FileFamilyContractError(
                "file_family_not_found", "file-family removal history was not found"
            ) from exc
        payloads, _settings, _anchors = self._derive(
            version_id, profile_id, frozen_settings=settings
        )
        raw = {name: value[1] for name, value in payloads.items()}
        expected = {Path(item["storage_ref"]).name for item in bundle["outputs"]}
        if set(raw) != expected:
            raise FileFamilyContractError(
                "file_family_contract_violation", "file-family rebuild outputs no longer match"
            )
        try:
            return self.bundles.rebuild(representation_id, raw)
        except RepresentationContractError as exc:
            raise FileFamilyContractError("file_family_contract_violation", str(exc)) from exc


__all__ = [
    "CSV_PROFILE_ID",
    "FILE_FAMILY_ERROR_CODES",
    "FILE_FAMILY_PROFILE_IDS",
    "FileFamilyContractError",
    "FileFamilyProfileManager",
    "XLSX_PROFILE_ID",
    "ZIP_PROFILE_ID",
    "validate_file_family_record",
]
