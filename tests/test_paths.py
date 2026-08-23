from pathlib import Path

import pytest

from provelume.paths import UnsafePathError, normalise_locator, safe_instance_path
from provelume.service import ProvelumeInstance


def test_windows_like_locator_normalisation() -> None:
    assert normalise_locator(r"Folder\Sub Folder\note.md") == "Folder/Sub Folder/note.md"
    with pytest.raises(UnsafePathError):
        normalise_locator(r"C:\private\note.md")
    with pytest.raises(UnsafePathError):
        normalise_locator(r"..\escape.txt")


def test_safe_instance_path_rejects_traversal(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    with pytest.raises(UnsafePathError):
        safe_instance_path(instance.root, "../outside")
