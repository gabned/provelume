"""Owned GitHub HTTPS worker, closed routes, no redirects, no implicit retries."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .mirror_contract import MirrorError, parse, raw, require
from .mirror_github_contract import API_VERSION, PROBE
from .productivity_http import _NoRedirect

MAX_BODY = 2 * 1024 * 1024
ROUTE = re.compile(
    r"/repos/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}(?:/git/blobs)?\Z"
)


def admitted_request(value):
    require(type(value) is dict and set(value) == {"route", "token", "probe"}, "github_endpoint")
    route, token, probe = value["route"], value["token"], value["probe"]
    require(
        type(token) is str
        and 0 < len(token) <= 8192
        and all(32 < ord(char) < 127 for char in token),
        "authorization_required",
    )
    require(
        type(probe) is bool
        and type(route) is str
        and (
            ROUTE.fullmatch(route)
            or route == "/user"
            or re.fullmatch(r"/installation/repositories\?per_page=100&page=[1-5]", route)
        ),
        "github_endpoint",
    )
    require(probe == route.endswith("/git/blobs"), "github_endpoint")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Provelume mirror",
        "X-GitHub-Api-Version": API_VERSION,
        "Authorization": "Bearer " + token,
    }
    data = None
    if probe:
        data = raw({"content": base64.b64encode(PROBE).decode(), "encoding": "base64"})
        headers["Content-Type"] = "application/json"
    return Request(
        "https://api.github.com" + route,
        headers=headers,
        data=data,
        method="POST" if probe else "GET",
    )


def request_direct(value):
    request = admitted_request(value)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            require(
                response.status == (201 if value["probe"] else 200)
                and response.headers.get_content_type() == "application/json",
                "github_response",
            )
            body = response.read(MAX_BODY + 1)
            require(len(body) <= MAX_BODY, "limit")
            lengths = response.headers.get_all("Content-Length")
            require(
                lengths is None
                or (len(lengths) == 1 and lengths[0].isdecimal() and int(lengths[0]) == len(body)),
                "github_response",
            )
            return {"status": response.status, "body": parse(body)}
    except HTTPError as error:
        # Never copy a remote body, URL, token or exception to diagnostic output.
        return {"status": error.code}


class GitHubHttp:
    def request(self, route, *, token, probe=False, deadline=None):
        payload = {"route": route, "token": token, "probe": probe}
        admitted_request(payload)  # Refuse before starting any process/network.
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "PATH",
                "HOME",
                "LANG",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "TMPDIR",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
                "REQUESTS_CA_BUNDLE",
                "CURL_CA_BUNDLE",
            }
        }
        environment["PYTHONNOUSERSITE"] = "1"
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--internal-github-http-worker"]
        else:
            environment["PYTHONPATH"] = str(Path(__file__).absolute().parent.parent)
            command = [sys.executable, "-m", "provelume.mirror_github_http"]
        timeout = min(20, deadline - time.monotonic()) if deadline is not None else 20
        require(timeout > 0, "deadline")
        # Secret request is a dedicated pipe, never an argv/env/temp-file value.
        with TemporaryDirectory(prefix="provelume-github-http-") as directory:
            target = Path(directory) / "response.json"
            try:
                result = subprocess.run(
                    command + [str(target)],
                    input=raw(payload),
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                require(
                    result.returncode == 0
                    and target.is_file()
                    and not target.is_symlink()
                    and target.stat().st_size <= MAX_BODY,
                    "github_transport",
                )
                response = parse(target.read_bytes())
            except (OSError, ValueError, subprocess.SubprocessError):
                raise MirrorError("github_transport") from None
        require(response.get("profile") == "github-http/2022-11-28", "github_transport")
        require(
            response.get("status") == (201 if probe else 200),
            "authorization_required"
            if response.get("status") in {401, 403, 404}
            else "rate_limited"
            if response.get("status") == 429
            else "github_transport",
        )
        require(type(response.get("body")) is dict, "github_response")
        return response["body"]


def main():
    try:
        args = sys.argv[1:]
        if args[:1] == ["--internal-github-http-worker"]:
            args = args[1:]
        require(len(args) == 1)
        payload = sys.stdin.buffer.read(16385)
        require(len(payload) <= 16384, "limit")
        result = request_direct(parse(payload))
        result["profile"] = "github-http/2022-11-28"
        with Path(args[0]).open("xb") as output:
            output.write(raw(result))
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
