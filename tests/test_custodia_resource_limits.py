"""Physical Linux cgroup fixtures; Windows uses its separate native Job limits."""

import sys
from pathlib import Path

import pytest

from provelume.ai_models import ModelError
from provelume.ai_runtime_resources import effective_limits

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux mountinfo and cgroup v2 filesystem semantics"
)

GIB = 1024**3


def fixture(tmp_path):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    mount = tmp_path / "cgroup"
    for directory in (mount, mount / "parent", mount / "parent/child"):
        directory.mkdir(exist_ok=True)
        (directory / "cgroup.controllers").write_text("cpu memory cpuset\n")
        (directory / "memory.max").write_text("max\n")
        (directory / "memory.current").write_text("0\n")
        (directory / "cpu.max").write_text("max 100000\n")
        (directory / "cpuset.cpus.effective").write_text("0-7\n")
    (proc / "self/cgroup").write_text("0::/parent/child\n")
    (proc / "self/mountinfo").write_text(f"11 10 0:1 / {mount} ro - cgroup2 cgroup2 rw\n")
    return proc, mount


def test_parent_limits_and_remaining_headroom_override_larger_host_capacity(tmp_path):
    proc, mount = fixture(tmp_path)
    (mount / "memory.max").write_text(str(16 * GIB))
    (mount / "parent/memory.max").write_text(str(8 * GIB))
    (mount / "parent/memory.current").write_text(str(6 * GIB))
    (mount / "parent/cpu.max").write_text("250000 100000")
    (mount / "parent/child/cpuset.cpus.effective").write_text("2-5")
    result = effective_limits(64 * GIB, 32 * GIB, set(range(8)), proc=proc)
    assert result["ram_total"] == 8 * GIB
    assert result["ram_available"] == 2 * GIB
    assert result["logical_cpus"] == 2
    assert result["cgroup_ancestors_observed"] == 3


@pytest.mark.parametrize("name,value", [("memory.max", "unknown"), ("cpu.max", "1 0"),
    ("cpuset.cpus.effective", "0-1,1-2"), ("memory.current", "-1"),
    ("cpuset.cpus.effective", "0-99999999"), ("memory.max", "7" * 4097)])
def test_malformed_applicable_limit_never_falls_back_to_host(tmp_path, name, value):
    proc, mount = fixture(tmp_path)
    (mount / "parent" / name).write_text(value)
    with pytest.raises(ModelError, match="compatibility"):
        effective_limits(64 * GIB, 32 * GIB, set(range(8)), proc=proc)


def test_missing_advertised_controller_file_is_unknown_and_refused(tmp_path):
    proc, mount = fixture(tmp_path)
    (mount / "parent/memory.max").unlink()
    with pytest.raises(ModelError, match="compatibility"):
        effective_limits(64 * GIB, 32 * GIB, set(range(8)), proc=proc)


def test_namespace_root_and_host_affinity_are_both_observed(tmp_path):
    proc, mount = fixture(tmp_path)
    (proc / "self/cgroup").write_text("0::/\n")
    (proc / "self/mountinfo").write_text(f"11 10 0:1 /.. {mount} ro - cgroup2 cgroup2 rw\n")
    (mount / "memory.max").write_text(str(12 * GIB))
    result = effective_limits(64 * GIB, 9 * GIB, {4, 5, 6, 7}, proc=proc)
    assert result["ram_total"] == 12 * GIB and result["ram_available"] == 9 * GIB
    assert result["logical_cpus"] == 4 and result["cgroup_ancestors_observed"] == 1
    assert result["unmounted_ancestors"] == "NOT_OBSERVED"


def test_unreadable_process_membership_refuses_admission(tmp_path):
    with pytest.raises(ModelError, match="compatibility"):
        effective_limits(64 * GIB, 32 * GIB, set(range(8)), proc=Path(tmp_path / "absent"))
