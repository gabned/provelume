"""Owned bounded GitLab.com v4 read worker; never a general HTTP client."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .mirror_contract import parse, raw, require
from .mirror_github_http import GitHubHttp
from .productivity_http import _NoRedirect

MAX_BODY = 2 * 1024 * 1024


def admitted_request(value):
    require(
        type(value) is dict
        and set(value) == {"route", "token", "probe"}
        and value["probe"] is False,
        "gitlab_endpoint",
    )
    route, token = value["route"], value["token"]
    require(
        type(route) is str
        and (
            route in {"/user", "/personal_access_tokens/self", "/version"}
            or re.fullmatch(r"/projects/[1-9][0-9]{0,18}", route)
        ),
        "gitlab_endpoint",
    )
    require(
        type(token) is str
        and 0 < len(token) <= 8192
        and all(32 < ord(char) < 127 for char in token),
        "authorization_required",
    )
    return Request(
        "https://gitlab.com/api/v4" + route,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "Provelume GitLab mirror",
            "PRIVATE-TOKEN": token,
        },
    )


def request_direct(value):
    request = admitted_request(value)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            require(
                response.status == 200
                and response.headers.get_content_type() == "application/json",
                "gitlab_response",
            )
            data = response.read(MAX_BODY + 1)
            lengths = response.headers.get_all("Content-Length")
            require(
                len(data) <= MAX_BODY
                and (
                    lengths is None
                    or (
                        len(lengths) == 1
                        and lengths[0].isdecimal()
                        and int(lengths[0]) == len(data)
                    )
                ),
                "limit",
            )
            return {"status": 200, "body": parse(data)}
    except HTTPError as error:
        return {"status": error.code}


class GitLabHttp(GitHubHttp):
    # Only the bounded, pipe-based process mechanism is reused. Admission,
    # origin, header, routes and capability interpretation remain independent.
    profile = "gitlab-http/v4"
    worker_module = "provelume.mirror_gitlab_http"
    worker_flag = "--internal-gitlab-http-worker"
    admit = staticmethod(admitted_request)


def main():
    try:
        args = sys.argv[1:]
        if args[:1] == ["--internal-gitlab-http-worker"]:
            args = args[1:]
        require(len(args) == 1)
        payload = sys.stdin.buffer.read(16385)
        require(len(payload) <= 16384, "limit")
        result = request_direct(parse(payload))
        result["profile"] = "gitlab-http/v4"
        with Path(args[0]).open("xb") as output:
            output.write(raw(result))
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
