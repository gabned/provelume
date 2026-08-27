from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCE_REPOSITORY = "gabned/provelume"
RELEASES_API = "https://api.github.com/repos/gabned/provelume/releases?per_page=30"
UPDATE_MANIFEST_NAME = "provelume-windows-update.json"
UPDATE_SCHEMA_VERSION = 1
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
ALLOWED_UPDATE_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,254}$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    """Raised when update metadata or an update artifact fails closed."""


@dataclass(frozen=True, order=True, slots=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: object) -> SemanticVersion:
        match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", str(value or ""))
        if match is None:
            raise UpdateError(f"invalid semantic version: {value!r}")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class UpdateCandidate:
    version: str
    tag: str
    channel: str
    commit: str
    release_url: str
    manifest_url: str
    installer_name: str
    installer_url: str
    installer_sha256: str
    installer_size_bytes: int
    architecture: str
    installer_type: str
    minimum_windows_build: int
    signature_status: str
    automatic_apply: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_asset_name(value: object) -> str:
    name = str(value or "")
    if SAFE_ASSET_NAME.fullmatch(name) is None or Path(name).name != name:
        raise UpdateError(f"unsafe update asset name: {name!r}")
    return name


def _validated_https_url(value: object) -> str:
    url = str(value or "")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_UPDATE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise UpdateError("update URL is not an allowed HTTPS endpoint")
    return url


class _RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        _validated_https_url(new_url)
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


class SafeHttpsClient:
    def __init__(self, *, timeout_seconds: float = 15.0):
        self.timeout_seconds = timeout_seconds
        self._opener = urllib.request.build_opener(_RestrictedRedirectHandler())

    def _open(self, url: str, *, accept: str):
        safe_url = _validated_https_url(url)
        request = urllib.request.Request(
            safe_url,
            headers={
                "Accept": accept,
                "User-Agent": "Provelume-Update-Client",
            },
            method="GET",
        )
        try:
            response = self._opener.open(request, timeout=self.timeout_seconds)
        except (OSError, urllib.error.URLError) as exc:
            raise UpdateError("update service request failed") from exc
        _validated_https_url(response.geturl())
        if getattr(response, "status", 200) != 200:
            response.close()
            raise UpdateError("update service returned a non-success response")
        return response

    @staticmethod
    def _declared_length(response, maximum: int) -> None:
        raw_length = response.headers.get("Content-Length")
        if raw_length is None:
            return
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise UpdateError("update response has an invalid content length") from exc
        if length < 0 or length > maximum:
            raise UpdateError("update response exceeds its safety limit")

    def get_json(self, url: str, *, maximum_bytes: int) -> Any:
        with self._open(url, accept="application/vnd.github+json, application/json") as response:
            self._declared_length(response, maximum_bytes)
            payload = response.read(maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise UpdateError("update JSON exceeds its safety limit")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("update service returned invalid JSON") from exc

    def download(
        self,
        url: str,
        *,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        if expected_size <= 0 or expected_size > MAX_INSTALLER_BYTES:
            raise UpdateError("installer size is outside the supported limit")
        if SHA256.fullmatch(expected_sha256) is None:
            raise UpdateError("installer SHA-256 is invalid")
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        temporary_name: str | None = None
        try:
            with self._open(url, accept="application/octet-stream") as response:
                self._declared_length(response, expected_size)
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{destination.name}.",
                    suffix=".part",
                    dir=destination.parent,
                    delete=False,
                ) as temporary:
                    temporary_name = temporary.name
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > expected_size or written > MAX_INSTALLER_BYTES:
                            raise UpdateError("installer download exceeds the declared size")
                        digest.update(chunk)
                        temporary.write(chunk)
                        if progress is not None:
                            progress(written, expected_size)
                    temporary.flush()
                    os.fsync(temporary.fileno())
            if written != expected_size:
                raise UpdateError("installer size does not match the update manifest")
            if digest.hexdigest() != expected_sha256:
                raise UpdateError("installer SHA-256 does not match the update manifest")
            os.replace(temporary_name, destination)
            temporary_name = None
            return destination
        finally:
            if temporary_name is not None:
                with suppress(OSError):
                    Path(temporary_name).unlink()


def _release_assets(value: object) -> dict[str, ReleaseAsset]:
    if not isinstance(value, list) or len(value) > 100:
        raise UpdateError("release asset inventory is invalid")
    assets: dict[str, ReleaseAsset] = {}
    for row in value:
        if not isinstance(row, dict):
            raise UpdateError("release asset inventory contains an invalid row")
        name = _safe_asset_name(row.get("name"))
        if name in assets:
            raise UpdateError(f"release contains a duplicate asset: {name}")
        try:
            size = int(row["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UpdateError(f"release asset size is invalid: {name}") from exc
        if size <= 0 or size > MAX_INSTALLER_BYTES:
            raise UpdateError(f"release asset size is outside the supported limit: {name}")
        assets[name] = ReleaseAsset(
            name=name,
            url=_validated_https_url(row.get("browser_download_url")),
            size_bytes=size,
        )
    return assets


def _windows_manifest(
    value: object,
    *,
    version: str,
    tag: str,
    channel: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UpdateError("Windows update manifest must be one JSON object")
    expected_fields = {
        "schema_version",
        "source_repository",
        "version",
        "tag",
        "commit",
        "channel",
        "artifact",
        "trust",
    }
    if set(value) != expected_fields:
        raise UpdateError("Windows update manifest fields are incomplete or unsupported")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise UpdateError("unsupported Windows update manifest schema")
    if value["source_repository"] != SOURCE_REPOSITORY:
        raise UpdateError("Windows update manifest has an unexpected source repository")
    if value["version"] != version or value["tag"] != tag or value["channel"] != channel:
        raise UpdateError("Windows update manifest identity differs from the release")
    if FULL_COMMIT.fullmatch(str(value["commit"])) is None:
        raise UpdateError("Windows update manifest commit is invalid")
    artifact = value["artifact"]
    if not isinstance(artifact, dict) or set(artifact) != {
        "name",
        "sha256",
        "size_bytes",
        "platform",
        "architecture",
        "installer_type",
        "minimum_windows_build",
        "automatic_apply",
    }:
        raise UpdateError("Windows update artifact fields are incomplete or unsupported")
    artifact["name"] = _safe_asset_name(artifact["name"])
    if SHA256.fullmatch(str(artifact["sha256"])) is None:
        raise UpdateError("Windows update artifact SHA-256 is invalid")
    try:
        artifact["size_bytes"] = int(artifact["size_bytes"])
        artifact["minimum_windows_build"] = int(artifact["minimum_windows_build"])
    except (TypeError, ValueError) as exc:
        raise UpdateError("Windows update artifact numeric fields are invalid") from exc
    if artifact["size_bytes"] <= 0 or artifact["size_bytes"] > MAX_INSTALLER_BYTES:
        raise UpdateError("Windows update artifact size is outside the supported limit")
    if artifact["platform"] != "windows" or artifact["architecture"] != "x86_64":
        raise UpdateError("Windows update artifact targets an unsupported platform")
    if artifact["installer_type"] != "inno_setup":
        raise UpdateError("Windows update installer type is unsupported")
    if artifact["minimum_windows_build"] < 19045:
        raise UpdateError("Windows update minimum build is below the supported baseline")
    if artifact["automatic_apply"] is not False:
        raise UpdateError("this preview cannot declare unattended automatic apply")
    trust = value["trust"]
    if not isinstance(trust, dict) or set(trust) != {
        "publisher_authentication",
        "platform_signature",
    }:
        raise UpdateError("Windows update trust fields are incomplete or unsupported")
    if trust["publisher_authentication"] not in {
        "not_established",
        "provider_independent_signature_verified",
    }:
        raise UpdateError("Windows update publisher authentication state is unsupported")
    if trust["platform_signature"] not in {"unsigned_preview", "authenticode_verified"}:
        raise UpdateError("Windows update platform signature state is unsupported")
    return value


def select_update_candidate(
    releases: object,
    *,
    current_version: str,
    channel: str,
    fetch_manifest: Callable[[str], Any],
) -> UpdateCandidate | None:
    current = SemanticVersion.parse(current_version)
    if channel not in {"stable", "preview"}:
        raise UpdateError("update channel must be stable or preview")
    if not isinstance(releases, list) or len(releases) > 100:
        raise UpdateError("release catalogue is invalid")

    eligible: list[tuple[SemanticVersion, dict[str, Any]]] = []
    for release in releases:
        if not isinstance(release, dict):
            raise UpdateError("release catalogue contains an invalid row")
        if release.get("draft") is True:
            continue
        prerelease = release.get("prerelease")
        if not isinstance(prerelease, bool):
            raise UpdateError("release channel marker is invalid")
        if channel == "stable" and prerelease:
            continue
        tag = str(release.get("tag_name") or "")
        if not tag.startswith("v"):
            continue
        try:
            version = SemanticVersion.parse(tag[1:])
        except UpdateError:
            continue
        if version > current:
            eligible.append((version, release))

    for version, release in sorted(eligible, key=lambda row: row[0], reverse=True):
        release_channel = "preview" if release["prerelease"] else "stable"
        tag = f"v{version}"
        assets = _release_assets(release.get("assets"))
        manifest_asset = assets.get(UPDATE_MANIFEST_NAME)
        if manifest_asset is None:
            continue
        manifest = _windows_manifest(
            fetch_manifest(manifest_asset.url),
            version=str(version),
            tag=tag,
            channel=release_channel,
        )
        artifact = manifest["artifact"]
        installer = assets.get(artifact["name"])
        if installer is None:
            raise UpdateError("Windows installer declared by the manifest is missing")
        if installer.size_bytes != artifact["size_bytes"]:
            raise UpdateError("release and manifest installer sizes differ")
        release_url = _validated_https_url(release.get("html_url"))
        return UpdateCandidate(
            version=str(version),
            tag=tag,
            channel=release_channel,
            commit=str(manifest["commit"]),
            release_url=release_url,
            manifest_url=manifest_asset.url,
            installer_name=installer.name,
            installer_url=installer.url,
            installer_sha256=str(artifact["sha256"]),
            installer_size_bytes=installer.size_bytes,
            architecture=str(artifact["architecture"]),
            installer_type=str(artifact["installer_type"]),
            minimum_windows_build=int(artifact["minimum_windows_build"]),
            signature_status=str(manifest["trust"]["platform_signature"]),
            automatic_apply=bool(artifact["automatic_apply"]),
        )
    return None


def check_for_updates(
    *,
    current_version: str,
    channel: str = "preview",
    client: SafeHttpsClient | None = None,
) -> dict[str, Any]:
    selected_client = client or SafeHttpsClient()
    releases = selected_client.get_json(RELEASES_API, maximum_bytes=MAX_CATALOG_BYTES)
    candidate = select_update_candidate(
        releases,
        current_version=current_version,
        channel=channel,
        fetch_manifest=lambda url: selected_client.get_json(
            url,
            maximum_bytes=MAX_MANIFEST_BYTES,
        ),
    )
    return {
        "schema_version": UPDATE_SCHEMA_VERSION,
        "status": "update_available" if candidate is not None else "up_to_date",
        "current_version": current_version,
        "channel": channel,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "network_used": True,
        "endpoint_origin": "https://api.github.com",
        "transport": "github_releases",
        "instance_content_sent": False,
        "trust_boundary": (
            "Downloaded hashes provide consistency evidence; publisher authentication and "
            "Windows code signing are not established by the unsigned preview."
        ),
        "candidate": candidate.as_dict() if candidate is not None else None,
    }


def download_update(
    candidate: UpdateCandidate,
    destination_directory: Path,
    *,
    client: SafeHttpsClient | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    name = _safe_asset_name(candidate.installer_name)
    target = destination_directory.expanduser().resolve() / name
    selected_client = client or SafeHttpsClient(timeout_seconds=60.0)
    return selected_client.download(
        candidate.installer_url,
        destination=target,
        expected_size=candidate.installer_size_bytes,
        expected_sha256=candidate.installer_sha256,
        progress=progress,
    )


def candidates_from_rows(rows: Iterable[dict[str, Any]]) -> list[UpdateCandidate]:
    """Small test/support helper for reconstructing serialized candidates."""

    return [UpdateCandidate(**row) for row in rows]
