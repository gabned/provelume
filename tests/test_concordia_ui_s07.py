"""Real synthetic service readback, separate from human/Windows qualification."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_review_placement_routing import _bytes

from provelume.daily_journeys import document_journey, runtime_state, source_journey
from provelume.service import ProvelumeInstance
from provelume.setup_progress import SetupProgress, SetupProgressError
from provelume.web import create_app


@pytest.fixture
def archive(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    source = tmp_path / "input"
    source.mkdir()
    registered = instance.register_folder_source(source, name="Synthetic input")
    instance.rebuild_index()
    return instance, source, registered["id"]


def test_keep_counts_distinguish_present_files_from_text_pending_and_do_not_mutate(archive):
    instance, source, source_id = archive
    (source / "first.txt").write_text("Synthetic searchable alpha document.")
    instance.ingest(source)
    (source / "pending.txt").write_text("Synthetic unacquired beta document.")
    original = _bytes(instance.root)
    view = source_journey(instance, instance.folder_sources.public_view(source_id))
    assert view["files_present"] == 2
    assert view["to_complete"] == 1
    assert view["role"] == "folder" and view["mode"] == "keep"
    assert view["automation"] == "manual" and view["runtime"] == "stopped"
    assert view["counts_state"] == "current" and view["ocr_enabled"] is False
    assert _bytes(instance.root) == original
    instance.ingest(source)
    assert source_journey(instance, instance.folder_sources.public_view(source_id))[
        "to_complete"] == 0
    assert len(list(source.iterdir())) == 2


def test_unreadable_or_changed_input_cannot_become_false_zero(archive, monkeypatch):
    instance, _source, source_id = archive
    def unavailable(*args):
        raise OSError("synthetic read failure")
    monkeypatch.setattr(instance.inbox_transit, "status", unavailable)
    view = source_journey(instance, instance.folder_sources.public_view(source_id))
    assert view["to_complete"] is None and view["counts_state"] == "attention"


def test_document_reads_actual_text_index_and_materialized_library_separately(archive):
    instance, source, _source_id = archive
    (source / "note.txt").write_text("Synthetic searchable text.")
    acquisition = instance.ingest(source)[0]
    document = instance.get_document(acquisition["document_id"])
    before = _bytes(instance.root)
    view = document_journey(instance, document, instance.document_content(document["id"]))
    assert view["text"] == "native" and view["indexed"] is True
    assert view["library"] == "missing"
    assert _bytes(instance.root) == before


def test_saved_automation_does_not_invent_a_running_runtime():
    app = SimpleNamespace(state=SimpleNamespace())
    assert runtime_state(app) == "stopped"
    app.state.scheduler_runtime_active = True
    assert runtime_state(app) == "active"
    app.state.scheduler_runtime_error = "scheduler_cycle_failed"
    assert runtime_state(app) == "attention"
    app.state.scheduler_runtime_active = False
    assert runtime_state(app) == "stopped"
    app.state.scheduler_runtime_stopping = True
    assert runtime_state(app) == "stopping"


@pytest.mark.parametrize("language", ["en", "it", "de", "fr", "es", "pt", "ro"])
@pytest.mark.parametrize("mode", ["current", "preview"])
def test_daily_pages_render_all_catalogs_without_raw_keys(archive, tmp_path, language, mode):
    from provelume.shell_settings import LauncherSettings, ShellSettingsManager

    instance, source, _source_id = archive
    (source / "note.txt").write_text("Synthetic UI document.")
    document_id = instance.ingest(source)[0]["document_id"]
    manager = ShellSettingsManager(tmp_path / "shell.json", LauncherSettings(
        instance_path=str(instance.root), interface_mode=mode, language=language, schema_version=3))
    manager.save(manager.defaults)
    client = TestClient(create_app(instance.root, shell_settings_file=manager.path))
    for path in ("/inbox", "/sources", "/documents/" + document_id):
        response = client.get(path + "?lang=" + language)
        assert response.status_code == 200, response.text
        assert "journey." not in response.text
        assert '<svg' in response.text and 'aria-hidden="true"' in response.text
    assert not client.app.state.scheduler_runtime_active


def test_progress_is_private_minimal_revision_bound_and_per_instance(tmp_path):
    first = SetupProgress(tmp_path / "launcher.json", "inst_" + "a" * 32)
    second = SetupProgress(tmp_path / "launcher.json", "inst_" + "b" * 32)
    assert first.read()["revision"] == second.read()["revision"] == 0
    assert not first.root.exists()  # GET/read creates no progress or effects.
    applied = {"prepare": "op_" + "c" * 32}
    first.update(expected_revision=0, step="folders", completed=["space"],
                 bindings={"space": "d" * 64}, operations=applied)
    assert second.read()["revision"] == 0
    raw = first.path.read_text()
    assert str(tmp_path) not in raw and "credential" not in raw
    assert "path" not in json.loads(raw)
    with pytest.raises(SetupProgressError, match="stale"):
        first.update(expected_revision=0, step="ocr")
    discarded = first.discard(expected_revision=1)
    assert discarded["completed"] == [] and discarded["operations"] == applied
    assert discarded["revision"] == 2
    assert SetupProgress(tmp_path / "launcher.json", first.instance_id).read() == discarded


@pytest.mark.parametrize("changes", [
    {"step": "unknown"}, {"completed": ["space", "space"]},
    {"operations": {"download": "op_" + "a" * 32}},
    {"operations": {"test": "/private/input.pdf"}},
    {"bindings": {"folders": "private path"}},
])
def test_progress_refuses_unbounded_or_sensitive_payloads(tmp_path, changes):
    progress = SetupProgress(tmp_path / "launcher.json", "inst_" + "a" * 32)
    with pytest.raises(SetupProgressError):
        progress.update(**{"expected_revision": 0, "step": "space", **changes})
    assert not progress.path.exists()


def test_progress_refuses_symlink_storage(tmp_path):
    progress = SetupProgress(tmp_path / "launcher.json", "inst_" + "a" * 32)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    try:
        progress.root.symlink_to(foreign, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create a synthetic directory symlink")
    with pytest.raises(SetupProgressError):
        progress.read()
    assert list(Path(foreign).iterdir()) == []
