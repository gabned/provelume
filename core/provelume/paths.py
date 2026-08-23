from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


class UnsafePathError(ValueError):
    pass


def normalise_locator(value: str) -> str:
    candidate = value.replace("\\", "/")
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise UnsafePathError(f"unsafe source locator: {value!r}")
    if pure.parts and pure.parts[0].endswith(":"):
        raise UnsafePathError(f"absolute Windows locator is not allowed: {value!r}")
    return pure.as_posix()


def portable_config_path(instance_root: Path, target: Path) -> str:
    instance_root = instance_root.resolve()
    target = target.resolve()
    try:
        relative = os.path.relpath(target, start=instance_root)
    except ValueError:
        return str(target)
    return relative.replace("\\", "/")


def resolve_config_path(instance_root: Path, configured: str) -> Path:
    configured_path = Path(configured)
    if configured_path.is_absolute():
        return configured_path.resolve()
    return (instance_root / configured_path).resolve()


def safe_instance_path(instance_root: Path, relative_ref: str) -> Path:
    ref = normalise_locator(relative_ref)
    root = instance_root.resolve()
    candidate = (root / Path(*PurePosixPath(ref).parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(f"path escapes instance root: {relative_ref!r}") from exc
    return candidate
