from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from provelume.pytest_windows_shard import (
    CHILD_ENV,
    FORCE_ENV,
    balanced_shard_assignments,
)

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "provelume-windows-module "


def _run(directory: Path, *, forced: bool = True):
    environment = os.environ.copy()
    environment.pop(CHILD_ENV, None)
    environment.pop(FORCE_ENV, None)
    if forced:
        environment[FORCE_ENV] = "1"
    environment["PROVELUME_WINDOWS_SHARD_TIMEOUT_SECONDS"] = "60"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(ROOT / "pyproject.toml"),
         "-q", str(directory)],
        cwd=ROOT, env=environment, check=False, capture_output=True,
        encoding="utf-8", errors="replace", timeout=90,
    )
    output = completed.stdout + completed.stderr
    records = [json.loads(line.split(PREFIX, 1)[1])
               for line in output.splitlines() if PREFIX in line]
    return completed.returncode, output, records


def _modules(directory: Path, bodies: list[str]) -> list[str]:
    sources = []
    for index, body in enumerate(bodies):
        path = directory / f"test_module_{index}.py"
        path.write_text(body, encoding="utf-8")
        sources.append(path.relative_to(ROOT).as_posix())
    return sources


def test_completed_module_timings_preserve_failure_skip_and_targeted_behavior():
    with tempfile.TemporaryDirectory(prefix="provelume-timings-", dir=ROOT) as temporary:
        directory = Path(temporary)
        sources = _modules(directory, [
            "def test_one():\n    pass\ndef test_two():\n    pass\n",
            "import pytest\n@pytest.fixture\ndef unavailable():\n"
            "    pytest.skip('PRIVATE_FIXTURE_TEXT')\n"
            "def test_one(unavailable):\n    pass\ndef test_two():\n    pass\n",
            "def test_one():\n    assert False, 'PRIVATE_FAILURE_TEXT'\n"
            "def test_two():\n    pass\n",
            "import pytest\n@pytest.fixture\ndef broken_teardown():\n"
            "    yield\n    assert False, 'PRIVATE_TEARDOWN_TEXT'\n"
            "def test_one(broken_teardown):\n    pass\ndef test_two():\n    pass\n",
        ])
        code, output, records = _run(directory)
        assert code == 1, output
        assert len(records) == 4 and {r["module"] for r in records} == set(sources)
        for row in records:
            assert row["complete"] and row["selected"] == row["completed"] == 2
            assert row["shard_count"] == 4
            assert 0 <= row["shard_index"] < 4
            durations = row["duration_seconds"]
            assert all(math.isfinite(v) and v >= 0 for v in durations.values())
            assert math.isclose(durations["total"], sum(
                durations[phase] for phase in ("setup", "call", "teardown")))
            assert not any(value in json.dumps(row) for value in (
                "PRIVATE_", "test_one", "test_two", str(ROOT)))
        totals = {phase: {outcome: sum(r["phase_outcomes"][phase][outcome] for r in records)
                          for outcome in ("passed", "failed", "skipped")}
                  for phase in ("setup", "call", "teardown")}
        assert totals == {
            "setup": {"passed": 7, "failed": 0, "skipped": 1},
            "call": {"passed": 6, "failed": 1, "skipped": 0},
            "teardown": {"passed": 7, "failed": 1, "skipped": 0},
        }
        assert "windows-shards completed=True count=4" in output
        for index in range(4):
            assert f"windows-shard index={index}/4" in output
        direct_code, direct_output, direct_records = _run(directory, forced=False)
        assert direct_code == 1, direct_output
        assert direct_records == []


def test_interrupted_module_has_no_cost_but_completed_same_child_is_flushed():
    with tempfile.TemporaryDirectory(prefix="provelume-timings-", dir=ROOT) as temporary:
        directory = Path(temporary)
        body = "def test_one():\n    pass\ndef test_two():\n    pass\n"
        sources = _modules(directory, [body] * 4 + [
            "import os\ndef test_one():\n    pass\ndef test_two():\n    os._exit(17)\n",
        ])
        nodes = [f"{source}::{name}" for source in sources
                 for name in ("test_one", "test_two")]
        allocation = balanced_shard_assignments(nodes, 4)
        assert allocation[sources[0]] == allocation[sources[4]]
        code, output, records = _run(directory)
        assert code == 1, output
        assert len(records) == 4
        assert {r["module"] for r in records} == set(sources[:4])
        assert all(r["complete"] and r["selected"] == r["completed"] == 2 for r in records)
        assert f"windows-shard index={allocation[sources[4]]}/4" in output
        assert "exit_code=17" in output
        assert "windows-shards completed=True count=4" in output
        for index in range(4):
            assert f"windows-shard index={index}/4" in output
