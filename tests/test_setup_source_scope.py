"""Trial inputs and preexisting backlog cannot leak into ordinary Source work."""

from copy import deepcopy

import pytest

from provelume.ingest import run_ingestion_filesystem
from provelume.operations import OperationLedger
from provelume.review_effects import ReviewError
from provelume.service import ProvelumeInstance
from provelume.setup_source_scope import baseline_preview, eligible_inputs, install_baseline
from provelume.setup_trials import SetupTrials


def test_active_source_ordinary_ingestion_excludes_trial_inputs_even_after_replacement(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    root = tmp_path / "input"
    root.mkdir()
    sentinel = root / "ordinary.txt"
    sentinel.write_text("Ordinary authorized Source input")
    source = instance.register_folder_source(root, name="Existing active Source")
    before = deepcopy(instance.store.read_config())
    trial = SetupTrials(instance.store).start(
        source["id"], retention="keep", ocr_required=False, languages=["eng"],
        request_key="active-source-trial-001")
    generated = next(root.glob("setup-*.pdf"))
    generated.write_bytes(b"Changed input, preserve for review")
    assert eligible_inputs(instance.store, source["id"], root,
                           [(generated.name, generated), (sentinel.name, sentinel)]) == [
                               (sentinel.name, sentinel)]
    result = run_ingestion_filesystem(instance.store, root)
    assert [row.locator for row in result.items] == ["ordinary.txt"]
    assert instance.store.read_config() == before
    assert instance.folder_sources._snapshot(source["id"], max_files=1000)[1] == 1
    with pytest.raises(ReviewError):
        SetupTrials(instance.store).authority.read(trial["operation_id"], check_inputs=True)
    assert generated.read_bytes() == b"Changed input, preserve for review"
    assert instance.validate_instance()["status"] == "valid"


def test_new_source_baseline_preserves_backlog_but_admits_future_versions_and_arrivals(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    root = tmp_path / "input"
    root.mkdir()
    old = root / "existing.txt"
    old.write_text("Existing backlog must remain")
    source = instance.register_folder_source(root, name="New Inbox", lifecycle_state="paused")
    op = OperationLedger(instance.store).start(
        "setup.apply", "Activate only future inputs", related={"source_id": source["id"]})
    preview = baseline_preview(instance.store, source["id"])
    baseline = install_baseline(instance.store, op.id, preview)
    instance.set_folder_source_state(source["id"], "enabled")
    first = run_ingestion_filesystem(instance.store, root)
    assert not first.items and not first.acquisitions
    assert old.read_text() == "Existing backlog must remain"
    (root / "new.txt").write_text("Future arrival")
    old.write_text("New Version after explicit activation")
    second = run_ingestion_filesystem(instance.store, root)
    assert {row.locator for row in second.items} == {"existing.txt", "new.txt"}
    assert install_baseline(instance.store, op.id, preview) == baseline
    assert instance.validate_instance()["status"] == "valid"


def test_baseline_changed_since_preview_blocks_activation(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    root = tmp_path / "input"
    root.mkdir()
    source = instance.register_folder_source(root, name="New Inbox", lifecycle_state="paused")
    op = OperationLedger(instance.store).start(
        "setup.apply", "Activate only future inputs", related={"source_id": source["id"]})
    preview = baseline_preview(instance.store, source["id"])
    (root / "arrived-after-preview.txt").write_text("Not part of the confirmed inventory")
    with pytest.raises(ReviewError):
        install_baseline(instance.store, op.id, preview)
    assert instance.folder_sources.public_view(source["id"])["lifecycle_state"] == "paused"


def test_reserved_identity_cannot_redirect_an_existing_source(tmp_path):
    from provelume.folder_source_model import FolderSourceError

    instance = ProvelumeInstance.initialise(tmp_path / "space")
    root = tmp_path / "first"
    root.mkdir()
    other = tmp_path / "second"
    other.mkdir()
    source = instance.register_folder_source(root, name="Existing", lifecycle_state="paused")
    before = deepcopy(instance.store.read_config())
    with pytest.raises(FolderSourceError):
        instance.register_folder_source(other, name="Existing", lifecycle_state="paused",
                                        _registration_id=source["id"])
    assert instance.store.read_config() == before
