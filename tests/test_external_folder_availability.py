from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from provelume.configured_inbox import InboxManager
from provelume.folder_settings import FolderSettingsError, FolderSettingsManager
from provelume.service import ProvelumeInstance


def test_missing_external_folder_is_not_silently_recreated(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    drop = tmp_path / "mounted" / "drop"
    managed = tmp_path / "mounted" / "managed"
    FolderSettingsManager(instance.store).configure(
        drop_path=drop,
        managed_path=managed,
    )
    shutil.rmtree(tmp_path / "mounted")

    with pytest.raises(FolderSettingsError, match="external folder is unavailable"):
        InboxManager(instance.store).process_drop()

    assert not drop.exists()
    assert not managed.exists()
