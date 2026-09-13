from __future__ import annotations

import errno
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from provelume import storage
from provelume.instance_validation import _load_config, inspect_instance
from provelume.storage import InstanceStore


def _store(tmp_path: Path, payload: bytes = b"mode: one\n") -> InstanceStore:
    store = InstanceStore(tmp_path)
    store.paths.config.write_bytes(payload)
    return store


def _decoder_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    decode = yaml.safe_load

    def counted(stream):
        calls.append(stream.name)
        return decode(stream)

    monkeypatch.setattr(storage.yaml, "safe_load", counted)
    return calls


def test_identical_bytes_decode_once_but_open_and_read_every_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    calls = _decoder_calls(monkeypatch)
    opened: list[bytes] = []
    original_open = Path.open

    class ObservedRead:
        def __init__(self, handle):
            self.handle = handle
            self.name = handle.name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def read(self):
            payload = self.handle.read()
            opened.append(payload)
            return payload

    def observe(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return ObservedRead(handle) if path == store.paths.config else handle

    monkeypatch.setattr(Path, "open", observe)
    for _ in range(4):
        assert store.read_config() == {"mode": "one"}
    assert opened == [b"mode: one\n"] * 4
    assert calls == [str(store.paths.config)]


def test_same_size_and_mtime_changes_are_observed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.read_config() == {"mode": "one"}
    before = store.paths.config.stat()
    store.paths.config.write_bytes(b"mode: two\n")
    os.utime(store.paths.config, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = store.paths.config.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    assert store.read_config() == {"mode": "two"}


def test_replacement_and_deletion_after_hit_never_return_stale_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    calls = _decoder_calls(monkeypatch)
    assert store.read_config() == store.read_config() == {"mode": "one"}
    replacement = tmp_path / "replacement.yml"
    replacement.write_bytes(b"mode: two\n")
    replacement.replace(store.paths.config)
    assert store.read_config() == {"mode": "two"}
    store.paths.config.unlink()
    with pytest.raises(FileNotFoundError):
        store.read_config()
    store.paths.config.write_bytes(b"mode: two\n")
    assert store.read_config() == {"mode": "two"}
    assert len(calls) == 3


def test_unreadable_file_after_hit_is_not_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    calls = _decoder_calls(monkeypatch)
    assert store.read_config() == store.read_config() == {"mode": "one"}
    original_open = Path.open

    def deny(path, *args, **kwargs):
        if path == store.paths.config:
            raise PermissionError(errno.EACCES, "synthetic access denial", str(path))
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as denied:
        denied.setattr(Path, "open", deny)
        with pytest.raises(PermissionError, match="synthetic access denial"):
            store.read_config()
    assert store.read_config() == {"mode": "one"}
    assert len(calls) == 2


def test_nested_copies_and_yaml_aliases_are_independent_on_miss_and_hit(
    tmp_path: Path,
) -> None:
    store = _store(
        tmp_path,
        b"first: &item\n  values: [one]\nsecond: *item\ndate: 2026-09-13\n"
        b"binary: !!binary YWJj\n",
    )
    first = store.read_config()
    assert first["first"] is first["second"]
    first["first"]["values"].append("changed")
    second = store.read_config()
    assert second["first"]["values"] == ["one"]
    assert second["first"] is second["second"]
    second["second"]["values"].clear()
    third = store.read_config()
    assert third["first"]["values"] == ["one"]
    assert third["binary"] == b"abc"
    assert third["date"].isoformat() == "2026-09-13"


def test_read_modify_write_and_standalone_stores_remain_fresh(tmp_path: Path) -> None:
    store = _store(tmp_path, b"nested: {enabled: false}\n")
    other = InstanceStore(tmp_path)
    selected = store.read_config()
    assert other.read_config() == selected
    selected["nested"]["enabled"] = True
    assert store.read_config()["nested"]["enabled"] is False
    store.write_config(selected)
    assert store.read_config()["nested"]["enabled"] is True
    assert other.read_config()["nested"]["enabled"] is True


@pytest.mark.parametrize(
    ("payload", "exception"),
    ((b"name: \xff\n", UnicodeError), (b"name: [\n", yaml.YAMLError),
     (b"- nonempty\n", ValueError)),
)
def test_invalid_input_after_hit_preserves_error_and_can_be_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes, exception: type
) -> None:
    store = _store(tmp_path)
    calls = _decoder_calls(monkeypatch)
    assert store.read_config() == store.read_config() == {"mode": "one"}
    store.paths.config.write_bytes(payload)
    with pytest.raises(exception):
        store.read_config()
    value, problem = _load_config(store)
    assert value is None
    assert problem
    if exception is ValueError:
        assert problem == "provelume.yml must contain a mapping"
    store.paths.config.write_bytes(b"mode: one\n")
    assert store.read_config() == {"mode": "one"}
    assert len(calls) == 4


@pytest.mark.parametrize(
    "payload",
    (b"name: [\r\n", b"name: [\r", b"name: \xff\r\n",
     b"name: value\r\n" * 900 + b"broken: \xff\n"),
)
def test_buffer_errors_match_original_named_utf8_text_stream(
    tmp_path: Path, payload: bytes
) -> None:
    store = _store(tmp_path, payload)
    with (
        pytest.raises((UnicodeError, yaml.YAMLError)) as original,
        store.paths.config.open("r", encoding="utf-8") as handle,
    ):
        yaml.safe_load(handle)
    with pytest.raises(type(original.value)) as current:
        store.read_config()
    assert str(current.value) == str(original.value)


@pytest.mark.parametrize("payload", (b"", b"null\n", b"[]\n", b"false\n"))
def test_existing_falsey_yaml_default_semantics_are_preserved(
    tmp_path: Path, payload: bytes
) -> None:
    store = _store(tmp_path, payload)
    assert store.read_config() == store.read_config() == {}


def test_universal_newlines_match_original_text_stream(tmp_path: Path) -> None:
    store = _store(tmp_path, b'value: "one\rtwo\r\nthree"\r\n')
    with store.paths.config.open("r", encoding="utf-8") as handle:
        expected = yaml.safe_load(handle)
    assert store.read_config() == store.read_config() == expected


def test_concurrent_decodes_keep_each_buffer_paired_with_its_own_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    first_decoding = threading.Event()
    resume_first = threading.Event()
    decode = yaml.safe_load

    def interleaved(stream):
        value = decode(stream)
        if value == {"mode": "one"}:
            first_decoding.set()
            assert resume_first.wait(5), "second reader did not finish"
        return value

    monkeypatch.setattr(storage.yaml, "safe_load", interleaved)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(store.read_config)
        try:
            assert first_decoding.wait(5), "first reader did not capture its buffer"
            store.paths.config.write_bytes(b"mode: two\n")
            assert store.read_config() == {"mode": "two"}
        finally:
            resume_first.set()
        assert first.result(timeout=5) == {"mode": "one"}
    # The older reader may publish last; the next real read must still see two.
    assert store.read_config() == {"mode": "two"}


def test_inspection_reuses_decode_but_reruns_integrity_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = InstanceStore.initialise(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    calls = _decoder_calls(monkeypatch)
    first = inspect_instance(tmp_path)
    assert first["status"] == "valid"
    assert calls == [str(store.paths.config)]
    assert before == {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    store.paths.manifest.write_bytes(b"{}\n")
    second = inspect_instance(tmp_path)
    assert second["status"] == "invalid"
    assert second["content_fingerprint"] is None
    assert "instance_manifest_invalid" in {item["code"] for item in second["errors"]}
    assert len(calls) == 2
