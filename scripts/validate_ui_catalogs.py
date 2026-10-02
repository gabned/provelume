"""Offline catalog qualification; completeness is never linguistic approval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from provelume.catalog_registry import validate_catalogs  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structural-only", action="store_true",
                        help="Inspect structure while retaining visible completeness gaps")
    arguments = parser.parse_args()
    result = validate_catalogs(require_complete=not arguments.structural_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["automatic_contract"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
