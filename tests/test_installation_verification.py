from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

import provelume.installation as installation_module
from provelume.installation import (
    MAX_FINDINGS,
    RecordEntry,
    verify_current_installation,
    verify_recorded_installation,
)


def _record(path: str, data: bytes) -> RecordEntry:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return RecordEntry(
        path=path,
        hash_mode="sha256",
        hash_value=digest,
        size_bytes=len(data),
    )


def _fixture(tmp_path: Path) -> tuple[Path, list[RecordEntry]]:
    root = tmp_path / "site-packages"
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir()
    module = b"VALUE = 'synthetic'\n"
    metadata = b"Name: provelume\nVersion: 0.1.0\n"
    (package / "module.py").write_bytes(module)
    (dist_info / "METADATA").write_bytes(metadata)
    (dist_info / "RECORD").write_text("", encoding="utf-8")
    entries = [
        _record("provelume/module.py", module),
        _record("provelume-0.1.0.dist-info/METADATA", metadata),
        RecordEntry(
            path="provelume-0.1.0.dist-info/RECORD",
            hash_mode=None,
            hash_value=None,
            size_bytes=None,
        ),
    ]
    return root, entries


def test_record_verification_accepts_matching_package_files(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "package_integrity_verified"
    assert result["integrity"] == {
        "verified": True,
        "checked_files": 2,
        "tracked_files": 2,
        "unhashed_files": 0,
        "unexpected_files": 0,
    }
    assert result["origin"]["status"] == "not_established"
    assert result["network_used"] is False
    assert result["findings"] == []


def test_record_verification_detects_modified_file(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    (root / "provelume" / "module.py").write_text("VALUE = 'changed'\n", encoding="utf-8")

    result = verify_recorded_installation(root, entries, version="0.1.0")
    assert result["status"] == "modified_installation"
    assert any(finding["issue"] == "modified_file" for finding in result["findings"])


@pytest.mark.parametrize(
    ("hash_mode", "hash_value", "metadata_issue"),
    [
        (None, None, "unhashed_record"),
        ("sha512", "unsupported-digest", "unsupported_hash"),
        ("sha256", "invalid$", "invalid_record"),
    ],
)
def test_missing_file_remains_modified_with_unusable_record_hash(
    tmp_path: Path,
    hash_mode: str | None,
    hash_value: str | None,
    metadata_issue: str,
) -> None:
    root, entries = _fixture(tmp_path)
    module = entries[0]
    (root / module.path).unlink()
    entries[0] = RecordEntry(
        path=module.path,
        hash_mode=hash_mode,
        hash_value=hash_value,
        size_bytes=module.size_bytes,
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == module.path and finding["issue"] == "missing_file"
        for finding in result["findings"]
    )
    assert any(
        finding["path"] == module.path and finding["issue"] == metadata_issue
        for finding in result["findings"]
    )


@pytest.mark.parametrize(
    ("hash_mode", "hash_value", "metadata_issue"),
    [
        (None, None, "unhashed_record"),
        ("sha512", "unsupported-digest", "unsupported_hash"),
        ("sha256", "invalid$", "invalid_record"),
    ],
)
def test_size_mismatch_remains_modified_with_unusable_record_hash(
    tmp_path: Path,
    hash_mode: str | None,
    hash_value: str | None,
    metadata_issue: str,
) -> None:
    root, entries = _fixture(tmp_path)
    module = entries[0]
    entries[0] = RecordEntry(
        path=module.path,
        hash_mode=hash_mode,
        hash_value=hash_value,
        size_bytes=module.size_bytes + 1,
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == module.path and finding["issue"] == "modified_file"
        for finding in result["findings"]
    )
    assert any(
        finding["path"] == module.path and finding["issue"] == metadata_issue
        for finding in result["findings"]
    )


def test_size_mismatch_does_not_hash_the_mismatched_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, entries = _fixture(tmp_path)
    module = root / "provelume" / "module.py"
    module.write_bytes(b"oversized" * 10_000)

    def guarded_sha256(path: Path, *, max_bytes: int) -> str:
        if path == module:
            raise AssertionError("a conclusive size mismatch must not be hashed")
        assert path.stat().st_size <= max_bytes
        return hashlib.sha256(path.read_bytes()).hexdigest()

    monkeypatch.setattr("provelume.installation._sha256_file", guarded_sha256)

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    finding = next(
        item for item in result["findings"] if item["path"] == "provelume/module.py"
    )
    assert finding["issue"] == "modified_file"
    assert finding["actual_sha256"] is None


def test_hash_stream_stops_at_its_explicit_byte_limit(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"bounded" * 100)

    with pytest.raises(installation_module._HashBudgetExceeded):
        installation_module._sha256_file(payload, max_bytes=10)


def test_record_verification_detects_unexpected_package_file(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    (root / "provelume" / "injected.py").write_text("unexpected = True\n", encoding="utf-8")

    result = verify_recorded_installation(root, entries, version="0.1.0")
    assert result["status"] == "modified_installation"
    assert result["integrity"]["unexpected_files"] == 1
    assert any(
        finding["path"] == "provelume/injected.py"
        and finding["issue"] == "unexpected_file"
        for finding in result["findings"]
    )


def test_editable_installation_is_explicitly_unavailable(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    result = verify_recorded_installation(
        root,
        entries,
        version="0.1.0",
        editable=True,
    )
    assert result["status"] == "verification_unavailable"
    assert result["package"]["editable"] is True
    assert result["integrity"]["verified"] is False


def test_normal_console_script_record_outside_package_scope_is_ignored(
    tmp_path: Path,
) -> None:
    root, entries = _fixture(tmp_path)
    entries.append(
        RecordEntry(
            path="../../../bin/provelume",
            hash_mode="sha256",
            hash_value="not-needed-for-out-of-scope-entry",
            size_bytes=10,
        )
    )
    result = verify_recorded_installation(root, entries, version="0.1.0")
    assert result["status"] == "package_integrity_verified"


def test_unhashed_package_file_prevents_complete_green_result(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    entries[0] = RecordEntry(
        path="provelume/module.py",
        hash_mode=None,
        hash_value=None,
        size_bytes=None,
    )
    result = verify_recorded_installation(root, entries, version="0.1.0")
    assert result["status"] == "verification_unavailable"
    assert any(finding["issue"] == "unhashed_record" for finding in result["findings"])


def test_nested_record_named_metadata_file_requires_a_hash(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    nested_record = root / "provelume-0.1.0.dist-info" / "payload" / "RECORD"
    nested_record.parent.mkdir()
    nested_record.write_bytes(b"nested metadata")
    entries.append(
        RecordEntry(
            path="provelume-0.1.0.dist-info/payload/RECORD",
            hash_mode=None,
            hash_value=None,
            size_bytes=len(b"nested metadata"),
        )
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "verification_unavailable"
    assert any(
        finding["path"] == "provelume-0.1.0.dist-info/payload/RECORD"
        and finding["issue"] == "unhashed_record"
        for finding in result["findings"]
    )


def test_generated_bytecode_record_entry_is_ignored(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    bytecode = root / "provelume" / "__pycache__" / "module.cpython-312.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"generated")
    entries.append(
        RecordEntry(
            path="provelume/__pycache__/module.cpython-312.pyc",
            hash_mode=None,
            hash_value=None,
            size_bytes=None,
        )
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "package_integrity_verified"
    assert result["integrity"]["unhashed_files"] == 0


@pytest.mark.parametrize("suffix", [".pyc", ".pyo"])
def test_top_level_bytecode_is_not_ignored(tmp_path: Path, suffix: str) -> None:
    root, entries = _fixture(tmp_path)
    injected = root / "provelume" / f"evil{suffix}"
    injected.write_bytes(b"directly importable")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == f"provelume/evil{suffix}"
        and finding["issue"] == "unexpected_file"
        for finding in result["findings"]
    )


def test_non_bytecode_file_inside_pycache_is_unexpected(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    injected = root / "provelume" / "__pycache__" / "injected.txt"
    injected.parent.mkdir()
    injected.write_text("unexpected", encoding="utf-8")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume/__pycache__/injected.txt"
        and finding["issue"] == "unexpected_file"
        for finding in result["findings"]
    )


@pytest.mark.parametrize(
    ("cache_name", "bytecode_name"),
    [
        ("__PYCACHE__", "evil.PYC"),
        ("__PYCACHE__", "evil.pyc"),
        ("__pycache__", "evil.PYC"),
    ],
)
def test_noncanonical_bytecode_path_is_not_ignored(
    tmp_path: Path,
    cache_name: str,
    bytecode_name: str,
) -> None:
    root, entries = _fixture(tmp_path)
    injected = root / "provelume" / cache_name / bytecode_name
    injected.parent.mkdir()
    injected.write_bytes(b"noncanonical bytecode")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == f"provelume/{cache_name}/{bytecode_name}"
        and finding["issue"] == "unexpected_file"
        for finding in result["findings"]
    )


def test_symlinked_package_file_is_reported_as_unsafe(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("outside = True\n", encoding="utf-8")
    target = root / "provelume" / "module.py"
    target.unlink()
    try:
        os.symlink(outside, target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    result = verify_recorded_installation(root, entries, version="0.1.0")
    assert result["status"] == "modified_installation"
    assert any(finding["issue"] == "unsafe_path" for finding in result["findings"])


def test_symlinked_record_parent_directory_is_reported_as_unsafe(
    tmp_path: Path,
) -> None:
    root, entries = _fixture(tmp_path)
    dist_info = root / "provelume-0.1.0.dist-info"
    metadata = (dist_info / "METADATA").read_bytes()
    (dist_info / "METADATA").unlink()
    (dist_info / "RECORD").unlink()
    dist_info.rmdir()
    alternate = root / "alternate-dist-info"
    alternate.mkdir()
    (alternate / "METADATA").write_bytes(metadata)
    (alternate / "RECORD").write_text("", encoding="utf-8")
    try:
        os.symlink(alternate, dist_info, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume-0.1.0.dist-info/METADATA"
        and finding["issue"] == "unsafe_path"
        for finding in result["findings"]
    )


@pytest.mark.parametrize("ignored_name", ["cache.pyc", "cache.pyo", ".DS_Store"])
def test_ignored_package_file_symlink_is_reported_as_unsafe(
    tmp_path: Path,
    ignored_name: str,
) -> None:
    root, entries = _fixture(tmp_path)
    outside = tmp_path / "outside-generated"
    outside.write_bytes(b"generated")
    link = root / "provelume" / ignored_name
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == f"provelume/{ignored_name}"
        and finding["issue"] == "unsafe_path"
        for finding in result["findings"]
    )


def test_symlinked_package_directory_is_reported_as_unsafe(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "provelume" / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert result["integrity"]["unexpected_files"] == 1
    assert any(
        finding["path"] == "provelume/linked"
        and finding["issue"] == "unsafe_path"
        for finding in result["findings"]
    )


def test_non_regular_package_entry_is_reported_as_unsafe(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    fifo = root / "provelume" / "unexpected-pipe"
    mkfifo = getattr(os, "mkfifo", None)
    if mkfifo is None:
        pytest.skip("FIFO creation is unavailable")
    try:
        mkfifo(fifo)
    except (OSError, NotImplementedError):
        pytest.skip("FIFO creation is unavailable")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume/unexpected-pipe"
        and finding["issue"] == "unsafe_path"
        for finding in result["findings"]
    )


def test_undecodable_package_filename_is_escaped_for_utf8_output(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("byte-oriented POSIX filenames are unavailable")
    root, entries = _fixture(tmp_path)
    raw_path = os.fsencode(root / "provelume") + b"/invalid-\xff.py"
    descriptor = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, b"unexpected = True\n")
    finally:
        os.close(descriptor)

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    finding = next(
        item for item in result["findings"] if item["issue"] == "unexpected_file"
    )
    assert finding["path"] == "provelume/invalid-\\udcff.py"
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_junction_like_package_directory_is_reported_as_unsafe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, entries = _fixture(tmp_path)
    junction = root / "provelume" / "linked-cache"
    junction.mkdir()
    (junction / "generated.pyc").write_bytes(b"generated")
    original_is_junction = Path.is_junction

    def simulated_is_junction(path: Path) -> bool:
        return path == junction or original_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", simulated_is_junction)

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume/linked-cache"
        and finding["issue"] == "unsafe_path"
        for finding in result["findings"]
    )


def test_broken_symlinked_package_directory_is_reported_as_unsafe(
    tmp_path: Path,
) -> None:
    root, entries = _fixture(tmp_path)
    package = root / "provelume"
    (package / "module.py").unlink()
    package.rmdir()
    try:
        os.symlink(tmp_path / "missing-package", package, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume" and finding["issue"] == "unsafe_path"
        for finding in result["findings"]
    )


def test_symlinked_pycache_directory_is_reported_as_unsafe(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    outside = tmp_path / "outside-cache"
    outside.mkdir()
    link = root / "provelume" / "__pycache__"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume/__pycache__"
        and finding["issue"] == "unsafe_path"
        for finding in result["findings"]
    )


def test_package_scan_error_prevents_green_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, entries = _fixture(tmp_path)
    package = root / "provelume"
    real_scandir = os.scandir

    def failing_scandir(path: Path) -> os.ScandirIterator[str]:
        if Path(path) == package:
            error = PermissionError("synthetic scan failure")
            error.filename = str(package / "locked")
            raise error
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", failing_scandir)
    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume/locked"
        and finding["issue"] == "unreadable_path"
        for finding in result["findings"]
    )


def test_directory_entries_count_toward_scan_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, entries = _fixture(tmp_path)
    nested = root / "provelume" / "one" / "two"
    nested.mkdir(parents=True)
    monkeypatch.setattr("provelume.installation.MAX_PACKAGE_ENTRIES", 2)

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(finding["issue"] == "scan_limit" for finding in result["findings"])


def test_flat_directory_scan_limit_bounds_scandir_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, entries = _fixture(tmp_path)
    package = root / "provelume"
    for name in ("extra-a.py", "extra-b.py", "extra-c.py"):
        (package / name).write_text("unexpected = True\n", encoding="utf-8")
    real_scandir = os.scandir
    consumed = 0

    class GuardedScandir:
        def __init__(self, path: Path) -> None:
            self._iterator = real_scandir(path)

        def __enter__(self) -> GuardedScandir:
            return self

        def __exit__(self, *_args: object) -> None:
            self._iterator.close()

        def __iter__(self) -> GuardedScandir:
            return self

        def __next__(self) -> os.DirEntry[str]:
            nonlocal consumed
            consumed += 1
            if consumed > 3:
                raise AssertionError("scandir consumed entries beyond the fixed budget")
            return next(self._iterator)

    monkeypatch.setattr(os, "scandir", GuardedScandir)
    monkeypatch.setattr("provelume.installation.MAX_PACKAGE_ENTRIES", 2)

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert consumed == 3
    assert any(finding["issue"] == "scan_limit" for finding in result["findings"])


def test_dist_info_hash_without_package_payload_is_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "site-packages"
    dist_info = root / "provelume-0.1.0.dist-info"
    dist_info.mkdir(parents=True)
    metadata = b"Name: provelume\nVersion: 0.1.0\n"
    (dist_info / "METADATA").write_bytes(metadata)
    (dist_info / "RECORD").write_text("", encoding="utf-8")
    entries = [
        _record("provelume-0.1.0.dist-info/METADATA", metadata),
        RecordEntry(
            path="provelume-0.1.0.dist-info/RECORD",
            hash_mode=None,
            hash_value=None,
            size_bytes=None,
        ),
    ]

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "verification_unavailable"
    assert result["integrity"]["verified"] is False
    assert result["reason"] == (
        "No hashed Provelume package files were available in wheel RECORD."
    )


def test_record_hash_with_non_urlsafe_characters_is_invalid(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    valid = entries[0]
    entries[0] = RecordEntry(
        path=valid.path,
        hash_mode=valid.hash_mode,
        hash_value=f"{valid.hash_value}$$$$",
        size_bytes=valid.size_bytes,
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "verification_unavailable"
    assert any(finding["issue"] == "invalid_record" for finding in result["findings"])


def test_record_hash_with_noncanonical_pad_bits_is_invalid(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    valid = entries[0]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(valid.hash_value[-1])
    assert final_index % 4 == 0
    noncanonical = f"{valid.hash_value[:-1]}{alphabet[final_index + 1]}"
    entries[0] = RecordEntry(
        path=valid.path,
        hash_mode=valid.hash_mode,
        hash_value=noncanonical,
        size_bytes=valid.size_bytes,
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "verification_unavailable"
    assert any(finding["issue"] == "invalid_record" for finding in result["findings"])


def test_current_verifier_rejects_a_different_distribution_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DifferentDistribution:
        version = "0.1.0"
        files: tuple[()] = ()

        def read_text(self, _name: str) -> None:
            return None

        def locate_file(self, path: str) -> Path:
            return tmp_path / "different-site" / path

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: DifferentDistribution(),
    )

    result = verify_current_installation()

    assert result["status"] == "verification_unavailable"
    assert result["integrity"]["verified"] is False
    assert "does not match" in result["reason"]


def test_current_verifier_rejects_malformed_editable_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _entries = _fixture(tmp_path)
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    (dist_info / "direct_url.json").write_text("{malformed", encoding="utf-8")

    class MalformedDistribution:
        version = "0.1.0"
        _path = dist_info

        def read_text(self, name: str) -> str | None:
            path = dist_info / name
            return path.read_text(encoding="utf-8") if path.exists() else None

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: MalformedDistribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert result["status"] == "verification_unavailable"
    assert result["integrity"]["verified"] is False
    assert "could not be verified safely" in result["reason"]


def test_current_verifier_rejects_invalid_utf8_metadata_without_property_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _entries = _fixture(tmp_path)
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    (dist_info / "METADATA").write_bytes(b"Name: provelume\nVersion: \xff\n")

    class MalformedVersionDistribution:
        reads = 0
        _path = dist_info

        @property
        def version(self) -> str:
            self.reads += 1
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid metadata")

        def read_text(self, _name: str) -> None:
            return None

        def locate_file(self, path: str) -> Path:
            return root / path

    distribution = MalformedVersionDistribution()
    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: distribution,
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert distribution.reads == 0
    assert result["status"] == "verification_unavailable"
    assert result["package"]["version"] is None
    assert "could not be verified safely" in result["reason"]


@pytest.mark.parametrize(
    "invalid_metadata",
    [
        b"Name: provelume\n",
        b"Name: provelume\nVersion:\n",
        b"Name: provelume\nVersion:   \n",
        b"Name: provelume\nVersion: 0.1 0\n",
        b"Name: provelume\nVersion: banana\n",
        b"Name: provelume\nVersion: 1..0\n",
        b"Name: provelume\nVersion: 1.0-\n",
        "Name: provelume\nVersion: 1.0+K\n".encode(),
        "Name: provelume\nVersion: 1.0+ſ\n".encode(),
        "Name: provelume\nVersion: 1.0poſt1\n".encode(),
        b"Name: provelume\nVersion: 0.1.0\nVersion: 0.2.0\n",
    ],
)
def test_current_verifier_rejects_missing_or_invalid_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_metadata: bytes,
) -> None:
    root, _entries = _fixture(tmp_path)
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    (dist_info / "METADATA").write_bytes(invalid_metadata)

    class InvalidVersionDistribution:
        _path = dist_info

        def read_text(self, _name: str) -> None:
            return None

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: InvalidVersionDistribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert result["status"] == "verification_unavailable"
    assert result["package"]["version"] is None
    assert "could not be verified safely" in result["reason"]


@pytest.mark.parametrize(
    "invalid_metadata",
    [
        b"Version: 0.1.0\n",
        b"Name:\nVersion: 0.1.0\n",
        b"Name: another-project\nVersion: 0.1.0\n",
        b"Name: provelumeevil\nVersion: 0.1.0\n",
        b"Name: provelume\nName: provelume\nVersion: 0.1.0\n",
    ],
)
def test_current_verifier_rejects_missing_or_mismatched_distribution_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_metadata: bytes,
) -> None:
    root, _entries = _fixture(tmp_path)
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    (dist_info / "METADATA").write_bytes(invalid_metadata)

    class InvalidNameDistribution:
        _path = dist_info

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: InvalidNameDistribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert result["status"] == "verification_unavailable"
    assert result["package"]["version"] is None
    assert "could not be verified safely" in result["reason"]


@pytest.mark.parametrize("metadata_name", ["METADATA", "direct_url.json"])
def test_current_verifier_bounds_metadata_file_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata_name: str,
) -> None:
    root, _entries = _fixture(tmp_path)
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    (dist_info / metadata_name).write_bytes(b"x" * 65)

    class OversizedMetadataDistribution:
        _path = dist_info

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr("provelume.installation.MAX_METADATA_BYTES", 64)
    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: OversizedMetadataDistribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert result["status"] == "verification_unavailable"
    expected_version = None if metadata_name == "METADATA" else "0.1.0"
    assert result["package"]["version"] == expected_version
    assert "safety limit" in result["reason"]


def test_current_verifier_handles_distribution_discovery_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_distribution(_name: str) -> None:
        raise ValueError("malformed installed metadata")

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        fail_distribution,
    )

    result = verify_current_installation()

    assert result["status"] == "verification_unavailable"
    assert result["package"]["version"] is None
    assert "could not be verified safely" in result["reason"]


@pytest.mark.parametrize("linked_path", ["metadata_root", "METADATA", "direct_url.json"])
def test_current_verifier_rejects_linked_metadata_before_version_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    linked_path: str,
) -> None:
    root, _entries = _fixture(tmp_path)
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    outside = tmp_path / "outside-metadata"
    try:
        if linked_path == "metadata_root":
            outside.mkdir()
            (outside / "METADATA").write_text(
                "Name: provelume\nVersion: 9.9.9\n",
                encoding="utf-8",
            )
            (outside / "RECORD").write_text("", encoding="utf-8")
            (dist_info / "METADATA").unlink()
            (dist_info / "RECORD").unlink()
            dist_info.rmdir()
            os.symlink(outside, dist_info, target_is_directory=True)
        else:
            outside.write_text("outside", encoding="utf-8")
            target = dist_info / linked_path
            if target.exists():
                target.unlink()
            os.symlink(outside, target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    class LinkedMetadataDistribution:
        _path = dist_info
        version_reads = 0

        @property
        def version(self) -> str:
            self.version_reads += 1
            return "9.9.9"

        def read_text(self, _name: str) -> None:
            return None

        def locate_file(self, path: str) -> Path:
            return root / path

    distribution = LinkedMetadataDistribution()
    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: distribution,
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert distribution.version_reads == 0
    assert result["status"] == "verification_unavailable"
    assert result["package"]["version"] is None


def test_current_verifier_preserves_missing_raw_record_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "site-packages"
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Name: provelume\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    present = b"present = True\n"
    missing = b"missing = True\n"
    (package / "present.py").write_bytes(present)
    present_record = _record("provelume/present.py", present)
    missing_record = _record("provelume/missing.py", missing)
    record_text = (
        f"{present_record.path},sha256={present_record.hash_value},{len(present)}\n"
        f"{missing_record.path},sha256={missing_record.hash_value},{len(missing)}\n"
        "provelume-0.1.0.dist-info/RECORD,,\n"
    )
    (dist_info / "RECORD").write_text(record_text, encoding="utf-8")

    class RawDistribution:
        version = "0.1.0"
        _path = dist_info

        @property
        def files(self):
            raise AssertionError("Distribution.files must not be materialized")

        def read_text(self, _name: str) -> None:
            return None

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: RawDistribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "provelume/missing.py"
        and finding["issue"] == "missing_file"
        for finding in result["findings"]
    )


def test_current_verifier_caps_raw_record_before_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "site-packages"
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Name: provelume\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    present = b"present = True\n"
    (package / "present.py").write_bytes(present)
    present_record = _record("provelume/present.py", present)
    record_text = (
        f"{present_record.path},sha256={present_record.hash_value},{len(present)}\n"
        "provelume-0.1.0.dist-info/RECORD,,\n"
        "this row is deliberately malformed and must not be parsed\n"
        + ("ignored,sha256=invalid,1\n" * 100)
    )
    (dist_info / "RECORD").write_text(record_text, encoding="utf-8")

    class RawDistribution:
        version = "0.1.0"
        _path = dist_info

        @property
        def files(self):
            raise AssertionError("Distribution.files must not be materialized")

        def read_text(self, _name: str) -> None:
            return None

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr("provelume.installation.MAX_RECORD_ENTRIES", 2)
    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: RawDistribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == "<RECORD>" and finding["issue"] == "scan_limit"
        for finding in result["findings"]
    )


def test_current_verifier_keeps_hard_finding_before_raw_record_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "site-packages"
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Name: provelume\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    missing = b"missing = True\n"
    missing_record = _record("provelume/missing.py", missing)
    record_text = (
        f"{missing_record.path},sha256={missing_record.hash_value},{len(missing)}\n"
        "malformed-row\n"
    )
    (dist_info / "RECORD").write_text(record_text, encoding="utf-8")

    class RawDistribution:
        version = "0.1.0"
        _path = dist_info

        @property
        def files(self):
            raise AssertionError("Distribution.files must not be materialized")

        def read_text(self, _name: str) -> None:
            return None

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: RawDistribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert result["status"] == "modified_installation"
    assert any(finding["issue"] == "missing_file" for finding in result["findings"])
    assert any(finding["issue"] == "invalid_record" for finding in result["findings"])


def test_current_verifier_does_not_compare_untracked_files_after_record_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "site-packages"
    package = root / "provelume"
    dist_info = root / "provelume-0.1.0.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Name: provelume\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    first = b"first = True\n"
    later = b"later = True\n"
    (package / "first.py").write_bytes(first)
    (package / "later.py").write_bytes(later)
    first_record = _record("provelume/first.py", first)
    later_record = _record("provelume/later.py", later)
    record_text = (
        f"{first_record.path},sha256={first_record.hash_value},{len(first)}\n"
        "malformed-row\n"
        f"{later_record.path},sha256={later_record.hash_value},{len(later)}\n"
    )
    (dist_info / "RECORD").write_text(record_text, encoding="utf-8")

    class RawDistribution:
        version = "0.1.0"
        _path = dist_info

        def read_text(self, _name: str) -> None:
            return None

        def locate_file(self, path: str) -> Path:
            return root / path

    monkeypatch.setattr(
        "provelume.installation.metadata.distribution",
        lambda _name: RawDistribution(),
    )
    monkeypatch.setattr(
        "provelume.installation.__file__",
        str(package / "installation.py"),
    )

    result = verify_current_installation()

    assert result["status"] == "verification_unavailable"
    assert result["integrity"]["unexpected_files"] == 0
    assert any(finding["issue"] == "invalid_record" for finding in result["findings"])
    assert not any(
        finding["path"] == "provelume/later.py"
        and finding["issue"] == "unexpected_file"
        for finding in result["findings"]
    )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "provelume/../escape.py",
        "./provelume/../escape.py",
        "unrelated/../provelume/module.py",
        "/provelume/module.py",
    ],
)
def test_invalid_record_path_inside_package_scope_fails_closed(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    root, entries = _fixture(tmp_path)
    entries.append(
        RecordEntry(
            path=unsafe_path,
            hash_mode="sha256",
            hash_value="invalid",
            size_bytes=1,
        )
    )
    result = verify_recorded_installation(root, entries, version="0.1.0")
    assert result["status"] == "modified_installation"
    assert any(finding["issue"] == "unsafe_path" for finding in result["findings"])


def test_hard_finding_survives_metadata_finding_cap(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    invalid_entries = []
    for index in range(MAX_FINDINGS):
        relative = f"provelume/invalid-{index}.py"
        (root / relative).write_bytes(b"present")
        invalid_entries.append(
            RecordEntry(
                path=relative,
                hash_mode="sha256",
                hash_value="invalid$",
                size_bytes=len(b"present"),
            )
        )
    entries.extend(invalid_entries)
    (root / "provelume" / "unexpected.py").write_text(
        "unexpected = True\n",
        encoding="utf-8",
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert result["integrity"]["unexpected_files"] == 1
    assert result["findings_truncated"] is True
    assert len(result["findings"]) == MAX_FINDINGS
    assert any(
        finding["path"] == "provelume/unexpected.py"
        and finding["issue"] == "unexpected_file"
        for finding in result["findings"]
    )


def test_size_less_record_entry_respects_cumulative_hash_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, entries = _fixture(tmp_path)
    module = entries[0]
    entries[0] = RecordEntry(
        path=module.path,
        hash_mode=module.hash_mode,
        hash_value=module.hash_value,
        size_bytes=None,
    )
    monkeypatch.setattr(
        "provelume.installation.MAX_HASH_BYTES",
        module.size_bytes - 1,
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert any(
        finding["path"] == module.path and finding["issue"] == "scan_limit"
        for finding in result["findings"]
    )


def test_hash_budget_is_cumulative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, entries = _fixture(tmp_path)
    module, metadata_entry = entries[:2]
    monkeypatch.setattr(
        "provelume.installation.MAX_HASH_BYTES",
        module.size_bytes + metadata_entry.size_bytes - 1,
    )

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert result["integrity"]["checked_files"] == 1
    assert any(
        finding["path"] == metadata_entry.path
        and finding["issue"] == "scan_limit"
        for finding in result["findings"]
    )


def test_record_entry_limit_bounds_duplicate_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, entries = _fixture(tmp_path)
    entries.extend([entries[0]] * 100)
    monkeypatch.setattr("provelume.installation.MAX_RECORD_ENTRIES", 3)
    hashes = 0

    def counted_sha256(path: Path, *, max_bytes: int) -> str:
        nonlocal hashes
        hashes += 1
        assert path.stat().st_size <= max_bytes
        return hashlib.sha256(path.read_bytes()).hexdigest()

    monkeypatch.setattr("provelume.installation._sha256_file", counted_sha256)

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "modified_installation"
    assert hashes == 2
    assert any(
        finding["path"] == "<RECORD>" and finding["issue"] == "scan_limit"
        for finding in result["findings"]
    )


def test_duplicate_relevant_record_path_is_invalid(tmp_path: Path) -> None:
    root, entries = _fixture(tmp_path)
    entries.append(entries[0])

    result = verify_recorded_installation(root, entries, version="0.1.0")

    assert result["status"] == "verification_unavailable"
    assert any(
        finding["path"] == "provelume/module.py"
        and finding["issue"] == "invalid_record"
        for finding in result["findings"]
    )
