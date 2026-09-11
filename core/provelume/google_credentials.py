from __future__ import annotations

import ctypes
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4


class GoogleCredentialError(ValueError):
    """Closed diagnostic; backend exceptions and secret material never escape."""


_SLOT = re.compile(r"google_[a-z0-9_]{1,160}\Z")
MAX_SECRET_BYTES = 16 * 1024


def _dpapi(value: bytes, *, decrypt: bool = False) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source = Blob(len(value), buffer)
    target = Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    function.restype = wintypes.BOOL
    # UI forbidden; current Windows user scope, never CRYPTPROTECT_LOCAL_MACHINE.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise GoogleCredentialError("google_secure_store_unavailable")
    try:
        if target.size > MAX_SECRET_BYTES * 2:
            raise GoogleCredentialError("google_secure_store_unavailable")
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.data)


class GoogleCredentialVault:
    """User-owned system storage outside every Instance; no plaintext fallback.

    Windows uses current-user DPAPI without a Python or shell subprocess. Other
    platforms instantiate the supported OS keyring backend directly, so an
    installed plaintext or null plugin cannot silently become the secret store.
    Construction and status-page reads never unlock or read the vault.
    """

    def __init__(self, *, windows_root: Path | None = None, forbidden_root: Path | None = None):
        self.windows_root = windows_root
        self.forbidden_root = forbidden_root

    def _path(self, slot: str) -> Path:
        root = self.windows_root
        if root is None:
            local = os.environ.get("LOCALAPPDATA")
            if not local or not Path(local).is_absolute():
                raise GoogleCredentialError("google_secure_store_unavailable")
            root = Path(local) / "Provelume" / "GoogleCredentials"
        if not root.is_absolute() or any(
            p.is_symlink() or p.is_junction() for p in (root, *root.parents)
        ):
            raise GoogleCredentialError("google_secure_store_unavailable")
        if self.forbidden_root and root.resolve().is_relative_to(self.forbidden_root.resolve()):
            raise GoogleCredentialError("google_secure_store_unavailable")
        path = root / f"{slot}.dpapi"
        if path.is_symlink():
            raise GoogleCredentialError("google_secure_store_unavailable")
        return path

    @staticmethod
    def _backend():
        if sys.platform == "darwin":
            from keyring.backends.macOS import Keyring
        else:
            from keyring.backends.SecretService import Keyring
        return Keyring()

    def _access(self, slot: str, action: str, value: str | None = None) -> str | None:
        if not isinstance(slot, str) or not _SLOT.fullmatch(slot):
            raise GoogleCredentialError("google_secure_store_unavailable")
        try:
            if os.name != "nt":
                backend = self._backend()
                if action == "read":
                    return backend.get_password("provelume.google", slot)
                if action == "write":
                    backend.set_password("provelume.google", slot, value)
                elif backend.get_password("provelume.google", slot) is not None:
                    backend.delete_password("provelume.google", slot)
                return None
            path = self._path(slot)
            if action == "read":
                if not path.exists():
                    return None
                with path.open("rb") as handle:
                    raw = handle.read(MAX_SECRET_BYTES * 2 + 1)
                if len(raw) > MAX_SECRET_BYTES * 2:
                    raise GoogleCredentialError("google_secure_store_unavailable")
                return _dpapi(raw, decrypt=True).decode("utf-8")
            if action == "delete":
                path.unlink(missing_ok=True)
                return None
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{slot}.{uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as handle:
                    handle.write(_dpapi(value.encode("utf-8")))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return None
        except Exception:
            raise GoogleCredentialError("google_secure_store_unavailable") from None

    def read(self, slot: str) -> dict[str, Any] | None:
        raw = self._access(slot, "read")
        if raw is None:
            return None
        try:
            if len(raw.encode("utf-8")) > MAX_SECRET_BYTES:
                raise ValueError
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeError):
            raise GoogleCredentialError("google_secure_store_unavailable") from None

    def write(self, slot: str, value: dict[str, Any]) -> None:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(raw.encode("utf-8")) > MAX_SECRET_BYTES:
            raise GoogleCredentialError("google_secure_store_unavailable")
        self._access(slot, "write", raw)

    def delete(self, slot: str) -> None:
        self._access(slot, "delete")


def write_windows_credential_smoke(output: Path) -> bool:
    """Explicit packaged-platform qualification with disposable synthetic material only."""
    from tempfile import TemporaryDirectory

    from .build_info import current_build_info

    evidence = {
        "schema_version": 1,
        "status": "FAIL",
        "checks": {},
        "exact_head": current_build_info().get("commit"),
        "frozen_executable": bool(getattr(sys, "frozen", False)),
        "network_used": False,
        "private_content_logged": False,
        "real_google_qualified": False,
    }
    try:
        if os.name != "nt":
            raise GoogleCredentialError("google_secure_store_unavailable")
        with TemporaryDirectory(prefix="provelume-google-vault-") as temporary:
            root = Path(temporary) / "credentials"
            vault = GoogleCredentialVault(windows_root=root)
            slot = "google_synthetic_smoke"
            value = {
                "access_token": "synthetic-smoke-access",
                "refresh_token": "synthetic-smoke-refresh",
            }
            vault.write(slot, value)
            encrypted = (root / f"{slot}.dpapi").read_bytes()
            if b"synthetic-smoke" in encrypted:
                raise GoogleCredentialError("google_secure_store_unavailable")
            evidence["checks"]["encrypted_outside_instance"] = "PASS"
            if GoogleCredentialVault(windows_root=root).read(slot) != value:
                raise GoogleCredentialError("google_secure_store_unavailable")
            evidence["checks"]["reopened_current_user"] = "PASS"
            (root / f"{slot}.dpapi").write_bytes(encrypted[:-20] + b"tampered")
            try:
                vault.read(slot)
            except GoogleCredentialError:
                evidence["checks"]["tamper_rejected"] = "PASS"
            else:
                raise GoogleCredentialError("google_secure_store_unavailable")
            vault.delete(slot)
            if vault.read(slot) is not None:
                raise GoogleCredentialError("google_secure_store_unavailable")
            evidence["checks"]["credential_deleted"] = "PASS"
        evidence["status"] = "PASS"
    except Exception:
        evidence["failure_code"] = "google_packaged_credential_store_failed"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return evidence["status"] == "PASS"
