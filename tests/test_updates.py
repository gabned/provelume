from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from provelume.updates import (
    SafeHttpsClient,
    UpdateCandidate,
    UpdateError,
    download_update,
    select_update_candidate,
)


def _manifest(version: str, *, channel: str = "preview", size: int = 42) -> dict:
    return {
        "schema_version": 1,
        "source_repository": "gabned/provelume",
        "version": version,
        "tag": f"v{version}",
        "commit": "a" * 40,
        "channel": channel,
        "artifact": {
            "name": f"Provelume-Setup-{version}-x64.exe",
            "sha256": "b" * 64,
            "size_bytes": size,
            "platform": "windows",
            "architecture": "x86_64",
            "installer_type": "inno_setup",
            "minimum_windows_build": 19045,
            "automatic_apply": False,
        },
        "trust": {
            "publisher_authentication": "not_established",
            "platform_signature": "unsigned_preview",
        },
    }


def _release(version: str, *, prerelease: bool = True, size: int = 42) -> dict:
    return {
        "draft": False,
        "prerelease": prerelease,
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/gabned/provelume/releases/tag/v{version}",
        "assets": [
            {
                "name": "provelume-windows-update.json",
                "size": 500,
                "browser_download_url": (
                    f"https://github.com/gabned/provelume/releases/download/v{version}/"
                    "provelume-windows-update.json"
                ),
            },
            {
                "name": f"Provelume-Setup-{version}-x64.exe",
                "size": size,
                "browser_download_url": (
                    f"https://github.com/gabned/provelume/releases/download/v{version}/"
                    f"Provelume-Setup-{version}-x64.exe"
                ),
            },
        ],
    }


def test_preview_channel_selects_highest_newer_windows_release() -> None:
    manifests = {
        "v0.4.0": _manifest("0.4.0"),
        "v0.5.0": _manifest("0.5.0"),
    }

    def fetch(url: str):
        tag = next(tag for tag in manifests if f"/{tag}/" in url)
        return manifests[tag]

    candidate = select_update_candidate(
        [_release("0.4.0"), _release("0.5.0")],
        current_version="0.3.0",
        channel="preview",
        fetch_manifest=fetch,
    )

    assert candidate is not None
    assert candidate.version == "0.5.0"
    assert candidate.installer_name == "Provelume-Setup-0.5.0-x64.exe"
    assert candidate.signature_status == "unsigned_preview"
    assert candidate.automatic_apply is False


def test_stable_channel_ignores_preview_and_never_downgrades() -> None:
    stable = _release("1.0.0", prerelease=False)
    candidate = select_update_candidate(
        [_release("1.1.0", prerelease=True), stable, _release("0.9.0", prerelease=False)],
        current_version="0.9.0",
        channel="stable",
        fetch_manifest=lambda _url: _manifest("1.0.0", channel="stable"),
    )
    assert candidate is not None
    assert candidate.version == "1.0.0"

    assert (
        select_update_candidate(
            [stable],
            current_version="1.0.0",
            channel="stable",
            fetch_manifest=lambda _url: pytest.fail("manifest must not be fetched"),
        )
        is None
    )


def test_update_manifest_fails_closed_on_identity_or_apply_claim() -> None:
    wrong = _manifest("0.4.0")
    wrong["artifact"]["automatic_apply"] = True
    with pytest.raises(UpdateError, match="automatic apply"):
        select_update_candidate(
            [_release("0.4.0")],
            current_version="0.3.0",
            channel="preview",
            fetch_manifest=lambda _url: wrong,
        )

    mismatched = _manifest("0.5.0")
    with pytest.raises(UpdateError, match="identity differs"):
        select_update_candidate(
            [_release("0.4.0")],
            current_version="0.3.0",
            channel="preview",
            fetch_manifest=lambda _url: mismatched,
        )


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int) -> bytes:
        result = self.payload[self.offset : self.offset + size]
        self.offset += len(result)
        return result


def _candidate(payload: bytes, *, digest: str | None = None) -> UpdateCandidate:
    return UpdateCandidate(
        version="0.4.0",
        tag="v0.4.0",
        channel="preview",
        commit="a" * 40,
        release_url="https://github.com/gabned/provelume/releases/tag/v0.4.0",
        manifest_url=(
            "https://github.com/gabned/provelume/releases/download/v0.4.0/"
            "provelume-windows-update.json"
        ),
        installer_name="Provelume-Setup-0.4.0-x64.exe",
        installer_url=(
            "https://github.com/gabned/provelume/releases/download/v0.4.0/"
            "Provelume-Setup-0.4.0-x64.exe"
        ),
        installer_sha256=digest or hashlib.sha256(payload).hexdigest(),
        installer_size_bytes=len(payload),
        architecture="x86_64",
        installer_type="inno_setup",
        minimum_windows_build=19045,
        signature_status="unsigned_preview",
        automatic_apply=False,
    )


def test_download_is_atomic_and_checks_size_and_sha256(tmp_path: Path, monkeypatch) -> None:
    payload = b"synthetic installer bytes"
    client = SafeHttpsClient()
    monkeypatch.setattr(client, "_open", lambda *_args, **_kwargs: _Response(payload))

    result = download_update(_candidate(payload), tmp_path, client=client)
    assert result.read_bytes() == payload
    assert not list(tmp_path.glob("*.part"))

    bad = _candidate(payload, digest="0" * 64)
    with pytest.raises(UpdateError, match="SHA-256"):
        download_update(bad, tmp_path / "bad", client=client)
    assert not (tmp_path / "bad" / bad.installer_name).exists()


@pytest.mark.parametrize(
    "url",
    (
        "http://github.com/gabned/provelume/releases",
        "https://user:secret@github.com/gabned/provelume/releases",
        "https://example.test/update.json",
    ),
)
def test_update_transport_rejects_unsafe_or_unexpected_urls(url: str) -> None:
    release = _release("0.4.0")
    release["assets"][0]["browser_download_url"] = url
    with pytest.raises(UpdateError, match="allowed HTTPS"):
        select_update_candidate(
            [release],
            current_version="0.3.0",
            channel="preview",
            fetch_manifest=lambda _url: _manifest("0.4.0"),
        )
