from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from importlib import metadata
from pathlib import Path
from typing import Any


def _pillow() -> tuple[Any, Any, Any]:
    from PIL import Image, features
    from PIL.Image import DecompressionBombError, DecompressionBombWarning

    return Image, features, (DecompressionBombError, DecompressionBombWarning)


def _probe() -> dict[str, Any]:
    import pypdfium2
    import pypdfium2_raw

    image, features, _bombs = _pillow()
    del image
    versions = {}
    for feature in ("jpg", "zlib", "libtiff"):
        try:
            value = features.version(feature)
        except Exception:
            value = None
        if value:
            versions[feature] = str(value)
    raw_root = Path(pypdfium2_raw.__file__).resolve().parent
    libraries = sorted(
        path.resolve()
        for pattern in ("libpdfium.so", "pdfium.dll", "libpdfium.dylib")
        for path in raw_root.glob(pattern)
    )
    return {
        "pypdfium2": metadata.version("pypdfium2"),
        "pdfium": str(getattr(pypdfium2, "PDFIUM_INFO", "unknown")),
        "pillow": metadata.version("Pillow"),
        "pdfium_library": str(libraries[0]) if libraries else None,
        "pillow_codecs": versions,
    }


def _pdf_pages(path: Path, dpi: int) -> list[dict[str, int]]:
    import pypdfium2

    document = pypdfium2.PdfDocument(str(path))
    try:
        result = []
        for page_number in range(len(document)):
            page = document[page_number]
            try:
                width_points, height_points = page.get_size()
            finally:
                page.close()
            # PDFium rounds transformed page edges internally. One conservative
            # guard pixel keeps planning at or above the actual bitmap on every
            # qualified build without allocating the bitmap during inspection.
            width = max(1, math.ceil(float(width_points) * dpi / 72.0) + 1)
            height = max(1, math.ceil(float(height_points) * dpi / 72.0) + 1)
            result.append(
                {"number": page_number + 1, "width": width, "height": height}
            )
        return result
    finally:
        document.close()


def _image_pages(path: Path, media_type: str, max_page_pixels: int) -> list[dict[str, int]]:
    image, _features, bombs = _pillow()
    expected = {
        "image/tiff": "TIFF",
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/bmp": "BMP",
    }[media_type]
    previous_limit = image.MAX_IMAGE_PIXELS
    image.MAX_IMAGE_PIXELS = max_page_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", bombs[1])
            opened = image.open(path)
            try:
                if opened.format != expected:
                    raise ValueError("decoded image format does not match the media type")
                count = int(getattr(opened, "n_frames", 1))
                pages = []
                for index in range(count):
                    opened.seek(index)
                    width, height = opened.size
                    pages.append(
                        {"number": index + 1, "width": int(width), "height": int(height)}
                    )
                return pages
            finally:
                opened.close()
    finally:
        image.MAX_IMAGE_PIXELS = previous_limit


def _inspect(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.input)
    if args.media_type == "application/pdf":
        pages = _pdf_pages(path, args.dpi)
    else:
        pages = _image_pages(path, args.media_type, args.max_page_pixels)
    return {"pages": pages}


def _render_pdf(path: Path, output: Path, page_number: int, dpi: int) -> tuple[int, int]:
    import pypdfium2

    document = pypdfium2.PdfDocument(str(path))
    try:
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=dpi / 72.0)
            try:
                selected = bitmap.to_pil().convert("RGB")
            finally:
                bitmap.close()
        finally:
            page.close()
        try:
            selected.save(output, format="PNG", optimize=False, compress_level=6)
            return tuple(int(value) for value in selected.size)
        finally:
            selected.close()
    finally:
        document.close()


def _render_image(
    path: Path,
    output: Path,
    media_type: str,
    page_number: int,
    max_page_pixels: int,
) -> tuple[int, int]:
    image, _features, bombs = _pillow()
    expected = {
        "image/tiff": "TIFF",
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/bmp": "BMP",
    }[media_type]
    previous_limit = image.MAX_IMAGE_PIXELS
    image.MAX_IMAGE_PIXELS = max_page_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", bombs[1])
            opened = image.open(path)
            try:
                if opened.format != expected:
                    raise ValueError("decoded image format does not match the media type")
                opened.seek(page_number - 1)
                opened.load()
                selected = opened.convert("RGB")
            finally:
                opened.close()
            try:
                selected.save(output, format="PNG", optimize=False, compress_level=6)
                return tuple(int(value) for value in selected.size)
            finally:
                selected.close()
    finally:
        image.MAX_IMAGE_PIXELS = previous_limit


def _render(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.input)
    output = Path(args.output)
    if args.media_type == "application/pdf":
        width, height = _render_pdf(path, output, args.page, args.dpi)
    else:
        width, height = _render_image(
            path,
            output,
            args.media_type,
            args.page,
            args.max_page_pixels,
        )
    return {"page": args.page, "width": width, "height": height}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("operation", choices=("probe", "inspect", "render"))
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument(
        "--media-type",
        choices=("application/pdf", "image/tiff", "image/png", "image/jpeg", "image/bmp"),
    )
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--max-page-pixels", type=int, default=80_000_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.operation == "probe":
            result = _probe()
        else:
            if not args.input or not args.media_type:
                raise ValueError("renderer input is incomplete")
            if args.operation == "render" and not args.output:
                raise ValueError("renderer output is incomplete")
            result = _inspect(args) if args.operation == "inspect" else _render(args)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        sys.stderr.write(exc.__class__.__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
