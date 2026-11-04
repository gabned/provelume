"""Real named-input binding: no Source traversal or processing consent."""

import os
from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import pytest

from provelume.review_effects import ReviewError
from provelume.service import ProvelumeInstance
from provelume.setup_trial_inputs import observe_selection, revalidate_selection, validate_selection


@pytest.fixture
def trial(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space")
    folder = tmp_path / "input"
    folder.mkdir()
    source = instance.register_folder_source(folder, name="Synthetic setup input")
    for name in ["native-text.pdf", "scan-it-en.pdf"]:
        (folder / name).write_bytes(files("provelume").joinpath(
            "resources", "setup-trial", name).read_bytes())
    (folder / "unrelated-sentinel.txt").write_text("UNRELATED SYNTHETIC INPUT")
    return instance, folder, source["id"]


def test_observes_only_exact_names_without_folder_traversal_or_consent(trial, monkeypatch):
    instance, folder, source_id = trial
    config = deepcopy(instance.store.read_config())
    original = Path.rglob

    def reject_traversal(path, *args, **kwargs):
        if path == folder:
            pytest.fail("An exact input selection must not traverse its Source")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", reject_traversal)
    selected = observe_selection(instance.store, source_id, {
        "native": "native-text.pdf", "scan": "scan-it-en.pdf"})
    assert [row["fixture"] for row in selected["inputs"]] == ["native", "scan"]
    assert revalidate_selection(instance.store, selected) == selected
    assert instance.store.read_config() == config
    assert instance.store.list_canonical("acquisitions") == []
    assert (folder / "unrelated-sentinel.txt").read_text() == "UNRELATED SYNTHETIC INPUT"


def test_fixture_name_cannot_authorize_different_bytes(trial):
    instance, folder, source_id = trial
    path = folder / "native-text.pdf"
    original = path.read_bytes()
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(ReviewError):
        observe_selection(instance.store, source_id, {"native": path.name})
    assert instance.store.list_canonical("acquisitions") == []


def test_same_bytes_at_replaced_input_identity_invalidate_selection(trial):
    instance, folder, source_id = trial
    selected = observe_selection(instance.store, source_id, {"native": "native-text.pdf"})
    path = folder / "native-text.pdf"
    path.rename(folder / "previous.pdf")
    path.write_bytes((folder / "previous.pdf").read_bytes())
    with pytest.raises(ReviewError):
        revalidate_selection(instance.store, selected)
    assert path.is_file() and (folder / "previous.pdf").is_file()


def test_replaced_root_with_identical_named_bytes_is_stale(trial):
    instance, folder, source_id = trial
    selected = observe_selection(instance.store, source_id, {"native": "native-text.pdf"})
    previous = folder.with_name("previous-input")
    folder.rename(previous)
    folder.mkdir()
    (folder / "native-text.pdf").write_bytes((previous / "native-text.pdf").read_bytes())
    with pytest.raises(ReviewError):
        revalidate_selection(instance.store, selected)
    assert (previous / "unrelated-sentinel.txt").is_file()


def test_foreign_instance_and_changed_source_configuration_are_refused(trial, tmp_path):
    instance, _folder, source_id = trial
    selected = observe_selection(instance.store, source_id, {"native": "native-text.pdf"})
    foreign = ProvelumeInstance.initialise(tmp_path / "other-space")
    with pytest.raises(ReviewError):
        revalidate_selection(foreign.store, selected)
    instance.set_folder_source_state(source_id, "paused")
    with pytest.raises(ReviewError):
        revalidate_selection(instance.store, selected)


def test_hardlinked_input_cannot_become_trial_authority(trial):
    instance, folder, source_id = trial
    os.link(folder / "native-text.pdf", folder / "alias.pdf")
    with pytest.raises(ReviewError):
        observe_selection(instance.store, source_id, {"native": "native-text.pdf"})
    assert (folder / "alias.pdf").is_file()


@pytest.mark.parametrize("mutation", ["extra", "missing-native", "unknown-resource", "duplicate",
                                      "wrong-hash", "wrong-size", "traversal", "foreign-shape"])
def test_untrusted_selection_has_a_closed_bounded_schema(trial, mutation):
    instance, _folder, source_id = trial
    selected = observe_selection(instance.store, source_id, {"native": "native-text.pdf"})
    value = deepcopy(selected)
    row = value["inputs"][0]
    if mutation == "extra":
        value["authority"] = "global"
    elif mutation == "missing-native":
        value["inputs"] = []
    elif mutation == "unknown-resource":
        row["fixture"] = "unrelated-sentinel"
    elif mutation == "duplicate":
        value["inputs"].append(deepcopy(row))
    elif mutation == "wrong-hash":
        row["input"]["sha256"] = "0" * 64
    elif mutation == "wrong-size":
        row["input"]["size_bytes"] = True
    elif mutation == "traversal":
        row["input"]["locator"] = "../native-text.pdf"
    else:
        row["input"]["identity"]["foreign"] = 1
    with pytest.raises(ReviewError):
        validate_selection(value)
