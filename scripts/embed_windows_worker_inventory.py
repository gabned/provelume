"""Embed the closed public-code manifest into the frozen executable, before signing."""

import argparse
import ctypes as c
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from provelume.ai_windows_package import RESOURCE_ID, build_inventory  # noqa: E402


def embed(root, commit):
    if sys.platform != "win32":
        raise ValueError("native Windows builder required")
    raw = build_inventory(root, commit)
    from PyInstaller.archive.readers import CArchiveReader

    executable = root / "Provelume.exe"
    archive = CArchiveReader(str(executable))
    original = executable.read_bytes()
    start = archive._start_offset
    if not 0 < start < len(original) or archive._end_offset != len(original):
        raise ValueError("unexpected frozen executable archive framing")
    payload = original[start:]
    # UpdateResource may discard the PE overlay. Preserve the exact PyInstaller
    # package, update only the PE image, then restore and independently parse it.
    executable.write_bytes(original[:start])
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.BeginUpdateResourceW.argtypes = [c.c_wchar_p, c.c_int]
    kernel.BeginUpdateResourceW.restype = c.c_void_p
    kernel.UpdateResourceW.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.c_uint16,
                                     c.c_void_p, c.c_uint32]
    kernel.EndUpdateResourceW.argtypes = [c.c_void_p, c.c_int]
    handle = kernel.BeginUpdateResourceW(str(executable), False)
    if not handle:
        raise ValueError("frozen resource update unavailable")
    try:
        buffer = c.create_string_buffer(raw)
        if not kernel.UpdateResourceW(handle, c.c_void_p(10), c.c_void_p(RESOURCE_ID),
                                      0, buffer, len(raw)):
            raise ValueError("frozen inventory resource update failed")
        succeeded = kernel.EndUpdateResourceW(handle, False)
        handle = None
        if not succeeded:
            raise ValueError("frozen inventory publication failed")
    finally:
        if handle:
            kernel.EndUpdateResourceW(handle, True)
    with executable.open("ab") as stream:
        stream.write(payload)
    verified = CArchiveReader(str(executable))
    rebuilt = executable.read_bytes()
    if (verified.toc != archive.toc or verified.options != archive.options
            or rebuilt[verified._start_offset:] != payload):
        raise ValueError("frozen Python package changed during resource embedding")
    return {"files": len(json.loads(raw)["files"]),
            "inventory_sha256": hashlib.sha256(raw).hexdigest(), "source_commit": commit}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    print(json.dumps(embed(args.root, args.commit)))
