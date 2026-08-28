from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .index import index_status, rebuild_search_index, search_index_content_matches
from .instance_backup import create_backup
from .instance_lifecycle import InstanceLifecycleError, InstanceLifecycleManager
from .instance_schema import (
    CURRENT_INSTANCE_SCHEMA_VERSION,
    DERIVED_STATE_POLICY,
    LEGACY_INSTANCE_SCHEMA_VERSION,
)
from .instance_validation import inspect_instance
from .library_projection import LibraryProjectionManager
from .paths import safe_instance_path
from .storage import CANONICAL_KINDS, InstanceStore, utc_now

PORTABLE_BUNDLE_SCHEMA_VERSION = 1
PORTABLE_BUNDLE_KIND = "provelume-portable-instance"
PORTABLE_MANIFEST_NAME = "portable-manifest.json"
PORTABLE_PAYLOAD_PREFIX = "instance/"

DERIVED_STATE_MODES = ("rebuild", "include")
MAX_PORTABLE_ENTRIES = 100_000
MAX_PORTABLE_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_PORTABLE_FILE_BYTES = 16 * 1024 * 1024 * 1024
MAX_PORTABLE_TOTAL_BYTES = 512 * 1024 * 1024 * 1024
MAX_PORTABLE_PATH_CHARS = 240
MAX_PORTABLE_SEGMENT_CHARS = 120

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_INSTANCE_ID = re.compile(r"inst_[0-9a-f]{32}\Z")
_EXPORT_ID = re.compile(r"export_[0-9a-f]{64}\Z")
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
    "com¹",
    "com²",
    "com³",
    "lpt¹",
    "lpt²",
    "lpt³",
}
_WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
_PAYLOAD_ROOTS = [
    "provelume.yml",
    "instance-manifest.json",
    "originals/",
    "knowledge/",
    "state/",
    "inbox/submissions/",
    "indexes/",
    "library/",
]
_TRANSIENT_PREFIXES = ["state/locks/"]


class PortableTransferError(RuntimeError):
    pass


def _is_unsafe_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info


def _derived_policy(mode: str) -> dict[str, str]:
    if mode not in DERIVED_STATE_MODES:
        raise ValueError("derived_state must be 'rebuild' or 'include'")
    return {
        "mode": mode,
        "indexes": "include" if mode == "include" else DERIVED_STATE_POLICY["indexes"],
        "library": "include" if mode == "include" else DERIVED_STATE_POLICY["library"],
        "state_artifacts": DERIVED_STATE_POLICY["state_artifacts"],
    }


def _omitted_prefixes(mode: str) -> list[str]:
    result = list(_TRANSIENT_PREFIXES)
    if mode == "rebuild":
        result.extend(("indexes/", "library/"))
    return result


def _portable_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PortableTransferError("portable entry path is unsafe")
    if value != unicodedata.normalize("NFC", value):
        raise PortableTransferError("portable entry path is not Unicode NFC")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
        or len(value) > MAX_PORTABLE_PATH_CHARS
    ):
        raise PortableTransferError("portable entry path is unsafe")
    for segment in pure.parts:
        if (
            len(segment) > MAX_PORTABLE_SEGMENT_CHARS
            or segment.endswith((" ", "."))
            or any(ord(character) < 32 for character in segment)
            or any(character in _WINDOWS_FORBIDDEN for character in segment)
            or segment.split(".", 1)[0].rstrip(" ").casefold()
            in _WINDOWS_RESERVED
        ):
            raise PortableTransferError(
                f"portable entry path is not Windows-safe: {value}"
            )
    return value


def _validate_path_set(paths: list[str]) -> None:
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise PortableTransferError("portable entry paths must be unique and sorted")
    nodes: dict[str, tuple[str, str]] = {}
    for path in paths:
        parts = PurePosixPath(path).parts
        for index in range(1, len(parts) + 1):
            node = "/".join(parts[:index])
            folded = node.casefold()
            kind = "file" if index == len(parts) else "directory"
            previous = nodes.get(folded)
            if previous is not None and previous != (node, kind):
                raise PortableTransferError(
                    "portable paths collide by case or file/directory identity"
                )
            nodes[folded] = (node, kind)


def _category(relative: str, mode: str) -> str | None:
    if relative in {"provelume.yml", "instance-manifest.json"}:
        return "instance"
    if relative.startswith(("originals/", "knowledge/")):
        return "authoritative"
    if relative.startswith("inbox/submissions/"):
        return "evidence"
    if relative == "state/locks" or relative.startswith("state/locks/"):
        return None
    if relative.startswith("state/derived/"):
        return "derived"
    if relative.startswith("state/"):
        return "durable_state"
    if relative.startswith(("indexes/", "library/")):
        return "derived" if mode == "include" else None
    return None


def _authoritative_paths(store: InstanceStore) -> set[str]:
    paths: set[str] = set()
    for kind in CANONICAL_KINDS:
        for record in store.list_canonical(kind):
            record_id = str(record["id"])
            paths.add(f"knowledge/{kind}/{record_id}.json")
    for original in store.list_canonical("originals"):
        reference = str(original["storage_ref"])
        target = safe_instance_path(store.paths.root, reference)
        relative = target.relative_to(store.paths.root).as_posix()
        if not relative.startswith("originals/"):
            raise PortableTransferError(
                "canonical Original storage must remain below originals/"
            )
        paths.add(relative)
    return paths


def _payload_files(
    store: InstanceStore,
    *,
    derived_state: str,
) -> tuple[list[tuple[dict[str, Any], Path]], int]:
    rows: list[tuple[dict[str, Any], Path]] = []
    omitted_files = 0
    authoritative_paths = _authoritative_paths(store)
    for path in sorted(
        store.paths.root.rglob("*"),
        key=lambda candidate: candidate.relative_to(store.paths.root).as_posix(),
    ):
        relative = path.relative_to(store.paths.root).as_posix()
        if _is_unsafe_link(path):
            raise PortableTransferError(
                f"Instance-internal link cannot be exported: {relative}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise PortableTransferError(
                f"Instance entry is not a regular file: {relative}"
            )
        category = _category(relative, derived_state)
        if category == "authoritative" and relative not in authoritative_paths:
            category = None
        if category is None:
            omitted_files += 1
            continue
        _portable_path(relative)
        try:
            size, digest = _file_identity(path)
        except OSError as exc:
            raise PortableTransferError(
                f"Instance file cannot be read: {relative}"
            ) from exc
        if size > MAX_PORTABLE_FILE_BYTES:
            raise PortableTransferError(
                f"Instance file exceeds the portable size limit: {relative}"
            )
        rows.append(
            (
                {
                    "category": category,
                    "path": relative,
                    "sha256": digest,
                    "size_bytes": size,
                },
                path,
            )
        )
    if len(rows) > MAX_PORTABLE_ENTRIES:
        raise PortableTransferError("Instance contains too many portable entries")
    total = sum(int(row["size_bytes"]) for row, _path in rows)
    if total > MAX_PORTABLE_TOTAL_BYTES:
        raise PortableTransferError("Instance exceeds the portable total size limit")
    _validate_path_set([str(row["path"]) for row, _path in rows])
    return rows, omitted_files


def _export_id(manifest_without_id: dict[str, Any]) -> str:
    return "export_" + hashlib.sha256(_canonical_bytes(manifest_without_id)).hexdigest()


def _build_manifest(
    *,
    validation: dict[str, Any],
    derived_state: str,
    rows: list[tuple[dict[str, Any], Path]],
    omitted_files: int,
) -> dict[str, Any]:
    entries = [row for row, _path in rows]
    unsigned = {
        "schema_version": PORTABLE_BUNDLE_SCHEMA_VERSION,
        "kind": PORTABLE_BUNDLE_KIND,
        "instance_id": validation["instance_id"],
        "instance_schema_version": validation["instance_schema_version"],
        "content_fingerprint": validation["content_fingerprint"],
        "derived_state": _derived_policy(derived_state),
        "payload_roots": list(_PAYLOAD_ROOTS),
        "omitted_prefixes": _omitted_prefixes(derived_state),
        "omitted_files": omitted_files,
        "entry_count": len(entries),
        "total_size_bytes": sum(int(row["size_bytes"]) for row in entries),
        "entries": entries,
        "network_used": False,
        "ai_used": False,
    }
    return {**unsigned, "export_id": _export_id(unsigned)}


def _destination(
    store: InstanceStore,
    destination: Path | str,
    *,
    export_id: str,
) -> Path:
    requested = Path(destination).expanduser()
    if requested.exists() and requested.is_dir():
        selected = requested / f"provelume-{export_id}.zip"
    elif requested.suffix.casefold() == ".zip":
        selected = requested
    else:
        selected = requested / f"provelume-{export_id}.zip"
    selected = selected.resolve()
    if _inside(selected, store.paths.root):
        raise PortableTransferError(
            "portable bundle must be stored outside the Instance root"
        )
    if selected.exists() or selected.is_symlink():
        raise PortableTransferError("portable bundle destination already exists")
    return selected


def _write_bundle(
    archive: Path,
    manifest: dict[str, Any],
    rows: list[tuple[dict[str, Any], Path]],
) -> tuple[int, int]:
    archive.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive.name}.", suffix=".tmp", dir=archive.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as bundle:
            bundle.writestr(_zip_info(PORTABLE_MANIFEST_NAME), _json_bytes(manifest))
            for row, source in rows:
                with source.open("rb") as source_handle, bundle.open(
                    _zip_info(f"{PORTABLE_PAYLOAD_PREFIX}{row['path']}"),
                    mode="w",
                ) as target_handle:
                    while chunk := source_handle.read(1024 * 1024):
                        target_handle.write(chunk)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        published = temporary.lstat()
        try:
            os.link(temporary, archive)
        except FileExistsError as exc:
            raise PortableTransferError(
                "portable bundle destination already exists"
            ) from exc
        except OSError as exc:
            raise PortableTransferError(
                "portable bundle cannot be published without overwrite"
            ) from exc
        return published.st_dev, published.st_ino
    finally:
        temporary.unlink(missing_ok=True)


def _unlink_published_bundle(archive: Path, identity: tuple[int, int]) -> None:
    try:
        current = archive.lstat()
    except OSError:
        return
    if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
        archive.unlink(missing_ok=True)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PortableTransferError("portable manifest contains duplicate JSON keys")
        result[key] = value
    return result


def _manifest_from_bundle(bundle: zipfile.ZipFile) -> tuple[dict[str, Any], bytes]:
    try:
        info = bundle.getinfo(PORTABLE_MANIFEST_NAME)
    except KeyError as exc:
        raise PortableTransferError("portable manifest is missing") from exc
    if info.file_size > MAX_PORTABLE_MANIFEST_BYTES:
        raise PortableTransferError("portable manifest exceeds the safety limit")
    try:
        raw = bundle.read(info)
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except PortableTransferError:
        raise
    except (UnicodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise PortableTransferError("portable manifest is unreadable") from exc
    if not isinstance(value, dict) or raw != _json_bytes(value):
        raise PortableTransferError("portable manifest is not canonical JSON")
    return value, raw


def _validate_manifest(manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    expected_keys = {
        "ai_used",
        "content_fingerprint",
        "derived_state",
        "entries",
        "entry_count",
        "export_id",
        "instance_id",
        "instance_schema_version",
        "kind",
        "network_used",
        "omitted_files",
        "omitted_prefixes",
        "payload_roots",
        "schema_version",
        "total_size_bytes",
    }
    if set(manifest) != expected_keys:
        raise PortableTransferError("portable manifest fields are incomplete or unsupported")
    derived = manifest.get("derived_state")
    mode = derived.get("mode") if isinstance(derived, dict) else None
    unsigned = dict(manifest)
    export_id = unsigned.pop("export_id", None)
    if (
        manifest.get("schema_version") != PORTABLE_BUNDLE_SCHEMA_VERSION
        or manifest.get("kind") != PORTABLE_BUNDLE_KIND
        or not isinstance(export_id, str)
        or _EXPORT_ID.fullmatch(export_id) is None
        or export_id != _export_id(unsigned)
        or not isinstance(manifest.get("instance_id"), str)
        or _INSTANCE_ID.fullmatch(str(manifest["instance_id"])) is None
        or manifest.get("instance_schema_version")
        not in {LEGACY_INSTANCE_SCHEMA_VERSION, CURRENT_INSTANCE_SCHEMA_VERSION}
        or not isinstance(manifest.get("content_fingerprint"), str)
        or _SHA256.fullmatch(str(manifest["content_fingerprint"])) is None
        or mode not in DERIVED_STATE_MODES
        or derived != _derived_policy(str(mode))
        or manifest.get("payload_roots") != _PAYLOAD_ROOTS
        or manifest.get("omitted_prefixes") != _omitted_prefixes(str(mode))
        or type(manifest.get("omitted_files")) is not int
        or int(manifest["omitted_files"]) < 0
        or manifest.get("network_used") is not False
        or manifest.get("ai_used") is not False
        or not isinstance(manifest.get("entries"), list)
    ):
        raise PortableTransferError("portable manifest contract is invalid")

    entries = manifest["entries"]
    if len(entries) > MAX_PORTABLE_ENTRIES:
        raise PortableTransferError("portable manifest contains too many entries")
    paths: list[str] = []
    total = 0
    validated: list[dict[str, Any]] = []
    for row in entries:
        if not isinstance(row, dict) or set(row) != {
            "category",
            "path",
            "sha256",
            "size_bytes",
        }:
            raise PortableTransferError("portable entry descriptor is invalid")
        path = row.get("path")
        digest = row.get("sha256")
        size = row.get("size_bytes")
        category = row.get("category")
        if (
            not isinstance(path, str)
            or _portable_path(path) != path
            or category != _category(path, str(mode))
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or type(size) is not int
            or size < 0
            or size > MAX_PORTABLE_FILE_BYTES
        ):
            raise PortableTransferError("portable entry descriptor is invalid")
        total += size
        if total > MAX_PORTABLE_TOTAL_BYTES:
            raise PortableTransferError("portable bundle expands beyond the safety limit")
        paths.append(path)
        validated.append(dict(row))
    _validate_path_set(paths)
    required = {"provelume.yml"}
    if manifest["instance_schema_version"] == CURRENT_INSTANCE_SCHEMA_VERSION:
        required.add("instance-manifest.json")
    if not required.issubset(paths):
        raise PortableTransferError("portable bundle is missing required Instance files")
    if (
        manifest.get("entry_count") != len(validated)
        or manifest.get("total_size_bytes") != total
    ):
        raise PortableTransferError("portable manifest totals do not match its entries")
    return validated, str(mode)


def _validated_bundle(
    selected: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str, str]:
    try:
        before = selected.stat()
        if _is_unsafe_link(selected) or not selected.is_file():
            raise PortableTransferError("portable bundle is not a regular file")
        with zipfile.ZipFile(selected, mode="r") as bundle:
            manifest, manifest_bytes = _manifest_from_bundle(bundle)
            entries, mode = _validate_manifest(manifest)
            infos = bundle.infolist()
            if len(infos) != len(entries) + 1:
                raise PortableTransferError("portable bundle entry count is invalid")
            names = [info.filename for info in infos]
            expected_names = [PORTABLE_MANIFEST_NAME] + [
                f"{PORTABLE_PAYLOAD_PREFIX}{row['path']}" for row in entries
            ]
            if names != expected_names or len(names) != len(set(names)):
                raise PortableTransferError(
                    "portable bundle contains duplicate, undeclared or unordered entries"
                )
            by_name = {info.filename: info for info in infos}
            for info in infos:
                file_mode = info.external_attr >> 16
                file_type = stat.S_IFMT(file_mode)
                if (
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or info.compress_type
                    not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or file_type not in {0, stat.S_IFREG}
                ):
                    raise PortableTransferError(
                        "portable bundle contains a special, encrypted or unsupported entry"
                    )
            for row in entries:
                info = by_name[f"{PORTABLE_PAYLOAD_PREFIX}{row['path']}"]
                if info.file_size != row["size_bytes"]:
                    raise PortableTransferError(
                        f"portable payload size is invalid: {row['path']}"
                    )
                digest = hashlib.sha256()
                size = 0
                with bundle.open(info, mode="r") as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                if size != row["size_bytes"] or digest.hexdigest() != row["sha256"]:
                    raise PortableTransferError(
                        f"portable payload hash is invalid: {row['path']}"
                    )
        archive_sha256 = _sha256_file(selected)
        after = selected.stat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise PortableTransferError("portable bundle changed while it was validated")
    except PortableTransferError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise PortableTransferError("portable bundle cannot be read") from exc
    return (
        manifest,
        entries,
        hashlib.sha256(manifest_bytes).hexdigest(),
        archive_sha256,
    )


def verify_portable_bundle(archive: Path | str) -> dict[str, Any]:
    requested = Path(archive).expanduser()
    if requested.is_symlink():
        raise PortableTransferError("portable bundle path cannot be a symbolic link")
    selected = requested.resolve()
    manifest, entries, manifest_sha256, archive_sha256 = _validated_bundle(selected)
    return {
        "schema_version": PORTABLE_BUNDLE_SCHEMA_VERSION,
        "status": "valid",
        "archive": str(selected),
        "archive_sha256": archive_sha256,
        "manifest_sha256": manifest_sha256,
        "export_id": manifest["export_id"],
        "instance_id": manifest["instance_id"],
        "instance_schema_version": manifest["instance_schema_version"],
        "content_fingerprint": manifest["content_fingerprint"],
        "derived_state": dict(manifest["derived_state"]),
        "files": len(entries),
        "size_bytes": selected.stat().st_size,
        "payload_size_bytes": manifest["total_size_bytes"],
        "network_used": False,
        "ai_used": False,
    }


def _extract_bundle(
    selected: Path,
    destination: Path,
    *,
    expected_archive_sha256: str,
) -> dict[str, Any]:
    manifest, entries, manifest_sha256, observed_archive_sha256 = _validated_bundle(
        selected
    )
    if observed_archive_sha256 != expected_archive_sha256:
        raise PortableTransferError("portable bundle changed before extraction")
    destination.mkdir(parents=True, exist_ok=False)
    try:
        (destination / "originals").mkdir()
        (destination / "indexes").mkdir()
        (destination / "state" / "locks").mkdir(parents=True)
        for kind in CANONICAL_KINDS:
            (destination / "knowledge" / kind).mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(selected, mode="r") as bundle:
            for row in entries:
                output = safe_instance_path(destination, str(row["path"]))
                output.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    output,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                digest = hashlib.sha256()
                size = 0
                with bundle.open(
                    f"{PORTABLE_PAYLOAD_PREFIX}{row['path']}", mode="r"
                ) as source, os.fdopen(descriptor, "wb") as handle:
                    while chunk := source.read(1024 * 1024):
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                if size != row["size_bytes"] or digest.hexdigest() != row["sha256"]:
                    raise PortableTransferError(
                        f"portable payload changed during extraction: {row['path']}"
                    )
        if _sha256_file(selected) != expected_archive_sha256:
            raise PortableTransferError("portable bundle changed during extraction")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {
        "manifest": manifest,
        "manifest_sha256": manifest_sha256,
        "entries": entries,
    }


class PortableInstanceTransfer:
    """Deterministic export and rollback-safe cross-Instance import boundary."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.lifecycle = InstanceLifecycleManager(store)

    def export(
        self,
        destination: Path | str,
        *,
        derived_state: str = "rebuild",
    ) -> dict[str, Any]:
        _derived_policy(derived_state)
        self.lifecycle.prepare()
        with self.lifecycle._hold(purpose="portable-instance-export"):
            validation = inspect_instance(self.store.paths.root, deep=True)
            if validation["status"] != "valid":
                raise PortableTransferError("Instance validation failed before export")
            if derived_state == "include" and (
                not search_index_content_matches(self.store)
                or LibraryProjectionManager(self.store).status()["status"] != "ready"
            ):
                raise PortableTransferError(
                    "include export requires a ready search index and Markdown library"
                )
            rows, omitted_files = _payload_files(
                self.store,
                derived_state=derived_state,
            )
            manifest = _build_manifest(
                validation=validation,
                derived_state=derived_state,
                rows=rows,
                omitted_files=omitted_files,
            )
            archive = _destination(
                self.store,
                destination,
                export_id=str(manifest["export_id"]),
            )
            published_identity: tuple[int, int] | None = None
            try:
                published_identity = _write_bundle(archive, manifest, rows)
                verified = verify_portable_bundle(archive)
                final_validation = inspect_instance(self.store.paths.root, deep=True)
                final_rows, final_omitted = _payload_files(
                    self.store,
                    derived_state=derived_state,
                )
                if (
                    final_validation["status"] != "valid"
                    or final_validation["content_fingerprint"]
                    != validation["content_fingerprint"]
                    or [row for row, _path in final_rows]
                    != [row for row, _path in rows]
                    or final_omitted != omitted_files
                ):
                    raise PortableTransferError(
                        "Instance changed while the portable snapshot was built"
                    )
            except Exception:
                if published_identity is not None:
                    _unlink_published_bundle(archive, published_identity)
                raise
        return {
            **verified,
            "status": "completed",
            "completed_at": utc_now(),
            "omitted_files": omitted_files,
            "omitted_prefixes": _omitted_prefixes(derived_state),
        }

    def _prepare_staging(
        self,
        stage: Path,
        extracted: dict[str, Any],
        *,
        rollback: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
        manifest = extracted["manifest"]
        staged_store = InstanceStore(stage)
        validation = inspect_instance(stage, deep=True)
        migration = None
        if validation["status"] != "valid":
            raise PortableTransferError("import staging Instance failed validation")
        if validation["instance_schema_version"] == LEGACY_INSTANCE_SCHEMA_VERSION:
            staged_lifecycle = InstanceLifecycleManager(staged_store)
            try:
                migration = staged_lifecycle.prepare()
                migration_backup = migration.get("backup")
                if isinstance(migration_backup, dict):
                    staged_archive = Path(str(migration_backup["archive"]))
                    retained_archive = (
                        self.lifecycle.control_root
                        / "backups"
                        / staged_archive.name
                    )
                    retained_archive.parent.mkdir(parents=True, exist_ok=True)
                    if retained_archive.exists():
                        raise PortableTransferError(
                            "staged migration backup destination already exists"
                        )
                    os.replace(staged_archive, retained_archive)
                    migration_backup["archive"] = str(retained_archive)
            finally:
                shutil.rmtree(staged_lifecycle.control_root, ignore_errors=True)
            validation = inspect_instance(stage, deep=True)
        if (
            validation["status"] != "valid"
            or validation["instance_schema_version"]
            != CURRENT_INSTANCE_SCHEMA_VERSION
            or validation["instance_id"] != manifest["instance_id"]
            or validation["content_fingerprint"] != manifest["content_fingerprint"]
        ):
            raise PortableTransferError(
                "import staging identity or canonical fingerprint does not match"
            )

        policy = manifest["derived_state"]
        if policy["mode"] == "rebuild":
            shutil.rmtree(staged_store.paths.indexes, ignore_errors=True)
            shutil.rmtree(staged_store.paths.library, ignore_errors=True)
            staged_store.paths.indexes.mkdir(parents=True)
            indexed = rebuild_search_index(staged_store, recover_missing_derived=True)
            library = LibraryProjectionManager(staged_store).rebuild()
            derived_result = {
                "policy": dict(policy),
                "indexes": "rebuilt",
                "documents_indexed": indexed,
                "library": "rebuilt",
                "library_content_fingerprint": library["content_fingerprint"],
            }
        else:
            included_index_status = index_status(staged_store)
            included_index_content_matches = search_index_content_matches(staged_store)
            included_library_status = LibraryProjectionManager(staged_store).status()
            if (
                included_index_status != "ready"
                or not included_index_content_matches
                or included_library_status["status"] != "ready"
            ):
                raise PortableTransferError(
                    "included derived state failed staged index or library validation"
                )
            derived_result = {
                "policy": dict(policy),
                "indexes": "included_as_exported",
                "library": "included_as_exported",
                "library_content_fingerprint": included_library_status[
                    "content_fingerprint"
                ],
            }

        import_id = f"import_{uuid4().hex}"
        receipt_ref = f"state/lifecycle/import-receipts/{import_id}.json"
        receipt = {
            "schema_version": PORTABLE_BUNDLE_SCHEMA_VERSION,
            "kind": "provelume-portable-import-receipt",
            "id": import_id,
            "status": "completed",
            "imported_at": utc_now(),
            "export_id": manifest["export_id"],
            "source_instance_id": manifest["instance_id"],
            "archive_sha256": extracted["archive_sha256"],
            "manifest_sha256": extracted["manifest_sha256"],
            "content_fingerprint": manifest["content_fingerprint"],
            "prior_instance_backup_sha256": rollback["archive_sha256"],
            "derived_state": dict(policy),
            "migration_applied": migration is not None,
            "network_used": False,
            "ai_used": False,
        }
        staged_store._atomic_json(stage / receipt_ref, receipt)
        final = inspect_instance(stage, deep=True)
        if (
            final["status"] != "valid"
            or final["content_fingerprint"] != manifest["content_fingerprint"]
        ):
            raise PortableTransferError(
                "import staging changed canonical state while derived state was prepared"
            )
        return derived_result, migration, {"ref": receipt_ref, "value": receipt}

    def import_bundle(self, archive: Path | str) -> dict[str, Any]:
        requested = Path(archive).expanduser()
        if requested.is_symlink():
            raise PortableTransferError("portable bundle path cannot be a symbolic link")
        selected = requested.resolve()
        if _inside(selected, self.store.paths.root):
            raise PortableTransferError(
                "portable import archive must be outside the target Instance"
            )
        self.lifecycle.prepare()
        verified = verify_portable_bundle(selected)
        before = inspect_instance(self.store.paths.root, deep=True)
        if before["status"] != "valid":
            raise PortableTransferError("target Instance validation failed before import")

        root = self.store.paths.root
        stage = root.parent / f".{root.name}.import-stage-{uuid4().hex}"
        previous = root.parent / f".{root.name}.import-previous-{uuid4().hex}"
        moved_previous = False
        installed_stage = False
        with self.lifecycle._hold(purpose="portable-instance-import"):
            current = inspect_instance(root, deep=True)
            if current["status"] != "valid":
                raise PortableTransferError(
                    "target Instance changed before the import lock was acquired"
                )
            rollback = create_backup(self.store, reason="pre_portable_import")
            self.lifecycle._write_pending(
                operation="import",
                rollback=rollback,
                requested_archive_sha256=verified["archive_sha256"],
            )
            try:
                extracted = _extract_bundle(
                    selected,
                    stage,
                    expected_archive_sha256=str(verified["archive_sha256"]),
                )
                extracted["archive_sha256"] = verified["archive_sha256"]
                derived, migration, receipt = self._prepare_staging(
                    stage,
                    extracted,
                    rollback=rollback,
                )
                os.replace(root, previous)
                moved_previous = True
                os.replace(stage, root)
                installed_stage = True
                installed = inspect_instance(root, deep=True)
                if (
                    installed["status"] != "valid"
                    or installed["instance_id"] != verified["instance_id"]
                    or installed["content_fingerprint"]
                    != verified["content_fingerprint"]
                ):
                    raise PortableTransferError(
                        "installed portable Instance failed final validation"
                    )
                shutil.rmtree(previous)
                moved_previous = False
                self.lifecycle._clear_pending()
            except Exception as exc:
                try:
                    if installed_stage and root.exists():
                        shutil.rmtree(root)
                    if moved_previous and previous.exists():
                        os.replace(previous, root)
                        moved_previous = False
                    else:
                        self.lifecycle._replace_from_archive(
                            Path(str(rollback["archive"])),
                            expected_instance_id=str(rollback["instance_id"]),
                        )
                    restored = inspect_instance(root, deep=True)
                    if (
                        restored["status"] != "valid"
                        or restored["instance_id"] != current["instance_id"]
                        or restored["content_fingerprint"]
                        != current["content_fingerprint"]
                    ):
                        raise PortableTransferError(
                            "portable import rollback did not restore the target identity"
                        )
                    self.lifecycle._clear_pending()
                except Exception as rollback_exc:
                    raise InstanceLifecycleError(
                        "portable import failed and rollback could not be verified"
                    ) from rollback_exc
                raise PortableTransferError(
                    "portable import failed; the verified target backup was restored"
                ) from exc
            finally:
                shutil.rmtree(stage, ignore_errors=True)

        return {
            "schema_version": PORTABLE_BUNDLE_SCHEMA_VERSION,
            "status": "imported",
            "instance_id": verified["instance_id"],
            "replaced_instance_id": current["instance_id"],
            "archive_sha256": verified["archive_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "export_id": verified["export_id"],
            "content_fingerprint": verified["content_fingerprint"],
            "rollback_backup": rollback,
            "migration": migration,
            "derived_state": derived,
            "receipt": receipt["ref"],
            "network_used": False,
            "ai_used": False,
        }


__all__ = [
    "DERIVED_STATE_MODES",
    "PORTABLE_BUNDLE_KIND",
    "PORTABLE_BUNDLE_SCHEMA_VERSION",
    "PORTABLE_MANIFEST_NAME",
    "PortableInstanceTransfer",
    "PortableTransferError",
    "verify_portable_bundle",
]
