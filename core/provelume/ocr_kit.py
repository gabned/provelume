"""Explicit offline host provisioning. Import never enables OCR or touches an Instance."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .ocr_contract import OcrContractError
from .publication import canonical_bytes, file_identity, parse_receipt, read_metadata
from .shell_settings import ShellSettingsManager, default_settings

MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 2048
SHA = re.compile(r"[0-9a-f]{64}\Z")
MANIFEST = "ocr-kit.json"
ENGINE = "engine/tesseract.exe"
WORKER = "worker/ProvelumeOcrWorker.exe"
PACKS = {"eng": "tessdata/eng.traineddata", "ita": "tessdata/ita.traineddata"}


class OcrKitError(OcrContractError):
    def __init__(self, message="Offline OCR kit is unavailable or invalid", *, code=None):
        super().__init__(code or "ocr_renderer_unavailable", message)


def _check(condition, message="Offline OCR kit is unavailable or invalid", *, code=None):
    if not condition:
        raise OcrKitError(message, code=code)


def host_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Provelume/ocr"


def _safe(path: Path) -> Path:
    path = path.expanduser().absolute()
    for part in (path, *path.parents):
        _check(not part.is_symlink() and not part.is_junction())
        if part.exists():
            _check(not getattr(part.lstat(), "st_file_attributes", 0) & 0x400)
    return path


def _relative(value: str) -> str:
    _check(isinstance(value, str) and len(value) <= 240 and "\\" not in value)
    path = PurePosixPath(value)
    _check(not path.is_absolute() and path.as_posix() == value)
    _check(
        all(
            re.fullmatch(r"[A-Za-z0-9_.+-]+", p)
            and p not in {".", ".."}
            and p[-1:] not in {".", " "}
            and p.split(".")[0].upper()
            not in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *[f"COM{i}" for i in range(1, 10)],
                *[f"LPT{i}" for i in range(1, 10)],
            }
            for p in path.parts
        )
    )
    return value


def _json(raw: bytes):
    _check(len(raw) <= 2 * 1024 * 1024)

    def pairs(items):
        result = {}
        for key, value in items:
            _check(key not in result)
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise OcrKitError() from exc
    _check(isinstance(value, dict))
    return value


def validate_manifest(value, build, *, python_version=None):
    _check(
        set(value)
        == {
            "schema_version",
            "source_repository",
            "version",
            "commit",
            "platform",
            "architecture",
            "python",
            "entrypoints",
            "files",
            "components",
            "native_dependencies",
            "trust",
        }
    )
    _check(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _check(value["source_repository"] == "gabned/provelume")
    _check(value["version"] == build.get("version") and value["commit"] == build.get("commit"))
    _check(re.fullmatch(r"[0-9a-f]{40}", str(value["commit"])) is not None)
    _check(value["platform"] == "windows" and value["architecture"] == "x86_64")
    _check(value["python"] == (python_version or platform.python_version()))
    _check(value["entrypoints"] == {"engine": ENGINE, "worker": WORKER, "packs": PACKS})
    rows = value["files"]
    _check(isinstance(rows, list) and 1 <= len(rows) <= MAX_FILES)
    seen, total = set(), 0
    for row in rows:
        _check(isinstance(row, dict) and set(row) == {"path", "size_bytes", "sha256"})
        name = _relative(row["path"])
        _check(name.casefold() not in seen and name != MANIFEST)
        seen.add(name.casefold())
        _check(type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= MAX_BYTES)
        _check(isinstance(row["sha256"], str) and SHA.fullmatch(row["sha256"]))
        total += row["size_bytes"]
    _check(total <= MAX_BYTES)
    _check(
        {
            name.casefold()
            for name in (
                ENGINE,
                WORKER,
                *PACKS.values(),
                "components.json",
                "native-dependencies.json",
            )
        }.issubset(seen)
    )
    _check(isinstance(value["components"], list) and value["components"])
    _check(isinstance(value["native_dependencies"], list) and value["native_dependencies"])
    return value


@dataclass(frozen=True)
class InstalledOcrKit:
    root: Path
    sha256: str
    manifest_sha256: str
    build: dict

    def verify(self):
        _safe(self.root)
        manifest_path = _safe(self.root / MANIFEST)
        with manifest_path.open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        _check(hashlib.sha256(raw).hexdigest() == self.manifest_sha256)
        manifest = validate_manifest(_json(raw), self.build)
        expected = {row["path"] for row in manifest["files"]} | {MANIFEST}
        actual = set()
        for path in self.root.rglob("*"):
            _safe(path)
            if path.is_dir():
                continue
            _check(path.is_file())
            name = path.relative_to(self.root).as_posix()
            _check(name in expected)
            actual.add(name)
        for row in manifest["files"]:
            path = self.root / row["path"]
            code = (
                "ocr_engine_unavailable"
                if row["path"].startswith("engine/")
                else "ocr_language_pack_missing"
                if row["path"].startswith("tessdata/")
                else "ocr_renderer_unavailable"
            )
            _check(path.is_file(), code=code)
            _check(
                file_identity(path)
                == {"name": path.name, "sha256": row["sha256"], "size_bytes": row["size_bytes"]},
                code=code,
            )
        _check(actual == expected)
        return manifest


def active_kit(*, root=None, build=None) -> InstalledOcrKit:
    from .build_info import current_build_info

    root = _safe(Path(root) if root is not None else host_root())
    build = current_build_info() if build is None else build
    try:
        with _safe(root / "active.json").open("rb") as stream:
            pointer = _json(stream.read(4097))
        _check(set(pointer) == {"schema_version", "sha256", "manifest_sha256"})
        _check(pointer["schema_version"] == 1)
        _check(
            all(
                isinstance(pointer[k], str) and SHA.fullmatch(pointer[k])
                for k in ("sha256", "manifest_sha256")
            )
        )
        kit = InstalledOcrKit(
            root / "kits" / pointer["sha256"],
            pointer["sha256"],
            pointer["manifest_sha256"],
            dict(build),
        )
        kit.verify()
        return kit
    except OcrKitError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise OcrKitError() from exc


def _authority(archive, build, receipt_path, expected_sha256, development):
    identity = file_identity(archive)
    if expected_sha256 is not None:
        if development:
            _check(build.get("official") is False and build.get("channel") == "development")
        _check(isinstance(expected_sha256, str) and SHA.fullmatch(expected_sha256))
        _check(identity["sha256"] == expected_sha256)
        _check(receipt_path is None)
        return identity
    _check(not development and receipt_path is not None)
    receipt = parse_receipt(read_metadata(receipt_path))
    _check(build.get("official") is True)
    _check(
        all(
            receipt[k] == build.get(k)
            for k in ("source_repository", "version", "tag", "commit", "channel")
        )
    )
    _check(identity in receipt["artifacts"])
    _check(identity["name"] == f"provelume-{build['version']}-ocr-windows-x64.zip")
    return identity


def import_kit(
    archive: Path,
    *,
    receipt_path=None,
    expected_sha256=None,
    development=False,
    root=None,
    build=None,
):
    from .build_info import current_build_info

    build = dict(build if build is not None else current_build_info())
    archive = _safe(archive)
    root = _safe(Path(root) if root is not None else host_root())
    _check(0 < archive.stat().st_size <= MAX_BYTES)
    identity = _authority(archive, build, receipt_path, expected_sha256, development)
    root.mkdir(parents=True, exist_ok=True)
    # Reuse the accepted short-lived host OS lock; no Instance or preference write.
    manager = ShellSettingsManager(root / "provisioning.json", default_settings())
    with manager.hold():
        kits = _safe(root / "kits")
        kits.mkdir(exist_ok=True)
        destination = kits / identity["sha256"]
        staging = Path(tempfile.mkdtemp(prefix="staging-", dir=root))
        try:
            with zipfile.ZipFile(archive) as source:
                infos = source.infolist()
                _check(1 < len(infos) <= MAX_FILES + 1)
                names = [_relative(i.filename) for i in infos]
                _check(len({n.casefold() for n in names}) == len(names))
                _check(sum(i.file_size for i in infos) <= MAX_BYTES + 2 * 1024 * 1024)
                _check(
                    all(
                        not i.is_dir()
                        and not i.flag_bits & 1
                        and stat.S_IFMT(i.external_attr >> 16) in {0, stat.S_IFREG}
                        for i in infos
                    )
                )
                _check(MANIFEST in names)
                info = source.getinfo(MANIFEST)
                _check(info.file_size <= 2 * 1024 * 1024)
                raw = source.read(info)
                manifest = validate_manifest(_json(raw), build)
                expected = {row["path"]: row for row in manifest["files"]}
                _check(set(names) == set(expected) | {MANIFEST})
                for info in infos:
                    _check(
                        info.file_size
                        == (
                            len(raw)
                            if info.filename == MANIFEST
                            else expected[info.filename]["size_bytes"]
                        )
                    )
                    target = staging / info.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(info) as incoming, target.open("xb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            manifest_hash = hashlib.sha256(raw).hexdigest()
            candidate = InstalledOcrKit(staging, identity["sha256"], manifest_hash, build)
            candidate.verify()
            _check(file_identity(archive) == identity)
            if destination.exists():
                try:
                    InstalledOcrKit(destination, identity["sha256"], manifest_hash, build).verify()
                except (OcrKitError, OSError):
                    # Preserve damaged owned bytes for diagnosis; repair only a
                    # non-reparse tree from the independently authorized archive.
                    _safe(destination)
                    for path in destination.rglob("*"):
                        _safe(path)
                    os.rename(destination, root / ("quarantine-" + uuid4().hex))
                    os.rename(staging, destination)
            else:
                os.rename(staging, destination)
            pointer = {
                "schema_version": 1,
                "sha256": identity["sha256"],
                "manifest_sha256": manifest_hash,
            }
            target = _safe(root / "active.json")
            fd, name = tempfile.mkstemp(prefix="pointer-", dir=root)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical_bytes(pointer))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, target)
            finally:
                Path(name).unlink(missing_ok=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return {
        "status": "imported",
        "kit": identity,
        "network_used": False,
        "ocr_enablement_changed": False,
        "source_authorization_changed": False,
        "origin_authentication": "not_established",
    }


def remove_kit(*, root=None, build=None):
    root = _safe(Path(root) if root is not None else host_root())
    manager = ShellSettingsManager(root / "provisioning.json", default_settings())
    with manager.hold():
        kit = active_kit(root=root, build=build)
        # Verify the complete owned tree before deleting only that tree. Never
        # follow a reparse point or delete an Instance, shared engine or prior kit.
        _safe(root / "active.json").unlink()
        shutil.rmtree(kit.root)
    return {"status": "removed", "network_used": False, "instance_mutation": False}
