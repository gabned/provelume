"""Only local OS-vault locators cross into the owned credential helper."""

import os
from pathlib import PurePosixPath, PureWindowsPath

from .mirror_contract import require


def credential_environment(*, platform=None, environ=None):
    platform = os.name if platform is None else platform
    source = os.environ if environ is None else environ
    result = {}
    if platform == "nt":
        value = source.get("LOCALAPPDATA")
        require(
            type(value) is str
            and 0 < len(value) <= 4096
            and PureWindowsPath(value).is_absolute()
            and not PureWindowsPath(value).drive.startswith("\\\\")
            and not any(ord(char) < 32 for char in value),
            "credential_context",
        )
        result["LOCALAPPDATA"] = value
    else:
        value = source.get("DBUS_SESSION_BUS_ADDRESS")
        if value is not None:
            require(
                type(value) is str
                and 0 < len(value) <= 4096
                and value.startswith(("unix:path=", "unix:abstract="))
                and ";" not in value
                and not any(ord(char) < 32 for char in value),
                "credential_context",
            )
            result["DBUS_SESSION_BUS_ADDRESS"] = value
        value = source.get("XDG_RUNTIME_DIR")
        if value is not None:
            require(
                type(value) is str
                and 0 < len(value) <= 4096
                and PurePosixPath(value).is_absolute()
                and not any(ord(char) < 32 for char in value),
                "credential_context",
            )
            result["XDG_RUNTIME_DIR"] = value
    return result
