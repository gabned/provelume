"""Admission must reject nonlocal targets before any path/Source probe or Git."""

from pathlib import Path

import pytest
from test_concordia_git_s17 import git_fixture

from provelume.maintenance_local_files import MaintenanceTargetError
from provelume.mirror_contract import MirrorError
from provelume.mirror_git_runtime import GitSession


def test_nonlocal_target_is_rejected_before_source_or_target_metadata(tmp_path, monkeypatch):
    import provelume.maintenance_local_files as local_files

    _instance, _mirrors, git, destination = git_fixture(tmp_path)
    selected = tmp_path / "Destination.git"
    original = Path.is_symlink

    def probe(path):
        if path == selected:
            pytest.fail("Nonlocal target was probed before locality admission")
        return original(path)

    def denied(_value):
        raise MaintenanceTargetError("target_remote")

    monkeypatch.setattr(Path, "is_symlink", probe)
    monkeypatch.setattr(local_files, "absolute_local_path", denied)
    monkeypatch.setattr(GitSession, "run", lambda *_args, **_kwargs: pytest.fail("Git ran"))
    with pytest.raises(MaintenanceTargetError, match="target_remote"):
        git.initialize_local(
            destination["id"],
            expected_destination_sha256=destination["destination_sha256"],
            confirmed=True,
        )


def test_local_initialization_does_not_resolve_or_probe_source_inputs(tmp_path, monkeypatch):
    _instance, mirrors, git, destination = git_fixture(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Local mirror tried to resolve a configured Source input")

    monkeypatch.setattr(mirrors.store, "source_path", forbidden)
    assert (
        git.initialize_local(
            destination["id"],
            expected_destination_sha256=destination["destination_sha256"],
            confirmed=True,
        )["status"]
        == "initialized"
    )
    assert (
        git.prepare(destination["id"], expected_revision=1, confirmed=True)["publication"]
        == "PREVIEW_ONLY"
    )


def test_target_acquiring_unknown_content_before_init_is_preserved(tmp_path, monkeypatch):
    _instance, mirrors, git, destination = git_fixture(tmp_path)
    initialize = git._initialize_pinned

    def changed(session, pinned, binding):
        (pinned / "unknown-user-content.txt").write_text("Synthetic preexisting content\n")
        return initialize(session, pinned, binding)

    monkeypatch.setattr(git, "_initialize_pinned", changed)
    with pytest.raises(MirrorError, match="git_target_not_empty"):
        git.initialize_local(
            destination["id"],
            expected_destination_sha256=destination["destination_sha256"],
            confirmed=True,
        )
    root = tmp_path / "Destination.git"
    assert (root / "unknown-user-content.txt").read_text() == "Synthetic preexisting content\n"
    assert not (root / "HEAD").exists() and not (root / "config").exists()
    assert not (root / "provelume-mirror-target.json").exists()
    assert mirrors.operation_ledger(destination["id"])["serial"] == 0
