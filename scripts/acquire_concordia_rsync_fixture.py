"""Acquire the pinned public Windows qualification input; never install the product."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.request import urlopen


def acquire(output):
    manifest = (
        Path(__file__).absolute().parents[1] / "core/provelume/mirror_rsync_windows_inputs.json"
    )
    inputs = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        inputs.get("repository") != "git-for-windows/git-sdk-64"
        or not re.fullmatch(r"[0-9a-f]{40}", inputs.get("commit", ""))
        or type(inputs.get("entries")) is not list
        or len(inputs["entries"]) != 11
    ):
        raise ValueError("closed public fixture source required")
    names = set()
    for row in inputs["entries"]:
        if (
            type(row) is not dict
            or set(row) != {"name", "bytes", "sha256", "git_blob"}
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.(?:exe|dll)", row["name"])
            or row["name"] in names
            or type(row["bytes"]) is not int
            or not 0 < row["bytes"] <= 16 * 1024 * 1024
            or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            or not re.fullmatch(r"[0-9a-f]{40}", row["git_blob"])
        ):
            raise ValueError("closed bounded fixture entry required")
        names.add(row["name"])
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("fresh fixture directory required")
    output.mkdir(parents=True, mode=0o700)
    deadline = time.monotonic() + 300
    records = []
    for row in inputs["entries"]:
        url = (
            "https://raw.githubusercontent.com/"
            + inputs["repository"]
            + "/"
            + inputs["commit"]
            + "/usr/bin/"
            + row["name"]
        )
        # Inherit the environment's proxy and CA policy; no authentication or retry.
        with urlopen(url, timeout=15) as response:
            if response.url != url:
                raise ValueError("unapproved fixture redirect")
            data = bytearray()
            while chunk := response.read(1024 * 1024):
                data.extend(chunk)
                if len(data) > row["bytes"] or time.monotonic() >= deadline:
                    raise ValueError("fixture acquisition limit")
        if (
            len(data) != row["bytes"]
            or hashlib.sha256(data).hexdigest() != row["sha256"]
            or hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            != row["git_blob"]
        ):
            raise ValueError("fixture integrity")
        with (output / row["name"]).open("xb") as stream:
            stream.write(data)
        records.append({"name": row["name"], "bytes": len(data), "sha256": row["sha256"]})
    return {
        "schema": inputs["schema"],
        "repository": inputs["repository"],
        "commit": inputs["commit"],
        "source_verification": inputs["source_verification"],
        "files": records,
        "application_install": False,
        "native_windows_execution": "NOT_RUN",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(acquire(arguments.output.absolute()), sort_keys=True))
