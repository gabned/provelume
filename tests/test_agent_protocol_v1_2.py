from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "agent-protocol"


def test_agent_protocol_v1_2_contracts() -> None:
    subprocess.run([sys.executable, str(TOOL), "self-test"], cwd=ROOT, check=True)


def test_agent_protocol_tool_is_executable_in_git() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "--stage", "--", "tools/agent-protocol"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.split(maxsplit=1)[0] == "100755"
