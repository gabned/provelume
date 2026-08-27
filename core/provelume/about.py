from __future__ import annotations

import os
import platform
import sys
from typing import Any

from . import __version__
from .build_info import current_build_info

ABOUT_SCHEMA_VERSION = 1


def packaging_mode() -> str:
    if os.name == "nt" and bool(getattr(sys, "frozen", False)):
        return "windows_installer"
    return "python_package"


def current_about() -> dict[str, Any]:
    """Return local product identity without performing a network request."""

    build = current_build_info()
    return {
        "schema_version": ABOUT_SCHEMA_VERSION,
        "product": "Provelume",
        "version": __version__,
        "channel": build.get("channel") or "unknown",
        "source_repository": build.get("source_repository"),
        "tag": build.get("tag"),
        "commit": build.get("commit"),
        "official_build_metadata": bool(build.get("official")),
        "build_identity_status": build.get("identity_status"),
        "runtime": {
            "packaging": packaging_mode(),
            "platform": platform.system().casefold() or "unknown",
            "architecture": platform.machine().casefold() or "unknown",
            "python": platform.python_version(),
        },
        "updates": {
            "manual_check_available": True,
            "check_on_start_default": False,
            "automatic_apply": False,
            "initial_transport": "github_releases",
            "network_required_for_check": True,
            "instance_content_sent": False,
            "publisher_authentication": "not_established",
            "platform_signature": "not_verified",
        },
    }
