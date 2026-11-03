"""Reject invalid new names before creating anything; preserve existing identities."""

import pytest

from provelume.service import ProvelumeInstance


@pytest.mark.parametrize("name", ["", "   ", "x" * 121, "Synthetic\ncontrol"])
def test_invalid_new_space_name_creates_no_files(tmp_path, name):
    root = tmp_path / "new-space"
    with pytest.raises(ValueError):
        ProvelumeInstance.initialise(root, name=name)
    assert not root.exists()


def test_existing_space_identity_is_not_replaced_by_a_new_name(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "space", name="  Synthetic personal space  ")
    before = instance.store.read_config()
    assert before["instance"]["name"] == "Synthetic personal space"
    reopened = ProvelumeInstance.initialise(instance.root, name="")
    assert reopened.store.read_config() == before
