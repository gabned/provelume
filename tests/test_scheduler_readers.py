"""UI journal readers retain a snapshot while an owned writer replaces the file."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from provelume.service import ProvelumeInstance


@pytest.mark.parametrize("legacy_windows_handle", [False, True])
def test_journal_snapshot_allows_atomic_replacement(
    tmp_path, monkeypatch, legacy_windows_handle
):
    if legacy_windows_handle and os.name != "nt":
        pytest.skip("negative control uses actual Windows CRT sharing semantics")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    journal = instance.scheduler.journal
    journal._ensure_directories()
    path = journal.root / "synthetic-reader.json"
    instance.store._atomic_json(path, {"revision": 1})
    reading, release = threading.Event(), threading.Event()
    original_loads = json.loads
    reader_identity = []

    def held_read(payload, *args, **kwargs):
        value = original_loads(payload, *args, **kwargs)
        if threading.get_ident() == reader_identity[0]:
            reading.set()
            assert release.wait(10), "reader was not released"
        return value

    def read():
        reader_identity.append(threading.get_ident())
        if legacy_windows_handle:
            # Reproduce the original actual Windows failure on the same file.
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        return journal._read_json(path)

    def write():
        with journal.hold():
            instance.store._atomic_json(path, {"revision": 2})
            return journal._read_json(path)

    monkeypatch.setattr(json, "loads", held_read)
    with ThreadPoolExecutor(max_workers=2) as executor:
        reader = executor.submit(read)
        try:
            assert reading.wait(10)
            writer = executor.submit(write)
            if legacy_windows_handle:
                with pytest.raises(PermissionError):
                    writer.result(timeout=5)
            else:
                # The writer must finish before this reader closes: an exclusive
                # read lock would block navigation and is not a valid solution.
                assert writer.result(timeout=5) == {"revision": 2}
        finally:
            release.set()
        assert reader.result(timeout=10) == {"revision": 1}
    assert journal._read_json(path) == {"revision": 1 if legacy_windows_handle else 2}


@pytest.mark.skipif(os.name != "nt", reason="actual Windows CRT rename sharing")
def test_windows_atomic_replacement_waits_for_a_transient_reader(tmp_path, monkeypatch):
    from provelume import storage

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    path = instance.store.paths.state / "synthetic-transient-reader.json"
    instance.store._atomic_json(path, {"revision": 1})
    blocked = threading.Event()
    original_replace = storage.os.replace
    observed = []

    def observed_replace(source, target):
        try:
            return original_replace(source, target)
        except PermissionError as error:
            observed.append(error.winerror)
            blocked.set()
            raise

    monkeypatch.setattr(storage.os, "replace", observed_replace)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with path.open("rb"):
            writer = executor.submit(instance.store._atomic_json, path, {"revision": 2})
            assert blocked.wait(5), "the real read handle did not conflict with replacement"
        writer.result(timeout=5)
    assert observed and set(observed) <= {5, 32}
    assert json.loads(path.read_text()) == {"revision": 2}
