"""Fresh Linux mount boundaries used by private AI and maintenance file reads."""

import os
from pathlib import Path

import pytest

from provelume.maintenance_local_files import MaintenanceTargetError, absolute_local_path

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux mountinfo locality")


def mount(path, filesystem="ext4"):
    escaped = path.replace("\\", "\\134").replace(" ", "\\040")
    escaped = escaped.replace("\t", "\\011").replace("\n", "\\012")
    return f"10 1 0:1 / {escaped} rw - {filesystem} source rw\n"


def observe(monkeypatch, rows):
    original = Path.read_text

    def read(path, **kwargs):
        if str(path) == "/proc/self/mountinfo":
            return rows()
        return original(path, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)


def test_closest_component_mount_and_each_remount_are_observed(monkeypatch):
    rows = mount("/") + mount("/work", "nfs") + mount("/work/local", "ext4")
    observe(monkeypatch, lambda: rows)
    selected = Path("/work/local/deep/model.gguf")
    assert absolute_local_path(selected) == selected
    assert absolute_local_path("/workspace/model.gguf") == Path("/workspace/model.gguf")
    with pytest.raises(MaintenanceTargetError, match="target_remote"):
        absolute_local_path("/work/local-sibling/model.gguf")
    rows = mount("/") + mount("/work/local", "nfs4")
    with pytest.raises(MaintenanceTargetError, match="target_remote"):
        absolute_local_path(selected)
    rows = mount("/") + mount("/work/local", "unrecognised")
    with pytest.raises(MaintenanceTargetError, match="target_locality_unknown"):
        absolute_local_path(selected)


@pytest.mark.parametrize("component", ["space here", "tab\there", "line\nhere", r"literal\040"])
def test_kernel_escaped_mount_names_cannot_hide_remote_storage(monkeypatch, component):
    root = "/work/" + component
    observe(monkeypatch, lambda: mount("/") + mount(root, "cifs"))
    with pytest.raises(MaintenanceTargetError, match="target_remote"):
        absolute_local_path(root + "/private.json")
    sibling = Path(root + "-sibling/private.json")
    assert absolute_local_path(sibling) == sibling


@pytest.mark.parametrize("rows", ["", "malformed", mount("/") + "malformed\n", mount("relative")])
def test_unusable_mount_observations_never_grant_locality(monkeypatch, rows):
    observe(monkeypatch, lambda: rows)
    with pytest.raises(MaintenanceTargetError, match="target_locality_unknown"):
        absolute_local_path("/work/private.json")
