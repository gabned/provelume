"""Add verified installed asset provenance before the release SBOM fingerprint step."""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import os
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

from provelume.cura_icons import (
    BOM_REF,
    RESOURCE_PATH,
    asset_sbom_component,
    is_asset_sbom_component,
    verify_icon_subset,
)

MAX_SBOM_BYTES = 8 * 1024 * 1024
MAX_COMPONENTS = 10_000


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def assert_installed_resources() -> str:
    """Reject checkout/editable fallback: release augmentation reads the installed wheel."""
    distribution = importlib.metadata.distribution("provelume")
    root = files("provelume")
    _require(isinstance(root, Path), "installed filesystem package resources are required")
    _require(
        root.resolve() == Path(distribution.locate_file("provelume")).resolve(),
        "imported resources differ from the installed distribution",
    )
    direct = distribution.read_text("direct_url.json")
    if direct:
        _require(
            not json.loads(direct).get("dir_info", {}).get("editable"),
            "editable source is not an installed release artifact",
        )
    members = {str(item).replace("\\", "/") for item in distribution.files or ()}
    subset = verify_icon_subset()
    expected = {
        "provelume/" + RESOURCE_PATH + "/" + name
        for name in ("subset.json", "LICENSE", *(item["file"] for item in subset.manifest["icons"]))
    }
    _require(expected <= members, "installed distribution RECORD omits declared icon resources")
    return distribution.version


def augment_sbom(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic, idempotent augmentation; never overwrite conflicting asset provenance."""
    _require(
        isinstance(payload, dict)
        and payload.get("bomFormat") == "CycloneDX"
        and payload.get("specVersion") == "1.6",
        "CycloneDX 1.6 JSON is required",
    )
    result = copy.deepcopy(payload)
    components = result.get("components")
    _require(
        isinstance(components, list)
        and len(components) < MAX_COMPONENTS
        and all(isinstance(row, dict) for row in components),
        "invalid component inventory",
    )
    metadata = result.get("metadata")
    application = metadata.get("component") if isinstance(metadata, dict) else None
    _require(
        isinstance(application, dict)
        and application.get("type") == "application"
        and str(application.get("name", "")).casefold() == "provelume",
        "the SBOM application must identify Provelume",
    )
    application_ref = application.get("bom-ref")
    _require(
        isinstance(application_ref, str) and bool(application_ref) and application_ref != BOM_REF,
        "the application needs an unambiguous bom-ref",
    )
    asset = asset_sbom_component()
    selected = [row for row in components if is_asset_sbom_component(row)]
    _require(not selected or selected == [asset], "conflicting or duplicate Lucide provenance")
    if not selected:
        components.append(asset)
    references = [row["bom-ref"] for row in components if "bom-ref" in row]
    _require(
        all(isinstance(ref, str) and ref for ref in references)
        and len(references) == len(set(references))
        and application_ref not in references,
        "duplicate or invalid component bom-ref",
    )
    components.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))
    dependencies = result.setdefault("dependencies", [])
    _require(
        isinstance(dependencies, list)
        and len(dependencies) <= MAX_COMPONENTS
        and all(
            isinstance(row, dict)
            and isinstance(row.get("ref"), str)
            and isinstance(row.get("dependsOn", []), list)
            and all(isinstance(ref, str) for ref in row.get("dependsOn", []))
            for row in dependencies
        ),
        "invalid dependency inventory",
    )
    dependency_refs = [row["ref"] for row in dependencies]
    _require(len(dependency_refs) == len(set(dependency_refs)), "duplicate dependency reference")
    roots = [row for row in dependencies if row["ref"] == application_ref]
    if roots:
        roots[0]["dependsOn"] = sorted(set(roots[0].get("dependsOn", [])) | {BOM_REF})
    else:
        dependencies.append({"ref": application_ref, "dependsOn": [BOM_REF]})
    if BOM_REF not in dependency_refs:
        dependencies.append({"ref": BOM_REF, "dependsOn": []})
    else:
        _require(
            next(row for row in dependencies if row["ref"] == BOM_REF)
            == {"ref": BOM_REF, "dependsOn": []},
            "conflicting Lucide dependency relationship",
        )
    dependencies.sort(key=lambda row: row["ref"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbom", type=Path, required=True)
    args = parser.parse_args()
    installed_version = assert_installed_resources()
    path = args.sbom
    _require(path.is_file() and not path.is_symlink(), "SBOM must be a regular local file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SBOM_BYTES + 1)
    _require(len(raw) <= MAX_SBOM_BYTES, "SBOM exceeds its byte limit")
    payload = json.loads(raw)
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    application = metadata.get("component") if isinstance(metadata, dict) else None
    _require(
        isinstance(application, dict) and application.get("version") == installed_version,
        "SBOM application version differs from the installed distribution",
    )
    result = augment_sbom(payload)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    _require(len(encoded) <= MAX_SBOM_BYTES, "augmented SBOM exceeds its byte limit")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".asset-sbom-", delete=False
        ) as out:
            temporary = Path(out.name)
            out.write(encoded)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
