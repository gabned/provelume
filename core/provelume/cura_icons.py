"""Verified, package-owned Lucide sources and decorative Cura rendering (ADR 0028)."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any
from zipfile import Path as ZipPath

from markupsafe import Markup

COMPONENT_ID = "ui.lucide"
BOM_REF = "provelume:ui.lucide"
RESOURCE_PATH = "static/icons/lucide"
LICENSE_RESOURCE_PATH = "notices/lucide-LICENSE.txt"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_FILE_BYTES = 16 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_ICONS = 64
_NAME = re.compile(r"[a-z][a-z-]{0,40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_BLOB = re.compile(r"[0-9a-f]{40}\Z")
_NAMESPACE = "{http://www.w3.org/2000/svg}"
_ROOT_ATTRIBUTES = {
    "width": "24",
    "height": "24",
    "viewBox": "0 0 24 24",
    "fill": "none",
    "stroke": "currentColor",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
}
_GEOMETRY = {
    "path": {"d"},
    "circle": {"cx", "cy", "r"},
    "polyline": {"points"},
    "rect": {"x", "y", "width", "height", "rx", "ry"},
    "line": {"x1", "x2", "y1", "y2"},
}
_NUMBER_DATA = re.compile(r"[-+0-9.,\sEe]+\Z")
_PATH_DATA = re.compile(r"[-+0-9.,\sMmLlHhVvCcSsQqTtAaZzEe]+\Z")


class IconAssetError(ValueError):
    """Closed error without machine-local resource paths."""

    def __init__(self, code: str):
        if code not in {"packaged_asset_missing", "packaged_asset_invalid"}:
            raise ValueError("unsupported icon asset error")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VerifiedIconSubset:
    manifest: dict[str, Any]
    manifest_sha256: str
    svgs: dict[str, bytes]


def _require(condition: bool) -> None:
    if not condition:
        raise IconAssetError("packaged_asset_invalid")


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _reject_link(resource: Traversable) -> None:
    if isinstance(resource, Path):
        _require(not resource.is_symlink() and not resource.is_junction())
    elif isinstance(resource, ZipPath) and resource.at:
        try:
            mode = resource.root.getinfo(resource.at).external_attr >> 16
        except KeyError:
            return  # An implicit archive directory has no separate entry.
        _require(not stat.S_ISLNK(mode))


def _read(resource: Traversable, limit: int) -> bytes:
    _reject_link(resource)
    if not resource.is_file():
        raise IconAssetError("packaged_asset_missing")
    with resource.open("rb") as stream:
        raw = stream.read(limit + 1)
    _require(len(raw) <= limit)
    return raw


def _package_resource(path: str) -> Traversable:
    resource = files("provelume")
    _reject_link(resource)
    for segment in path.split("/"):
        resource = resource.joinpath(segment)
        _reject_link(resource)
    return resource


def _resource_root() -> Traversable:
    return _package_resource(RESOURCE_PATH)


def _license_resource() -> Traversable:
    return _package_resource(LICENSE_RESOURCE_PATH)


def _catalogue_digest() -> str:
    raw = _read(files("provelume").joinpath("component_catalogue.json"), 512 * 1024)
    catalogue = json.loads(raw)
    selected = [row for row in catalogue["components"] if row.get("id") == COMPONENT_ID]
    _require(len(selected) == 1)
    digest = selected[0]["expected_sha256"]
    _require(isinstance(digest, str) and _DIGEST.fullmatch(digest) is not None)
    return digest


def _validate_svg(raw: bytes) -> None:
    # Reject declarations/entities before XML parsing; there is no resolver or active markup.
    _require(raw.startswith(b"<svg") and raw.rstrip().endswith(b"</svg>") and b"\0" not in raw)
    raw.decode("utf-8")
    _require(not re.search(rb"<\s*[!?]|&", raw))
    node = ET.fromstring(raw)
    _require(node.tag == _NAMESPACE + "svg" and node.attrib == _ROOT_ATTRIBUTES)
    _require(not (node.text or "").strip() and 0 < len(node) <= 32)
    for child in node:
        tag = child.tag.removeprefix(_NAMESPACE)
        _require(child.tag == _NAMESPACE + tag and tag in _GEOMETRY)
        _require(bool(child.attrib) and set(child.attrib) <= _GEOMETRY[tag] and not len(child))
        _require(not (child.text or "").strip() and not (child.tail or "").strip())
        for key, value in child.attrib.items():
            pattern = _PATH_DATA if key == "d" else _NUMBER_DATA
            _require(pattern.fullmatch(value) is not None)


def _verify_entry(
    resource: Traversable,
    entry: Any,
    expected_file: str,
    expected_source: str,
) -> bytes:
    _require(isinstance(entry, dict))
    keys = {"file", "source_path", "bytes", "sha256", "git_blob"}
    _require(set(entry) == keys or set(entry) == keys | {"name"})
    _require(entry["file"] == expected_file and entry["source_path"] == expected_source)
    _require(type(entry["bytes"]) is int and 0 < entry["bytes"] <= MAX_FILE_BYTES)
    _require(isinstance(entry["sha256"], str) and _DIGEST.fullmatch(entry["sha256"]) is not None)
    _require(isinstance(entry["git_blob"], str) and _BLOB.fullmatch(entry["git_blob"]) is not None)
    raw = _read(resource, MAX_FILE_BYTES)
    _require(len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"])
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    _require(blob == entry["git_blob"])
    return raw


def verify_icon_subset(expected_sha256: str | None = None) -> VerifiedIconSubset:
    """Verify the single closed package manifest and every source; never install or fetch."""
    try:
        digest = expected_sha256 if expected_sha256 is not None else _catalogue_digest()
        _require(isinstance(digest, str) and _DIGEST.fullmatch(digest) is not None)
        root = _resource_root()
        raw = _read(root.joinpath("subset.json"), MAX_MANIFEST_BYTES)
        _require(hashlib.sha256(raw).hexdigest() == digest)
        manifest = json.loads(raw)
        _require(
            isinstance(manifest, dict)
            and set(manifest)
            == {
                "schema_version",
                "component_id",
                "name",
                "version",
                "source",
                "license_expression",
                "license",
                "icons",
                "update_route",
                "license_reference",
            }
        )
        _require(_canonical(manifest) == raw and manifest["schema_version"] == 1)
        _require(
            manifest["component_id"] == COMPONENT_ID
            and manifest["name"] == "Lucide SVG subset"
            and manifest["license_expression"] == "ISC AND MIT"
            and manifest["update_route"] == "reviewed_provelume_release"
        )
        source = manifest["source"]
        _require(isinstance(source, dict) and set(source) == {"repository", "tag", "commit"})
        _require(source["repository"] == "https://github.com/lucide-icons/lucide")
        _require(
            isinstance(source["commit"], str) and _BLOB.fullmatch(source["commit"]) is not None
        )
        _require(
            isinstance(manifest["version"], str)
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest["version"]) is not None
            and source["tag"] == manifest["version"]
        )
        icons = manifest["icons"]
        _require(isinstance(icons, list) and 0 < len(icons) <= MAX_ICONS)
        names = [entry.get("name") for entry in icons if isinstance(entry, dict)]
        _require(
            len(names) == len(icons)
            and all(isinstance(name, str) and _NAME.fullmatch(name) for name in names)
        )
        _require(names == sorted(set(names)))
        expected_files = {"subset.json", *(name + ".svg" for name in names)}
        entries = []
        for resource in root.iterdir():
            _reject_link(resource)
            entries.append(resource)
            _require(len(entries) <= MAX_ICONS + 1 and resource.is_file())
        observed_files = {resource.name for resource in entries}
        if expected_files - observed_files:
            raise IconAssetError("packaged_asset_missing")
        _require(observed_files == expected_files)
        license_bytes = _verify_entry(
            _license_resource(),
            manifest["license"],
            LICENSE_RESOURCE_PATH,
            "LICENSE",
        )
        _require(b"ISC License" in license_bytes and b"The MIT License (MIT)" in license_bytes)
        reference = manifest["license_reference"]
        base = source["repository"] + "/blob/" + source["commit"] + "/"
        _require(
            isinstance(reference, dict)
            and set(reference)
            == {
                "url",
                "triangle_alert_alias",
                "alias_metadata_url",
                "alias_metadata_sha256",
            }
        )
        _require(
            reference["url"] == base + "LICENSE"
            and reference["triangle_alert_alias"] == "alert-triangle"
            and reference["alias_metadata_url"] == base + "icons/triangle-alert.json"
            and _DIGEST.fullmatch(reference["alias_metadata_sha256"]) is not None
        )
        svgs = {}
        total = len(raw) + len(license_bytes)
        for entry in icons:
            name = entry["name"]
            data = _verify_entry(
                root.joinpath(name + ".svg"),
                entry,
                name + ".svg",
                "icons/" + name + ".svg",
            )
            _validate_svg(data)
            svgs[name] = data
            total += len(data)
            _require(total <= MAX_TOTAL_BYTES)
        return VerifiedIconSubset(manifest, digest, svgs)
    except IconAssetError:
        raise
    except FileNotFoundError as exc:
        raise IconAssetError("packaged_asset_missing") from exc
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ET.ParseError) as exc:
        raise IconAssetError("packaged_asset_invalid") from exc


def render_icon(name: str) -> Markup:
    """Return decorative markup only; the caller must provide its visible localized label."""
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError("unknown Cura icon")
    return icon_renderer()(name)


def icon_renderer() -> Callable[[str], Markup]:
    """Verify once for one response; never reuse verification across requests."""
    subset = verify_icon_subset()
    icons = {
        name: Markup(
            raw.decode("utf-8").replace(
                "<svg",
                '<svg class="cura-icon" aria-hidden="true" focusable="false"',
                1,
            )
        )
        for name, raw in subset.svgs.items()
    }

    def render(name: str) -> Markup:
        if not isinstance(name, str) or name not in icons:
            raise ValueError("unknown Cura icon")
        return icons[name]

    return render


def asset_sbom_component(expected_sha256: str | None = None) -> dict[str, Any]:
    """Build one CycloneDX component from the actual verified installed resources."""
    subset = verify_icon_subset(expected_sha256)
    manifest = subset.manifest
    origin = manifest["source"]
    properties = {
        "provelume:component-id": COMPONENT_ID,
        "provelume:source-commit": origin["commit"],
        "provelume:subset-sha256": subset.manifest_sha256,
        "provelume:subset-resource": RESOURCE_PATH + "/subset.json",
        "provelume:license-sha256": manifest["license"]["sha256"],
        "provelume:license-resource": manifest["license"]["file"],
    }
    properties.update(
        {"provelume:asset-sha256:" + row["file"]: row["sha256"] for row in manifest["icons"]}
    )
    return {
        "type": "library",
        "bom-ref": BOM_REF,
        "name": manifest["name"],
        "version": manifest["version"],
        "description": "Vendored unchanged Lucide SVG sources; hashes bind the declared subset.",
        "licenses": [{"expression": manifest["license_expression"]}],
        "hashes": [{"alg": "SHA-256", "content": subset.manifest_sha256}],
        "externalReferences": [
            {"type": "vcs", "url": origin["repository"] + "/tree/" + origin["commit"]},
            {
                "type": "distribution",
                "url": origin["repository"] + "/releases/tag/" + origin["tag"],
            },
            {"type": "license", "url": manifest["license_reference"]["url"]},
        ],
        "properties": [{"name": key, "value": value} for key, value in sorted(properties.items())],
    }


def is_asset_sbom_component(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    properties = row.get("properties")
    return (
        row.get("bom-ref") == BOM_REF
        or row.get("name") == "Lucide SVG subset"
        or any(
            isinstance(item, dict)
            and item.get("name") == "provelume:component-id"
            and item.get("value") == COMPONENT_ID
            for item in (properties if isinstance(properties, list) else [])
        )
    )


def asset_sbom_matches(rows: list[Any], expected_sha256: str) -> bool:
    selected = [row for row in rows if is_asset_sbom_component(row)]
    if len(selected) != 1:
        return False
    try:
        return selected[0] == asset_sbom_component(expected_sha256)
    except IconAssetError:
        return False
