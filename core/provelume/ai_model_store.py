"""Explicit, bounded model package lifecycle on one local filesystem.

Persisted pointers are recovery hints, never self-test or inference authority.
All consumers receive verified immutable bytes, not a pathname to reopen.
"""

from __future__ import annotations

import io
import os
import platform
import re
import shutil
import stat
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .ai_contract import digest
from .ai_model_download import ArtifactDownload, checkpoint
from .ai_models import (
    MAX_FILES,
    MAX_INSTALLED,
    MAX_PACKAGE_BYTES,
    MAX_TOTAL_BYTES,
    ModelEntry,
    ModelError,
    ModelRegistry,
    RuntimeSelection,
    check,
    exact,
    parse_json,
    sha256,
)
from .instance_lifecycle import InstanceLifecycleBusy, _acquire_os_lock, _release_os_lock
from .maintenance_local_files import (
    MaintenanceTargetError,
    absolute_local_path,
    file_identity,
    open_local_file,
    open_local_lock,
    pinned_parent,
    write_local_bytes,
)
from .representations import canonical_json_bytes

SELF_TEST_TTL_SECONDS = 60
OPERATION_SECONDS = 30
FREE_SPACE_RESERVE = 1024 * 1024
_PACKAGE_NAME = re.compile(r"[0-9a-f]{64}\.pkg\Z")
_STAGE_NAME = re.compile(r"[0-9a-f]{32}\.part\Z")
_TEMP_NAME = re.compile(r"\.maintenance-[0-9a-f]{32}\.tmp\Z")


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedModel:
    entry: ModelEntry
    model: object
    license: bytes


@dataclass(frozen=True, slots=True, repr=False)
class SelfTestEvidence:
    model_id: str
    binding: str
    result: str
    expires: float

    def public_record(self):
        return {"model_id": self.model_id, "binding": self.binding, "result": self.result,
                "scope": "SYNTHETIC_ONLY", "inference_authorized": False}


def inspect_package(raw: bytes, entry: ModelEntry) -> VerifiedModel:
    """No extraction paths or executable deserialization; only two stored members."""
    check(len(raw) == entry.package_size and sha256(raw) == entry.package_sha256, "integrity")
    check(len(raw) <= MAX_PACKAGE_BYTES, "limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            check(len(entries) == MAX_FILES, "package")
            check(not archive.comment, "package")
            check({item.filename for item in entries} == set(entry.file_inventory), "package")
            check(sum(item.file_size for item in entries) <= MAX_TOTAL_BYTES, "limit")
            contents = {}
            for item in entries:
                # Exact case-sensitive names exclude path traversal, collisions, ADS,
                # reserved names, absolute paths and Unicode/Windows aliases.
                check(item.orig_filename == item.filename and item.filename not in contents,
                      "package")
                size, expected = entry.file_inventory[item.filename]
                check(item.file_size == size and item.compress_size == size, "limit")
                check(item.compress_type == zipfile.ZIP_STORED and item.flag_bits == 0, "package")
                check(item.create_system == 3 and item.external_attr >> 16 == 0o100600,
                      "package")
                check(not item.extra and not item.comment and not item.is_dir(), "package")
                with archive.open(item) as handle:
                    data = handle.read(size + 1)
                check(len(data) == size and sha256(data) == expected, "integrity")
                contents[item.filename] = data
            check(contents["model.bin"].startswith(b"PROVELUME-SYNTHETIC-MODEL/1\n"), "package")
            check(contents["LICENSE.txt"] ==
                  b"CC0-1.0\nSynthetic lifecycle fixture; not an inference model.\n", "license")
            return VerifiedModel(entry, contents["model.bin"], contents["LICENSE.txt"])
    except ModelError:
        raise
    except Exception:
        raise ModelError("package") from None


def _safe_stat(path: Path, *, directory: bool = False):
    info = path.lstat()
    check(not (getattr(info, "st_file_attributes", 0) & 0x400), "unsafe_path")
    check(stat.S_ISDIR(info.st_mode) if directory else
          stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe_path")
    return info


def _read(path: Path, maximum: int) -> bytes:
    with open_local_file(path) as handle:
        info = os.fstat(handle.fileno())
        check(info.st_nlink == 1 and info.st_size <= maximum, "unsafe_path")
        before = file_identity(handle)
        data = handle.read(maximum + 1)
        check(len(data) <= maximum, "limit")
        check(file_identity(handle) == before, "integrity")
        return data


class ModelStore:
    def __init__(self, root: Path | str, *, registry: ModelRegistry | None = None,
                 allowed_ids: tuple[str, ...] | None = None):
        # Pure construction: no directory creation, probing, recovery or network.
        self.root = Path(root)
        check(self.root.is_absolute(), "unsafe_path")
        self.registry = registry or ModelRegistry.packaged()
        self.allowed_ids = (tuple(entry.id for entry in self.registry.entries)
                            if allowed_ids is None else allowed_ids)
        check(type(self.allowed_ids) is tuple and
              len(set(self.allowed_ids)) == len(self.allowed_ids))
        check(all(item in tuple(e.id for e in self.registry.entries) for item in self.allowed_ids))
        self._evidence: dict[str, SelfTestEvidence] = {}
        self._native_runners = {}
        self._session = uuid4().hex

    @classmethod
    def for_instance(cls, root: Path | str):
        # Existing lifecycle control directory is external to portable Instance data.
        instance = Path(root).absolute()
        return cls(instance.parent / f".{instance.name}.provelume" / "ai-models")

    def _entry(self, identifier: str, runtime: RuntimeSelection | None = None):
        entry = self.registry.entry(identifier)
        check(identifier in self.allowed_ids, "revoked")
        if runtime is not None:
            runtime.validate(entry)
        return entry

    def _prepare(self):
        absolute_local_path(self.root)
        # Create one ancestor at a time after checking existing ancestors. No links.
        for parent in reversed((self.root, *self.root.parents)):
            if not parent.exists():
                with pinned_parent(parent):
                    parent.mkdir(mode=0o700)
            _safe_stat(parent, directory=True)
        for name in ("staging", "verified"):
            target = self.root / name
            with pinned_parent(target):
                target.mkdir(mode=0o700, exist_ok=True)
                _safe_stat(target, directory=True)

    @contextmanager
    def _hold(self):
        acquired = False
        try:
            self._prepare()
            with open_local_lock(self.root / "operation.lock") as descriptor:
                check(os.fstat(descriptor).st_nlink == 1, "unsafe_path")
                _acquire_os_lock(descriptor)
                acquired = True
                try:
                    ignore = self.root / ".gitignore"
                    if ignore.exists():
                        check(_read(ignore, 32) == b"*\n", "state")
                    else:
                        write_local_bytes(ignore, b"*\n", replace=True)
                    yield
                finally:
                    if acquired:
                        _release_os_lock(descriptor)
        except ModelError:
            raise
        except InstanceLifecycleBusy:
            raise ModelError("busy") from None
        except MaintenanceTargetError as exc:
            raise ModelError("missing" if exc.code == "target_missing" else "unsafe_path") from None
        except OSError:
            raise ModelError("io") from None
        except Exception:
            raise ModelError("state") from None

    def _path(self, entry):
        return self.root / "verified" / (entry.package_sha256 + ".pkg")

    def _verify(self, entry):
        if entry.format == "gguf-v3-q4_k_m":
            from .ai_model_file import verify_file

            return verify_file(self._path(entry), entry)
        return inspect_package(_read(self._path(entry), MAX_PACKAGE_BYTES), entry)

    def verify(self, identifier: str, runtime: RuntimeSelection) -> VerifiedModel:
        with self._hold():
            return self._verify(self._entry(identifier, runtime))

    def _state(self):
        path = self.root / "selection.json"
        try:
            raw = _read(path, 4096)
        except MaintenanceTargetError as exc:
            if exc.code == "target_missing":
                return {"schema_version": 1, "active": None, "previous": None}
            raise
        value = exact(parse_json(raw, 4096), {"schema_version", "active", "previous"}, "state")
        check(type(value["schema_version"]) is int and value["schema_version"] == 1, "state")
        for key in ("active", "previous"):
            check(value[key] is None or
                  value[key] in tuple(entry.id for entry in self.registry.entries), "state")
        return value

    def _write_state(self, value):
        path = self.root / "selection.json"
        if path.exists():
            _safe_stat(path)
        write_local_bytes(path, canonical_json_bytes(value), replace=True)

    def _space(self, required: int):
        check(shutil.disk_usage(self.root).free >= required + FREE_SPACE_RESERVE, "space")

    def _install(self, identifier, runtime, chunks, *, license_accepted, cancel, deadline):
        entry = self._entry(identifier, runtime)
        check(license_accepted == entry.license, "license")
        checkpoint(cancel, deadline)
        with self._hold():
            target = self._path(entry)
            if target.exists():
                self._verify(entry)
                return {"id": entry.id, "state": "verified", "activated": False}
            installed = list((self.root / "verified").iterdir())
            staged = list((self.root / "staging").iterdir())
            check(len(staged) < MAX_INSTALLED, "limit")
            check(all(_STAGE_NAME.fullmatch(p.name) for p in staged), "state")
            check(len(installed) < MAX_INSTALLED, "limit")
            check(all(_PACKAGE_NAME.fullmatch(p.name) for p in installed), "state")
            self._space(entry.package_size * 2)
            stage = self.root / "staging" / (uuid4().hex + ".part")
            # A staging file may survive a process crash; explicit recovery removes it.
            try:
                with pinned_parent(stage) as (path, parent):
                    if os.name == "nt":
                        from .maintenance_local_files import _windows_open

                        fd = _windows_open(path, directory=False, create=True)
                    else:
                        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                     os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    with os.fdopen(fd, "wb") as output:
                        total = 0
                        for chunk in chunks(entry, deadline):
                            checkpoint(cancel, deadline)
                            check(type(chunk) is bytes and 0 < len(chunk) <= 4096, "limit")
                            total += len(chunk)
                            check(total <= entry.package_size, "limit")
                            self._space(len(chunk))
                            check(output.write(chunk) == len(chunk), "io")
                        checkpoint(cancel, deadline)
                        check(total == entry.package_size, "integrity")
                        output.flush()
                        os.fsync(output.fileno())
                if entry.format == "gguf-v3-q4_k_m":
                    from .ai_model_file import publish_file

                    publish_file(stage, target, entry, cancel=cancel, deadline=deadline)
                else:
                    raw = _read(stage, MAX_PACKAGE_BYTES)
                    inspect_package(raw, entry)
                    checkpoint(cancel, deadline)
                    write_local_bytes(target, raw, replace=True)
                self._verify(entry)
                return {"id": entry.id, "state": "verified", "activated": False}
            finally:
                self._delete(stage, missing=True)

    @staticmethod
    def _delete(path, *, missing=False):
        with pinned_parent(path) as (pinned, parent):
            try:
                _safe_stat(pinned)
            except FileNotFoundError:
                if missing:
                    return
                raise
            if os.name == "nt":
                pinned.unlink()
            else:
                os.unlink(pinned.name, dir_fd=parent)

    def install(self, identifier: str, runtime: RuntimeSelection, *, requested: bool = False,
                license_accepted: str, cancel=lambda: False, transport=None):
        check(requested is True, "consent")
        # No transport is opened until inside the storage lock and after admission.
        downloader = transport or ArtifactDownload()
        return self._install(identifier, runtime,
                             lambda entry, deadline: downloader.fetch(
                                 entry, cancel=cancel, deadline=deadline),
                             license_accepted=license_accepted, cancel=cancel,
                             deadline=time.monotonic() + OPERATION_SECONDS)

    def import_offline(self, identifier: str, path: Path | str, runtime: RuntimeSelection, *,
                       requested: bool = False, license_accepted: str, cancel=lambda: False):
        check(requested is True, "consent")

        def chunks(entry, deadline):
            with open_local_file(path) as handle:
                info = os.fstat(handle.fileno())
                check(info.st_nlink == 1 and info.st_size == entry.package_size, "integrity")
                before = file_identity(handle)
                while True:
                    checkpoint(cancel, deadline)
                    chunk = handle.read(4096)
                    if not chunk:
                        break
                    yield chunk
                check(file_identity(handle) == before, "integrity")

        return self._install(identifier, runtime, chunks, license_accepted=license_accepted,
                             cancel=cancel, deadline=time.monotonic() + OPERATION_SECONDS)

    def update(self, identifier: str, runtime: RuntimeSelection, **request):
        # Installation is explicit and never moves the active pointer by itself.
        with self._hold():
            check(self._state()["active"] is not None, "missing")
        return self.install(identifier, runtime, **request)

    def _binding(self, entry, runtime):
        return digest({"model": entry.model_sha256, "package": entry.package_sha256,
                       "runtime": runtime.fingerprint, "registry": sha256(self.registry.raw),
                       "admission": self.allowed_ids, "session": self._session})

    def self_test(self, identifier: str, runtime: RuntimeSelection, runner, *,
                  requested: bool = False, cancel=lambda: False):
        check(requested is True, "consent")
        with self._hold():
            entry = self._entry(identifier, runtime)
            self._evidence.pop(identifier, None)
            self._native_runners.pop(identifier, None)
            model = self._verify(entry)
            started = time.monotonic()
            checkpoint(cancel, started + OPERATION_SECONDS)
            try:
                # Trusted host implementation only; packages never supply a runner.
                if entry.format == "gguf-v3-q4_k_m":
                    from .ai_runtime import LocalRuntime

                    check(type(runner) is LocalRuntime, "self_test")
                result = runner(model, runtime, cancel)
            except Exception:
                raise ModelError("self_test") from None
            checkpoint(cancel, started + OPERATION_SECONDS)
            check(type(result) is str and result in ("PASSED", "FAILED", "UNKNOWN"), "self_test")
            # A callback cannot validate bytes that changed while it was running.
            self._verify(self._entry(identifier, runtime))
            evidence = SelfTestEvidence(identifier, self._binding(entry, runtime), result,
                                        started + SELF_TEST_TTL_SECONDS)
            if result == "PASSED":
                self._evidence[identifier] = evidence
                if entry.format == "gguf-v3-q4_k_m":
                    self._native_runners[identifier] = runner
            return evidence

    def _admit_evidence(self, entry, runtime, evidence):
        check(type(evidence) is SelfTestEvidence and evidence.result == "PASSED", "self_test")
        check(self._evidence.get(entry.id) is evidence and
              evidence.binding == self._binding(entry, runtime) and
              time.monotonic() < evidence.expires, "stale")
        if entry.format == "gguf-v3-q4_k_m":
            runner = self._native_runners.get(entry.id)
            check(runner is not None, "stale")
            try:
                runner.validate_installation()
            except Exception:
                self._evidence.pop(entry.id, None)
                runner.close()
                raise ModelError("stale") from None
        return self._verify(entry)

    def activate(self, identifier: str, runtime: RuntimeSelection, evidence: SelfTestEvidence, *,
                 requested: bool = False):
        check(requested is True, "consent")
        with self._hold():
            entry = self._entry(identifier, runtime)
            self._admit_evidence(entry, runtime, evidence)
            state = self._state()
            if state["active"] != identifier:
                state["previous"], state["active"] = state["active"], identifier
                self._write_state(state)
            return {"id": identifier, "state": "internally_active", "inference_authorized": False}

    @contextmanager
    def use(self, runtime: RuntimeSelection):
        # Lifetime lock excludes update/removal in another process as well.
        with self._hold():
            identifier = self._state()["active"]
            check(identifier is not None, "missing")
            entry = self._entry(identifier, runtime)
            model = self._admit_evidence(entry, runtime, self._evidence.get(identifier))
            yield model

    def rollback(self, runtime: RuntimeSelection, runner, *, requested: bool = False):
        check(requested is True, "consent")
        with self._hold():
            before = self._state()
            identifier = before["previous"]
            check(identifier is not None, "missing")
            self._verify(self._entry(identifier, runtime))
        evidence = self.self_test(identifier, runtime, runner, requested=True)
        with self._hold():
            check(self._state() == before, "stale")
            self._admit_evidence(self._entry(identifier, runtime), runtime, evidence)
            self._write_state({"schema_version": 1, "active": identifier,
                               "previous": before["active"]})
            return {"id": identifier, "state": "internally_active", "inference_authorized": False}

    def deactivate(self, *, requested: bool = False):
        check(requested is True, "consent")
        with self._hold():
            state = self._state()
            if state["active"] is not None:
                state["previous"], state["active"] = state["active"], None
                self._write_state(state)
            self._evidence.clear()

    def remove(self, identifier: str, *, requested: bool = False):
        check(requested is True, "consent")
        # Revoked packages can still be removed, but never activated/used.
        entry = self.registry.entry(identifier)
        with self._hold():
            state = self._state()
            check(state["active"] != identifier, "in_use")
            self._delete(self._path(entry))
            self._evidence.pop(identifier, None)
            if state["previous"] == identifier:
                state["previous"] = None
                self._write_state(state)

    def recover(self, *, requested: bool = False):
        check(requested is True, "consent")
        with self._hold():
            self._evidence.clear()
            staged = list((self.root / "staging").iterdir())
            check(len(staged) <= MAX_INSTALLED and
                  all(_STAGE_NAME.fullmatch(path.name) for path in staged), "state")
            for path in staged:
                _safe_stat(path)
            for path in staged:
                self._delete(path)
            abandoned = [path for directory in (self.root, self.root / "verified")
                         for path in directory.iterdir() if _TEMP_NAME.fullmatch(path.name)]
            check(len(abandoned) <= MAX_INSTALLED, "state")
            for path in abandoned:
                _safe_stat(path)
            for path in abandoned:
                self._delete(path)
            # Do not infer last-good or silently activate orphaned verified packages.
            state = self._state()
            return {"discarded_staging": len(staged), "discarded_temporary": len(abandoned),
                    "selection": state,
                    "self_test": "UNKNOWN", "inference_authorized": False}

    def status(self):
        # No writes/recovery/network, including on missing storage.
        result = self.registry.inventory()
        result["storage"] = "not_observed"
        for row in result["entries"]:
            try:
                entry = self.registry.entry(row["id"])
                self._verify(entry)
                row["installation"] = "verified_bytes"
            except (ModelError, MaintenanceTargetError, OSError):
                row["installation"] = "missing_or_unverified"
        # Persisted selection never grants fresh self-test authority on a state read.
        result["self_test"] = "NOT_EVALUATED"
        return result


def default_runtime() -> RuntimeSelection:
    return RuntimeSelection(platform=platform.system().lower())
