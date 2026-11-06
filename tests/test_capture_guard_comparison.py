from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts import compare_capture_path_guard as comparison


def test_source_factor_rejects_an_extra_product_change_or_partial_inventory():
    after = (Path(__file__).resolve().parents[1] / comparison.PRODUCT).read_bytes()
    before = after.replace(b"from .local_path_guard import kernel_no_links\n", b"", 1)
    start = before.index(b"    # On supported Linux hosts")
    end = before.index(b"    for parent in (path, *path.parents):", start)
    before = before[:start] + before[end:]
    comparison.verify_factor(before, after, comparison.PATHS)
    for old, new in ((before + b"\n", after), (before, after + b"\n")):
        with pytest.raises(ValueError, match="declared factor"):
            comparison.verify_factor(old, new, comparison.PATHS)
    with pytest.raises(ValueError, match="uncontrolled"):
        comparison.verify_factor(before, after, comparison.PATHS | {"core/provelume/ai_runtime.py"})
    with pytest.raises(ValueError, match="uncontrolled"):
        comparison.verify_factor(before, after, {comparison.PRODUCT})


def test_one_admission_cannot_be_consumed_twice(tmp_path):
    source, environment = {"owner_head": "a" * 40}, {"kernel": "synthetic"}
    admission = {"schema": "concordia-capture-guard-admission/v1", "status": "ADMITTED",
                 "source": source, "environment": environment}
    path = tmp_path / "started.json"
    comparison.consume(admission, source, environment, path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        comparison.consume(admission, source, environment, path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("field", ["status", "source", "environment", "schema"])
def test_admission_drift_refuses_before_consumption(tmp_path, field):
    source, environment = {"owner_head": "a" * 40}, {"kernel": "synthetic"}
    admission = {"schema": "concordia-capture-guard-admission/v1", "status": "ADMITTED",
                 "source": source, "environment": environment}
    changed = copy.deepcopy(admission)
    changed[field] = "changed"
    path = tmp_path / "started.json"
    with pytest.raises(ValueError, match="changed after admission"):
        comparison.consume(changed, source, environment, path)
    assert not path.exists()
