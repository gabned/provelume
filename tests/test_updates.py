from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from provelume.updates import (
    MAX_MANIFEST_BYTES,
    SafeHttpsClient,
    UpdateCandidate,
    UpdateError,
    check_for_updates,
    download_update,
    select_update_candidate,
)


def _resolve_tag_commit(_tag: str) -> str:
    return "a" * 40


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
        resolve_tag_commit=_resolve_tag_commit,
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
        resolve_tag_commit=_resolve_tag_commit,
    )
    assert candidate is not None
    assert candidate.version == "1.0.0"

    assert (
        select_update_candidate(
            [stable],
            current_version="1.0.0",
            channel="stable",
            fetch_manifest=lambda _url: pytest.fail("manifest must not be fetched"),
            resolve_tag_commit=lambda _tag: pytest.fail("tag must not be resolved"),
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
            resolve_tag_commit=_resolve_tag_commit,
        )

    mismatched = _manifest("0.5.0")
    with pytest.raises(UpdateError, match="identity differs"):
        select_update_candidate(
            [_release("0.4.0")],
            current_version="0.3.0",
            channel="preview",
            fetch_manifest=lambda _url: mismatched,
            resolve_tag_commit=_resolve_tag_commit,
        )


def test_update_manifest_commit_must_match_the_release_tag_commit() -> None:
    with pytest.raises(UpdateError, match="tag commit"):
        select_update_candidate(
            [_release("0.4.0")],
            current_version="0.3.0",
            channel="preview",
            fetch_manifest=lambda _url: _manifest("0.4.0"),
            resolve_tag_commit=lambda _tag: "c" * 40,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda value: value.update({"unknown": True}), "incomplete or unsupported"),
        (lambda value: value["artifact"].update({"platform": "linux"}), "unsupported platform"),
        (lambda value: value["artifact"].update({"architecture": "arm64"}), "unsupported platform"),
        (lambda value: value.update({"commit": "not-a-commit"}), "commit is invalid"),
    ),
)
def test_update_manifest_rejects_unknown_or_incompatible_identity(mutate, message: str) -> None:
    manifest = _manifest("0.4.0")
    mutate(manifest)
    with pytest.raises(UpdateError, match=message):
        select_update_candidate(
            [_release("0.4.0")],
            current_version="0.3.0",
            channel="preview",
            fetch_manifest=lambda _url: manifest,
            resolve_tag_commit=_resolve_tag_commit,
        )


def test_missing_manifest_is_skipped_without_fetching_or_downgrading() -> None:
    release = _release("0.4.0")
    release["assets"] = [release["assets"][1]]
    assert (
        select_update_candidate(
            [release],
            current_version="0.3.0",
            channel="preview",
            fetch_manifest=lambda _url: pytest.fail("missing manifest must not be fetched"),
            resolve_tag_commit=lambda _tag: pytest.fail("missing manifest has no candidate"),
        )
        is None
    )


def test_update_check_resolves_the_release_tag_and_sends_no_instance_content() -> None:
    calls: list[tuple[str, int]] = []

    class _Client:
        def get_json(self, url: str, *, maximum_bytes: int):
            calls.append((url, maximum_bytes))
            if url.endswith("releases?per_page=30"):
                return [_release("0.4.0")]
            if url.endswith("provelume-windows-update.json"):
                return _manifest("0.4.0")
            if url.endswith("/commits/v0.4.0"):
                return {"sha": "a" * 40}
            raise AssertionError(f"unexpected update URL: {url}")

    result = check_for_updates(
        current_version="0.3.0",
        channel="preview",
        client=_Client(),
    )

    assert result["status"] == "update_available"
    assert result["network_used"] is True
    assert result["instance_content_sent"] is False
    assert [url for url, _maximum in calls] == [
        "https://api.github.com/repos/gabned/provelume/releases?per_page=30",
        (
            "https://github.com/gabned/provelume/releases/download/v0.4.0/"
            "provelume-windows-update.json"
        ),
        "https://api.github.com/repos/gabned/provelume/commits/v0.4.0",
    ]


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


class _InterruptedResponse(_Response):
    def __init__(self, payload: bytes):
        super().__init__(payload)
        self.reads = 0

    def read(self, size: int) -> bytes:
        self.reads += 1
        if self.reads > 1:
            raise OSError("synthetic connection interruption")
        return super().read(min(size, 4))


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


def test_interrupted_download_removes_partial_file(tmp_path: Path, monkeypatch) -> None:
    payload = b"synthetic installer bytes"
    client = SafeHttpsClient()
    monkeypatch.setattr(
        client,
        "_open",
        lambda *_args, **_kwargs: _InterruptedResponse(payload),
    )

    with pytest.raises(OSError, match="interruption"):
        download_update(_candidate(payload), tmp_path, client=client)
    assert not list(tmp_path.rglob("*.part"))
    assert not (tmp_path / _candidate(payload).installer_name).exists()


@pytest.mark.parametrize("payload", (b"{malformed", b"\xff"))
def test_update_json_rejects_malformed_or_non_utf8_payload(payload: bytes, monkeypatch) -> None:
    client = SafeHttpsClient()
    monkeypatch.setattr(client, "_open", lambda *_args, **_kwargs: _Response(payload))
    with pytest.raises(UpdateError, match="invalid JSON"):
        client.get_json(
            "https://github.com/gabned/provelume/releases/download/v0.4.0/manifest.json",
            maximum_bytes=MAX_MANIFEST_BYTES,
        )


def test_update_json_rejects_oversized_payload_without_parsing(monkeypatch) -> None:
    client = SafeHttpsClient()
    payload = b" " * (MAX_MANIFEST_BYTES + 1)
    response = _Response(payload)
    response.headers = {}
    monkeypatch.setattr(client, "_open", lambda *_args, **_kwargs: response)
    with pytest.raises(UpdateError, match="exceeds its safety limit"):
        client.get_json(
            "https://github.com/gabned/provelume/releases/download/v0.4.0/manifest.json",
            maximum_bytes=MAX_MANIFEST_BYTES,
        )


def test_update_transport_wraps_timeout_as_a_bounded_error(monkeypatch) -> None:
    client = SafeHttpsClient(timeout_seconds=0.01)

    def timeout(*_args, **_kwargs):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(client._opener, "open", timeout)
    with pytest.raises(UpdateError, match="request failed"):
        client.get_json(
            "https://api.github.com/repos/gabned/provelume/releases?per_page=30",
            maximum_bytes=MAX_MANIFEST_BYTES,
        )


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
            resolve_tag_commit=_resolve_tag_commit,
        )
