from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from provelume.pytest_windows_shard import (
    CHILD_ENV,
    DISABLE_ENV,
    FORCE_ENV,
    SHARD_COUNT,
    _child_working_directory,
    _should_orchestrate,
    shard_for_nodeid,
)

ROOT = Path(__file__).resolve().parents[1]


def test_child_working_directory_prefers_versioned_config_over_volume_root(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "repository"
    config_dir.mkdir()
    config_file = config_dir / "pyproject.toml"
    config_file.write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    fake = SimpleNamespace(inipath=config_file, rootpath=Path(config_file.anchor))
    assert _child_working_directory(fake) == config_dir.resolve()


def test_hash_partition_is_stable_disjoint_and_complete() -> None:
    nodeids = [f"tests/test_synthetic_{index}.py::test_case" for index in range(1000)]
    partitions = [
        {nodeid for nodeid in nodeids if shard_for_nodeid(nodeid, SHARD_COUNT) == index}
        for index in range(SHARD_COUNT)
    ]
    assert set.union(*partitions) == set(nodeids)
    assert not set.intersection(*partitions)
    assert all(partitions)
    assert shard_for_nodeid("tests/test_one.py::test_a", SHARD_COUNT) == (
        shard_for_nodeid("tests/test_one.py::test_b", SHARD_COUNT)
    )
    assert shard_for_nodeid(nodeids[123], SHARD_COUNT) == shard_for_nodeid(
        nodeids[123],
        SHARD_COUNT,
    )


def test_orchestration_is_only_automatic_for_bare_windows_full_suite(monkeypatch) -> None:
    monkeypatch.delenv(CHILD_ENV, raising=False)
    monkeypatch.delenv(DISABLE_ENV, raising=False)
    monkeypatch.delenv(FORCE_ENV, raising=False)
    assert _should_orchestrate(("tests/test_shell_settings.py",)) is False
    monkeypatch.setenv(FORCE_ENV, "1")
    assert _should_orchestrate(("tests/test_shell_settings.py",)) is True
    monkeypatch.setenv(CHILD_ENV, "1")
    assert _should_orchestrate(()) is False


def test_two_process_harness_completes_bounded_and_cleans_children() -> None:
    target = (
        ROOT
        / "tests"
        / "test_windows_pytest_sharding.py"
    )
    nodeid = f"{target}::test_hash_partition_is_stable_disjoint_and_complete"
    environment = os.environ.copy()
    environment[FORCE_ENV] = "1"
    environment["PROVELUME_WINDOWS_SHARD_TIMEOUT_SECONDS"] = "60"
    environment.pop(CHILD_ENV, None)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(ROOT / "pyproject.toml"),
            "-q",
            nodeid,
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "windows-shard index=0/2" in output
    assert "windows-shard index=1/2" in output
    assert "windows-shards completed=True" in output


def test_shard_children_bind_root_and_effective_collection_targets() -> None:
    source = (ROOT / "core/provelume/pytest_windows_shard.py").read_text(encoding="utf-8")
    assert "root = _child_working_directory(config)" in source
    assert "Path(inipath).resolve().parent" in source
    assert 'f"--rootdir={root}"' in source
    assert "collection_targets" not in source
    assert "cwd=root" in source
