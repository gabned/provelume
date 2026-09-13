from __future__ import annotations

import os
import platform
import re
import sys
from importlib.resources import files
from typing import Any

from . import __version__
from .build_info import current_build_info
from .publication import current_publication

ABOUT_SCHEMA_VERSION = 1
SOURCE_REPOSITORY_URL = "https://github.com/gabned/provelume"
RELEASES_URL = f"{SOURCE_REPOSITORY_URL}/releases"
RELEASE_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
NOTICE_NAMES = ("LICENSE", "NOTICE.md", "THIRD_PARTY_NOTICES.md")
NOTICE_RESOURCES = {
    **{name: ("notices", name) for name in NOTICE_NAMES},
    "Lucide LICENSE": ("notices", "lucide-LICENSE.txt"),
}


def packaged_notice_texts() -> dict[str, str]:
    """Only the shipped, fixed notice resources; never fetch or traverse user paths."""
    result = {}
    for name, resource in NOTICE_RESOURCES.items():
        try:
            with files("provelume").joinpath(*resource).open("rb") as handle:
                raw = handle.read(256 * 1024 + 1)
            if len(raw) <= 256 * 1024:
                result[name] = raw.decode("utf-8")
        except (OSError, UnicodeError):
            continue
    return result


def public_about_links(about: dict[str, Any]) -> dict[str, str]:
    """Fixed public links; untrusted build strings cannot select a destination."""
    links = {"repository": SOURCE_REPOSITORY_URL, "releases": RELEASES_URL}
    tag = about.get("tag")
    if isinstance(tag, str) and RELEASE_TAG.fullmatch(tag):
        links["installed_release"] = f"{RELEASES_URL}/tag/{tag}"
    return links


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
        "public_links": public_about_links(build),
        "publication": current_publication(build=build),
        "credits": {
            "author": "Gabriele Falistocco",
            "developer": "Neobeta S.r.l.",
            "copyright": "Copyright 2026 Neobeta S.r.l.",
            "license": "PolyForm-Noncommercial-1.0.0",
            "notices": list(NOTICE_NAMES),
            "notice_texts": packaged_notice_texts(),
        },
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
