"""Native qualification errors retain a closed phase without private exception text."""

import json

import pytest

from provelume.mirror_contract import MirrorError
from provelume.mirror_rsync_windows_qualification import (
    WindowsComponentsFailure,
    qualification_phase,
)


@pytest.mark.parametrize("kind", [OSError, ValueError, KeyError, TypeError])
def test_native_failure_exposes_phase_and_type_without_exception_message(kind):
    with (
        pytest.raises(WindowsComponentsFailure) as caught,
        qualification_phase("native_version"),
    ):
        raise kind("synthetic-private-path-and-secret")
    assert caught.value.code == "rsync_windows_qualification"
    assert caught.value.evidence == {
        "schema": "concordia-rsync-windows-components-failure/v1",
        "phase": "native_version",
        "exception": kind.__name__,
    }
    assert "private" not in json.dumps(caught.value.evidence)


def test_native_failure_preserves_original_closed_code_and_containment_evidence():
    original = MirrorError("git_containment")
    original.containment_evidence = {"operation": "CreateProcessW", "native_error": 5}
    with (
        pytest.raises(WindowsComponentsFailure) as caught,
        qualification_phase("native_local_copy"),
    ):
        raise original
    assert caught.value.code == "git_containment"
    assert caught.value.evidence["containment"] == original.containment_evidence
