from __future__ import annotations

import argparse
import hashlib
import struct
import zlib
from pathlib import Path

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
BACKGROUND = (49, 95, 76, 255)
FOREGROUND = (255, 255, 255, 255)
VERIFY = (220, 233, 226, 255)
TRANSPARENT = (0, 0, 0, 0)
SUPERSAMPLE = 4


def _rounded_square(x: float, y: float) -> bool:
    left, top, right, bottom, radius = 16.0, 16.0, 240.0, 240.0, 52.0
    if not left <= x <= right or not top <= y <= bottom:
        return False
    nearest_x = min(max(x, left + radius), right - radius)
    nearest_y = min(max(y, top + radius), bottom - radius)
    return (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= radius**2


def _letter_p(x: float, y: float) -> bool:
    if 70 <= x <= 107 and 62 <= y <= 190:
        return True
    center_x, center_y = 133.0, 111.5
    outer = ((x - center_x) / 57.0) ** 2 + ((y - center_y) / 49.5) ** 2 <= 1
    inner = ((x - center_x) / 20.0) ** 2 + ((y - center_y) / 16.5) ** 2 < 1
    return outer and x >= 96 and not inner


def _distance_to_segment(
    x: float,
    y: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
    ratio = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length_squared))
    px, py = ax + ratio * dx, ay + ratio * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def _verification_mark(x: float, y: float) -> bool:
    return min(
        _distance_to_segment(x, y, (133, 180), (150, 197)),
        _distance_to_segment(x, y, (150, 197), (188, 154)),
    ) <= 7.5


def _sample(x: float, y: float) -> tuple[int, int, int, int]:
    if not _rounded_square(x, y):
        return TRANSPARENT
    if _verification_mark(x, y):
        return VERIFY
    if _letter_p(x, y):
        return FOREGROUND
    return BACKGROUND


def _blend(samples: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    count = len(samples)
    alpha = sum(value[3] for value in samples) / count
    if alpha == 0:
        return TRANSPARENT
    channels = []
    for index in range(3):
        premultiplied = sum(value[index] * value[3] for value in samples) / count
        channels.append(round(premultiplied / alpha))
    return (*channels, round(alpha))


def _rgba(size: int) -> bytes:
    scale = 256 / size
    pixels = bytearray()
    for row in range(size):
        for column in range(size):
            samples = []
            for sample_y in range(SUPERSAMPLE):
                for sample_x in range(SUPERSAMPLE):
                    x = (column + (sample_x + 0.5) / SUPERSAMPLE) * scale
                    y = (row + (sample_y + 0.5) / SUPERSAMPLE) * scale
                    samples.append(_sample(x, y))
            pixels.extend(_blend(samples))
    return bytes(pixels)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _png(size: int) -> bytes:
    rgba = _rgba(size)
    rows = b"".join(
        b"\x00" + rgba[offset : offset + size * 4]
        for offset in range(0, len(rgba), size * 4)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(rows, level=9))
        + _chunk(b"IEND", b"")
    )


def build_ico() -> bytes:
    images = [(size, _png(size)) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = bytearray()
    payload = bytearray()
    for size, image in images:
        encoded_size = 0 if size == 256 else size
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                encoded_size,
                encoded_size,
                0,
                0,
                1,
                32,
                len(image),
                offset,
            )
        )
        payload.extend(image)
        offset += len(image)
    return header + bytes(entries) + bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce the versioned Provelume Windows icon")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output or root / "assets" / "windows" / "provelume.ico"
    expected = build_ico()
    if args.check:
        if not output.is_file() or output.read_bytes() != expected:
            print("Provelume Windows icon is missing or not reproducible.")
            return 1
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(expected)
    print(
        f"provelume.ico sizes={','.join(map(str, SIZES))} "
        f"sha256={hashlib.sha256(expected).hexdigest()} bytes={len(expected)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
