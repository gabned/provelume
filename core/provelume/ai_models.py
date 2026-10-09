"""Governed S04 artifact identities, not inference or Recommended authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

from .ai_contract import Capability, Limits, Profile, digest
from .representations import canonical_json_bytes
from .web_transport import GuardedWebLimits, canonical_web_origin, canonical_web_url

MAX_MANIFEST_BYTES = 32 * 1024
MAX_PACKAGE_BYTES = 128 * 1024
MAX_FILE_BYTES = 64 * 1024
MAX_FILES = 2
MAX_TOTAL_BYTES = 96 * 1024
MAX_INSTALLED = 8
FORMAT = "synthetic-bytes-v1"
NATIVE_FORMATS = ("gguf-v3-q4_k_m", "gguf-v3-q2_k", "gguf-v3-q5_k_m", "gguf-v3-q8_0")
RUNTIME = "provelume.synthetic-fixture"
RUNTIME_VERSION = "1"
CONFIGURATION = {"schema_version": 1, "purpose": "lifecycle-self-test-only"}
# Governed together with the manifest by ordinary application distribution gates.
# This pin is not accepted from an offline package or a download response.
MANIFEST_SHA256 = "23ca1939ccf7acc788da37440773c6f29c908f353a2226b4a96dc3272f2e6bd3"
_ID = re.compile(r"[a-z][a-z0-9_.-]{0,79}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class ModelError(ValueError):
    """Closed, content/path/URL-free diagnostics; no underlying exception text."""

    def __init__(self, code: str):
        if code not in {
            "manifest",
            "untrusted",
            "unknown",
            "compatibility",
            "revoked",
            "license",
            "origin",
            "package",
            "integrity",
            "limit",
            "unsafe_path",
            "missing",
            "busy",
            "space",
            "io",
            "cancelled",
            "timeout",
            "network",
            "self_test",
            "stale",
            "in_use",
            "consent",
            "state",
        }:
            raise ValueError("invalid model error code")
        self.code = code
        super().__init__("model_" + code)


def check(condition: bool, code: str = "manifest") -> None:
    if not condition:
        raise ModelError(code)


def exact(value: Any, keys: set[str], code: str = "manifest") -> dict:
    check(type(value) is dict and set(value) == keys, code)
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        check(key not in result)
        result[key] = value
    return result


def parse_json(raw: bytes, maximum: int = MAX_MANIFEST_BYTES) -> Any:
    check(type(raw) is bytes and len(raw) <= maximum, "limit")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeError, ValueError, RecursionError):
        raise ModelError("manifest") from None


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    check(type(value) is str and _HASH.fullmatch(value) is not None)


def _id(value):
    check(type(value) is str and _ID.fullmatch(value) is not None)


def artifact_url(value: Any) -> str:
    try:
        result = canonical_web_url(value, limits=GuardedWebLimits())
        check(result == value and result.startswith("https://"), "origin")
        # No credentials, query tokens, fragments, alternate ports or ambiguous escaping.
        from urllib.parse import urlsplit

        parts = urlsplit(result)
        check(parts.port in (None, 443) and not parts.query and not parts.fragment, "origin")
        check("%" not in parts.path, "origin")
        check(all(segment not in (".", "..") for segment in parts.path.split("/")), "origin")
        return result
    except ModelError:
        raise
    except Exception:
        raise ModelError("origin") from None


@dataclass(frozen=True, slots=True)
class ModelEntry:
    id: str
    version: str
    channel: str
    qualification: str
    app_version: str
    runtime_id: str
    runtime_version: str
    format: str
    license: str
    origin: str
    url: str
    package_sha256: str
    package_size: int
    model_sha256: str
    model_size: int
    license_sha256: str
    license_size: int
    evidence: str

    @property
    def native(self):
        return self.format in NATIVE_FORMATS

    @property
    def file_inventory(self):
        return {
            "model.bin": (self.model_size, self.model_sha256),
            "LICENSE.txt": (self.license_size, self.license_sha256),
        }

    @property
    def profile(self) -> Profile:
        # Reuse the single S01 profile schema. No LocalityEvidence is manufactured.
        return Profile(
            id=self.id,
            provider=self.runtime_id,
            model=self.id if self.runtime_id == "llama.cpp" else "fixture.model",
            revision=self.model_sha256,
            route_revision=digest({"runtime": self.runtime_id, "version": self.runtime_version}),
            capabilities=(Capability.STRUCTURED_OUTPUT,),
            limits=Limits(4096, 128, 1, 60)
            if self.runtime_id == "llama.cpp"
            else Limits(1024, 32, 1, 5),
        )


def parse_manifest(raw: bytes) -> tuple[ModelEntry, ...]:
    """Validate untrusted metadata. This function does NOT approve installation."""
    value = exact(parse_json(raw), {"schema_version", "repository", "entries"})
    check(type(value["schema_version"]) is int and value["schema_version"] == 1)
    check(value["repository"] == "gabned/provelume")
    rows = value["entries"]
    check(type(rows) is list and 1 <= len(rows) <= MAX_INSTALLED)
    entries = []
    seen = set()
    for row in rows:
        exact(row, set(ModelEntry.__dataclass_fields__))
        item = ModelEntry(**row)
        _id(item.id)
        check(item.id not in seen)
        seen.add(item.id)
        check(type(item.version) is str and re.fullmatch(r"[1-9][0-9]{0,3}", item.version))
        check(item.channel in ("candidate", "stable"))
        native = item.native
        retired = False
        if native:
            from .ai_runtime_contract import RETIRED_MODEL_IDS, native_model_pin

            pin = native_model_pin(item.id)
            retired = item.id in RETIRED_MODEL_IDS
        check(item.qualification == ("RETIRED" if retired else
              "CANDIDATE_NOT_QUALIFIED" if native else "SYNTHETIC_ONLY"))
        check(item.app_version == "0.11.0")
        check(
            (item.runtime_id, item.runtime_version, item.format)
            == (
                ("llama.cpp", "b11379", pin.format)
                if native
                else (RUNTIME, RUNTIME_VERSION, FORMAT)
            ),
            "compatibility",
        )
        check(item.license == ("Apache-2.0" if native else "CC0-1.0"), "license")
        artifact_url(item.url)
        check(item.origin == canonical_web_origin(item.url, limits=GuardedWebLimits()), "origin")
        check(
            item.evidence
            == (
                pin.evidence
                if native
                else "repository:docs/architecture/ai-model-lifecycle.md#provenance"
            )
        )
        for value in (item.package_sha256, item.model_sha256, item.license_sha256):
            _hash(value)
        maximum_model = pin.size if native else MAX_FILE_BYTES
        for size, maximum in (
            (item.package_size, maximum_model if native else MAX_PACKAGE_BYTES),
            (item.model_size, maximum_model),
            (item.license_size, MAX_FILE_BYTES),
        ):
            check(type(size) is int and 1 <= size <= maximum, "limit")
        if native:
            check(
                item.model_size == pin.size
                and item.package_size == pin.size
                and item.model_sha256 == pin.sha256
                and item.package_sha256 == pin.sha256
                and item.url == pin.url,
                "compatibility",
            )
        else:
            check(item.model_size + item.license_size <= MAX_TOTAL_BYTES, "limit")
        entries.append(item)
    return tuple(entries)


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    """Only the exact shipped manifest can cross the repository trust boundary."""

    raw: bytes
    _entries: tuple[ModelEntry, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        check(type(self.raw) is bytes and len(self.raw) <= MAX_MANIFEST_BYTES, "untrusted")
        check(sha256(self.raw) == MANIFEST_SHA256, "untrusted")
        # Both the admitted bytes and parsed entries are immutable. Reuse this
        # pure calculation during cancellation polls; activation, revocation
        # and self-test freshness still come from ModelStore on every call.
        object.__setattr__(self, "_entries", parse_manifest(self.raw))

    @classmethod
    def packaged(cls):
        return cls(files("provelume").joinpath("model_registry.json").read_bytes())

    @property
    def entries(self):
        return self._entries

    def entry(self, identifier: str) -> ModelEntry:
        for entry in self.entries:
            if entry.id == identifier:
                return entry
        raise ModelError("unknown")

    def discover(self, *, requested: bool = False):
        check(requested is True, "consent")
        # Deliberately local: future registry changes ship with the app, not an updater.
        return tuple(entry.id for entry in self.entries if entry.qualification != "RETIRED")

    def inventory(self):
        return {
            "schema_version": 1,
            "manifest_sha256": sha256(self.raw),
            "provenance": "application_distribution",
            "network_used": False,
            "recommended": None,
            "advanced_byom": "UNSUPPORTED_NO_QUALIFIED_RUNTIME",
            "entries": [
                {
                    "id": entry.id,
                    "category": "model",
                    "version": entry.version,
                    "channel": entry.channel,
                    "qualification": entry.qualification,
                    "app_version": entry.app_version,
                    "runtime_id": entry.runtime_id,
                    "runtime_version": entry.runtime_version,
                    "format": entry.format,
                    "expected_sha256": entry.model_sha256,
                    "license": entry.license,
                    "origin": entry.origin,
                    "size_bytes": entry.model_size,
                    "status": "unverified",
                    "installation": "not_observed",
                    "offline_qualified": False,
                    "inference_authorized": False,
                }
                for entry in self.entries
            ],
        }


@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    """Host selection, never package-supplied executable/configuration code."""

    id: str = RUNTIME
    version: str = RUNTIME_VERSION
    format: str = FORMAT
    app_version: str = "0.11.0"
    platform: str = "unknown"
    configuration: bytes = canonical_json_bytes(CONFIGURATION)

    def validate(self, entry: ModelEntry):
        check(entry.qualification != "RETIRED", "revoked")
        check(
            (self.id, self.version, self.format, self.app_version)
            == (entry.runtime_id, entry.runtime_version, entry.format, entry.app_version),
            "compatibility",
        )
        check(self.platform in ("linux", "windows"), "compatibility")
        if self.id == "llama.cpp":
            from .ai_runtime_contract import CONFIGURATION as native_configuration

            check(self.configuration == canonical_json_bytes(native_configuration), "compatibility")
        else:
            check(self.configuration == canonical_json_bytes(CONFIGURATION), "compatibility")

    @property
    def fingerprint(self):
        return digest(
            {
                "id": self.id,
                "version": self.version,
                "format": self.format,
                "app_version": self.app_version,
                "platform": self.platform,
                "configuration": sha256(self.configuration),
            }
        )
