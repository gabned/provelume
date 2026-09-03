from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
from collections.abc import Callable, Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

COMPONENT_INVENTORY_SCHEMA_VERSION = 1
COMPONENT_CATALOGUE_VERSION = 1
MAX_CATALOGUE_BYTES = 512 * 1024
MAX_SBOM_BYTES = 8 * 1024 * 1024
MAX_SBOM_COMPONENTS = 10_000

COMPONENT_CATEGORIES = frozenset(
    {
        "first_party",
        "python_package",
        "native_tool",
        "codec",
        "model",
        "language_pack",
        "host_prerequisite",
    }
)
COMPONENT_STATES = frozenset(
    {"installed", "missing", "ahead", "incompatible", "eol", "unsupported", "unverified"}
)
RELEASE_EVIDENCE_STATES = frozenset({"unavailable", "matched", "mismatch"})
CHECK_STATES = frozenset({"not_checked", "current", "stale"})
DETECTION_KINDS = frozenset(
    {"distribution", "python_runtime", "platform", "executable_presence", "external_evidence"}
)
CLASS_COVERAGE_STATES = frozenset({"inventoried", "not_selected", "unavailable"})

_VERSION = re.compile(r"[0-9]+(?:\.[0-9A-Za-z]+)*(?:[-+][0-9A-Za-z.-]+)?\Z")
_CONSTRAINT = re.compile(r"(==|>=|<=|>|<)([0-9]+(?:\.[0-9A-Za-z]+)*)\Z")
_COMPONENT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}\Z")


class ComponentInventoryError(ValueError):
    """Closed failure for malformed catalogue or release evidence."""

    def __init__(self, code: str, message: str):
        if code not in {
            "component_catalogue_invalid",
            "component_sbom_invalid",
            "component_sbom_limit_exceeded",
        }:
            raise ValueError("component inventory error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _load_packaged_catalogue() -> dict[str, Any]:
    resource = files("provelume").joinpath("component_catalogue.json")
    raw = resource.read_bytes()
    if len(raw) > MAX_CATALOGUE_BYTES:
        raise ComponentInventoryError(
            "component_catalogue_invalid", "component catalogue exceeds its byte limit"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ComponentInventoryError(
            "component_catalogue_invalid", "component catalogue is not valid JSON"
        ) from exc
    return _validate_catalogue(payload)


def _exact_object(value: Any, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ComponentInventoryError(
            "component_catalogue_invalid", f"{name} fields are incomplete or unsupported"
        )
    return dict(value)


def _text(value: Any, name: str, *, maximum: int = 500) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or len(value) > maximum
    ):
        raise ComponentInventoryError("component_catalogue_invalid", f"{name} is invalid")
    return value


def _optional_text(value: Any, name: str, *, maximum: int = 500) -> str | None:
    if value is None:
        return None
    return _text(value, name, maximum=maximum)


def _validate_catalogue(value: Any) -> dict[str, Any]:
    catalogue = _exact_object(
        value,
        "catalogue",
        {"schema_version", "catalogue_version", "components", "class_coverage"},
    )
    if (
        catalogue["schema_version"] != COMPONENT_INVENTORY_SCHEMA_VERSION
        or catalogue["catalogue_version"] != COMPONENT_CATALOGUE_VERSION
    ):
        raise ComponentInventoryError(
            "component_catalogue_invalid", "component catalogue version is unsupported"
        )
    components = catalogue["components"]
    if not isinstance(components, list) or not components or len(components) > 1_000:
        raise ComponentInventoryError(
            "component_catalogue_invalid", "component catalogue size is invalid"
        )
    identifiers: set[str] = set()
    component_keys = {
        "id",
        "category",
        "name",
        "purpose",
        "dependency_relation",
        "delivery",
        "update_route",
        "origin",
        "license",
        "notices",
        "purl",
        "expected_sha256",
        "required",
        "approved_version",
        "version_constraint",
        "platforms",
        "detection",
        "sbom_required",
        "eol",
    }
    for index, raw in enumerate(components):
        item = _exact_object(raw, f"components[{index}]", component_keys)
        identifier = _text(item["id"], "component id", maximum=100)
        if _COMPONENT_ID.fullmatch(identifier) is None or identifier in identifiers:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component ids must be unique and portable"
            )
        identifiers.add(identifier)
        if item["category"] not in COMPONENT_CATEGORIES:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component category is unsupported"
            )
        _text(item["name"], "component name")
        purpose = _exact_object(item["purpose"], "component purpose", {"en", "it"})
        _text(purpose["en"], "English purpose")
        _text(purpose["it"], "Italian purpose")
        for field in ("dependency_relation", "delivery", "update_route", "origin", "license"):
            _text(item[field], field)
        _text(item["notices"], "notices", maximum=1_000)
        _optional_text(item["purl"], "purl")
        digest = _optional_text(item["expected_sha256"], "expected_sha256")
        if digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component SHA-256 is invalid"
            )
        approved = _optional_text(item["approved_version"], "approved_version")
        constraint = _optional_text(item["version_constraint"], "version_constraint")
        if approved is not None and _VERSION.fullmatch(approved) is None:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "approved component version is invalid"
            )
        if constraint is not None:
            _parse_constraint(constraint)
        if type(item["required"]) is not bool or type(item["sbom_required"]) is not bool:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component booleans are invalid"
            )
        if type(item["eol"]) is not bool:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component EOL state is invalid"
            )
        platforms = item["platforms"]
        if not isinstance(platforms, list) or not platforms:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component platforms are invalid"
            )
        for selected in platforms:
            _text(selected, "platform", maximum=50)
        detection = _exact_object(item["detection"], "component detection", {"kind", "value"})
        if detection["kind"] not in DETECTION_KINDS:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component detection kind is unsupported"
            )
        _text(detection["value"], "component detection value", maximum=100)
    coverage = catalogue["class_coverage"]
    if not isinstance(coverage, list) or len(coverage) != len(COMPONENT_CATEGORIES):
        raise ComponentInventoryError(
            "component_catalogue_invalid", "component class coverage is incomplete"
        )
    covered: set[str] = set()
    for raw in coverage:
        item = _exact_object(raw, "class coverage", {"category", "state"})
        if item["category"] not in COMPONENT_CATEGORIES or item["category"] in covered:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component class coverage is invalid"
            )
        if item["state"] not in CLASS_COVERAGE_STATES:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component class coverage state is invalid"
            )
        covered.add(item["category"])
    return catalogue


def _version_key(value: str) -> tuple[tuple[int, int | str], ...]:
    if _VERSION.fullmatch(value) is None:
        raise ValueError("version is not comparable")
    base = re.split(r"[-+]", value, maxsplit=1)[0]
    result: list[tuple[int, int | str]] = []
    for part in base.split("."):
        result.append((0, int(part)) if part.isdigit() else (1, part.casefold()))
    return tuple(result)


def _compare(left: str, right: str) -> int:
    left_key = _version_key(left)
    right_key = _version_key(right)
    width = max(len(left_key), len(right_key))
    padded_left = left_key + ((0, 0),) * (width - len(left_key))
    padded_right = right_key + ((0, 0),) * (width - len(right_key))
    return (padded_left > padded_right) - (padded_left < padded_right)


def _parse_constraint(value: str) -> tuple[tuple[str, str], ...]:
    result = []
    for part in value.split(","):
        match = _CONSTRAINT.fullmatch(part.strip())
        if match is None:
            raise ComponentInventoryError(
                "component_catalogue_invalid", "component version constraint is invalid"
            )
        result.append((match.group(1), match.group(2)))
    return tuple(result)


def _matches(version: str, constraint: str | None) -> bool:
    if constraint is None:
        return True
    for operator, expected in _parse_constraint(constraint):
        compared = _compare(version, expected)
        if not {
            "==": compared == 0,
            ">=": compared >= 0,
            "<=": compared <= 0,
            ">": compared > 0,
            "<": compared < 0,
        }[operator]:
            return False
    return True


def _is_ahead(version: str, approved: str | None, constraint: str | None) -> bool:
    if approved is not None:
        return _compare(version, approved) > 0
    if constraint is None:
        return False
    upper = [
        expected for operator, expected in _parse_constraint(constraint) if operator in {"<", "<="}
    ]
    return bool(upper and _compare(version, upper[0]) >= 0)


def _load_sbom(path: Path) -> tuple[dict[str, set[str]], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ComponentInventoryError(
            "component_sbom_invalid", "release SBOM cannot be read"
        ) from exc
    if len(raw) > MAX_SBOM_BYTES:
        raise ComponentInventoryError(
            "component_sbom_limit_exceeded", "release SBOM exceeds its byte limit"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ComponentInventoryError(
            "component_sbom_invalid", "release SBOM is not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping) or payload.get("bomFormat") != "CycloneDX":
        raise ComponentInventoryError(
            "component_sbom_invalid", "release SBOM is not a CycloneDX document"
        )
    components = payload.get("components")
    if not isinstance(components, list) or len(components) > MAX_SBOM_COMPONENTS:
        raise ComponentInventoryError(
            "component_sbom_limit_exceeded", "release SBOM component count is invalid"
        )
    inventory: dict[str, set[str]] = {}
    for row in components:
        if not isinstance(row, Mapping):
            raise ComponentInventoryError(
                "component_sbom_invalid", "release SBOM contains an invalid component"
            )
        version = row.get("version")
        for identity in (row.get("purl"), row.get("name")):
            if isinstance(identity, str) and identity and isinstance(version, str) and version:
                inventory.setdefault(identity.casefold(), set()).add(version)
    return inventory, hashlib.sha256(raw).hexdigest()


class ComponentInventory:
    """Read-only installed and release component catalogue."""

    def __init__(
        self,
        *,
        catalogue: Mapping[str, Any] | None = None,
        distribution_versions: Mapping[str, str] | None = None,
        executable_present: Callable[[str], bool] | None = None,
        python_version: str | None = None,
        platform_name: str | None = None,
    ):
        self.catalogue = (
            _validate_catalogue(catalogue) if catalogue is not None else _load_packaged_catalogue()
        )
        self._versions = (
            {key.casefold(): value for key, value in distribution_versions.items()}
            if distribution_versions is not None
            else None
        )
        self._executable_present = executable_present or (
            lambda name: shutil.which(name) is not None
        )
        self._python_version = python_version or platform.python_version()
        self._platform_name = (platform_name or platform.system() or "unknown").casefold()

    def _distribution_version(self, name: str) -> str | None:
        if self._versions is not None:
            return self._versions.get(name.casefold())
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    def _observed_version(self, item: Mapping[str, Any]) -> tuple[str | None, str]:
        detection = item["detection"]
        kind = detection["kind"]
        value = detection["value"]
        if kind == "distribution":
            version = self._distribution_version(value)
            return version, "installed_distribution_metadata" if version else "distribution_missing"
        if kind == "python_runtime":
            return self._python_version, "runtime_metadata"
        if kind == "platform":
            return self._platform_name, "runtime_metadata"
        if kind == "executable_presence":
            present = self._executable_present(value)
            return ("unknown" if present else None), (
                "executable_present_version_unverified" if present else "executable_missing"
            )
        return None, "explicit_evidence_not_supplied"

    @staticmethod
    def _state(item: Mapping[str, Any], version: str | None, evidence: str) -> tuple[str, str]:
        if item["eol"]:
            return "eol", "catalogue_marks_component_eol"
        if evidence == "explicit_evidence_not_supplied":
            return "unverified", evidence
        if version is None:
            return "missing", "required_component_missing" if item[
                "required"
            ] else "optional_component_missing"
        if version == "unknown":
            return "unverified", evidence
        try:
            compatible = _matches(version, item["version_constraint"])
            ahead = _is_ahead(version, item["approved_version"], item["version_constraint"])
        except ValueError:
            return "unverified", "installed_version_not_comparable"
        if compatible:
            return "installed", "installed_version_within_declared_contract"
        if ahead:
            return "ahead", "installed_version_ahead_of_declared_contract"
        return "incompatible", "installed_version_outside_declared_contract"

    def read(self, *, release_sbom: Path | str | None = None) -> dict[str, Any]:
        sbom_inventory: dict[str, set[str]] | None = None
        sbom_sha256: str | None = None
        if release_sbom is not None:
            sbom_inventory, sbom_sha256 = _load_sbom(Path(release_sbom))

        records: list[dict[str, Any]] = []
        release_mismatches: list[str] = []
        for raw in self.catalogue["components"]:
            item = dict(raw)
            version, evidence = self._observed_version(item)
            state, reason = self._state(item, version, evidence)
            release_state = "not_required"
            if item["sbom_required"]:
                release_state = "unavailable"
                if sbom_inventory is not None:
                    identities = [
                        selected.casefold()
                        for selected in (item["purl"], item["detection"]["value"], item["name"])
                        if isinstance(selected, str)
                    ]
                    seen_versions = set().union(
                        *(sbom_inventory.get(identity, set()) for identity in identities)
                    )
                    if version is not None and version in seen_versions:
                        release_state = "matched"
                    else:
                        release_state = "mismatch"
                        release_mismatches.append(item["id"])
            records.append(
                {
                    "id": item["id"],
                    "category": item["category"],
                    "name": item["name"],
                    "purpose": item["purpose"],
                    "dependency_relation": item["dependency_relation"],
                    "delivery": item["delivery"],
                    "update_route": item["update_route"],
                    "origin": item["origin"],
                    "license": item["license"],
                    "notices": item["notices"],
                    "purl": item["purl"],
                    "expected_sha256": item["expected_sha256"],
                    "required": item["required"],
                    "approved_version": item["approved_version"],
                    "version_constraint": item["version_constraint"],
                    "effective_version": version,
                    "latest_known_version": None,
                    "latest_check": {
                        "status": "not_checked",
                        "checked_at": None,
                        "source": None,
                    },
                    "security_status": "unverified",
                    "status": state,
                    "status_reason": reason,
                    "evidence": evidence,
                    "release_evidence": release_state,
                    "platforms": item["platforms"],
                    "local_path_redacted": True,
                }
            )

        release_status = "unavailable"
        if sbom_inventory is not None:
            release_status = "mismatch" if release_mismatches else "matched"
        if release_status not in RELEASE_EVIDENCE_STATES:
            raise AssertionError("release evidence state escaped its closed registry")
        counts = {state: 0 for state in sorted(COMPONENT_STATES)}
        for record in records:
            counts[record["status"]] += 1
        return {
            "schema_version": COMPONENT_INVENTORY_SCHEMA_VERSION,
            "catalogue_version": COMPONENT_CATALOGUE_VERSION,
            "platform": self._platform_name,
            "network": {
                "used": False,
                "catalogue_check": "not_performed",
                "automatic_update": False,
            },
            "mutated": False,
            "class_coverage": self.catalogue["class_coverage"],
            "release_evidence": {
                "status": release_status,
                "sbom_sha256": sbom_sha256,
                "mismatched_component_ids": sorted(release_mismatches),
            },
            "summary": {
                "total": len(records),
                "required": sum(1 for row in records if row["required"]),
                "states": counts,
            },
            "components": sorted(records, key=lambda row: (row["category"], row["id"])),
        }

    def export_bytes(self, *, release_sbom: Path | str | None = None) -> bytes:
        return _canonical_json(self.read(release_sbom=release_sbom))
