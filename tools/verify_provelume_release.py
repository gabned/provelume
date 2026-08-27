#!/usr/bin/env python3
"""Compatibility entry point for the canonical offline release verifier."""

import sys
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1] / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from provelume.release_bundle import VerificationError, main, verify_bundle  # noqa: E402

__all__ = ["VerificationError", "main", "verify_bundle"]


if __name__ == "__main__":
    raise SystemExit(main())
