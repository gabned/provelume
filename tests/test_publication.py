from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from provelume.publication import (
    MAX_RECEIPT_BYTES,
    PublicationError,
    current_publication,
    default_receipt_path,
    import_publication,
    parse_receipt,
    read_metadata,
    write_once,
)
from scripts.publication_dry_run import OfflinePublicRecord, synthetic_bundle
from scripts.publication_receipt import create_receipt


@pytest.fixture
def publication(tmp_path):
    bundle, manifest = synthetic_bundle(tmp_path)
    client = OfflinePublicRecord(bundle, tmp_path / "public")
    raw = create_receipt(
        client.release(manifest["tag"]),
        bundle=bundle,
        resolved_commit=manifest["commit"],
        observed_at="2026-01-01T12:00:00Z",
    )
    receipt = tmp_path / "publication-receipt.json"
    receipt.write_bytes(raw)
    build = {
        key: manifest[key] for key in ("source_repository", "version", "tag", "commit", "channel")
    }
    build["official"] = True
    return bundle, receipt, build


@pytest.mark.parametrize(
    ("seconds", "status", "new", "remaining"),
    [
        (-1, "clock_unusable", False, 0),
        (0, "available", True, 86400),
        (86399, "available", True, 1),
        (86400, "available", False, 0),
        (90000, "available", False, 0),
    ],
)
def test_new_uses_actual_publication_and_exact_24_hour_boundary(
    publication,
    seconds,
    status,
    new,
    remaining,
):
    _bundle, receipt, build = publication
    now = datetime(2026, 1, 1, 12, tzinfo=UTC) + timedelta(seconds=seconds)
    result = current_publication(now=now, receipt_path=receipt, build=build)
    assert (result["status"], result["new"], result["remaining_seconds"]) == (
        status,
        new,
        remaining,
    )
    assert result["expires_at"] == "2026-01-02T12:00:00Z"
    assert result["network_used"] is False
    assert result["origin_authentication"] == "not_established"


def test_read_is_timezone_independent_uncached_and_never_writes(publication):
    _bundle, receipt, build = publication
    before = receipt.read_bytes()
    first = current_publication(
        now=datetime.fromisoformat("2026-01-01T14:00:00+02:00"), receipt_path=receipt, build=build
    )
    assert first["remaining_seconds"] == 86400
    assert receipt.read_bytes() == before
    receipt.unlink()
    assert current_publication(receipt_path=receipt, build=build)["status"] == "missing"
    assert not receipt.exists()


def test_missing_invalid_identity_and_unusable_clock_are_honest(publication, tmp_path):
    _bundle, receipt, build = publication
    assert current_publication(receipt_path=tmp_path / "absent", build=build)["new"] is False
    wrong = dict(build, commit="b" * 40)
    assert current_publication(receipt_path=receipt, build=wrong)["status"] == "identity_mismatch"
    assert (
        current_publication(receipt_path=receipt, build=dict(build, official=False))["status"]
        == "missing"
    )
    assert (
        current_publication(now=datetime(2026, 1, 1), receipt_path=receipt, build=build)["status"]
        == "clock_unusable"
    )
    receipt.write_bytes(b"not-json")
    assert current_publication(receipt_path=receipt, build=build)["status"] == "invalid"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(schema_version=True),
        lambda v: v.update(extra=True),
        lambda v: v.update(observed_at="2025-12-31T00:00:00Z"),
        lambda v: v.update(published_at="2026-01-01T12:00:00"),
        lambda v: v.update(release_url="https://example.com/"),
        lambda v: v["artifacts"][0].update(name="../escape.whl"),
        lambda v: v["artifacts"][0].update(size_bytes=True),
        lambda v: v["artifacts"].append(copy.deepcopy(v["artifacts"][0])),
    ],
)
def test_closed_receipt_rejects_malformed_or_conflicting_evidence(publication, mutate):
    _bundle, receipt, _build = publication
    value = json.loads(receipt.read_bytes())
    mutate(value)
    with pytest.raises(PublicationError):
        parse_receipt(value)


def test_duplicate_fields_and_bounded_reads_reject(publication):
    _bundle, receipt, _build = publication
    with pytest.raises(PublicationError, match="duplicate"):
        parse_receipt(b'{"schema_version":1,"schema_version":1}')
    receipt.write_bytes(b" " * (MAX_RECEIPT_BYTES + 1))
    with pytest.raises(PublicationError, match="limit"):
        read_metadata(receipt)


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz", ".exe"])
def test_offline_import_binds_payload_and_identity_and_is_idempotent(
    publication,
    tmp_path,
    suffix,
):
    bundle, receipt, build = publication
    target = tmp_path / "separate-install-state" / "publication-receipt.json"
    payload = next(path for path in bundle.iterdir() if path.name.endswith(suffix))
    kwargs = {
        "manifest_path": bundle / "release-manifest.json",
        "payload_path": payload,
        "destination": target,
        "build": build,
    }
    first = import_publication(receipt, **kwargs)
    assert import_publication(receipt, **kwargs) == first
    assert target.read_bytes() == receipt.read_bytes()
    assert first["network_used"] is False
    payload.write_bytes(b"tampered payload")
    with pytest.raises(PublicationError, match="payload bytes"):
        import_publication(receipt, **kwargs)
    assert target.read_bytes() == receipt.read_bytes()


def test_write_once_conflict_and_link_reject_without_replacement(tmp_path):
    target = tmp_path / "receipt.json"
    write_once(target, b"original")
    with pytest.raises(PublicationError, match="different bytes"):
        write_once(target, b"replacement")
    assert target.read_bytes() == b"original"
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Host does not grant symlink creation")
    with pytest.raises(PublicationError, match="link-like"):
        write_once(link, b"original")


def test_import_cli_reports_actual_local_result(publication, tmp_path, monkeypatch, capsys):
    import argparse

    from provelume import build_info
    from provelume.publication_cli import add_publication_commands, handle_publication_command

    bundle, receipt, build = publication
    monkeypatch.setattr(build_info, "current_build_info", lambda: build)
    parser = argparse.ArgumentParser()
    add_publication_commands(parser.add_subparsers(dest="command"))
    target = tmp_path / "imported.json"
    args = parser.parse_args(
        [
            "publication",
            "import",
            "--receipt",
            str(receipt),
            "--manifest",
            str(bundle / "release-manifest.json"),
            "--payload",
            str(next(bundle.glob("*.whl"))),
            "--destination",
            str(target),
        ]
    )
    assert handle_publication_command(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "imported"
    assert target.read_bytes() == receipt.read_bytes()


def test_default_storage_is_external_to_package_and_version_scoped(publication, monkeypatch):
    _bundle, _receipt, build = publication
    monkeypatch.delenv("PROVELUME_PUBLICATION_RECEIPT", raising=False)
    path = default_receipt_path(build)
    assert path.parts[-3:] == (
        "publication",
        f"{build['version']}-{build['commit']}",
        "publication-receipt.json",
    )
    assert "site-packages" not in path.parts


def test_windows_headless_import_is_exclusive_and_does_not_start_shell(
    publication,
    tmp_path,
    monkeypatch,
):
    from provelume import build_info, desktop

    bundle, receipt, build = publication
    monkeypatch.setattr(build_info, "current_build_info", lambda: build)
    monkeypatch.setattr(desktop, "run_ui", lambda **kwargs: pytest.fail("No shell may start"))
    args = [
        "--import-publication",
        str(receipt),
        "--publication-manifest",
        str(bundle / "release-manifest.json"),
        "--publication-payload",
        str(next(bundle.glob("*.exe"))),
        "--publication-destination",
        str(tmp_path / "installed.json"),
    ]
    assert desktop.main(args) == 0
    assert (tmp_path / "installed.json").read_bytes() == receipt.read_bytes()
    with pytest.raises(SystemExit, match="only one"):
        desktop.main([*args, "--diagnostics-file", str(tmp_path / "diagnostics.json")])
    assert not (tmp_path / "diagnostics.json").exists()


def test_packaged_credits_have_real_offline_texts():
    from provelume.about import current_about

    about = current_about()
    for name in about["credits"]["notices"]:
        assert about["credits"]["notice_texts"][name] == Path(name).read_text(encoding="utf-8")
    assert about["credits"]["notice_texts"]["Lucide LICENSE"] == Path(
        "core/provelume/notices/lucide-LICENSE.txt"
    ).read_text(encoding="utf-8")
    assert about["public_links"]["repository"] == "https://github.com/gabned/provelume"
