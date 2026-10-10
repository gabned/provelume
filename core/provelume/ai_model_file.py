"""Bounded raw GGUF extension to the S04 store, not another registry."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .ai_model_download import checkpoint
from .ai_models import check, sha256
from .maintenance_local_files import file_identity, open_local_file, pinned_parent


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedModelFile:
    path: Path
    size: int
    sha256: str


def verify_stream(handle, entry, *, cancel=lambda: False, deadline=float("inf")):
    checkpoint(cancel, deadline)
    before = file_identity(handle)
    info = os.fstat(handle.fileno())
    check(info.st_size == entry.model_size and info.st_nlink == 1, "integrity")
    handle.seek(0)
    digest = hashlib.sha256()
    count = 0
    while True:
        checkpoint(cancel, deadline)
        block = handle.read(1024 * 1024)
        checkpoint(cancel, deadline)
        if not block:
            break
        if count == 0:
            check(block[:8] == b"GGUF\x03\0\0\0", "package")
        count += len(block)
        check(count <= entry.model_size, "limit")
        digest.update(block)
    check(count == entry.model_size and digest.hexdigest() == entry.model_sha256, "integrity")
    check(file_identity(handle) == before, "integrity")
    handle.seek(0)


def verify_file(path, entry, *, cancel=lambda: False, deadline=float("inf")):
    from .ai_model_store import VerifiedModel
    from .ai_runtime_contract import native_model_pin

    with open_local_file(path) as handle:
        verify_stream(handle, entry, cancel=cancel, deadline=deadline)
    license_file = native_model_pin(entry.id).license_file
    license_bytes = files("provelume").joinpath("runtime_notices", license_file).read_bytes()
    check(
        len(license_bytes) == entry.license_size and sha256(license_bytes) == entry.license_sha256,
        "license",
    )
    checkpoint(cancel, deadline)
    return VerifiedModel(
        entry, VerifiedModelFile(path, entry.model_size, entry.model_sha256), license_bytes
    )


def publish_file(stage, target, entry, *, cancel, deadline):
    with open_local_file(stage) as handle:
        verify_stream(handle, entry, cancel=cancel, deadline=deadline)
    with (
        pinned_parent(stage) as (source, source_parent),
        pinned_parent(target) as (destination, destination_parent),
    ):
        check(not destination.exists(), "state")
        checkpoint(cancel, deadline)
        if os.name == "nt":
            os.rename(source, destination)
        else:
            os.rename(source.name, destination.name,
                      src_dir_fd=source_parent, dst_dir_fd=destination_parent)
