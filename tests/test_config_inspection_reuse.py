from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest
import yaml

from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.instance_validation import inspect_instance
from provelume.storage import InstanceStore


def _count_decodes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    decode = yaml.safe_load

    def counted(stream):
        seen.append(stream.name)
        return decode(stream)

    monkeypatch.setattr(yaml, "safe_load", counted)
    return seen


def test_warm_owner_still_reads_and_revalidates_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InstanceStore.initialise(tmp_path)
    manager = InstanceLifecycleManager(store)
    calls = _count_decodes(monkeypatch)
    reads: list[str] = []
    open_file = Path.open

    def observed(path, *args, **kwargs):
        if path == store.paths.config:
            reads.append(str(path))
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed)
    assert manager.validate()["status"] == "valid"
    assert manager.validate()["status"] == "valid"
    assert len(reads) == 6  # Initial read and both independent Source validators.
    assert calls == []
    store.paths.manifest.write_bytes(b"{}\n")
    damaged = manager.validate()
    assert damaged["status"] == "invalid"
    assert damaged["content_fingerprint"] is None
    assert "instance_manifest_invalid" in {row["code"] for row in damaged["errors"]}
    assert len(reads) == 9
    assert calls == []


@pytest.mark.parametrize("payload", (b"name: \xff\n", b"name: [\n", b"- invalid\n"))
def test_inherited_success_does_not_mask_invalid_config(
    tmp_path: Path, payload: bytes
) -> None:
    store = InstanceStore.initialise(tmp_path)
    original = store.paths.config.read_bytes()
    store.paths.config.write_bytes(payload)
    inherited = inspect_instance(tmp_path, _config_source=store)
    ordinary = inspect_instance(tmp_path)
    assert inherited["status"] == ordinary["status"] == "invalid"
    assert inherited["errors"] == ordinary["errors"]
    store.paths.config.write_bytes(original)
    assert inspect_instance(tmp_path, _config_source=store)["status"] == "valid"


def test_same_metadata_replacement_changes_authority(tmp_path: Path) -> None:
    store = InstanceStore.initialise(tmp_path)
    original = store.paths.config.read_bytes()
    identity = store.read_config()["instance"]["id"]
    replacement = "inst_" + ("a" if identity[5] != "a" else "b") * 32
    changed = original.replace(identity.encode(), replacement.encode())
    stat = store.paths.config.stat()
    candidate = tmp_path / "replacement.yml"
    candidate.write_bytes(changed)
    os.utime(candidate, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    candidate.replace(store.paths.config)
    assert store.paths.config.stat().st_size == stat.st_size
    assert store.paths.config.stat().st_mtime_ns == stat.st_mtime_ns
    result = inspect_instance(tmp_path, _config_source=store)
    assert result["status"] == "invalid"
    assert result["errors"] == inspect_instance(tmp_path)["errors"]


def test_missing_and_denied_config_keep_ordinary_error_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InstanceStore.initialise(tmp_path)
    original = store.paths.config.read_bytes()
    store.paths.config.unlink()
    assert (
        inspect_instance(tmp_path, _config_source=store)["errors"]
        == inspect_instance(tmp_path)["errors"]
    )
    store.paths.config.write_bytes(original)
    open_file = Path.open

    def denied(path, *args, **kwargs):
        if path == store.paths.config:
            raise PermissionError(errno.EACCES, "synthetic read denied", str(path))
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    result = inspect_instance(tmp_path, _config_source=store)
    assert result["status"] == "invalid"
    assert result["errors"] == inspect_instance(tmp_path)["errors"]


def test_different_root_and_default_calls_do_not_inherit_a_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = InstanceStore.initialise(tmp_path / "first")
    second = InstanceStore.initialise(tmp_path / "second")
    calls = _count_decodes(monkeypatch)
    assert (
        inspect_instance(second.paths.root, _config_source=first)["status"] == "valid"
    )
    assert calls == [str(second.paths.config)]
    assert inspect_instance(first.paths.root)["status"] == "valid"
    assert calls == [str(second.paths.config), str(first.paths.config)]


def test_fresh_root_resolution_and_copied_results_remain_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = InstanceStore.initialise(tmp_path / "instance")
    returned = owner.read_config()
    returned["instance"]["id"] = "not-the-authority"
    calls = _count_decodes(monkeypatch)
    old = tmp_path / "old"
    owner.paths.root.rename(old)
    replacement = InstanceStore.initialise(tmp_path / "instance")
    calls.clear()
    actual = inspect_instance(replacement.paths.root, _config_source=owner)
    assert actual["status"] == "valid"
    assert actual["instance_id"] == replacement.read_config()["instance"]["id"]
    assert actual["instance_id"] != returned["instance"]["id"]
    assert calls == [str(replacement.paths.config)]


def test_cold_donor_does_not_gain_implicit_shared_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    InstanceStore.initialise(tmp_path)
    donor = InstanceStore(tmp_path)
    calls = _count_decodes(monkeypatch)
    assert inspect_instance(tmp_path, _config_source=donor)["status"] == "valid"
    assert inspect_instance(tmp_path, _config_source=donor)["status"] == "valid"
    assert calls == [str(donor.paths.config)] * 2


@pytest.mark.parametrize("donor_change", ("update", "clear"))
def test_donor_change_after_seed_keeps_bytes_and_nested_copies_independent(
    tmp_path: Path,
    donor_change: str,
) -> None:
    donor = InstanceStore(tmp_path)
    first = b"nested: {values: [one]}\n"
    donor.paths.config.write_bytes(first)
    assert donor.read_config() == {"nested": {"values": ["one"]}}
    receiver = InstanceStore(tmp_path)
    receiver._reuse_config_decoding_from(donor)
    expected = "one"
    if donor_change == "update":
        donor.paths.config.write_bytes(b"nested: {values: [two]}\n")
        expected = "two"
        assert donor.read_config() == {"nested": {"values": ["two"]}}
    else:
        donor.paths.config.unlink()
        with pytest.raises(FileNotFoundError):
            donor.read_config()
        donor.paths.config.write_bytes(first)
    result = receiver.read_config()
    assert result == {"nested": {"values": [expected]}}
    result["nested"]["values"].append("local mutation")
    assert (
        receiver.read_config()
        == donor.read_config()
        == {"nested": {"values": [expected]}}
    )
