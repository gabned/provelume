from __future__ import annotations

import os
from pathlib import Path

import pytest

from provelume.paths import UnsafePathError
from provelume.service import ProvelumeInstance


def test_ingestion_rejects_symlink_escape(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside source boundary\n", encoding="utf-8")
    link = source / "escape.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    with pytest.raises(UnsafePathError):
        instance.ingest(source)
    assert instance.store.list_canonical("documents") == []
