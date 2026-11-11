"""Bounded Gitea-only HTTPS GET worker with an explicitly selected CA."""

import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, Request, build_opener

from .mirror_contract import parse, raw, require
from .mirror_gitea_contract import endpoint, tls_context, validate_ca
from .mirror_github_http import GitHubHttp
from .productivity_http import _NoRedirect

MAX_BODY = 2 * 1024 * 1024


def admitted_request(value):
    require(
        type(value) is dict
        and set(value) == {"route", "token", "probe", "endpoint", "ca_pem"}
        and value["probe"] is False,
        "gitea_endpoint",
    )
    endpoint(value["endpoint"])
    validate_ca(value["ca_pem"])
    route, token = value["route"], value["token"]
    require(
        type(route) is str
        and (
            route in {"/user", "/token", "/version"}
            or re.fullmatch(
                r"/repos/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/"
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}",
                route,
            )
        ),
        "gitea_endpoint",
    )
    require(
        type(token) is str
        and 0 < len(token) <= 8192
        and all(32 < ord(char) < 127 for char in token),
        "authorization_required",
    )
    return Request(
        value["endpoint"] + "/api/v1" + route,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "Provelume Gitea mirror",
            "Authorization": "token " + token,
        },
    )


def request_direct(value):
    request = admitted_request(value)
    try:
        with build_opener(_NoRedirect(), HTTPSHandler(context=tls_context(value["ca_pem"]))).open(
            request, timeout=15
        ) as response:
            require(
                response.status == 200
                and response.headers.get_content_type() == "application/json",
                "gitea_response",
            )
            body = response.read(MAX_BODY + 1)
            lengths = response.headers.get_all("Content-Length")
            require(
                len(body) <= MAX_BODY
                and (
                    lengths is None
                    or (
                        len(lengths) == 1
                        and lengths[0].isdecimal()
                        and int(lengths[0]) == len(body)
                    )
                ),
                "limit",
            )
            return {"status": 200, "body": parse(body)}
    except HTTPError as error:
        return {"status": error.code}


class GiteaHttp(GitHubHttp):
    provider = "gitea"
    profile = "gitea-http/28.3.0/v1"
    worker_module = "provelume.mirror_gitea_http"
    worker_flag = "--internal-gitea-http-worker"
    admit = staticmethod(admitted_request)

    def request(self, route, *, token, endpoint, ca_pem, deadline=None):
        return self.perform(
            {
                "route": route,
                "token": token,
                "probe": False,
                "endpoint": endpoint,
                "ca_pem": ca_pem,
            },
            deadline=deadline,
            expected_status=200,
        )


def main():
    try:
        args = sys.argv[1:]
        if args[:1] == ["--internal-gitea-http-worker"]:
            args = args[1:]
        require(len(args) == 1)
        payload = sys.stdin.buffer.read(16385)
        require(len(payload) <= 16384, "limit")
        result = request_direct(parse(payload))
        result["profile"] = "gitea-http/28.3.0/v1"
        with Path(args[0]).open("xb") as output:
            output.write(raw(result))
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
