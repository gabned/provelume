"""NEW S07 synthetic resources; scan storage corrected after real decompression rejection.

Deterministic PDF structure; no timestamps, identifiers, network or application use.
Run with the existing project environment. Raster reproducibility requires the
Pillow version and zlib runtime recorded in manifest.json; the font is bundled.
"""

from __future__ import annotations

import hashlib
import io
import json
import zlib
from pathlib import Path

import PIL
import pypdf
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / ".agent/s07/generated-trial-fixtures"
NATIVE_TOKEN = "LUMENATIVE731"
SCAN_TOKEN_IT = "LUMESCANITALIA842"
SCAN_TOKEN_EN = "LUMESCANENGLISH953"
NATIVE_LINES = [
    "Provelume synthetic native text document.",
    "Documento sintetico italiano con testo incorporato affidabile.",
    "Independent English fixture with reliable embedded text.",
    f"Search token: {NATIVE_TOKEN}",
    "This document contains no personal information or account references.",
]
SCAN_LINES = [
    "PROVELUME - SYNTHETIC SCAN",
    "",
    "Documento di prova in italiano.",
    "Il testo e presente solo come immagine.",
    f"Codice di ricerca: {SCAN_TOKEN_IT}",
    "",
    "Independent synthetic English document.",
    "The text appears only as raster pixels.",
    f"Search token: {SCAN_TOKEN_EN}",
    "",
    "No personal information. No credentials.",
]


def pdf(objects: list[bytes]) -> bytes:
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, content in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{i} 0 obj\n".encode() + content + b"\nendobj\n")
    offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for position in offsets[1:]:
        output.extend(f"{position:010d} 00000 n \n".encode())
    output.extend(
        (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
         f"startxref\n{offset}\n%%EOF\n").encode()
    )
    return bytes(output)


def stream(data: bytes, attributes: str = "") -> bytes:
    return f"<< /Length {len(data)} {attributes} >>\nstream\n".encode() + data + b"\nendstream"


def native_pdf() -> bytes:
    ops = ["BT /F1 16 Tf 50 780 Td 24 TL"]
    for index, line in enumerate(NATIVE_LINES):
        if index:
            ops.append("T*")
        literal = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({literal}) Tj")
    ops.append("ET")
    return pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
             b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            stream("\n".join(ops).encode("ascii")),
        ]
    )


def scan_pdf(compression_level=0) -> bytes:
    image = Image.new("L", (1654, 2339), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    y = 180
    for line in SCAN_LINES:
        draw.text((110, y), line, font=font, fill=0)
        y += 105
    raw = zlib.compress(image.tobytes(), level=compression_level)
    return pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
             b"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"),
            stream(
                raw,
                ("/Type /XObject /Subtype /Image /Width 1654 /Height 2339 "
                 "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode"),
            ),
            stream(b"q 595 0 0 842 0 0 cm /Im0 Do Q"),
        ]
    )


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> dict:
    outputs = {
        "native-text.pdf": native_pdf(),
        "scan-it-en.pdf": scan_pdf(),
        "unrelated-sentinel.txt": (
            b"S07 UNRELATED SYNTHETIC SENTINEL - never selected by the trial.\n"),
    }
    native_text = pypdf.PdfReader(io.BytesIO(outputs["native-text.pdf"])).pages[0].extract_text()
    scan_reader = pypdf.PdfReader(io.BytesIO(outputs["scan-it-en.pdf"]))
    scan_text = scan_reader.pages[0].extract_text()
    assert NATIVE_TOKEN in native_text and len(native_text.strip()) >= 32
    assert scan_text.strip() == ""
    assert len(scan_reader.pages[0].images) == 1
    # Regenerate bytes in memory: structure has no changing IDs/timestamps.
    assert outputs["native-text.pdf"] == native_pdf()
    assert outputs["scan-it-en.pdf"] == scan_pdf()
    manifest = {
        "status": "NEW_UNQUALIFIED_PREPARATION",
        "provenance": ("New synthetic resources; same scan pixels as public recipe 6573511376, "
                       "stored without compression after its real OCR decompression-limit "
                       "rejection. "
                       "No gate or limit changed."),
        "scope": ("Fixture bytes and structural sanity only; no integrated ingestion, Original, "
                  "OCR, search, Inbox, Windows kit or manual qualification."),
        "recipe_sha256": digest(Path(__file__).read_bytes()),
        "dependencies": {
            "pillow": PIL.__version__,
            "pypdf": pypdf.__version__,
            "raster_font": "Pillow bundled load_default(size=44)",
            "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
        },
        "files": {
            name: {"bytes": len(data), "sha256": digest(data)} for name, data in outputs.items()
        },
        "expected_search_tokens": {
            "native": NATIVE_TOKEN,
            "scan_it": SCAN_TOKEN_IT,
            "scan_en": SCAN_TOKEN_EN,
        },
        "sanity": {
            "native_embedded_text_characters": len(native_text),
            "native_exact_token_present": True,
            "scan_embedded_text_characters": len(scan_text),
            "scan_raster_images": 1,
            "in_memory_regeneration_identical": True,
        },
    }
    for name, data in outputs.items():
        (ROOT / name).write_bytes(data)
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    print(json.dumps(build(), indent=2, sort_keys=True))
