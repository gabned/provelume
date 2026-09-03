from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .component_inventory import ComponentInventory, ComponentInventoryError


def add_component_inventory_commands(subparsers: Any) -> None:
    inventory = subparsers.add_parser(
        "component-inventory",
        help="Inspect installed and declared release components without network access",
    )
    inventory.add_argument(
        "--release-sbom",
        type=Path,
        help="optional local CycloneDX release SBOM to reconcile read-only",
    )


def handle_component_inventory_command(args: argparse.Namespace) -> int | None:
    if args.command != "component-inventory":
        return None
    try:
        result = ComponentInventory().read(release_sbom=args.release_sbom)
    except ComponentInventoryError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["release_evidence"]["status"] != "mismatch" else 3
