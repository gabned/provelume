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
    original_load = json.load
    reader_identity = []

    def held_read(handle, *args, **kwargs):
        value = original_load(handle, *args, **kwargs)
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

    monkeypatch.setattr(json, "load", held_read)
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
