"""Instance-scoped, revocable Capture verifiers; host key never travels with data."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from .atomic_commit import (
    AtomicCommitLimits,
    AtomicCommitProfile,
    AtomicInstanceCommit,
    AtomicRecoveryHandler,
    _load_transaction_manifest,
    _validate_transaction_manifest,
    recover_atomic_transactions,
)
from .capture_journal import CaptureJournalError, _read, _safe, _unique
from .instance_lifecycle import InstanceLifecycleManager
from .storage import utc_now

MAX_DEVICES = 128
MAX_CHALLENGES = 16
MAX_AUDIT = 4096
PATH = "state/capture-authority.json"
PROFILE = AtomicCommitProfile(
    "device-authority",
    "capture.authority",
    r"inst_[0-9a-f]{32}\Z",
    AtomicCommitLimits(1, 4 * 1024 * 1024, 4 * 1024 * 1024, 4 * 1024 * 1024, 8 * 1024 * 1024),
)
SCOPE = "capture.submit+self.receipts+self.original.download+metadata.proposals"
_DEVICE = re.compile(r"dev_[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def _owner_guard(authorize_owner):
    if authorize_owner() is not None:
        raise PermissionError("Capture owner guard must explicitly authorize the action")


def trusted_capture_origin(value):
    if not isinstance(value, str) or len(value) > 512:
        raise CaptureJournalError("Explicit HTTPS Capture origin required")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or "\\" in value
            or any(c.isspace() for c in value)
        ):
            raise ValueError()
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError()
    except ValueError as exc:
        raise CaptureJournalError("Explicit HTTPS Capture origin required") from exc
    if value != value.lower().rstrip("/"):
        raise CaptureJournalError("Capture origin must be canonical without a trailing slash")
    return value


def _stamp(value):
    if not isinstance(value, str):
        raise CaptureJournalError("Invalid Capture authority time")
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp
    except ValueError as exc:
        raise CaptureJournalError("Invalid Capture authority time") from exc


def validate_authority(value, instance_id):
    try:
        if (
            set(value)
            != {
                "schema_version",
                "instance_id",
                "origin",
                "host_binding",
                "devices",
                "challenges",
                "audit",
            }
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["instance_id"] != instance_id
            or not _HASH.fullmatch(value["host_binding"])
            or not isinstance(value["devices"], dict)
            or len(value["devices"]) > MAX_DEVICES
            or not isinstance(value["challenges"], list)
            or len(value["challenges"]) > MAX_CHALLENGES
            or not isinstance(value["audit"], list)
            or len(value["audit"]) > MAX_AUDIT
        ):
            raise ValueError()
        trusted_capture_origin(value["origin"])
        for device, row in value["devices"].items():
            if (
                not _DEVICE.fullmatch(device)
                or set(row) != {"label", "verifier", "issued_at", "revoked_at", "scope"}
                or not isinstance(row["label"], str)
                or not 1 <= len(row["label"]) <= 80
                or any(ord(c) < 32 for c in row["label"])
                or not _HASH.fullmatch(row["verifier"])
                or row["scope"] != SCOPE
            ):
                raise ValueError()
            _stamp(row["issued_at"])
            if row["revoked_at"] is not None:
                _stamp(row["revoked_at"])
        seen = set()
        for row in value["challenges"]:
            if (
                set(row) != {"verifier", "expires_at", "used_at"}
                or not _HASH.fullmatch(row["verifier"])
                or row["verifier"] in seen
            ):
                raise ValueError()
            seen.add(row["verifier"])
            _stamp(row["expires_at"])
            if row["used_at"] is not None:
                _stamp(row["used_at"])
        ids = set()
        for row in value["audit"]:
            if (
                set(row) != {"id", "at", "action", "device_id"}
                or not re.fullmatch(r"audit_[0-9a-f]{32}", row["id"])
                or row["id"] in ids
                or row["action"] not in {"configured", "challenge", "paired", "revoked"}
                or (row["device_id"] is not None and row["device_id"] not in value["devices"])
            ):
                raise ValueError()
            ids.add(row["id"])
            _stamp(row["at"])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise CaptureJournalError("Invalid Capture authority schema") from exc
    return value


class CaptureAuthority:
    def __init__(self, store):
        self.store = store
        self.lifecycle = InstanceLifecycleManager(store)
        self.instance_id = store.read_config()["instance"]["id"]
        self.path = store.paths.root / PATH
        self.key_path = self.lifecycle.control_root / "capture-host-key.bin"

    def read(self):
        from .capture_journal import CaptureJournal

        CaptureJournal(self.store)._read_ready()
        _safe(self.path)
        if not self.path.exists():
            return None
        return validate_authority(
            json.loads(_read(self.path, 4 * 1024 * 1024), object_pairs_hook=_unique),
            self.instance_id,
        )

    def _key(self, *, create=False):
        _safe(self.key_path)
        if not self.key_path.exists():
            if not create:
                return None
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            key = secrets.token_bytes(32)
            if sys.platform == "win32":
                from .google_credentials import _dpapi

                encoded = _dpapi(key)
            else:
                encoded = key
            fd = os.open(self.key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        if sys.platform != "win32" and self.key_path.stat().st_mode & 0o077:
            raise PermissionError("Capture host key requires owner-only permissions")
        encoded = _read(self.key_path, 4096)
        if sys.platform == "win32":
            from .google_credentials import _dpapi

            encoded = _dpapi(encoded, decrypt=True)
        if len(encoded) != 32:
            raise CaptureJournalError("Capture host key is invalid")
        return encoded

    def _binding(self, key):
        return hashlib.sha256(key + self.instance_id.encode()).hexdigest()

    def _verifier(self, key, secret, purpose, origin):
        if not isinstance(secret, str) or not _TOKEN.fullmatch(secret):
            raise PermissionError("Capture credential rejected")
        return hmac.new(
            key, f"{self.instance_id}:{origin}:{purpose}:{secret}".encode(), hashlib.sha256
        ).hexdigest()

    def _audit(self, value, action, device=None):
        if len(value["audit"]) >= MAX_AUDIT:
            raise CaptureJournalError("Capture authority audit full; history retained")
        value["audit"].append(
            dict(id="audit_" + uuid4().hex, at=utc_now(), action=action, device_id=device)
        )

    def _write(self, value):
        validate_authority(value, self.instance_id)
        transaction = AtomicInstanceCommit(
            self.store,
            self.lifecycle.control_root / "transactions",
            profile=PROFILE,
            owner_id=self.instance_id,
        )
        transaction.add(
            PATH, json.dumps(value, sort_keys=True, allow_nan=False).encode(), immutable=False
        )
        transaction.commit()

    def configure(self, origin, *, confirm_rebind, authorize_owner):
        origin = trusted_capture_origin(origin)
        if confirm_rebind is not True:
            raise PermissionError("Explicit rebind/revocation confirmation required")
        _owner_guard(authorize_owner)
        with self.lifecycle._hold(purpose="capture-authority"):
            _owner_guard(authorize_owner)
            previous = self.read()
            key = self._key(create=True)
            value = previous or dict(
                schema_version=1,
                instance_id=self.instance_id,
                origin=origin,
                host_binding=self._binding(key),
                devices={},
                challenges=[],
                audit=[],
            )
            for row in value["devices"].values():
                row["revoked_at"] = row["revoked_at"] or utc_now()
            value.update(origin=origin, host_binding=self._binding(key), challenges=[])
            self._audit(value, "configured")
            self._write(value)
        return self.management()

    def management(self):
        value = self.read()
        if value is None:
            return dict(origin=None, active=False, devices=[], scope=SCOPE)
        key = self._key()
        active = key is not None and hmac.compare_digest(value["host_binding"], self._binding(key))
        return dict(
            origin=value["origin"],
            active=active,
            scope=SCOPE,
            devices=[
                dict(
                    device_id=k,
                    label=r["label"],
                    issued_at=r["issued_at"],
                    revoked_at=r["revoked_at"],
                )
                for k, r in value["devices"].items()
            ],
        )

    def challenge(self, *, authorize_owner):
        _owner_guard(authorize_owner)
        with self.lifecycle._hold(purpose="capture-pairing"):
            _owner_guard(authorize_owner)
            value = self.read()
            key = self._key()
            if (
                value is None
                or key is None
                or not hmac.compare_digest(value["host_binding"], self._binding(key))
            ):
                raise PermissionError("Configure/rebind Capture explicitly before pairing")
            now = datetime.now(UTC)
            value["challenges"] = [
                r
                for r in value["challenges"]
                if r["used_at"] is None and _stamp(r["expires_at"]) > now
            ]
            if len(value["challenges"]) >= MAX_CHALLENGES:
                raise CaptureJournalError("Capture pairing challenge bound reached")
            secret = secrets.token_urlsafe(32)
            expires = (now + timedelta(seconds=120)).isoformat()
            value["challenges"].append(
                dict(
                    verifier=self._verifier(key, secret, "pair", value["origin"]),
                    expires_at=expires,
                    used_at=None,
                )
            )
            self._audit(value, "challenge")
            self._write(value)
        return dict(
            schema_version=1,
            origin=value["origin"],
            instance_id=self.instance_id,
            scope=SCOPE,
            challenge=secret,
            expires_at=expires,
        )

    def redeem(self, challenge, label, *, origin):
        if (
            not isinstance(label, str)
            or not 1 <= len(label) <= 80
            or any(ord(c) < 32 for c in label)
        ):
            raise CaptureJournalError("Capture device label is invalid")
        with self.lifecycle._hold(purpose="capture-pairing-redemption"):
            value = self.read()
            key = self._key()
            if (
                value is None
                or key is None
                or value["origin"] != origin
                or not hmac.compare_digest(value["host_binding"], self._binding(key))
            ):
                raise PermissionError("Capture pairing destination rejected")
            verifier = self._verifier(key, challenge, "pair", origin)
            row = next(
                (r for r in value["challenges"] if hmac.compare_digest(r["verifier"], verifier)),
                None,
            )
            if (
                row is None
                or row["used_at"] is not None
                or _stamp(row["expires_at"]) <= datetime.now(UTC)
            ):
                raise PermissionError("Capture pairing challenge expired or used")
            if len(value["devices"]) >= MAX_DEVICES:
                raise CaptureJournalError("Capture device bound reached")
            device = "dev_" + uuid4().hex
            token = secrets.token_urlsafe(32)
            token_verifier = self._verifier(key, token, "credential", origin)
            if device in value["devices"] or any(
                hmac.compare_digest(existing["verifier"], token_verifier)
                for existing in value["devices"].values()
            ):
                raise CaptureJournalError("Capture credential or device identity conflict")
            row["used_at"] = utc_now()
            value["devices"][device] = dict(
                label=label,
                issued_at=utc_now(),
                revoked_at=None,
                scope=SCOPE,
                verifier=token_verifier,
            )
            self._audit(value, "paired", device)
            self._write(value)
        return dict(
            device_id=device,
            credential=token,
            origin=origin,
            instance_id=self.instance_id,
            scope=SCOPE,
        )

    def authorize(self, device, token, *, origin):
        value = self.read()
        key = self._key()
        if (
            value is None
            or key is None
            or value["origin"] != origin
            or not hmac.compare_digest(value["host_binding"], self._binding(key))
        ):
            raise PermissionError("Capture authority unavailable; explicit pairing required")
        row = value["devices"].get(device)
        if (
            row is None
            or row["revoked_at"] is not None
            or not hmac.compare_digest(
                row["verifier"], self._verifier(key, token, "credential", origin)
            )
        ):
            raise PermissionError("Capture credential rejected or revoked")

    def revoke(self, device, *, authorize_owner):
        _owner_guard(authorize_owner)
        with self.lifecycle._hold(purpose="capture-revoke"):
            _owner_guard(authorize_owner)
            value = self.read()
            if value is None or device not in value["devices"]:
                raise CaptureJournalError("Capture device unavailable")
            if value["devices"][device]["revoked_at"] is None:
                value["devices"][device]["revoked_at"] = utc_now()
                self._audit(value, "revoked", device)
                self._write(value)
        return self.management()


def recover_capture_authority_locked(store):
    authority = CaptureAuthority(store)
    root = authority.lifecycle.control_root / "transactions"
    _safe(root)
    if not root.exists():
        return None
    for index, stage in enumerate(root.glob("device-authority-*")):
        if index >= MAX_AUDIT:
            raise CaptureJournalError("Capture authority recovery bound reached")
        manifest = _load_transaction_manifest(stage, max_entries=1, error_type=CaptureJournalError)
        if manifest is None:
            continue
        _validate_transaction_manifest(
            store, stage, manifest, profile=PROFILE, error_type=CaptureJournalError
        )
        if manifest["operation_id"] != authority.instance_id or len(manifest["entries"]) != 1:
            raise CaptureJournalError("Capture authority recovery identity rejected")
        entry = manifest["entries"][0]
        if entry["relative"] != PATH or entry["immutable"] is not False:
            raise CaptureJournalError("Capture authority recovery outside domain allowlist")
        for path in [stage / entry["candidate_ref"], authority.path] + (
            [stage / entry["preimage_ref"]] if entry["had_preimage"] else []
        ):
            if path.exists():
                validate_authority(
                    json.loads(_read(path, 4 * 1024 * 1024), object_pairs_hook=_unique),
                    authority.instance_id,
                )
    return recover_atomic_transactions(
        store, authority.lifecycle.control_root, handlers=(AtomicRecoveryHandler(profile=PROFILE),)
    )
