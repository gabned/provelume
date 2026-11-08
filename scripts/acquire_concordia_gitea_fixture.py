"""Acquire the pinned public Gitea server fixture; never an application install."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).absolute().parents[1] / "core"))
from provelume.mirror_gitea_server_qualification import INPUTS  # noqa: E402


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if not (
            parsed.scheme == "https"
            and parsed.hostname == "release-assets.githubusercontent.com"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        ):
            raise ValueError("unapproved fixture redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def acquire(output):
    expected = INPUTS.get(sys.platform)
    if expected is None or output.exists() or output.is_symlink():
        raise ValueError("fresh supported fixture destination required")
    name = "gitea-28.3.0-" + ("windows-amd64.exe" if os.name == "nt" else "linux-amd64")
    url = "https://github.com/go-gitea/gitea/releases/download/v28.3.0/" + name
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name(output.name + ".part")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
    digest, count, deadline = hashlib.sha256(), 0, time.monotonic() + 300
    # No authentication, cookies, retry or candidate-selected URL.
    with opener.open(url, timeout=15) as response, stage.open("xb") as stream:
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > expected["bytes"] or time.monotonic() >= deadline:
                raise ValueError("fixture acquisition limit")
            digest.update(chunk)
            stream.write(chunk)
    if count != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError("fixture integrity")
    stage.rename(output)
    if os.name != "nt":
        output.chmod(0o700)
    return {"url": url, "bytes": count, "sha256": digest.hexdigest(),
            "upstream_signature": "NOT_VERIFIED", "application_component": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(acquire(arguments.output.absolute()), sort_keys=True))
