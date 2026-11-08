"""Owned HTTPS worker for read APIs and the closed Asana OAuth endpoints."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .productivity_contract import ProductivityError, require, text

OAUTH_POST_ENDPOINTS = frozenset("https://app.asana.com/-/" + suffix for suffix in (
    "oauth_token", "oauth_revoke", "token_info"))
MAX_BODY = 2 * 1024 * 1024


class ProductivityHttpError(ProductivityError):
    def __init__(self, status, retry_after=None):
        self.status, self.retry_after = status, retry_after
        super().__init__("authorization_required" if status in {401, 403} else (
            "rate_limited" if status == 429 else "transport"))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_direct(value):
    url, origin = value["url"], value["origin"]
    text(url, 16384)
    parsed = urlsplit(url)
    require(parsed.scheme == "https" and "https://" + parsed.netloc == origin
            and parsed.username is None and parsed.password is None and not parsed.fragment,
            "endpoint")
    fields, token = value.get("fields"), value.get("token")
    require(fields is None or url in OAUTH_POST_ENDPOINTS, "unsupported")
    headers = {"Accept": "application/json", "User-Agent": "Provelume productivity readonly"}
    if token is not None:
        text(token, 8192)
        require(all(32 < ord(char) < 127 for char in token), "authorization_required")
        headers["Authorization"] = "Bearer " + token
    data = None
    if fields is not None:
        data = urlencode(fields).encode("ascii")
        require(len(data) <= 16384, "limit")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, headers=headers, data=data,
                      method="POST" if fields is not None else "GET")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            require(response.status == 200 and (response.headers.get_content_type()
                    == "application/json" or url == "https://app.asana.com/-/oauth_revoke"),
                    "response")
            raw = response.read(MAX_BODY + 1)
            require(len(raw) <= MAX_BODY, "limit")
            length = response.headers.get("Content-Length")
            require(length is None or (len(response.headers.get_all("Content-Length")) == 1
                    and length.isdecimal() and int(length) == len(raw)), "response")
            return {"status": 200, "body": base64.b64encode(raw).decode("ascii")}
    except HTTPError as error:
        retry = error.headers.get("Retry-After")
        return {"status": error.code, "retry_after": int(retry) if retry and retry.isdecimal()
                and len(retry) <= 8 else None}


class ProductivityHttp:
    """One request, at most 20 seconds including DNS; no retries/redirects."""

    def request(self, url, *, origin, token=None, fields=None, deadline=None):
        import time

        payload = {"url": url, "origin": origin, "token": token, "fields": fields}
        raw = json.dumps(payload).encode()
        require(len(raw) <= 32768, "limit")
        environment = {key: value for key, value in os.environ.items() if key.upper() in {
            "PATH", "HOME", "LANG", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}}
        environment["PYTHONNOUSERSITE"] = "1"
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--internal-productivity-http-worker"]
        else:
            environment["PYTHONPATH"] = str(Path(__file__).absolute().parent.parent)
            command = [sys.executable, "-m", "provelume.productivity_http"]
        timeout = min(20, deadline - time.monotonic()) if deadline is not None else 20
        require(timeout > 0, "deadline")
        with TemporaryDirectory(prefix="provelume-productivity-http-") as directory:
            source, target = Path(directory) / "request", Path(directory) / "response"
            source.write_bytes(raw)
            try:
                result = subprocess.run(command + [str(source), str(target)], env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=timeout, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                require(result.returncode == 0 and target.is_file() and not target.is_symlink()
                        and target.stat().st_size <= 3 * 1024 * 1024, "transport")
                response = json.loads(target.read_bytes())
            except (OSError, ValueError, subprocess.TimeoutExpired):
                raise ProductivityError("transport") from None
        require(response.get("worker_profile") == "productivity-http/v1", "transport")
        if response.get("refusal") is not None:
            require(response["refusal"] in {"endpoint", "unsupported", "limit", "response",
                                            "invalid", "authorization_required"}, "transport")
            raise ProductivityError(response["refusal"])
        if response.get("status") != 200:
            raise ProductivityHttpError(response.get("status"), response.get("retry_after"))
        raw = base64.b64decode(response["body"], validate=True)
        require(len(raw) <= MAX_BODY, "limit")
        return raw


def main():
    try:
        arguments = sys.argv[1:]
        if arguments[:1] == ["--internal-productivity-http-worker"]:
            arguments = arguments[1:]
        require(len(arguments) == 2)
        source, target = map(Path, arguments)
        require(not source.is_symlink() and not target.is_symlink()
                and source.stat().st_size <= 32768)
        try:
            result = request_direct(json.loads(source.read_bytes()))
        except ProductivityError as error:
            result = {"status": 0, "refusal": error.code}
        result["worker_profile"] = "productivity-http/v1"
        with target.open("xb") as stream:
            stream.write(json.dumps(result).encode())
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
